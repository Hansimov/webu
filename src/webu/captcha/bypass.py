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
) -> Path:
    """保存调试截图。"""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(TZ_SHANGHAI).strftime("%Y%m%d_%H%M%S")
    safe_proxy = (
        (proxy_url or "direct")
        .replace("://", "_")
        .replace(":", "_")
        .replace("/", "")
    )
    filename = f"{ts}_bypass_{stage}_{safe_proxy}.png"
    path = SCREENSHOT_DIR / filename
    path.write_bytes(screenshot_bytes)
    logger.mesg(f"  📸 [{stage}]: {path}")
    return path


def save_debug_html(html: str, stage: str) -> Path:
    """保存调试 HTML。"""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(TZ_SHANGHAI).strftime("%Y%m%d_%H%M%S")
    path = SCREENSHOT_DIR / f"{ts}_{stage}.html"
    path.write_text(html, encoding="utf-8")
    logger.mesg(f"  📄 [{stage}]: {path}")
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
    ):
        self.max_wait_after_click = max_wait_after_click
        self.max_solve_attempts = max_solve_attempts
        self.save_screenshots = save_screenshots
        self.verbose = verbose

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

        # 保存绕过前截图
        if self.save_screenshots:
            try:
                shot = await page.screenshot(full_page=True)
                save_debug_screenshot(shot, "before_click", proxy_url)
            except Exception:
                pass

        # Step 1: 点击 reCAPTCHA checkbox
        clicked = await self._click_checkbox(page)
        if not clicked:
            if self.verbose:
                logger.warn("  × Failed to click reCAPTCHA checkbox")
            return False

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

            success = await self._solve_one_round(
                page, solver, proxy_url, attempt
            )
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
                save_debug_screenshot(shot, "failed", proxy_url)
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
                        logger.mesg(
                            f"    Checkbox {selector} failed: {str(e)[:80]}"
                        )
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
        """执行一轮图片验证解题。"""
        try:
            bframe = page.frame_locator(self.BFRAME_SELECTOR)

            # 1) 截取整个 challenge 区域
            challenge_shot = await page.screenshot(full_page=False)
            if self.save_screenshots:
                save_debug_screenshot(
                    challenge_shot, f"challenge_round{attempt}", proxy_url
                )

            # 2) 截取 bframe 内部的图片区域
            #    找到 challenge 图片容器
            challenge_frame = self._find_challenge_frame(page)
            if not challenge_frame:
                if self.verbose:
                    logger.mesg("    Cannot find challenge frame")
                return False

            # 获取 bframe 的内容截图 (通过 challenge frame 直接截取)
            challenge_image_bytes = await self._capture_challenge_image(
                page, challenge_frame
            )
            if not challenge_image_bytes:
                if self.verbose:
                    logger.mesg("    Failed to capture challenge image")
                return False

            if self.save_screenshots:
                save_debug_screenshot(
                    challenge_image_bytes,
                    f"challenge_image_round{attempt}",
                    proxy_url,
                )

            # 3) 获取题目文本（从 bframe 内提取）
            task_text = await self._get_challenge_task_text(challenge_frame)
            if self.verbose:
                logger.mesg(f"    Task: {task_text or '(unknown)'}")

            # 4) 调用 solver 解题
            cell_indices = await solver.solve(
                image_bytes=challenge_image_bytes,
                task_text=task_text,
            )
            if not cell_indices:
                if self.verbose:
                    logger.mesg("    Solver returned no cells to click")
                return False

            if self.verbose:
                logger.mesg(f"    Solver says click: {cell_indices}")

            # 5) 获取网格布局信息并点击对应格子
            grid_info = await self._detect_grid_layout(challenge_frame)
            if not grid_info:
                if self.verbose:
                    logger.mesg("    Cannot detect grid layout")
                return False

            rows, cols, grid_rect = grid_info
            if self.verbose:
                logger.mesg(
                    f"    Grid: {rows}×{cols}, "
                    f"rect=({grid_rect['x']},{grid_rect['y']},"
                    f"{grid_rect['width']}×{grid_rect['height']})"
                )

            # 6) 模拟点击每个格子
            for idx in cell_indices:
                if idx < 1 or idx > rows * cols:
                    continue
                # 格子编号从 1 开始，按行优先排列
                row = (idx - 1) // cols
                col = (idx - 1) % cols
                cell_w = grid_rect["width"] / cols
                cell_h = grid_rect["height"] / rows
                # 格子中心坐标（相对于 viewport）
                cx = grid_rect["x"] + col * cell_w + cell_w / 2
                cy = grid_rect["y"] + row * cell_h + cell_h / 2
                # 添加随机偏移
                cx += random.uniform(-cell_w * 0.15, cell_w * 0.15)
                cy += random.uniform(-cell_h * 0.15, cell_h * 0.15)

                await self._human_like_click(page, int(cx), int(cy))
                if self.verbose:
                    logger.mesg(
                        f"    ✓ Clicked cell {idx} at ({int(cx)}, {int(cy)})"
                    )
                await asyncio.sleep(random.uniform(0.3, 0.7))

            # 7) 点击 Verify 按钮
            await asyncio.sleep(random.uniform(0.5, 1.0))
            verify_clicked = await self._click_verify(page, challenge_frame)
            if not verify_clicked:
                if self.verbose:
                    logger.mesg("    Cannot find Verify button")
                return False

            # 8) 等待结果
            await asyncio.sleep(random.uniform(1.0, 2.0))
            nav = await self._wait_for_navigation(page, proxy_url, timeout=10.0)
            return nav

        except Exception as e:
            if self.verbose:
                logger.mesg(f"    Solve round error: {str(e)[:200]}")
            return False

    def _find_challenge_frame(self, page):
        """查找 challenge bframe 对应的 Frame 对象。"""
        for frame in page.frames:
            url = frame.url or ""
            if "bframe" in url or (
                "recaptcha" in url and "anchor" not in url
            ):
                return frame
        return None

    async def _capture_challenge_image(self, page, challenge_frame) -> Optional[bytes]:
        """截取 challenge 内图片区域。

        reCAPTCHA 的图片通常在 .rc-imageselect-challenge 容器中。
        """
        try:
            # 尝试获取图片容器的边界
            rect = await challenge_frame.evaluate("""() => {
                // 优先找图片表格
                const table = document.querySelector(
                    'table.rc-imageselect-table-33, '
                    + 'table.rc-imageselect-table-44, '
                    + 'table.rc-imageselect-table'
                );
                if (table) {
                    const r = table.getBoundingClientRect();
                    return {x: r.x, y: r.y, width: r.width, height: r.height};
                }
                // 回退：找 challenge 容器
                const challenge = document.querySelector(
                    '.rc-imageselect-challenge'
                );
                if (challenge) {
                    const r = challenge.getBoundingClientRect();
                    return {x: r.x, y: r.y, width: r.width, height: r.height};
                }
                return null;
            }""")

            if not rect:
                # 最后回退：整个 bframe 截图
                bframe_el = page.locator(self.BFRAME_SELECTOR).first
                if await bframe_el.count() > 0:
                    return await bframe_el.screenshot()
                return None

            # 需要把 bframe 内的坐标转换为页面坐标
            # 先获取 bframe 的位置
            bframe_rect = await page.evaluate("""(selector) => {
                const iframe = document.querySelector(selector);
                if (!iframe) return null;
                const r = iframe.getBoundingClientRect();
                return {x: r.x, y: r.y, width: r.width, height: r.height};
            }""", self.BFRAME_SELECTOR)

            if bframe_rect:
                clip = {
                    "x": bframe_rect["x"] + rect["x"],
                    "y": bframe_rect["y"] + rect["y"],
                    "width": rect["width"],
                    "height": rect["height"],
                }
                return await page.screenshot(clip=clip)

            # 回退
            bframe_el = page.locator(self.BFRAME_SELECTOR).first
            if await bframe_el.count() > 0:
                return await bframe_el.screenshot()
            return None

        except Exception as e:
            if self.verbose:
                logger.mesg(f"    Capture error: {str(e)[:150]}")
            # 回退到 bframe 截图
            try:
                bframe_el = page.locator(self.BFRAME_SELECTOR).first
                if await bframe_el.count() > 0:
                    return await bframe_el.screenshot()
            except Exception:
                pass
            return None

    async def _get_challenge_task_text(self, challenge_frame) -> Optional[str]:
        """从 challenge frame 提取题目文本。"""
        try:
            text = await challenge_frame.evaluate("""() => {
                // 主要的指示文本
                const instructions = document.querySelector(
                    '.rc-imageselect-instructions'
                );
                if (instructions) return instructions.innerText.trim();
                // 回退
                const desc = document.querySelector(
                    '.rc-imageselect-desc, .rc-imageselect-desc-no-canonical'
                );
                if (desc) return desc.innerText.trim();
                return null;
            }""")
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
            info = await challenge_frame.evaluate("""() => {
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
            }""")

            if not info:
                return None

            rows = info["rows"]
            cols = info["cols"]

            # 转换 bframe 内坐标到页面坐标
            bframe_rect = await challenge_frame.evaluate("""() => {
                // 获取 frame 在父页面中的位置 — 这里我们在 frame 内部,
                // 需要通过 window.frameElement 获取
                // 但跨域 frame 无法直接访问 frameElement
                // 返回 null 表示需要从外部获取
                return null;
            }""")

            # 从 page 获取 bframe 位置
            page = challenge_frame.page
            bframe_pos = await page.evaluate("""(selector) => {
                const iframe = document.querySelector(selector);
                if (!iframe) return null;
                const r = iframe.getBoundingClientRect();
                return {x: r.x, y: r.y};
            }""", self.BFRAME_SELECTOR)

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

    async def _click_verify(self, page, challenge_frame) -> bool:
        """点击 Verify / 验证 按钮。"""
        try:
            # 尝试在 challenge frame 中定位按钮
            btn_rect = await challenge_frame.evaluate("""() => {
                const btn = document.querySelector(
                    '#recaptcha-verify-button'
                );
                if (btn) {
                    const r = btn.getBoundingClientRect();
                    return {x: r.x, y: r.y, width: r.width, height: r.height};
                }
                return null;
            }""")

            if btn_rect:
                # 转换到 viewport 坐标
                bframe_pos = await page.evaluate("""(selector) => {
                    const iframe = document.querySelector(selector);
                    if (!iframe) return null;
                    const r = iframe.getBoundingClientRect();
                    return {x: r.x, y: r.y};
                }""", self.BFRAME_SELECTOR)

                if bframe_pos:
                    cx = (
                        bframe_pos["x"]
                        + btn_rect["x"]
                        + btn_rect["width"] / 2
                    )
                    cy = (
                        bframe_pos["y"]
                        + btn_rect["y"]
                        + btn_rect["height"] / 2
                    )
                else:
                    cx = btn_rect["x"] + btn_rect["width"] / 2
                    cy = btn_rect["y"] + btn_rect["height"] / 2

                await self._human_like_click(page, int(cx), int(cy))
                if self.verbose:
                    logger.mesg(
                        f"    ✓ Clicked Verify at ({int(cx)}, {int(cy)})"
                    )
                return True

            # 回退: 通过 frame_locator 点击
            bframe = page.frame_locator(self.BFRAME_SELECTOR)
            verify_btn = bframe.locator("#recaptcha-verify-button")
            if await verify_btn.count() > 0:
                await verify_btn.click(delay=random.randint(50, 150))
                if self.verbose:
                    logger.mesg("    ✓ Clicked Verify button (frame_locator)")
                return True

            return False

        except Exception as e:
            if self.verbose:
                logger.mesg(f"    Verify click error: {str(e)[:120]}")
            return False

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
                    logger.okay(f"    ✓ Navigated to: {url[:80]}")
                try:
                    await page.wait_for_selector(
                        "#search, #rso, div.g", timeout=10000
                    )
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
                save_debug_screenshot(shot, "nav_timeout", proxy_url)
                html = await page.content()
                save_debug_html(html, "nav_timeout")
            except Exception:
                pass

        return False
