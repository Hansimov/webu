"""测试 VLM API — 通过 LLMClient 调用验证码识别。

支持多种 API 后端（配置在 configs/llms.json 中）：
  - sf_qwen3_vl_8b:  SiliconFlow Qwen3-VL-8B-Instruct
  - ai_qwen3_vl_8b:  本地 qvl_machine 服务

使用 captcha 模块的 GridAnnotator 标注验证码样本图片,
通过 LLMClient 发送 VLM 请求，验证 API 调用与结果。

样本: debugs/captcha-samples/traffic-lights.jpg
预期输出: [2, 3, 4]

用法:
  python debugs/llms/test_sf_vlm.py [config_key] [--stream] [--no-stream]
  python debugs/llms/test_sf_vlm.py sf_qwen3_vl_8b --stream
  python debugs/llms/test_sf_vlm.py ai_qwen3_vl_8b
"""

import json
import re
import sys
import requests

from pathlib import Path
from tclogger import logger, logstr

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from webu.captcha.solver import (
    GridAnnotator,
    _encode_image_bytes_to_base64,
    SOLVE_PROMPT_TEMPLATE,
)
from webu.llms.client import LLMClient


# ── 配置 ──────────────────────────────────────────────────────────

LLM_CONFIG_PATH = PROJECT_ROOT / "configs" / "llms.json"
DEFAULT_CONFIG_KEY = "sf_qwen3_vl_8b"

SAMPLE_IMAGE = PROJECT_ROOT / "debugs" / "captcha-samples" / "traffic-lights.jpg"
EXPECTED_INDICES = [2, 3, 4]
TASK_TEXT = "Select all images with traffic lights"

ANNOTATED_OUTPUT = (
    PROJECT_ROOT
    / "debugs"
    / "captcha-samples"
    / "annotated"
    / "traffic-lights_annotated.png"
)

DEFAULT_TIMEOUT = 300  # 5 min — thinking models need more time


# ── 工具函数 ──────────────────────────────────────────────────────


def load_llm_config(config_key: str) -> dict:
    """从 configs/llms.json 加载指定模型配置。"""
    with open(LLM_CONFIG_PATH) as f:
        all_configs = json.load(f)
    if config_key not in all_configs:
        raise KeyError(
            f"Config key '{config_key}' not found in {LLM_CONFIG_PATH}. "
            f"Available: {list(all_configs.keys())}"
        )
    return all_configs[config_key]


def detect_model_from_endpoint(endpoint: str) -> str:
    """从 OpenAI 兼容 API 自动检测模型名称。

    依次尝试:
      1. /v1/models (标准 OpenAI / vLLM)
      2. /info (tfmx qvl_machine)
      3. 返回空字符串(让服务端使用默认模型)
    """
    # 从 .../v1/chat/completions 推导出 base_url
    base_url = endpoint
    for suffix in ["/v1/chat/completions", "/chat/completions"]:
        if base_url.endswith(suffix):
            base_url = base_url[: -len(suffix)]
            break
    base_url = base_url.rstrip("/")

    # 尝试 /v1/models (标准 OpenAI / vLLM)
    models_url = f"{base_url}/v1/models"
    logger.mesg(f"  Trying: {logstr.file(models_url)}")
    try:
        resp = requests.get(models_url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("data", [])
            if models:
                model_id = models[0].get("id", "")
                logger.success(f"  Detected model (v1/models): {logstr.file(model_id)}")
                return model_id
    except Exception:
        pass

    # 尝试 /info (tfmx qvl_machine)
    info_url = f"{base_url}/info"
    logger.mesg(f"  Trying: {logstr.file(info_url)}")
    try:
        resp = requests.get(info_url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            available = data.get("available_models", [])
            if available:
                model_id = available[0]
                logger.success(f"  Detected model (info): {logstr.file(model_id)}")
                if len(available) > 1:
                    logger.mesg(f"  All models: {available}")
                return model_id
    except Exception:
        pass

    # 都失败了 — 返回空字符串，让服务端使用默认模型
    logger.warn("  × Could not detect model; will use server default (empty model)")
    return ""


def build_vlm_messages(prompt: str, image_data_url: str) -> list[dict]:
    """构造 OpenAI VLM 格式的消息（带图片）。"""
    content_parts = [
        {"type": "image_url", "image_url": {"url": image_data_url}},
        {"type": "text", "text": prompt},
    ]
    return [{"role": "user", "content": content_parts}]


def parse_indices(text: str, max_index: int) -> list[int]:
    """从 VLM 回复中解析格子编号列表。

    对于 thinking model 的输出，先去除 <think>...</think> 块。
    """
    # Strip thinking blocks
    clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if not clean:
        clean = text  # fallback to full text

    # 1) ```json [...] ```
    json_block = re.search(r"```json\s*(\[.*?\])\s*```", clean, re.DOTALL)
    if json_block:
        try:
            indices = json.loads(json_block.group(1))
            if indices == [-1]:
                return [-1]
            return _validate(indices, max_index)
        except (json.JSONDecodeError, TypeError):
            pass

    # 2) [...] JSON array
    array_match = re.search(r"\[-?[\d\s,]+\]", clean)
    if array_match:
        try:
            indices = json.loads(array_match.group(0))
            if indices == [-1]:
                return [-1]
            return _validate(indices, max_index)
        except (json.JSONDecodeError, TypeError):
            pass

    # 3) comma-separated numbers
    nums = re.findall(r"\b(\d{1,2})\b", clean)
    if nums:
        return _validate([int(n) for n in nums], max_index)

    return []


def _validate(indices: list, max_index: int) -> list[int]:
    result = []
    for idx in indices:
        if isinstance(idx, (int, float)):
            idx = int(idx)
            if 1 <= idx <= max_index:
                result.append(idx)
    return sorted(set(result))


def validate_result(indices: list[int], expected: list[int]) -> bool:
    """验证结果，返回是否通过。"""
    if indices == expected:
        logger.success(f"  ✓ PASS — VLM returned correct indices: {indices}")
        return True

    expected_set = set(expected)
    result_set = set(indices)
    if expected_set.issubset(result_set):
        extra = result_set - expected_set
        logger.warn(
            f"  ~ PARTIAL — Correct indices included, but extra: {sorted(extra)}\n"
            f"    Got:      {indices}\n"
            f"    Expected: {expected}"
        )
        return True
    else:
        missing = expected_set - result_set
        logger.err(
            f"  × FAIL — Incorrect indices\n"
            f"    Got:      {indices}\n"
            f"    Expected: {expected}\n"
            f"    Missing:  {sorted(missing)}"
        )
        return False


# ── 准备标注图片和 prompt (公共步骤) ─────────────────────────────


def prepare_vlm_request():
    """标注图片、构造 prompt 和 messages。返回 (messages, total_cells)。"""
    logger.mesg(f"\n[Prepare] Annotating: {logstr.file(str(SAMPLE_IMAGE))}")
    if not SAMPLE_IMAGE.exists():
        logger.err(f"  × Sample image not found: {SAMPLE_IMAGE}")
        sys.exit(1)

    annotator = GridAnnotator(verbose=True)
    result = annotator.annotate(str(SAMPLE_IMAGE))
    logger.success(
        f"  Grid: {result.rows}×{result.cols}, "
        f"cells: {result.total_cells}, "
        f"image: {result.original_size}"
    )

    ANNOTATED_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    ANNOTATED_OUTPUT.write_bytes(result.annotated_image)
    logger.mesg(f"  Saved: {logstr.file(str(ANNOTATED_OUTPUT))}")

    rows, cols = result.grid_size
    total = result.total_cells
    prompt = SOLVE_PROMPT_TEMPLATE.format(
        grid_desc=f"{rows}×{cols}",
        task_desc=f"Task: {TASK_TEXT}",
        total=total,
        feedback="",
    )
    logger.file(f"  Prompt (first 200 chars):\n    {prompt[:200]}...")

    image_data_url = _encode_image_bytes_to_base64(result.annotated_image)
    messages = build_vlm_messages(prompt, image_data_url)
    return messages, total


# ── 测试函数 ──────────────────────────────────────────────────────


def test_vlm(config_key: str, stream: bool):
    """测试指定配置的 VLM 调用。"""
    mode_str = "stream" if stream else "json"
    logger.note("=" * 60)
    logger.note(f"Test: {config_key} — {mode_str} mode")
    logger.note("=" * 60)

    # 1) 加载配置
    logger.mesg(f"\n[1] Loading config: {logstr.file(config_key)}")
    config = load_llm_config(config_key)

    endpoint = config.get("endpoint", "")
    api_key = config.get("api_key", "")
    api_format = config.get("api_format", "openai")
    model = config.get("model", "")

    # 自动检测模型（本地服务器可能不需要在 config 中指定 model）
    if not model:
        model = detect_model_from_endpoint(endpoint)
        # model 可以为空 — 部分服务器（如 qvl_machine）会使用默认模型

    logger.success(
        f"  endpoint:   {endpoint}\n"
        f"  model:      {model or '(server default)'}\n"
        f"  api_format: {api_format}\n"
        f"  api_key:    {'***' + api_key[-6:] if api_key else '(none)'}"
    )

    # 2) 准备标注图片和 prompt
    messages, total = prepare_vlm_request()

    # 3) 创建 LLMClient 并调用
    logger.mesg(f"\n[2] Calling VLM ({mode_str}) ...")
    client = LLMClient(
        endpoint=endpoint,
        api_key=api_key,
        api_format=api_format,
        model=model,
        timeout=DEFAULT_TIMEOUT,
        verbose_user=True,
        verbose_assistant=True,
        verbose_content=True,
        verbose_usage=True,
        verbose_finish=True,
        verbose=True,
    )

    try:
        response_text = client.chat(
            messages=messages,
            stream=stream,
            max_tokens=2048,
            temperature=0.2,
        )
    except Exception as e:
        logger.err(f"  × Chat failed: {e}")
        return False

    if not response_text:
        logger.err("  × Empty response")
        return False

    # 4) 解析和验证
    logger.mesg(f"\n[3] Parsing response")
    # Show raw response (truncated for thinking models)
    display_text = response_text
    if len(display_text) > 500:
        display_text = display_text[:200] + "\n  ...\n  " + display_text[-200:]
    logger.file(f"  Raw response:\n  {display_text}")

    indices = parse_indices(response_text, total)
    logger.mesg(f"  Parsed indices: {indices}")
    logger.mesg(f"  Expected:       {EXPECTED_INDICES}")

    logger.mesg(f"\n[4] Validation")
    return validate_result(indices, EXPECTED_INDICES)


# ── 入口 ──────────────────────────────────────────────────────────


def main():
    args = sys.argv[1:]

    # Parse arguments
    config_key = DEFAULT_CONFIG_KEY
    stream = True  # default to stream for better UX

    for arg in args:
        if arg == "--stream":
            stream = True
        elif arg == "--no-stream":
            stream = False
        elif not arg.startswith("-"):
            config_key = arg

    # Run test
    ok = test_vlm(config_key, stream=stream)

    print()
    logger.note("=" * 60)
    if ok:
        logger.success(f"✓ Test passed: {config_key}")
    else:
        logger.err(f"× Test failed: {config_key}")
    logger.note("=" * 60)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
