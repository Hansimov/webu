"""CAPTCHA 验证码解题器 — 网格检测、标注、VLM 图像理解。

负责：
  1. GridAnnotator: 检测子图网格（3x3 / 4x4），在右下角标注编号
  2. CaptchaSolver: 调用远程视觉理解大模型服务，解析输出
"""

import base64
import io
import json
import re

import cv2
import httpx
import numpy as np

from pathlib import Path
from tclogger import logger, logstr
from typing import Optional

# 配置文件
CAPTCHA_CONFIG_PATH = Path("configs/captcha.json")

# 调试输出目录
DEBUG_DIR = Path("debugs/captcha-samples")

# ═════════════════════════════════════════════════════════════════
# GridAnnotator: 网格检测与标注
# ═════════════════════════════════════════════════════════════════


class GridAnnotator:
    """检测 reCAPTCHA 图片中的子图网格，并标注编号。

    支持 3x3 和 4x4 两种网格。标注方式：在每个格子右下角绘制编号。

    用法:
        annotator = GridAnnotator()
        result = annotator.annotate("path/to/challenge.png")
        # result.annotated_image: 标注后的图片 (bytes, PNG)
        # result.grid_size: (rows, cols)
        # result.cell_rects: [(x, y, w, h), ...] 每个格子的矩形
    """

    def __init__(
        self,
        font_scale: float = 0.9,
        font_thickness: int = 2,
        label_color: tuple = (0, 0, 255),  # BGR: 红色
        label_bg_color: tuple = (255, 255, 255),  # BGR: 白色背景
        verbose: bool = True,
    ):
        self.font_scale = font_scale
        self.font_thickness = font_thickness
        self.label_color = label_color
        self.label_bg_color = label_bg_color
        self.verbose = verbose

    def annotate(
        self,
        image_input: str | bytes | np.ndarray,
        grid_size: tuple[int, int] | None = None,
    ) -> "AnnotationResult":
        """检测网格并标注编号。

        reCAPTCHA 图片包含 header（标题/指示文字）和 grid（子图网格）两部分。
        本方法自动检测 grid 的实际边界，只在 grid 区域内标注编号。

        Args:
            image_input: 图片路径、bytes 或 numpy 数组
            grid_size: 强制指定网格大小 (rows, cols)；None 则自动检测

        Returns:
            AnnotationResult
        """
        # 读取图片
        img = self._load_image(image_input)
        h, w = img.shape[:2]

        # 检测网格区域（header + grid 分界）
        grid_top, grid_bottom, detected_n = self._detect_grid_region(img)

        if grid_size:
            rows, cols = grid_size
        else:
            rows, cols = detected_n, detected_n

        if self.verbose:
            grid_h = grid_bottom - grid_top
            logger.mesg(
                f"  Grid: {rows}×{cols}, "
                f"image: {w}×{h}, "
                f"grid_region: y=[{grid_top},{grid_bottom}] h={grid_h}"
            )

        # 计算每个格子的矩形区域（仅 grid 区域内）
        cell_rects = self._compute_cell_rects(
            img, rows, cols, grid_top, grid_bottom,
        )

        # 在图片上标注编号
        annotated = self._draw_labels(img.copy(), cell_rects, rows, cols)

        # 编码为 PNG
        _, png_bytes = cv2.imencode(".png", annotated)

        return AnnotationResult(
            annotated_image=png_bytes.tobytes(),
            grid_size=(rows, cols),
            cell_rects=cell_rects,
            original_size=(w, h),
        )

    def annotate_to_file(
        self,
        image_input: str | bytes | np.ndarray,
        output_path: str,
        grid_size: tuple[int, int] | None = None,
    ) -> "AnnotationResult":
        """检测网格并标注编号，保存到文件。"""
        result = self.annotate(image_input, grid_size)
        Path(output_path).write_bytes(result.annotated_image)
        if self.verbose:
            logger.mesg(f"  Saved annotated image: {output_path}")
        return result

    def _load_image(self, image_input: str | bytes | np.ndarray) -> np.ndarray:
        """加载图片为 numpy 数组 (BGR)。"""
        if isinstance(image_input, np.ndarray):
            return image_input
        if isinstance(image_input, (str, Path)):
            img = cv2.imread(str(image_input))
            if img is None:
                raise FileNotFoundError(f"Cannot read image: {image_input}")
            return img
        if isinstance(image_input, bytes):
            arr = np.frombuffer(image_input, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("Cannot decode image bytes")
            return img
        raise TypeError(f"Unsupported image type: {type(image_input)}")

    def _detect_grid_region(
        self, img: np.ndarray, tolerance: float = 0.15,
    ) -> tuple[int, int, int]:
        """检测网格区域的上下边界和行列数。

        reCAPTCHA 图片结构：
          - 顶部：标题/指示文字（header 区域）
          - 中部：子图网格（grid 区域，占满图片宽度）
          - 底部（可能）：按钮区域

        算法：
          1. 用 HoughLinesP 检测强水平线 → 聚类
          2. 对 3×3 和 4×4 两种候选分别尝试匹配等距线序列
          3. 选择匹配最好的候选
          4. 回退：假设网格在底部正方形区域

        Returns:
            (grid_top_y, grid_bottom_y, grid_n) 其中 grid_n = 3 或 4
        """
        h, w = img.shape[:2]

        # 1. 检测强水平线
        clusters = self._find_horizontal_line_clusters(img)

        # 去掉顶部和底部的边框线
        filtered = [y for y in clusters if h * 0.03 < y < h * 0.97]

        if self.verbose:
            logger.mesg(f"  H-line clusters: {len(clusters)} raw, {len(filtered)} filtered")

        # 2. 对 3×3 和 4×4 尝试匹配
        best_score = float("inf")
        best_result = None

        for n in [3, 4]:
            expected_spacing = w / n

            for start_idx in range(len(filtered)):
                matched = [filtered[start_idx]]

                for j in range(start_idx + 1, len(filtered)):
                    expected_next = matched[-1] + expected_spacing
                    if abs(filtered[j] - expected_next) < expected_spacing * tolerance:
                        matched.append(filtered[j])
                        if len(matched) == n + 1:
                            break

                if len(matched) == n + 1:
                    spacings = [
                        matched[k + 1] - matched[k]
                        for k in range(len(matched) - 1)
                    ]
                    avg_sp = sum(spacings) / len(spacings)
                    # 分数 = 间距偏差 + cell 宽高比偏差
                    spacing_score = sum(abs(s - avg_sp) for s in spacings)
                    cell_h = avg_sp
                    cell_w = w / n
                    aspect_score = abs(cell_h / cell_w - 1.0) * 100
                    total_score = spacing_score + aspect_score

                    if total_score < best_score:
                        best_score = total_score
                        best_result = (int(matched[0]), int(matched[-1]), n)

        if best_result:
            grid_top, grid_bottom, grid_n = best_result
            if self.verbose:
                logger.mesg(
                    f"  Detected {grid_n}×{grid_n}, "
                    f"grid: y=[{grid_top},{grid_bottom}], "
                    f"score={best_score:.1f}"
                )
            return best_result

        # 3. 回退：假设网格在底部正方形区域
        grid_top = max(0, h - w)
        if self.verbose:
            logger.mesg(f"  Fallback: grid_top={grid_top}, 3×3")
        return grid_top, h, 3

    def _find_horizontal_line_clusters(
        self, img: np.ndarray, merge_gap: int = 15,
    ) -> list[int]:
        """检测强水平线并聚类，返回 y 坐标列表。"""
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        edges = cv2.Canny(gray, 100, 200)
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=int(w * 0.5),
            minLineLength=int(w * 0.4),
            maxLineGap=10,
        )

        y_positions = []
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                angle = abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)
                if angle < 5:
                    y_positions.append((y1 + y2) // 2)

        y_positions.sort()

        # 聚类：合并间距 < merge_gap 的线
        clusters: list[int] = []
        for y in y_positions:
            if clusters and abs(y - clusters[-1]) < merge_gap:
                clusters[-1] = (clusters[-1] + y) // 2
            else:
                clusters.append(int(y))

        return clusters

    def _compute_cell_rects(
        self,
        img: np.ndarray,
        rows: int,
        cols: int,
        grid_top: int,
        grid_bottom: int,
    ) -> list[tuple[int, int, int, int]]:
        """计算每个格子的 (x, y, w, h) 矩形区域。

        仅在检测到的 grid 区域内划分格子（排除 header 区域）。
        编号按行优先：第一行 1,2,3 → 第二行 4,5,6 → ...
        """
        h, w = img.shape[:2]
        grid_height = grid_bottom - grid_top
        cell_w = w / cols
        cell_h = grid_height / rows

        rects = []
        for r in range(rows):
            for c in range(cols):
                x = int(c * cell_w)
                y = int(grid_top + r * cell_h)
                cw = int((c + 1) * cell_w) - x
                ch = int(grid_top + (r + 1) * cell_h) - y
                rects.append((x, y, cw, ch))

        return rects

    def _draw_labels(
        self,
        img: np.ndarray,
        cell_rects: list[tuple[int, int, int, int]],
        rows: int,
        cols: int,
    ) -> np.ndarray:
        """在每个格子的右下角绘制编号。"""
        font = cv2.FONT_HERSHEY_SIMPLEX

        for i, (x, y, cw, ch) in enumerate(cell_rects):
            label = str(i + 1)

            # 计算文字大小
            (tw, th), baseline = cv2.getTextSize(
                label, font, self.font_scale, self.font_thickness
            )

            # 右下角位置（留 margin）
            margin = 4
            lx = x + cw - tw - margin
            ly = y + ch - margin

            # 绘制白色背景矩形
            pad = 3
            cv2.rectangle(
                img,
                (lx - pad, ly - th - pad),
                (lx + tw + pad, ly + baseline + pad),
                self.label_bg_color,
                cv2.FILLED,
            )

            # 绘制编号文字
            cv2.putText(
                img,
                label,
                (lx, ly),
                font,
                self.font_scale,
                self.label_color,
                self.font_thickness,
                cv2.LINE_AA,
            )

        return img


class AnnotationResult:
    """GridAnnotator 的输出结果。"""

    def __init__(
        self,
        annotated_image: bytes,
        grid_size: tuple[int, int],
        cell_rects: list[tuple[int, int, int, int]],
        original_size: tuple[int, int],
    ):
        self.annotated_image = annotated_image
        self.grid_size = grid_size
        self.cell_rects = cell_rects
        self.original_size = original_size

    @property
    def rows(self) -> int:
        return self.grid_size[0]

    @property
    def cols(self) -> int:
        return self.grid_size[1]

    @property
    def total_cells(self) -> int:
        return self.rows * self.cols


# ═════════════════════════════════════════════════════════════════
# CaptchaSolver: VLM 图像理解解题
# ═════════════════════════════════════════════════════════════════


def _load_captcha_config() -> dict:
    """加载 captcha 配置。"""
    if CAPTCHA_CONFIG_PATH.exists():
        with open(CAPTCHA_CONFIG_PATH) as f:
            return json.load(f)
    return {}


def _encode_image_bytes_to_base64(image_bytes: bytes, fmt: str = "png") -> str:
    """将图片 bytes 编码为 base64 data URL。"""
    mime = f"image/{fmt}"
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _encode_image_file_to_base64(image_path: str) -> str:
    """将图片文件编码为 base64 data URL。"""
    path = Path(image_path)
    suffix = path.suffix.lower().lstrip(".")
    mime_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    mime = mime_map.get(suffix, "image/jpeg")
    data = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{data}"


SOLVE_PROMPT_TEMPLATE = """\
这是一个 reCAPTCHA 验证码图片，图中是一个 {grid_desc} 的网格。
{task_desc}
每个格子的右下角有编号标注（1-{total}）。

请仔细观察每个格子的内容，判断哪些格子符合要求，然后输出需要选择的格子编号列表。

输出格式（严格遵守）：
```json
[编号1, 编号2, ...]
```

例如，如果应该选择第 1、4、7 个格子，输出：
```json
[1, 4, 7]
```
"""


class CaptchaSolver:
    """调用远程视觉理解大模型解答 reCAPTCHA 图片验证。

    流程：
      1. 接收 challenge 图片 (bytes) 和任务文本
      2. 用 GridAnnotator 标注网格编号
      3. 构造 prompt + 标注图片，调用 VLM 服务
      4. 解析返回的 JSON 列表
    """

    def __init__(
        self,
        endpoint: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        timeout: float = 60.0,
        verbose: bool = True,
    ):
        config = _load_captcha_config()
        self.endpoint = (endpoint or config.get("endpoint", "")).rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.verbose = verbose
        self._annotator = GridAnnotator(verbose=verbose)

    async def solve(
        self,
        image_bytes: bytes,
        task_text: str | None = None,
        grid_size: tuple[int, int] | None = None,
    ) -> list[int]:
        """解答 CAPTCHA。

        Args:
            image_bytes: challenge 区域的截图 (PNG/JPG)
            task_text: 题目文本（如 "Select all images with crosswalks"）
            grid_size: 强制指定网格 (rows, cols)；None 自动检测

        Returns:
            需要点击的格子编号列表（1-based），空列表表示失败
        """
        if not self.endpoint:
            logger.warn("  × VLM endpoint not configured (configs/captcha.json)")
            return []

        # 1) 标注网格
        if self.verbose:
            logger.mesg("  → Annotating grid ...")
        result = self._annotator.annotate(image_bytes, grid_size)

        # 保存标注图片（调试用）
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        annotated_path = DEBUG_DIR / "last_annotated.png"
        annotated_path.write_bytes(result.annotated_image)
        if self.verbose:
            logger.mesg(f"    Annotated: {annotated_path}")

        # 2) 构造 prompt
        rows, cols = result.grid_size
        total = result.total_cells
        grid_desc = f"{rows}×{cols}"

        if task_text:
            task_desc = f"题目要求：{task_text}"
        else:
            task_desc = "请根据图片中的提示文字，判断应该选择哪些格子。"

        prompt = SOLVE_PROMPT_TEMPLATE.format(
            grid_desc=grid_desc,
            task_desc=task_desc,
            total=total,
        )

        if self.verbose:
            logger.mesg(f"    Grid: {grid_desc}, total={total}")
            if task_text:
                logger.mesg(f"    Task: {task_text}")

        # 3) 调用 VLM
        image_url = _encode_image_bytes_to_base64(result.annotated_image)
        messages = self._build_messages(prompt, image_url)

        if self.verbose:
            logger.mesg(f"    Calling VLM: {self.endpoint} ...")

        try:
            response_text = await self._call_vlm(messages)
        except Exception as e:
            logger.warn(f"  × VLM call failed: {str(e)[:200]}")
            return []

        if self.verbose:
            logger.mesg(f"    VLM response: {response_text[:200]}")

        # 4) 解析结果
        indices = self._parse_response(response_text, total)
        if self.verbose:
            logger.mesg(f"    Parsed indices: {indices}")

        return indices

    async def solve_from_file(
        self,
        image_path: str,
        task_text: str | None = None,
        grid_size: tuple[int, int] | None = None,
    ) -> list[int]:
        """从文件解答 CAPTCHA（便捷方法）。"""
        image_bytes = Path(image_path).read_bytes()
        return await self.solve(image_bytes, task_text, grid_size)

    def _build_messages(
        self,
        prompt: str,
        image_url: str,
    ) -> list[dict]:
        """构造 OpenAI 格式的消息（带图片）。"""
        content_parts = [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": prompt},
        ]
        return [{"role": "user", "content": content_parts}]

    async def _call_vlm(self, messages: list[dict]) -> str:
        """调用远程 VLM 服务。"""
        payload = {
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": False,
        }

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout)
        ) as client:
            resp = await client.post(
                f"{self.endpoint}/v1/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        # 提取回复文本
        choices = data.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        content = message.get("content", "")
        return content if isinstance(content, str) else str(content)

    def _parse_response(self, text: str, max_index: int) -> list[int]:
        """从 VLM 回复中解析格子编号列表。

        支持多种常见格式：
          - ```json\n[1, 4, 7]\n```
          - [1, 4, 7]
          - 1, 4, 7
        """
        # 1) 尝试匹配 ```json [...] ```
        json_block = re.search(r"```json\s*(\[.*?\])\s*```", text, re.DOTALL)
        if json_block:
            try:
                indices = json.loads(json_block.group(1))
                return self._validate_indices(indices, max_index)
            except (json.JSONDecodeError, TypeError):
                pass

        # 2) 尝试匹配任意 [...] JSON 数组
        array_match = re.search(r"\[[\d\s,]+\]", text)
        if array_match:
            try:
                indices = json.loads(array_match.group(0))
                return self._validate_indices(indices, max_index)
            except (json.JSONDecodeError, TypeError):
                pass

        # 3) 尝试匹配逗号分隔的数字
        nums = re.findall(r"\b(\d{1,2})\b", text)
        if nums:
            indices = [int(n) for n in nums]
            return self._validate_indices(indices, max_index)

        return []

    def _validate_indices(self, indices: list, max_index: int) -> list[int]:
        """验证并过滤索引。"""
        result = []
        for idx in indices:
            if isinstance(idx, (int, float)):
                idx = int(idx)
                if 1 <= idx <= max_index:
                    result.append(idx)
        return sorted(set(result))
