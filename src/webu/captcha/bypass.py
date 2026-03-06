"""CAPTCHA 自动绕过 — 使用 Playwright 在 headless 浏览器内操作。

核心思路：
  所有鼠标移动和点击操作都在浏览器沙箱内完成（Playwright page.mouse API），
  不使用系统级别的 pyautogui / mss，因此：
  - 完全兼容 headless 模式
  - 不同浏览器实例之间互不干扰
  - 不影响用户桌面或其他窗口

流程：
  1. 点击 reCAPTCHA checkbox → 可能直接通过，也可能弹出图片验证
  2. 如果弹出图片验证 → 截取题目图片 → 交给 CaptchaSolver 解题
  3. 根据 solver 返回的格子编号，模拟点击对应区域
  4. 点击 Verify 按钮 → 等待页面跳转
"""

import asyncio
import random
import time

from datetime import datetime, timezone, timedelta
from pathlib import Path
from tclogger import logger, logstr
from typing import Optional

# 截图保存目录
SCREENSHOT_DIR = Path("data/google_api_screenshots")
TZ_SHANGHAI = timezone(timedelta(hours=8))


def save_debug_screenshot(
    screenshot_bytes: bytes,
    stage: str,
    proxy_url: str = "",
    base_dir: Path | None = None,
) -> Path:
    """保存调试截图。"""
    out_dir = base_dir or SCREENSHOT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(TZ_SHANGHAI).strftime("%Y%m%d_%H%M%S")
    safe_proxy = (
        (proxy_url or "direct").replace("://", "_").replace(":", "_").replace("/", "")
    )
    filename = f"{ts}_bypass_{stage}_{safe_proxy}.png"
    path = out_dir / filename
    path.write_bytes(screenshot_bytes)
    logger.mesg(f"  📸 [{stage}]: {logstr.file(path)}")
    return path


def save_debug_html(
    html: str,
    stage: str,
    base_dir: Path | None = None,
) -> Path:
    """保存调试 HTML。"""
    out_dir = base_dir or SCREENSHOT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(TZ_SHANGHAI).strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{ts}_{stage}.html"
    path.write_text(html, encoding="utf-8")
    logger.mesg(f"  📄 [{stage}]: {logstr.file(path)}")
    return path


class CaptchaBypass:
    """reCAPTCHA 自动绕过器（图像理解 + 模拟鼠标点击）。

    在 Playwright 页面上检测并尝试绕过 Google reCAPTCHA。
    所有操作均在浏览器内部（headless 安全），不触碰系统鼠标/屏幕。
    """

    # reCAPTCHA checkbox iframe
    RECAPTCHA_IFRAME_SELECTORS = [
        "iframe[title='reCAPTCHA']",
        "iframe[src*='recaptcha/enterprise/anchor']",
        "iframe[src*='recaptcha/api2/anchor']",
    ]

    # reCAPTCHA checkbox 选择器
    CHECKBOX_SELECTORS = [
        "#recaptcha-anchor",
        ".recaptcha-checkbox-border",
        "#recaptcha-anchor-label",
    ]

    # challenge bframe 选择器
    BFRAME_SELECTOR = "iframe[title*='recaptcha challenge']"

    # /sorry/ URL 模式
    SORRY_URL_PATTERNS = ["/sorry/", "/sorry?"]

    def __init__(
        self,
        max_wait_after_click: float = 15.0,
        max_solve_attempts: int = 3,
        save_screenshots: bool = True,
        verbose: bool = True,
        run_dir: Path | None = None,
    ):
        self.max_wait_after_click = max_wait_after_click
        self.max_solve_attempts = max_solve_attempts
        self.save_screenshots = save_screenshots
        self.verbose = verbose

        # 每次运行使用独立的截图子目录
        if run_dir:
            self._run_dir = run_dir
        else:
            ts = datetime.now(TZ_SHANGHAI).strftime("%Y%m%d_%H%M%S")
            self._run_dir = SCREENSHOT_DIR / ts
        self._run_dir.mkdir(parents=True, exist_ok=True)

    @property
    def run_dir(self) -> Path:
        """本次运行的截图子目录。"""
        return self._run_dir

    def _screenshot(self, data: bytes, stage: str, proxy_url: str = "") -> Path:
        """保存截图到本次运行目录。"""
        return save_debug_screenshot(data, stage, proxy_url, base_dir=self._run_dir)

    def _save_html(self, html: str, stage: str) -> Path:
        """保存 HTML 到本次运行目录。"""
        return save_debug_html(html, stage, base_dir=self._run_dir)

    # ═══════════════════════════════════════════════════════════
    # 公开接口
    # ═══════════════════════════════════════════════════════════

    async def attempt_bypass(self, page, proxy_url: str = "") -> bool:
        """尝试绕过当前页面的 CAPTCHA。

        Args:
            page: Playwright Page 对象（当前在 Google sorry 页面上）
            proxy_url: 当前使用的代理地址（仅用于日志和截图命名）

        Returns:
            True = 成功绕过（页面已跳转到搜索结果）
            False = 绕过失败
        """
        if self.verbose:
            logger.note("> Attempting CAPTCHA bypass ...")

        if self.verbose:
            logger.mesg(f"  Screenshots dir: {logstr.file(self._run_dir)}")

        # 保存绕过前截图
        if self.save_screenshots:
            try:
                shot = await page.screenshot(full_page=True)
                self._screenshot(shot, "before_click", proxy_url)
            except Exception:
                pass

        # Step 1: 点击 reCAPTCHA checkbox
        clicked = await self._click_checkbox(page)
        if not clicked:
            if self.verbose:
                logger.warn("  × Failed to click reCAPTCHA checkbox")
            return False

        # 保存点击后截图
        if self.save_screenshots:
            try:
                await asyncio.sleep(0.5)
                shot = await page.screenshot(full_page=False)
                self._screenshot(shot, "after_checkbox", proxy_url)
            except Exception:
                pass

        # Step 2: 等待 — 可能直接通过，也可能弹出图片验证
        navigated = await self._wait_for_navigation(page, proxy_url)
        if navigated:
            return True

        # Step 3: 检测是否出现了图片验证
        has_challenge = await self._has_image_challenge(page)
        if not has_challenge:
            if self.verbose:
                logger.warn("  × No image challenge detected, cannot proceed")
            return False

        # Step 4: 使用 CaptchaSolver 解题（可能多轮）
        from .solver import CaptchaSolver

        solver = CaptchaSolver(verbose=self.verbose)

        for attempt in range(self.max_solve_attempts):
            if self.verbose:
                logger.note(
                    f"  → Solve attempt {attempt + 1}/{self.max_solve_attempts}"
                )

            success = await self._solve_one_round(page, solver, proxy_url, attempt)
            if success:
                return True

            # 检查是否还有新的图片验证（有时需要多轮）
            await asyncio.sleep(random.uniform(1.0, 2.0))
            still_challenge = await self._has_image_challenge(page)
            if not still_challenge:
                # 可能已经通过了
                nav = await self._wait_for_navigation(page, proxy_url, timeout=5.0)
                if nav:
                    return True
                break

        # 所有尝试失败
        if self.verbose:
            logger.warn("  × All CAPTCHA solve attempts failed")
        if self.save_screenshots:
            try:
                shot = await page.screenshot(full_page=True)
                self._screenshot(shot, "failed", proxy_url)
            except Exception:
                pass
        return False

    # ═══════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════

    async def _click_checkbox(self, page) -> bool:
        """点击 reCAPTCHA checkbox。"""
        if self.verbose:
            logger.mesg("  → Clicking reCAPTCHA checkbox ...")

        try:
            # 找到 reCAPTCHA anchor iframe
            iframe_selector = None
            for selector in self.RECAPTCHA_IFRAME_SELECTORS:
                try:
                    count = await page.locator(selector).count()
                    if count > 0:
                        iframe_selector = selector
                        if self.verbose:
                            logger.mesg(f"    Found iframe: {selector}")
                        break
                except Exception:
                    continue

            if not iframe_selector:
                if self.verbose:
                    logger.mesg("    No reCAPTCHA iframe found")
                return False

            frame = page.frame_locator(iframe_selector)

            # 随机延迟
            await asyncio.sleep(random.uniform(0.5, 1.5))

            # 尝试点击 checkbox
            for selector in self.CHECKBOX_SELECTORS:
                try:
                    checkbox = frame.locator(selector).first
                    if await checkbox.count() > 0:
                        await checkbox.click(
                            delay=random.randint(50, 150),
                            force=False,
                        )
                        if self.verbose:
                            logger.mesg(f"    ✓ Clicked: {selector}")
                        return True
                except Exception as e:
                    if self.verbose:
                        logger.mesg(f"    Checkbox {selector} failed: {str(e)[:80]}")
                    continue

            if self.verbose:
                logger.mesg("    No clickable checkbox found")
            return False

        except Exception as e:
            if self.verbose:
                logger.mesg(f"    Checkbox click error: {str(e)[:150]}")
            return False

    async def _has_image_challenge(self, page) -> bool:
        """检测是否出现了图片验证 bframe。"""
        try:
            count = await page.locator(self.BFRAME_SELECTOR).count()
            return count > 0
        except Exception:
            return False

    async def _solve_one_round(
        self,
        page,
        solver: "CaptchaSolver",
        proxy_url: str,
        attempt: int,
    ) -> bool:
        """执行一轮图片验证解题（含 Next 多步、Skip 处理和错误反馈）。

        reCAPTCHA 动作按钮有三种状态：
          - Verify: 提交答案，验证是否正确
          - Next:   提交答案后进入下一题（多步验证）
          - Skip:   跳过当前题目，获取新题

        错误恢复策略：
          - 如果 Verify 后仍有 challenge → 检测错误类型
          - "select more" 错误 → 告诉 VLM 上次漏选了
          - "incorrect response" → 告诉 VLM 上次选错了
          - 将错误反馈传给 solver 的下一次调用

        流程：
          1. 查找 challenge frame → 检测网格 → 获取题目 → 截图
          2. 调用 VLM solver（附带上一轮的错误反馈） → 点击格子
          3. 检测动作按钮类型并点击：
             - Verify → 等待页面跳转 / 检测错误并重试
             - Next   → 继续下一子轮
             - Skip   → 跳过 → 继续
        """
        MAX_SUB_ROUNDS = 8

        # 跟踪上一轮的状态，供反馈使用
        prev_error_feedback = None
        prev_selected_indices = None

        for sub in range(MAX_SUB_ROUNDS):
            rl = f"r{attempt}" if sub == 0 else f"r{attempt}.{sub}"

            try:
                # 1) 查找 challenge frame
                challenge_frame = self._find_challenge_frame(page)
                if not challenge_frame:
                    if self.verbose:
                        logger.mesg("    Cannot find challenge frame")
                    return False

                # 2) 从 DOM 检测网格布局
                grid_info = await self._detect_grid_layout(challenge_frame)
                if not grid_info:
                    if self.verbose:
                        logger.mesg("    Cannot detect grid layout")
                    return False

                rows, cols, grid_rect = grid_info
                if self.verbose:
                    logger.mesg(
                        f"    Grid: {rows}×{cols}, "
                        f"rect=({grid_rect['x']:.0f},{grid_rect['y']:.0f},"
                        f"{grid_rect['width']:.0f}×{grid_rect['height']:.0f})"
                    )

                # 3) 提取题目文本（含动态错误提示）
                task_text = await self._get_challenge_task_text(challenge_frame)
                if self.verbose:
                    logger.mesg(f"    Task: {task_text or '(unknown)'}")

                # 检测 reCAPTCHA 显示的错误状态
                error_state = await self._detect_error_state(challenge_frame)
                if error_state and self.verbose:
                    logger.mesg(f"    ⚠ Error state: {error_state}")

                # 如果页面显示了错误，更新反馈信息
                if error_state:
                    prev_error_feedback = error_state

                # 4) 截取网格图片（优先仅 TABLE 区域）
                challenge_image_bytes = await self._capture_challenge_image(
                    page, challenge_frame=challenge_frame
                )
                if not challenge_image_bytes:
                    if self.verbose:
                        logger.mesg("    Failed to capture challenge image")
                    return False

                if self.save_screenshots:
                    self._screenshot(
                        challenge_image_bytes, f"challenge_{rl}", proxy_url
                    )

                # 5) 调用 VLM solver（附带错误反馈和上次选择）
                cell_indices = await solver.solve(
                    image_bytes=challenge_image_bytes,
                    task_text=task_text,
                    grid_size=(rows, cols),
                    error_feedback=prev_error_feedback,
                    prev_indices=prev_selected_indices,
                )

                # VLM 返回 [-1] 表示无匹配 → 点 Skip
                if cell_indices == [-1]:
                    if self.verbose:
                        logger.mesg("    Solver: no matching cells → Skip")
                    action = await self._detect_and_click_action(page, challenge_frame)
                    if action:
                        if self.verbose:
                            logger.mesg(f"    → Clicked {action.capitalize()}")
                        prev_error_feedback = None
                        prev_selected_indices = None
                        await asyncio.sleep(random.uniform(1.0, 2.0))
                        continue
                    return False

                if not cell_indices:
                    if self.verbose:
                        logger.mesg("    Solver returned empty response")
                    return False

                if self.verbose:
                    logger.mesg(f"    Solver says click: {cell_indices}")

                # 记录本次选择（供反馈使用）
                prev_selected_indices = list(cell_indices)

                # 6) 模拟点击每个格子
                for idx in cell_indices:
                    if idx < 1 or idx > rows * cols:
                        continue
                    row = (idx - 1) // cols
                    col = (idx - 1) % cols
                    cell_w = grid_rect["width"] / cols
                    cell_h = grid_rect["height"] / rows
                    cx = grid_rect["x"] + col * cell_w + cell_w / 2
                    cy = grid_rect["y"] + row * cell_h + cell_h / 2
                    cx += random.uniform(-cell_w * 0.15, cell_w * 0.15)
                    cy += random.uniform(-cell_h * 0.15, cell_h * 0.15)

                    await self._human_like_click(page, int(cx), int(cy))
                    if self.verbose:
                        logger.mesg(
                            f"    ✓ Clicked cell {idx} " f"at ({int(cx)}, {int(cy)})"
                        )
                    await asyncio.sleep(random.uniform(0.3, 0.7))

                if self.save_screenshots:
                    try:
                        shot = await page.screenshot(full_page=False)
                        self._screenshot(shot, f"cells_clicked_{rl}", proxy_url)
                    except Exception:
                        pass

                # 7) 检测并点击动作按钮（Verify / Next / Skip）
                await asyncio.sleep(random.uniform(0.5, 1.0))
                action = await self._detect_and_click_action(page, challenge_frame)

                if self.save_screenshots:
                    try:
                        await asyncio.sleep(0.5)
                        shot = await page.screenshot(full_page=False)
                        self._screenshot(shot, f"{action or 'btn'}_{rl}", proxy_url)
                    except Exception:
                        pass

                if action == "verify":
                    await asyncio.sleep(random.uniform(1.5, 2.5))
                    # 检查验证码是否仍在
                    if await self._has_image_challenge(page):
                        # 检测错误类型，构建反馈信息
                        cf = self._find_challenge_frame(page)
                        if cf:
                            err = await self._detect_error_state(cf)
                        else:
                            err = None

                        if err and "select" in err.lower() and "more" in err.lower():
                            prev_error_feedback = (
                                "You did NOT select enough cells. "
                                "Some matching cells were MISSED. "
                                "Look more carefully at ALL cells, "
                                "especially at the edges/boundaries."
                            )
                            if self.verbose:
                                logger.mesg(
                                    "    → 'Select more' error — "
                                    "VLM missed some cells, retrying with feedback ..."
                                )
                        elif err and (
                            "incorrect" in err.lower() or "try again" in err.lower()
                        ):
                            prev_error_feedback = (
                                "Your selection was INCORRECT. "
                                "You may have selected wrong cells. "
                                "Re-examine each cell carefully."
                            )
                            if self.verbose:
                                logger.mesg(
                                    "    → 'Incorrect' error — "
                                    "VLM selected wrong cells, retrying with feedback ..."
                                )
                        else:
                            prev_error_feedback = (
                                "Previous attempt failed. "
                                "The challenge refreshed with new images."
                            )
                            prev_selected_indices = None
                            if self.verbose:
                                logger.mesg(
                                    "    → Challenge still present "
                                    "(new images?), re-solving ..."
                                )
                        continue
                    # 页面已离开 CAPTCHA，等待导航完成
                    nav = await self._wait_for_navigation(page, proxy_url, timeout=8.0)
                    return nav

                elif action == "next":
                    if self.verbose:
                        logger.mesg("    → Next sub-round ...")
                    # Next 意味着答对了当前步骤，清除错误反馈
                    prev_error_feedback = None
                    prev_selected_indices = None
                    await asyncio.sleep(random.uniform(1.5, 3.0))
                    continue

                elif action == "skip":
                    if self.verbose:
                        logger.mesg("    → Skipped, new challenge ...")
                    # Skip 也清除反馈
                    prev_error_feedback = None
                    prev_selected_indices = None
                    await asyncio.sleep(random.uniform(1.0, 2.0))
                    continue

                else:
                    if self.verbose:
                        logger.mesg("    Cannot find action button")
                    return False

            except Exception as e:
                if self.verbose:
                    logger.mesg(f"    Solve sub-round error: {str(e)[:200]}")
                return False

        if self.verbose:
            logger.mesg(f"    × Max sub-rounds ({MAX_SUB_ROUNDS}) reached")
        return False

    def _find_challenge_frame(self, page):
        """查找 challenge bframe 对应的 Frame 对象。"""
        for frame in page.frames:
            url = frame.url or ""
            if "bframe" in url or ("recaptcha" in url and "anchor" not in url):
                return frame
        return None

    async def _detect_error_state(self, challenge_frame) -> Optional[str]:
        """检测 reCAPTCHA 当前显示的错误状态。

        reCAPTCHA 在验证失败时会显示不同的错误提示：
        - "Please select all matching images" → 漏选了格子
        - "Please also check the new images" → 新图片需要选择
        - "Please try again" → 选错了
        - "Verification expired" → 超时

        Returns:
            错误消息文本，或 None（无错误）
        """
        try:
            error_text = await challenge_frame.evaluate(
                """() => {
                // reCAPTCHA 错误提示元素
                const selectors = [
                    '.rc-imageselect-error-select-more',
                    '.rc-imageselect-error-dynamic-more',
                    '.rc-imageselect-incorrect-response',
                    '.rc-imageselect-error-select-something',
                ];
                let texts = [];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const s = window.getComputedStyle(el);
                        if (s.display !== 'none' && s.visibility !== 'hidden'
                            && s.opacity !== '0') {
                            const t = el.innerText.trim();
                            if (t) texts.push(t);
                        }
                    }
                }
                return texts.length ? texts.join(' | ') : null;
            }"""
            )
            return error_text
        except Exception:
            return None

    async def _capture_challenge_image(
        self, page, challenge_frame=None
    ) -> Optional[bytes]:
        """截取 reCAPTCHA challenge 的网格图片区域。

        优先截取 grid TABLE 元素（仅包含网格图片，无 header/button）：
        - 标注更精确（图片即网格，无需检测 header 边界）
        - VLM 看到的图片更清晰

        降级方案：截取整个 bframe 元素（含 header + grid + buttons）。
        """
        # 优先：截取 grid TABLE 元素（精准的网格区域）
        if challenge_frame:
            table_selectors = [
                "table.rc-imageselect-table-44",
                "table.rc-imageselect-table-33",
                "table.rc-imageselect-table",
            ]
            for sel in table_selectors:
                try:
                    table = challenge_frame.locator(sel).first
                    if await table.count() > 0:
                        shot = await table.screenshot(timeout=10000)
                        if self.verbose:
                            logger.mesg(f"    ✓ Grid table captured ({sel})")
                        return shot
                except Exception:
                    continue

        # 降级：截取整个 bframe 元素
        try:
            bframe_el = page.locator(self.BFRAME_SELECTOR).first
            if await bframe_el.count() > 0:
                if self.verbose:
                    logger.mesg("    ↓ Fallback: full bframe screenshot")
                return await bframe_el.screenshot()
        except Exception as e:
            if self.verbose:
                logger.mesg(f"    Capture error: {str(e)[:150]}")
        return None

    async def _get_challenge_task_text(self, challenge_frame) -> Optional[str]:
        """从 challenge frame 提取题目文本（含动态提示如 'Please also check the new images'）。"""
        try:
            text = await challenge_frame.evaluate(
                """() => {
                let parts = [];

                // 主要的指示文本
                const instructions = document.querySelector(
                    '.rc-imageselect-instructions'
                );
                if (instructions) parts.push(instructions.innerText.trim());

                // 回退
                if (!parts.length) {
                    const desc = document.querySelector(
                        '.rc-imageselect-desc, '
                        + '.rc-imageselect-desc-no-canonical'
                    );
                    if (desc) parts.push(desc.innerText.trim());
                }

                // 动态提示（如 "Please also check the new images"）
                const dynamic = document.querySelectorAll(
                    '.rc-imageselect-error-dynamic-more, '
                    + '.rc-imageselect-error-select-more, '
                    + '.rc-imageselect-incorrect-response'
                );
                for (const el of dynamic) {
                    const s = window.getComputedStyle(el);
                    if (s.display !== 'none' && s.visibility !== 'hidden') {
                        const t = el.innerText.trim();
                        if (t) parts.push(t);
                    }
                }

                return parts.length ? parts.join(' | ') : null;
            }"""
            )
            return text
        except Exception:
            return None

    async def _detect_grid_layout(self, challenge_frame) -> Optional[tuple]:
        """检测网格布局。

        Returns:
            (rows, cols, rect_dict) 或 None
            rect_dict: {x, y, width, height} — 网格在 viewport 中的绝对位置
        """
        try:
            info = await challenge_frame.evaluate(
                """() => {
                // 检查 3x3
                let table = document.querySelector('table.rc-imageselect-table-33');
                if (table) {
                    const r = table.getBoundingClientRect();
                    return {rows: 3, cols: 3, x: r.x, y: r.y,
                            width: r.width, height: r.height};
                }
                // 检查 4x4
                table = document.querySelector('table.rc-imageselect-table-44');
                if (table) {
                    const r = table.getBoundingClientRect();
                    return {rows: 4, cols: 4, x: r.x, y: r.y,
                            width: r.width, height: r.height};
                }
                // 回退：通过行列数推断
                table = document.querySelector('table.rc-imageselect-table');
                if (table) {
                    const tbody = table.querySelector('tbody');
                    if (tbody) {
                        const trs = tbody.querySelectorAll('tr');
                        const rows = trs.length;
                        const cols = trs[0]
                            ? trs[0].querySelectorAll('td').length
                            : 0;
                        const r = table.getBoundingClientRect();
                        return {rows, cols, x: r.x, y: r.y,
                                width: r.width, height: r.height};
                    }
                }
                return null;
            }"""
            )

            if not info:
                return None

            rows = info["rows"]
            cols = info["cols"]

            # 从主页面获取 bframe iframe 的 viewport 位置偏移
            page = challenge_frame.page
            bframe_pos = await page.evaluate(
                """(selector) => {
                const iframe = document.querySelector(selector);
                if (!iframe) return null;
                const r = iframe.getBoundingClientRect();
                return {x: r.x, y: r.y};
            }""",
                self.BFRAME_SELECTOR,
            )

            if bframe_pos:
                grid_rect = {
                    "x": bframe_pos["x"] + info["x"],
                    "y": bframe_pos["y"] + info["y"],
                    "width": info["width"],
                    "height": info["height"],
                }
            else:
                grid_rect = {
                    "x": info["x"],
                    "y": info["y"],
                    "width": info["width"],
                    "height": info["height"],
                }

            return (rows, cols, grid_rect)

        except Exception as e:
            if self.verbose:
                logger.mesg(f"    Grid detect error: {str(e)[:120]}")
            return None

    async def _detect_and_click_action(
        self,
        page,
        challenge_frame,
    ) -> str | None:
        """检测并点击 reCAPTCHA 动作按钮。

        reCAPTCHA 使用同一个按钮 #recaptcha-verify-button，
        但其显示文本会在 Verify / Next / Skip 之间切换。

        Returns:
            "verify" | "next" | "skip" | None
        """
        try:
            btn_info = await challenge_frame.evaluate(
                """() => {
                const btn = document.querySelector(
                    '#recaptcha-verify-button'
                );
                if (!btn) return null;
                const r = btn.getBoundingClientRect();
                return {
                    x: r.x, y: r.y,
                    width: r.width, height: r.height,
                    text: btn.innerText.trim().toLowerCase(),
                };
            }"""
            )

            if btn_info:
                text = btn_info.get("text", "")
                if "skip" in text:
                    action = "skip"
                elif "next" in text:
                    action = "next"
                else:
                    action = "verify"

                # 转换到 viewport 坐标
                bframe_pos = await page.evaluate(
                    """(selector) => {
                    const iframe = document.querySelector(selector);
                    if (!iframe) return null;
                    const r = iframe.getBoundingClientRect();
                    return {x: r.x, y: r.y};
                }""",
                    self.BFRAME_SELECTOR,
                )

                if bframe_pos:
                    cx = bframe_pos["x"] + btn_info["x"] + btn_info["width"] / 2
                    cy = bframe_pos["y"] + btn_info["y"] + btn_info["height"] / 2
                else:
                    cx = btn_info["x"] + btn_info["width"] / 2
                    cy = btn_info["y"] + btn_info["height"] / 2

                await self._human_like_click(page, int(cx), int(cy))
                if self.verbose:
                    label = action.capitalize()
                    logger.mesg(f"    ✓ Clicked {label} " f"at ({int(cx)}, {int(cy)})")
                return action

            # 回退：frame_locator 方式
            bframe = page.frame_locator(self.BFRAME_SELECTOR)
            btn = bframe.locator("#recaptcha-verify-button")
            if await btn.count() > 0:
                text = (await btn.inner_text()).strip().lower()
                if "skip" in text:
                    action = "skip"
                elif "next" in text:
                    action = "next"
                else:
                    action = "verify"
                await btn.click(delay=random.randint(50, 150))
                if self.verbose:
                    logger.mesg(f"    ✓ Clicked {action} (frame_locator)")
                return action

            return None

        except Exception as e:
            if self.verbose:
                logger.mesg(f"    Action button error: {str(e)[:120]}")
            return None

    # ═══════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════

    async def _human_like_click(self, page, target_x: int, target_y: int):
        """模拟人类鼠标移动和点击。"""
        # 随机起始位置
        start_x = random.randint(100, 400)
        start_y = random.randint(100, 300)
        await page.mouse.move(start_x, start_y)
        await asyncio.sleep(random.uniform(0.05, 0.15))

        # 经过中间点（贝塞尔曲线模拟）
        steps = random.randint(3, 6)
        for i in range(steps):
            progress = (i + 1) / steps
            mid_x = int(start_x + (target_x - start_x) * progress)
            mid_y = int(start_y + (target_y - start_y) * progress)
            mid_x += random.randint(-5, 5)
            mid_y += random.randint(-3, 3)
            await page.mouse.move(mid_x, mid_y)
            await asyncio.sleep(random.uniform(0.02, 0.06))

        # 精确目标（微小偏移）
        final_x = target_x + random.randint(-2, 2)
        final_y = target_y + random.randint(-2, 2)
        await page.mouse.move(final_x, final_y)
        await asyncio.sleep(random.uniform(0.03, 0.1))

        # 按下和释放
        await page.mouse.down()
        await asyncio.sleep(random.uniform(0.05, 0.12))
        await page.mouse.up()

    async def _wait_for_navigation(
        self,
        page,
        proxy_url: str = "",
        timeout: float = None,
    ) -> bool:
        """等待页面跳转离开 /sorry/ 页面。"""
        wait_time = timeout or self.max_wait_after_click
        if self.verbose:
            logger.mesg(f"    Waiting for navigation ({wait_time:.0f}s) ...")

        start = time.time()
        while time.time() - start < wait_time:
            url = page.url
            is_sorry = any(p in url for p in self.SORRY_URL_PATTERNS)

            if not is_sorry and "google.com" in url:
                if self.verbose:
                    logger.okay(f"    ✓ Navigated to: {logstr.file(url[:80])}")
                try:
                    await page.wait_for_selector("#search, #rso, div.g", timeout=10000)
                except Exception:
                    pass
                return True

            await asyncio.sleep(0.5)

        if self.verbose:
            elapsed = time.time() - start
            logger.warn(
                f"    × Navigation timeout after {elapsed:.1f}s, "
                f"URL: {page.url[:80]}"
            )

        # 保存超时状态
        if self.save_screenshots:
            try:
                shot = await page.screenshot(full_page=True)
                self._screenshot(shot, "nav_timeout", proxy_url)
                html = await page.content()
                self._save_html(html, "nav_timeout")
            except Exception:
                pass

        return False
