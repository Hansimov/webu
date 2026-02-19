import asyncio
import functools
import time

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from tclogger import logger, logstr, brk

from .browser import GeminiBrowser
from .config import GeminiConfig, GeminiConfigType
from .constants import (
    GEMINI_URL,
    GEMINI_POLL_INTERVAL,
    GEMINI_MAX_RETRIES,
    GEMINI_RETRY_DELAY,
    SEL_LOGIN_AVATAR,
    SEL_LOGIN_BUTTON,
    SEL_PRO_BADGE,
    SEL_SIDEBAR_TOGGLE,
    SEL_NEW_CHAT_BUTTON,
    SEL_INPUT_AREA,
    SEL_SEND_BUTTON,
    SEL_TOOLS_BUTTON,
    SEL_IMAGE_GEN_OPTION,
    SEL_MODEL_SELECTOR,
    SEL_RESPONSE_CONTAINER,
    SEL_RESPONSE_TEXT,
    SEL_RESPONSE_IMAGES,
    SEL_RESPONSE_CODE_BLOCKS,
    SEL_LOADING_INDICATOR,
    SEL_STOP_BUTTON,
    SEL_ERROR_MESSAGE,
    SEL_QUOTA_WARNING,
)
from .errors import (
    GeminiError,
    GeminiLoginRequiredError,
    GeminiNetworkError,
    GeminiTimeoutError,
    GeminiResponseParseError,
    GeminiImageGenerationError,
    GeminiPageError,
    GeminiRateLimitError,
)
from .parser import GeminiResponse, GeminiResponseParser


# ── 重试装饰器 ───────────────────────────────────────────────


def with_retry(
    max_retries: int = GEMINI_MAX_RETRIES, delay: float = GEMINI_RETRY_DELAY
):
    """为异步方法添加重试逻辑的装饰器。

    在遇到 GeminiPageError 或 PlaywrightTimeoutError 时自动重试。
    不重试 GeminiLoginRequiredError 和 GeminiRateLimitError。
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except (GeminiLoginRequiredError, GeminiRateLimitError):
                    raise  # 不重试认证和限流错误
                except (GeminiPageError, PlaywrightTimeoutError) as e:
                    last_error = e
                    if attempt < max_retries:
                        logger.warn(f"  ⚠ 操作失败 (尝试 {attempt}/{max_retries}): {e}")
                        await asyncio.sleep(delay * attempt)  # 指数退避
                    else:
                        raise
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        logger.warn(f"  ⚠ 意外错误 (尝试 {attempt}/{max_retries}): {e}")
                        await asyncio.sleep(delay * attempt)
                    else:
                        raise

        return wrapper

    return decorator


class GeminiClient:
    """与 Gemini Web 界面交互的高级客户端。

    提供以下功能：
    - 登录状态检测（多策略回退）
    - 发送文本消息（带重试）
    - 接收和解析响应（流式检测）
    - 图片生成和下载
    - 会话管理（新建会话等）
    - 模型选择（确保 Pro）
    """

    def __init__(self, config: GeminiConfigType = None, config_path: str = None):
        self.config = GeminiConfig(config=config, config_path=config_path)
        self.browser = GeminiBrowser(config=self.config)
        self.parser = GeminiResponseParser()
        self.is_ready = False
        self._image_mode = False
        self._message_count = 0  # 当前会话的消息计数

    async def start(self) -> "GeminiClient":
        """启动 Gemini 客户端（启动浏览器并导航）。"""
        logger.note("> 启动 Gemini 客户端 ...")
        await self.browser.start()
        await self.browser.navigate_to_gemini()
        # 等待页面稳定
        await asyncio.sleep(3)
        self.is_ready = True
        self._message_count = 0
        logger.okay("  ✓ Gemini 客户端就绪")
        return self

    async def stop(self):
        """停止 Gemini 客户端。"""
        logger.note("> 停止 Gemini 客户端 ...")
        self.is_ready = False
        self._message_count = 0
        await self.browser.stop()
        logger.okay("  ✓ Gemini 客户端已停止")

    @property
    def page(self) -> Page:
        return self.browser.page

    # ── 登录检测 ──────────────────────────────────────────────────

    async def check_login_status(self) -> dict:
        """检查用户是否已登录 Gemini。

        使用多种策略检测登录状态，按可靠性排序：
        1. URL 检查（重定向到登录/同意页面 → 未登录）
        2. 头像/个人资料图片检测（已登录）
        3. 登录按钮检测（未登录）
        4. 输入框检测（已登录 - 最终回退）

        返回:
            dict 包含以下键:
            - logged_in (bool): 用户是否已登录
            - is_pro (bool): 用户是否有 Pro 订阅
            - message (str): 可读状态信息
        """
        if not self.is_ready:
            raise GeminiPageError("客户端未启动，请先调用 start()。")

        result = {"logged_in": False, "is_pro": False, "message": ""}

        try:
            # 策略 1：检查 URL 是否已重定向到登录/同意页面
            current_url = self.page.url
            if "consent.google.com" in current_url:
                result["message"] = "在 Google 同意页面，请在浏览器中接受 Cookie。"
                logger.warn(f"  × {result['message']}")
                return result

            if "accounts.google.com" in current_url:
                result["message"] = "用户在登录页面，请完成登录。"
                logger.warn(f"  × {result['message']}")
                return result

            # 策略 2：检查头像/个人资料图片（已登录时可见）
            avatar = await self.page.query_selector(SEL_LOGIN_AVATAR)
            if avatar and await avatar.is_visible():
                result["logged_in"] = True
                result["message"] = "用户已登录"

                # 检测 PRO 订阅 - 通过页面文本搜索
                try:
                    pro_text = await self.page.evaluate(
                        """() => {
                            const body = document.body.innerText;
                            return body.includes('PRO') || body.includes('Pro');
                        }"""
                    )
                    if pro_text:
                        # 进一步验证：PRO 标识在头部区域
                        pro_badge = await self.page.query_selector(SEL_PRO_BADGE)
                        if pro_badge:
                            result["is_pro"] = True
                        else:
                            # 使用 locator 匹配包含 PRO 文本的元素
                            pro_locator = self.page.locator("text=PRO").first
                            try:
                                if await pro_locator.is_visible(timeout=2000):
                                    result["is_pro"] = True
                            except Exception:
                                pass
                except Exception:
                    pass

                if result["is_pro"]:
                    result["message"] = "用户已登录 (PRO)"

                logger.okay(f"  ✓ {result['message']}")
                return result

            # 策略 3：检查登录按钮（未登录时可见）
            login_btn = await self.page.query_selector(SEL_LOGIN_BUTTON)
            if login_btn and await login_btn.is_visible():
                result["message"] = "用户未登录，请手动登录。"
                logger.warn(f"  × {result['message']}")
                return result

            # 策略 4：检测聊天输入框（仅登录后可见）
            input_area = await self.page.query_selector(SEL_INPUT_AREA)
            if input_area and await input_area.is_visible():
                result["logged_in"] = True
                result["message"] = "用户已登录"
                logger.okay(f"  ✓ {result['message']}")
                return result

            # 策略 5：尝试通过 locator 更宽泛地搜索
            try:
                # 未登录页面通常有 "Sign in" / "登录" 字样
                sign_in_locator = self.page.locator(
                    'a:has-text("Sign in"), a:has-text("登录")'
                ).first
                if await sign_in_locator.is_visible(timeout=3000):
                    result["message"] = "用户未登录，页面显示登录链接。"
                    logger.warn(f"  × {result['message']}")
                    return result
            except Exception:
                pass

            result["message"] = "无法确定登录状态，请检查浏览器。"
            logger.warn(f"  ? {result['message']}")
            return result

        except Exception as e:
            result["message"] = f"检查登录状态出错: {e}"
            logger.err(f"  × {result['message']}")
            return result

    async def ensure_logged_in(self):
        """确保用户已登录，未登录则抛出错误。"""
        status = await self.check_login_status()
        if not status["logged_in"]:
            raise GeminiLoginRequiredError(status["message"])
        return status

    # ── 会话管理 ──────────────────────────────────────────────────

    @with_retry(max_retries=2)
    async def new_chat(self):
        """开始新的会话。

        使用直接 URL 导航方式，避免点击 <a> 标签导致创建新标签页。
        优先提取新会话按钮的 href 并在当前标签页中导航。
        """
        logger.note("> 开始新会话 ...")

        # 先清理已有的多余标签页
        await self.browser.close_extra_pages()

        try:
            # 策略 1：提取新会话链接的 href，在当前页面内导航（避免新标签页）
            href = await self.page.evaluate(
                """() => {
                const selectors = [
                    'a[aria-label*="发起新对话"]',
                    'a[aria-label*="New chat"]',
                    'a[href*="/app"]',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.href) return el.href;
                }
                return null;
            }"""
            )

            target_url = href or GEMINI_URL
            logger.mesg(f"  导航到: {target_url}")
            await self.page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=self.config.page_load_timeout,
            )
            try:
                await self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            await asyncio.sleep(2)
            self._message_count = 0
            self._image_mode = False

            # 清理导航可能产生的多余标签页
            await self.browser.close_extra_pages()

            logger.okay("  ✓ 新会话已启动")

        except Exception as e:
            logger.warn(f"  ⚠ 新建会话失败: {e}，回退到基础 URL")
            try:
                await self.browser.navigate_to_gemini()
            except Exception:
                pass
            await asyncio.sleep(2)
            self._message_count = 0
            self._image_mode = False

    async def toggle_sidebar(self):
        """切换侧边栏开/关。"""
        try:
            toggle_btn = await self.page.query_selector(SEL_SIDEBAR_TOGGLE)
            if toggle_btn and await toggle_btn.is_visible():
                await toggle_btn.click()
                await asyncio.sleep(0.5)
                return

            # 回退：使用 locator
            toggle_locator = self.page.locator(SEL_SIDEBAR_TOGGLE).first
            await toggle_locator.click(timeout=5000)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warn(f"  × 切换侧边栏失败: {e}")

    # ── 图片生成模式 ─────────────────────────────────────────────

    @with_retry(max_retries=2)
    async def enable_image_generation(self):
        """通过选择工具启用图片生成模式。

        点击流程：工具按钮 → 弹出菜单 → 选择"生成图片"
        """
        logger.note("> 启用图片生成模式 ...")
        try:
            # 步骤 1：查找并点击工具按钮
            tools_btn = await self._find_element_with_fallback(
                css_selector=SEL_TOOLS_BUTTON,
                text_patterns=["工具", "Tools"],
                element_types="button",
                description="工具按钮",
            )
            await tools_btn.click()
            await asyncio.sleep(1)

            # 步骤 2：在弹出菜单中查找并点击图片生成选项
            img_option = await self._find_element_with_fallback(
                css_selector=SEL_IMAGE_GEN_OPTION,
                text_patterns=["生成图片", "Generate image"],
                element_types="button, span, div, [role='menuitem']",
                description="图片生成选项",
            )
            await img_option.click()
            await asyncio.sleep(1)
            self._image_mode = True
            logger.okay("  ✓ 图片生成模式已启用")

        except GeminiImageGenerationError:
            raise
        except Exception as e:
            raise GeminiImageGenerationError(f"启用图片生成失败: {e}")

    # ── 模型选择 ─────────────────────────────────────────────────

    async def ensure_pro_model(self):
        """确保已选择 Pro 模型。

        检查当前模型选择器状态并尝试切换到 Pro。
        """
        try:
            # 检查是否已有 Pro 按钮/选择器
            pro_selector = await self.page.query_selector(SEL_MODEL_SELECTOR)
            if pro_selector:
                text = await pro_selector.text_content()
                if text and "Pro" in text:
                    logger.mesg("  模型: Pro（已选择）")
                    return

            # 尝试通过 locator 查找
            try:
                pro_btn = self.page.locator('button:has-text("Pro")').first
                if await pro_btn.is_visible(timeout=3000):
                    text = await pro_btn.text_content()
                    if "Pro" in (text or ""):
                        logger.mesg("  模型: Pro（已选择）")
                        return
                    await pro_btn.click()
                    await asyncio.sleep(1)
                    logger.okay("  ✓ Pro 模型已选择")
            except Exception:
                pass

        except Exception as e:
            logger.warn(f"  × 无法验证/设置 Pro 模型: {e}")

    # ── 元素查找（公共辅助方法）────────────────────────────────

    async def _find_element_with_fallback(
        self,
        css_selector: str = None,
        text_patterns: list[str] = None,
        element_types: str = "button",
        description: str = "element",
    ):
        """使用多种策略查找页面元素。

        策略按优先级：
        1. CSS 选择器（query_selector）
        2. 文本内容匹配（locator + filter）
        3. 抛出 GeminiPageError

        Args:
            css_selector: CSS 选择器字符串
            text_patterns: 要匹配的文本模式列表
            element_types: 用于 locator 的元素类型
            description: 元素描述（用于错误消息）
        """
        # 策略 1：CSS 选择器
        if css_selector:
            selectors = [s.strip() for s in css_selector.split(",")]
            for sel in selectors:
                try:
                    el = await self.page.query_selector(sel)
                    if el and await el.is_visible():
                        return el
                except Exception:
                    continue

        # 策略 2：文本内容匹配
        if text_patterns:
            for pattern in text_patterns:
                try:
                    locator = (
                        self.page.locator(element_types).filter(has_text=pattern).first
                    )
                    if await locator.is_visible(timeout=3000):
                        return await locator.element_handle()
                except Exception:
                    continue

        raise GeminiPageError(f"找不到{description}。")

    # ── 消息发送 ─────────────────────────────────────────────────

    async def _find_input_area(self):
        """查找聊天输入框。

        Gemini 使用 contenteditable rich text 编辑器，按优先级尝试多种选择器。
        """
        # 按优先级尝试各个选择器
        selectors = [s.strip() for s in SEL_INPUT_AREA.split(",")]
        for sel in selectors:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    return el
            except Exception:
                continue

        # 更广泛的回退查找
        try:
            el = await self.page.query_selector('[contenteditable="true"]')
            if el and await el.is_visible():
                return el
        except Exception:
            pass

        # 使用 locator 最终回退
        try:
            locator = self.page.locator('[contenteditable="true"]').first
            if await locator.is_visible(timeout=5000):
                return await locator.element_handle()
        except Exception:
            pass

        raise GeminiPageError("找不到聊天输入框。")

    async def _find_send_button(self):
        """查找发送按钮。

        按优先级尝试多种选择器，支持中英文界面。
        Gemini 的发送按钮通常在 rich-textarea 或 input-area-container 附近。
        """
        selectors = [s.strip() for s in SEL_SEND_BUTTON.split(",")]
        for sel in selectors:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    return el
            except Exception:
                continue

        # 回退：在输入框附近查找提交类型按钮
        try:
            el = await self.page.query_selector('button[type="submit"]')
            if el and await el.is_visible():
                return el
        except Exception:
            pass

        # 回退：在 input area 容器附近查找 button（Gemini 发送按钮通常紧邻输入框）
        try:
            send_btn = await self.page.evaluate(
                """() => {
                // 查找 rich-textarea 附近的发送按钮
                const containers = document.querySelectorAll(
                    '.input-area-container, rich-textarea, .input-buttons-wrapper, ' +
                    '.input-area, [class*="input-area"]'
                );
                for (const c of containers) {
                    // 查找容器附近（同级、父级）的 button
                    const parent = c.closest('.input-area-container') || c.parentElement;
                    if (!parent) continue;
                    const btns = parent.querySelectorAll('button');
                    for (const btn of btns) {
                        if (btn.offsetParent === null && btn.offsetWidth === 0) continue;
                        const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                        const tooltip = (btn.getAttribute('mattooltip') || '').toLowerCase();
                        const text = (btn.textContent || '').trim().toLowerCase();
                        if (label.includes('send') || label.includes('发送') ||
                            tooltip.includes('send') || tooltip.includes('发送') ||
                            label.includes('submit') || label.includes('提交')) {
                            return {found: true, selector: 'nearby-button'};
                        }
                    }
                }
                return {found: false};
            }"""
            )
            if send_btn and send_btn.get("found"):
                # 用更精确的方式获取元素
                for sel in [
                    '.input-area-container button[aria-label*="Send" i]',
                    '.input-area-container button[aria-label*="发送"]',
                    '.input-area-container button[mattooltip*="Send" i]',
                    '.input-area-container button[mattooltip*="发送"]',
                ]:
                    try:
                        el = await self.page.query_selector(sel)
                        if el and await el.is_visible():
                            return el
                    except Exception:
                        continue
        except Exception:
            pass

        # 最终回退：用 locator 搜索发送相关按钮
        for text in ["Send", "发送", "Submit", "提交"]:
            try:
                locator = self.page.locator(f'button[aria-label*="{text}"]').first
                if await locator.is_visible(timeout=3000):
                    return await locator.element_handle()
            except Exception:
                continue

        raise GeminiPageError("找不到发送按钮。")

    async def _verify_input_content(self, input_area, expected_text: str) -> bool:
        """验证输入框是否包含期望的文本内容。

        Args:
            input_area: 输入框元素句柄
            expected_text: 期望的文本

        Returns:
            True 如果输入框包含文本的一部分（至少 50%）。
        """
        try:
            actual = await self.page.evaluate(
                "(el) => (el.innerText || el.textContent || '').trim()",
                input_area,
            )
            if not actual:
                return False
            # 检查至少包含前 20 个字符或 50% 的内容
            check_len = min(20, len(expected_text) // 2)
            return (
                expected_text[:check_len] in actual
                or len(actual) >= len(expected_text) * 0.5
            )
        except Exception:
            return False

    async def _type_message(self, text: str):
        """在输入框中输入消息，带验证和多种回退策略。

        策略按优先级：
        1. 聚焦输入框 + page.keyboard.type()
        2. JS 直接设置 innerHTML + 触发 input 事件
        3. 使用 page.fill()（少数情况有效）

        输入后验证文本是否真正出现在输入框中。
        """
        input_area = await self._find_input_area()
        await input_area.click()
        await asyncio.sleep(0.3)

        # 清除现有文本
        await self.page.keyboard.press("Control+a")
        await self.page.keyboard.press("Backspace")
        await asyncio.sleep(0.2)

        # 策略 1：聚焦后用 page.keyboard.type()（更可靠，模拟真实按键到聚焦元素）
        logger.mesg("  输入策略 1: keyboard.type() ...")
        await input_area.focus()
        await asyncio.sleep(0.1)
        await self.page.keyboard.type(text, delay=10)
        await asyncio.sleep(0.5)

        if await self._verify_input_content(input_area, text):
            logger.okay("  ✓ 文本已输入（keyboard.type）")
            return

        # 策略 2：JS 直接插入内容到 contenteditable
        logger.warn("  策略 1 未生效，尝试策略 2: JS 插入 ...")
        await self.page.evaluate(
            """(args) => {
                const [selector, text] = args;
                // 查找 Quill 编辑器或 contenteditable
                const editors = document.querySelectorAll(selector);
                let target = null;
                for (const el of editors) {
                    if (el.offsetParent !== null || el.offsetWidth > 0) {
                        target = el;
                        break;
                    }
                }
                if (!target) {
                    // 回退到任何可见的 contenteditable
                    const all = document.querySelectorAll('[contenteditable="true"]');
                    for (const el of all) {
                        if (el.offsetParent !== null || el.offsetWidth > 0) {
                            target = el;
                            break;
                        }
                    }
                }
                if (target) {
                    target.focus();
                    // 清除并插入新文本
                    target.innerHTML = '<p>' + text + '</p>';
                    // 触发 input / change 事件让框架感知变化
                    target.dispatchEvent(new Event('input', {bubbles: true}));
                    target.dispatchEvent(new Event('change', {bubbles: true}));
                    // Quill 编辑器需要额外的 composition 事件
                    target.dispatchEvent(new Event('compositionend', {bubbles: true}));
                }
            }""",
            [SEL_INPUT_AREA.replace(", ", ",").split(",")[0], text],
        )
        await asyncio.sleep(0.5)

        # 重新获取输入框引用（DOM 可能已变化）
        input_area = await self._find_input_area()
        if await self._verify_input_content(input_area, text):
            logger.okay("  ✓ 文本已输入（JS 插入）")
            return

        # 策略 3：使用 document.execCommand('insertText')
        logger.warn("  策略 2 未生效，尝试策略 3: execCommand ...")
        await input_area.click()
        await asyncio.sleep(0.2)
        await self.page.keyboard.press("Control+a")
        await self.page.keyboard.press("Backspace")
        await asyncio.sleep(0.1)
        await self.page.evaluate(
            """(text) => {
                document.execCommand('insertText', false, text);
            }""",
            text,
        )
        await asyncio.sleep(0.5)

        input_area = await self._find_input_area()
        if await self._verify_input_content(input_area, text):
            logger.okay("  ✓ 文本已输入（execCommand）")
            return

        # 策略 4：clipboard paste（最后手段）
        logger.warn("  策略 3 未生效，尝试策略 4: clipboard paste ...")
        await input_area.click()
        await asyncio.sleep(0.2)
        await self.page.keyboard.press("Control+a")
        await self.page.keyboard.press("Backspace")
        await asyncio.sleep(0.1)
        await self.page.evaluate(
            """async (text) => {
                // 尝试使用 Clipboard API
                try {
                    await navigator.clipboard.writeText(text);
                } catch(e) {
                    // 回退: 创建临时 textarea
                    const ta = document.createElement('textarea');
                    ta.value = text;
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand('copy');
                    document.body.removeChild(ta);
                }
            }""",
            text,
        )
        await self.page.keyboard.press("Control+v")
        await asyncio.sleep(0.5)

        input_area = await self._find_input_area()
        if await self._verify_input_content(input_area, text):
            logger.okay("  ✓ 文本已输入（clipboard paste）")
            return

        # 所有策略都失败
        logger.err("  × 所有输入策略均未成功将文本输入到编辑器")
        raise GeminiPageError("无法将文本输入到聊天输入框，所有策略均失败。")

    async def _submit_message(self):
        """提交已输入的消息，带验证。

        先尝试点击发送按钮，失败则使用 Enter 键提交。
        提交后验证输入框是否被清空（表示消息已发送）。
        """
        # 记录提交前的输入框内容长度
        pre_submit_content = ""
        try:
            input_area = await self._find_input_area()
            pre_submit_content = await self.page.evaluate(
                "(el) => (el.innerText || el.textContent || '').trim()",
                input_area,
            )
        except Exception:
            pass

        if not pre_submit_content:
            logger.warn("  ⚠ 提交前输入框为空，消息可能未输入成功")

        # 尝试点击发送按钮
        sent_via = None
        try:
            send_btn = await self._find_send_button()
            await send_btn.click()
            sent_via = "button"
            logger.mesg("  提交方式: 发送按钮")
        except GeminiPageError:
            # 回退：按回车键
            logger.mesg("  发送按钮未找到，使用 Enter 键提交")
            await self.page.keyboard.press("Enter")
            sent_via = "enter"

        await asyncio.sleep(1.5)

        # 验证提交成功：输入框应被清空，或出现加载指示器/新响应容器
        submit_ok = False

        # 检查 1：输入框是否被清空
        try:
            input_area = await self._find_input_area()
            post_content = await self.page.evaluate(
                "(el) => (el.innerText || el.textContent || '').trim()",
                input_area,
            )
            if len(post_content) < len(pre_submit_content) * 0.3:
                submit_ok = True
                logger.okay(f"  ✓ 消息已发送（输入框已清空, via {sent_via}）")
        except Exception:
            pass

        # 检查 2：是否出现加载指示器
        if not submit_ok:
            try:
                loading = await self.page.query_selector(SEL_LOADING_INDICATOR)
                if loading and await loading.is_visible():
                    submit_ok = True
                    logger.okay(f"  ✓ 消息已发送（检测到加载指示器, via {sent_via}）")
            except Exception:
                pass

        # 检查 3：是否出现停止按钮（流式响应）
        if not submit_ok:
            try:
                stop_btn = await self.page.query_selector(SEL_STOP_BUTTON)
                if stop_btn and await stop_btn.is_visible():
                    submit_ok = True
                    logger.okay(f"  ✓ 消息已发送（检测到停止按钮, via {sent_via}）")
            except Exception:
                pass

        if not submit_ok:
            # 等待更长时间再检查一次
            await asyncio.sleep(2)

            # 最终检查：查看页面上是否有用户消息气泡
            user_msg_found = await self.page.evaluate(
                """() => {
                    // 检查是否有新的用户消息容器
                    const userMsgs = document.querySelectorAll(
                        'user-query, .user-query, [class*="user-message"], ' +
                        '[class*="query-content"], message-content'
                    );
                    // 检查加载/思考相关的 DOM
                    const thinking = document.querySelectorAll(
                        'mat-progress-bar, [class*="loading"], [class*="thinking"], ' +
                        '[class*="progress"], .response-streaming'
                    );
                    return {
                        user_msgs: userMsgs.length,
                        thinking: thinking.length,
                        any_activity: userMsgs.length > 0 || thinking.length > 0,
                    };
                }"""
            )
            if user_msg_found.get("any_activity"):
                submit_ok = True
                logger.okay(f"  ✓ 消息已发送（检测到页面活动, via {sent_via}）")
            else:
                logger.warn(
                    f"  ⚠ 提交验证未通过 (via {sent_via})。"
                    f"输入框内容: '{pre_submit_content[:50]}...'"
                    f" → '{post_content[:50] if 'post_content' in dir() else '?'}'"
                )

    async def _count_response_containers(self) -> int:
        """计算当前页面上的模型响应数量（用 model-response 元素计数）。"""
        count = await self.page.evaluate(
            """() => {
            return document.querySelectorAll('model-response').length;
        }"""
        )
        return count

    async def _get_latest_response_content(self) -> dict:
        """从页面获取最新模型响应的内容。

        使用 JS 精确定位最新的 model-response 元素，
        然后从中提取 message-content 的 innerHTML 和 innerText。

        Returns:
            dict: {html: str, text: str, length: int} 或空 dict。
        """
        return await self.page.evaluate(
            """() => {
            // 优先用 model-response 定位最新响应
            const modelResponses = document.querySelectorAll('model-response');
            if (modelResponses.length === 0) return {html: '', text: '', length: 0};

            const lastResponse = modelResponses[modelResponses.length - 1];

            // 在 model-response 内查找 message-content（实际文本容器）
            const msgContent = lastResponse.querySelector('message-content');
            if (msgContent) {
                const html = msgContent.innerHTML;
                const text = (msgContent.innerText || '').trim();
                return {html, text, length: html.length};
            }

            // 回退：在 model-response 内查找 .markdown 或 .response-text
            const mdEl = lastResponse.querySelector('.markdown, .markdown-main-panel, .response-text');
            if (mdEl) {
                const html = mdEl.innerHTML;
                const text = (mdEl.innerText || '').trim();
                return {html, text, length: html.length};
            }

            // 最终回退：model-response 的 innerText
            const text = (lastResponse.innerText || '').trim();
            const html = lastResponse.innerHTML;
            return {html, text, length: html.length};
        }"""
        )

    async def _check_for_errors(self) -> str | None:
        """检查页面上是否有错误消息或配额警告。

        Returns:
            错误消息字符串，如果没有错误则返回 None。
        """
        # 检查错误消息
        error_el = await self.page.query_selector(SEL_ERROR_MESSAGE)
        if error_el:
            try:
                if await error_el.is_visible():
                    error_text = await error_el.text_content()
                    if error_text and error_text.strip():
                        return error_text.strip()
            except Exception:
                pass

        # 检查配额/限流警告
        quota_el = await self.page.query_selector(SEL_QUOTA_WARNING)
        if quota_el:
            try:
                if await quota_el.is_visible():
                    quota_text = await quota_el.text_content()
                    if quota_text and quota_text.strip():
                        return f"配额限制: {quota_text.strip()}"
            except Exception:
                pass

        return None

    async def _wait_for_response(self, timeout: int = None) -> str:
        """等待 Gemini 完成响应生成。

        使用多种信号检测响应完成：
        1. 新的 model-response 元素出现
        2. 加载指示器/停止按钮消失
        3. message-content 内容连续稳定（3 次轮询不变）
        4. 错误检测

        Returns:
            最新 message-content 的 innerHTML。
        """
        timeout = timeout or self.config.response_timeout
        t_start = time.time()
        elapsed = 0

        # 记录发送前的模型响应数量
        initial_container_count = await self._count_response_containers()

        logger.note("> 等待响应 ...")

        # 阶段 1：等待响应开始出现
        response_started = False
        while elapsed < timeout:
            # 检查错误
            error_msg = await self._check_for_errors()
            if error_msg:
                if (
                    "quota" in error_msg.lower()
                    or "limit" in error_msg.lower()
                    or "配额" in error_msg
                ):
                    raise GeminiRateLimitError(error_msg)
                raise GeminiPageError(f"Gemini 错误: {error_msg}")

            # 检查是否有新的 model-response
            current_count = await self._count_response_containers()
            if current_count > initial_container_count:
                response_started = True
                break

            # 检查加载指示器（表示响应正在处理中）
            loading = await self.page.query_selector(SEL_LOADING_INDICATOR)
            if loading:
                try:
                    if await loading.is_visible():
                        response_started = True
                        break
                except Exception:
                    pass

            # 检查 message-content 内容变化
            resp = await self._get_latest_response_content()
            if resp.get("length", 0) > 10:
                response_started = True
                break

            await asyncio.sleep(GEMINI_POLL_INTERVAL / 1000)
            elapsed = (time.time() - t_start) * 1000

        if not response_started:
            raise GeminiTimeoutError(
                "等待响应开始超时，可能输入未成功提交。",
                timeout_ms=timeout,
            )

        # 阶段 2：等待响应完成
        logger.mesg("  响应已开始，等待完成 ...")
        stable_count = 0
        last_content = ""
        last_content_length = 0

        while elapsed < timeout:
            # 检查错误
            error_msg = await self._check_for_errors()
            if error_msg:
                if (
                    "quota" in error_msg.lower()
                    or "limit" in error_msg.lower()
                    or "配额" in error_msg
                ):
                    raise GeminiRateLimitError(error_msg)
                logger.warn(f"  ⚠ 页面错误: {error_msg}")

            # 检查是否仍在加载/生成
            is_loading = False
            loading = await self.page.query_selector(SEL_LOADING_INDICATOR)
            if loading:
                try:
                    is_loading = await loading.is_visible()
                except Exception:
                    pass

            is_generating = False
            stop_btn = await self.page.query_selector(SEL_STOP_BUTTON)
            if stop_btn:
                try:
                    is_generating = await stop_btn.is_visible()
                except Exception:
                    pass

            # 获取最新响应内容（精确定位 message-content）
            resp = await self._get_latest_response_content()
            current_content = resp.get("html", "")

            # 检查内容稳定性
            if (
                current_content == last_content
                and not is_loading
                and not is_generating
                and len(current_content) > 0
            ):
                stable_count += 1
                if stable_count >= 3:  # 连续 3 次稳定 → 认为完成
                    break
            else:
                stable_count = 0
                last_content = current_content

            # 显示进度
            current_length = len(current_content)
            if current_length > last_content_length + 100:
                logger.mesg(f"  接收中... ({current_length} chars)")
                last_content_length = current_length

            await asyncio.sleep(GEMINI_POLL_INTERVAL / 1000)
            elapsed = (time.time() - t_start) * 1000

        if elapsed >= timeout:
            logger.warn("  ⚠ 响应可能不完整（已超时）")

        total_s = time.time() - t_start
        logger.okay(f"  ✓ 响应已收到 ({total_s:.1f}s)")
        return last_content

    async def _extract_images(self, download_base64: bool = True) -> list[dict]:
        """从最新响应中提取图片数据。

        支持多种图片来源：
        - 标准 <img> 标签（含 http/https/blob/data URL）
        - Canvas 元素（转换为 base64）
        - Blob URL（在页面内通过 canvas 转换，避免 URL 失效）

        Args:
            download_base64: 是否将图片下载为 base64（http/https URL）

        Returns:
            图片数据字典列表，每个字典可能包含 base64_data 和 mime_type。
        """
        images_data = []
        try:
            # 精确定位最新 model-response 中的图片
            model_responses = await self.page.query_selector_all("model-response")
            if not model_responses:
                return images_data

            last_response = model_responses[-1]

            # 等待图片加载完成（最长 20 秒）
            for attempt in range(40):
                has_images = await self.page.evaluate(
                    """(container) => {
                        const imgs = container.querySelectorAll('img');
                        const canvases = container.querySelectorAll('canvas');
                        return imgs.length > 0 || canvases.length > 0;
                    }""",
                    last_response,
                )
                if not has_images:
                    if attempt >= 5:
                        break
                    await asyncio.sleep(0.5)
                    continue

                all_loaded = await self.page.evaluate(
                    """(container) => {
                        const imgs = container.querySelectorAll('img');
                        if (imgs.length === 0) return true;
                        return Array.from(imgs).every(img =>
                            img.complete && (img.naturalHeight > 0 || img.src.startsWith('data:'))
                        );
                    }""",
                    last_response,
                )
                if all_loaded:
                    break
                await asyncio.sleep(0.5)

            # 统一使用 JS 提取所有图片数据（效率更高，减少 round-trip）
            images_data = await self.page.evaluate(
                """(container) => {
                    const results = [];

                    // 1. 提取 <img> 标签
                    const imgs = container.querySelectorAll('img');
                    for (const img of imgs) {
                        const src = img.src || img.getAttribute('src') || '';
                        if (!src) continue;

                        const width = img.naturalWidth || img.width || 0;
                        const height = img.naturalHeight || img.height || 0;

                        // 跳过小图标 (< 50px)
                        if (width > 0 && height > 0 && (width < 50 || height < 50)) continue;

                        const entry = {
                            src: src,
                            alt: img.alt || img.getAttribute('alt') || '',
                            width: width,
                            height: height,
                            type: 'img',
                        };

                        // 对于 data: URL，直接提取 base64
                        if (src.startsWith('data:')) {
                            const parts = src.split(',');
                            if (parts.length >= 2) {
                                const mimeMatch = parts[0].match(/data:([^;]+)/);
                                entry.mime_type = mimeMatch ? mimeMatch[1] : 'image/png';
                                entry.base64_data = parts.slice(1).join(',');
                            }
                        }

                        // 对于 blob: URL，通过 canvas 转换为 base64（blob URL 会失效）
                        if (src.startsWith('blob:') && img.complete && img.naturalWidth > 0) {
                            try {
                                const canvas = document.createElement('canvas');
                                canvas.width = img.naturalWidth;
                                canvas.height = img.naturalHeight;
                                const ctx = canvas.getContext('2d');
                                ctx.drawImage(img, 0, 0);
                                const dataUrl = canvas.toDataURL('image/png');
                                const b64 = dataUrl.split(',')[1];
                                if (b64) {
                                    entry.base64_data = b64;
                                    entry.mime_type = 'image/png';
                                }
                            } catch(e) {
                                // CORS 限制，标记需要后续通过 fetch 下载
                                entry.needs_download = true;
                            }
                        }

                        results.push(entry);
                    }

                    // 2. 提取 <canvas> 元素（Gemini 可能用 canvas 渲染生成的图片）
                    const canvases = container.querySelectorAll('canvas');
                    for (const canvas of canvases) {
                        if (canvas.width < 50 || canvas.height < 50) continue;
                        try {
                            const dataUrl = canvas.toDataURL('image/png');
                            const b64 = dataUrl.split(',')[1];
                            if (b64 && b64.length > 100) {
                                results.push({
                                    src: '',
                                    alt: 'canvas-image',
                                    width: canvas.width,
                                    height: canvas.height,
                                    type: 'canvas',
                                    base64_data: b64,
                                    mime_type: 'image/png',
                                });
                            }
                        } catch(e) {
                            // Canvas might be tainted by CORS
                        }
                    }

                    return results;
                }""",
                last_response,
            )

            # 对于需要下载的图片（http/https URL 或 CORS 限制的 blob URL），
            # 使用 browser 方法在页面上下文中通过 fetch 下载
            if download_base64:
                for img_data in images_data:
                    src = img_data.get("src", "")
                    if (
                        src
                        and not src.startswith("data:")
                        and not img_data.get("base64_data")
                        and (
                            img_data.get("needs_download")
                            or not src.startswith("blob:")
                        )
                        and img_data.get("width", 0) >= 50
                        and img_data.get("height", 0) >= 50
                    ):
                        try:
                            dl_result = await self.browser.download_image_as_base64(src)
                            if dl_result.get("base64_data"):
                                img_data["base64_data"] = dl_result["base64_data"]
                                img_data["mime_type"] = dl_result.get(
                                    "mime_type", "image/png"
                                )
                        except Exception as dl_err:
                            logger.warn(f"  × 下载图片失败: {dl_err}")

        except Exception as e:
            logger.warn(f"  × 提取图片出错: {e}")

        return images_data

    @with_retry(max_retries=2)
    async def send_message(
        self, text: str, image_mode: bool = False, download_images: bool = True
    ) -> GeminiResponse:
        """向 Gemini 发送消息并获取响应。

        参数:
            text: 要发送的消息文本
            image_mode: 是否使用图片生成模式
            download_images: 是否将响应中的图片下载为 base64

        返回:
            GeminiResponse 包含解析后的文本、Markdown、图片等
        """
        if not self.is_ready:
            raise GeminiPageError("客户端未启动，请先调用 start()。")

        await self.ensure_logged_in()

        # 清理多余标签页
        await self.browser.close_extra_pages()

        logger.note(f"> 发送消息: {logstr.mesg(brk(text[:100]))}")

        # 如果请求则启用图片模式
        if image_mode and not self._image_mode:
            await self.enable_image_generation()

        # 输入并提交
        await self._type_message(text)
        await self._submit_message()

        # 等待响应
        timeout = (
            self.config.image_generation_timeout
            if image_mode or self._image_mode
            else self.config.response_timeout
        )
        response_html = await self._wait_for_response(timeout=timeout)

        # 提取图片
        images_data = await self._extract_images(download_base64=download_images)

        # 解析响应
        response = self.parser.parse(
            html_content=response_html,
            image_data_list=images_data if images_data else None,
        )

        # 图片数据已由 parser.parse_images_from_elements() 完整处理，
        # 包括 base64_data 和 mime_type，无需再额外补充。

        # 使用后重置图片模式
        if image_mode:
            self._image_mode = False

        self._message_count += 1

        # 日志
        logger.mesg(f"  文本长度: {len(response.text)}")
        if response.images:
            logger.mesg(f"  图片数: {len(response.images)}")
            for i, img in enumerate(response.images):
                has_data = "✓" if img.base64_data else "×"
                logger.mesg(
                    f"    #{i+1}: {img.width}x{img.height} "
                    f"base64={has_data} alt={brk(img.alt[:50])}"
                )
        if response.code_blocks:
            logger.mesg(f"  代码块数: {len(response.code_blocks)}")

        return response

    async def generate_image(self, prompt: str) -> GeminiResponse:
        """使用 Gemini 的图片生成工具生成图片。

        参数:
            prompt: 要生成的图片描述

        返回:
            GeminiResponse 包含生成的图片（含 base64 数据）
        """
        logger.note(f"> 生成图片: {logstr.mesg(brk(prompt[:100]))}")
        return await self.send_message(prompt, image_mode=True, download_images=True)

    def save_images(
        self,
        response: GeminiResponse,
        output_dir: str = "data/images",
        prefix: str = "",
    ) -> list[str]:
        """将响应中的图片保存到磁盘。

        参数:
            response: 包含图片的 GeminiResponse
            output_dir: 保存目录（默认 data/images）
            prefix: 文件名前缀

        返回:
            保存成功的文件路径列表
        """
        if not response.images:
            logger.mesg("  没有图片需要保存")
            return []

        from pathlib import Path

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        saved_paths = []
        timestamp = int(time.time())

        for i, img in enumerate(response.images):
            if not img.base64_data:
                logger.warn(f"  × 图片 #{i+1} 无 base64 数据，跳过")
                continue

            ext = img.get_extension()
            prefix_part = f"{prefix}_" if prefix else ""
            filename = f"{prefix_part}{timestamp}_{i+1}.{ext}"
            filepath = output_path / filename

            try:
                img.save_to_file(str(filepath))
                saved_paths.append(str(filepath))
                size_info = f" ({img.width}x{img.height})" if img.width else ""
                logger.okay(f"  + 图片已保存: {filepath}{size_info}")
            except Exception as e:
                logger.warn(f"  × 保存图片 #{i+1} 失败: {e}")

        if saved_paths:
            logger.okay(f"  ✓ 共保存 {len(saved_paths)} 张图片到 {output_dir}")

        return saved_paths

    async def screenshot(self, path: str = None) -> bytes:
        """对当前状态截图。"""
        return await self.browser.screenshot(path=path)

    async def get_status(self) -> dict:
        """获取客户端完整状态信息。"""
        status = {
            "is_ready": self.is_ready,
            "message_count": self._message_count,
            "image_mode": self._image_mode,
        }
        if self.is_ready:
            try:
                login = await self.check_login_status()
                status.update(login)
            except Exception as e:
                status["login_check_error"] = str(e)

            page_info = await self.browser.get_page_info()
            status["page"] = page_info

        return status

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
        return False
