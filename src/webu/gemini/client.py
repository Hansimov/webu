import asyncio

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from tclogger import logger, logstr, brk, Runtimer

from .browser import GeminiBrowser
from .config import GeminiConfig, GeminiConfigType
from .constants import (
    GEMINI_URL,
    GEMINI_POLL_INTERVAL,
    SEL_LOGIN_AVATAR,
    SEL_LOGIN_BUTTON,
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
)
from .errors import (
    GeminiError,
    GeminiLoginRequiredError,
    GeminiNetworkError,
    GeminiTimeoutError,
    GeminiResponseParseError,
    GeminiImageGenerationError,
    GeminiPageError,
)
from .parser import GeminiResponse, GeminiResponseParser


class GeminiClient:
    """与 Gemini Web 界面交互的高级客户端。

    提供以下功能：
    - 登录状态检测
    - 发送文本消息
    - 接收和解析响应
    - 图片生成
    - 会话管理（新建会话等）
    """

    def __init__(self, config: GeminiConfigType = None, config_path: str = None):
        self.config = GeminiConfig(config=config, config_path=config_path)
        self.browser = GeminiBrowser(config=self.config)
        self.parser = GeminiResponseParser()
        self.is_ready = False
        self._image_mode = False

    async def start(self) -> "GeminiClient":
        """启动 Gemini 客户端（启动浏览器并导航）。"""
        logger.note("> 启动 Gemini 客户端 ...")
        await self.browser.start()
        await self.browser.navigate_to_gemini()
        # 等待页面稳定
        await asyncio.sleep(3)
        self.is_ready = True
        logger.okay("  ✓ Gemini 客户端就绪")
        return self

    async def stop(self):
        """停止 Gemini 客户端。"""
        logger.note("> 停止 Gemini 客户端 ...")
        self.is_ready = False
        await self.browser.stop()
        logger.okay("  ✓ Gemini 客户端已停止")

    @property
    def page(self) -> Page:
        return self.browser.page

    # ── 登录检测 ──────────────────────────────────────────────────

    async def check_login_status(self) -> dict:
        """检查用户是否已登录 Gemini。

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
            # 检查是否在同意或重定向页面
            current_url = self.page.url
            if "consent.google.com" in current_url:
                result["message"] = "在 Google 同意页面，请在浏览器中接受 Cookie。"
                logger.warn(f"  × {result['message']}")
                return result

            if "accounts.google.com" in current_url:
                result["message"] = "用户在登录页面，请完成登录。"
                logger.warn(f"  × {result['message']}")
                return result

            # 检查头像/个人资料图片（表示已登录）
            avatar = await self.page.query_selector(SEL_LOGIN_AVATAR)
            if avatar:
                result["logged_in"] = True
                result["message"] = "用户已登录"
                page_content = await self.page.content()
                if "PRO" in page_content:
                    result["is_pro"] = True
                    result["message"] = "用户已登录 (PRO)"

                logger.okay(f"  ✓ {result['message']}")
                return result

            # 检查登录按钮（表示未登录）
            login_btn = await self.page.query_selector(SEL_LOGIN_BUTTON)
            if login_btn:
                result["message"] = "用户未登录，请手动登录。"
                logger.warn(f"  × {result['message']}")
                return result

            # 深入检查 —— 查找聊天输入框（仅登录后可见）
            input_area = await self.page.query_selector(SEL_INPUT_AREA)
            if input_area:
                result["logged_in"] = True
                result["message"] = "User is logged in"
                logger.okay(f"  ✓ {result['message']}")
                return result

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

    async def new_chat(self):
        """开始新的会话。"""
        logger.note("> 开始新会话 ...")
        try:
            # 尝试点击新建会话按钮
            new_chat_btn = await self.page.query_selector(SEL_NEW_CHAT_BUTTON)
            if new_chat_btn:
                await new_chat_btn.click()
                await asyncio.sleep(2)
                logger.okay("  ✓ 新会话已启动")
                return

            # 回退：直接导航到 Gemini URL
            await self.browser.navigate_to_gemini()
            await asyncio.sleep(2)
            logger.okay("  ✓ 新会话已启动（通过导航）")
        except Exception as e:
            logger.warn(f"  × 新建会话失败: {e}")
            # 最后回退
            await self.browser.navigate_to_gemini()

    async def toggle_sidebar(self):
        """切换侧边栏开/关。"""
        try:
            toggle_btn = await self.page.query_selector(SEL_SIDEBAR_TOGGLE)
            if toggle_btn:
                await toggle_btn.click()
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.warn(f"  × 切换侧边栏失败: {e}")

    # ── 图片生成模式 ─────────────────────────────────────────────

    async def enable_image_generation(self):
        """通过选择工具启用图片生成模式。"""
        logger.note("> 启用图片生成模式 ...")
        try:
            # 点击工具按钮
            tools_btn = await self.page.query_selector(SEL_TOOLS_BUTTON)
            if not tools_btn:
                # 尝试更通用的查找方式
                tools_btn = (
                    await self.page.locator("button")
                    .filter(has_text="工具")
                    .or_(self.page.locator("button").filter(has_text="Tools"))
                    .first.element_handle()
                )

            if tools_btn:
                await tools_btn.click()
                await asyncio.sleep(1)

                # 点击图片生成选项
                img_option = await self.page.query_selector(SEL_IMAGE_GEN_OPTION)
                if not img_option:
                    img_option = (
                        await self.page.locator("button, span, div")
                        .filter(has_text="生成图片")
                        .or_(
                            self.page.locator("button, span, div").filter(
                                has_text="Generate image"
                            )
                        )
                        .first.element_handle()
                    )

                if img_option:
                    await img_option.click()
                    await asyncio.sleep(1)
                    self._image_mode = True
                    logger.okay("  ✓ 图片生成模式已启用")
                    return
                else:
                    raise GeminiImageGenerationError("在工具菜单中找不到图片生成选项。")
            else:
                raise GeminiImageGenerationError("找不到工具按钮。")

        except GeminiImageGenerationError:
            raise
        except Exception as e:
            raise GeminiImageGenerationError(f"启用图片生成失败: {e}")

    # ── 模型选择 ─────────────────────────────────────────────────

    async def ensure_pro_model(self):
        """确保已选择 Pro 模型。"""
        try:
            page_content = await self.page.content()
            # 检查是否已选择 Pro
            pro_selector = await self.page.query_selector(SEL_MODEL_SELECTOR)
            if pro_selector:
                text = await pro_selector.text_content()
                if text and "Pro" in text:
                    logger.mesg("  模型: Pro（已选择）")
                    return

            # 尝试查找并点击 Pro 选项
            pro_btn = (
                await self.page.locator("button")
                .filter(has_text="Pro")
                .first.element_handle()
            )
            if pro_btn:
                await pro_btn.click()
                await asyncio.sleep(1)
                logger.okay("  ✓ Pro 模型已选择")
        except Exception as e:
            logger.warn(f"  × 无法验证/设置 Pro 模型: {e}")

    # ── 消息发送 ─────────────────────────────────────────────────

    async def _find_input_area(self) -> object:
        """查找聊天输入框。"""
        # 尝试多个选择器
        selectors = SEL_INPUT_AREA.split(", ")
        for sel in selectors:
            el = await self.page.query_selector(sel.strip())
            if el:
                return el

        # 更广泛的回退查找
        el = await self.page.query_selector('[contenteditable="true"]')
        if el:
            return el

        raise GeminiPageError("找不到聊天输入框。")

    async def _find_send_button(self) -> object:
        """查找发送按钮。"""
        selectors = SEL_SEND_BUTTON.split(", ")
        for sel in selectors:
            el = await self.page.query_selector(sel.strip())
            if el:
                return el

        # 在输入框附近查找提交类型按钮
        el = await self.page.query_selector('button[type="submit"]')
        if el:
            return el

        raise GeminiPageError("找不到发送按钮。")

    async def _type_message(self, text: str):
        """在输入框中输入消息。"""
        input_area = await self._find_input_area()
        await input_area.click()
        await asyncio.sleep(0.3)

        # 清除现有文本
        await self.page.keyboard.press("Control+a")
        await self.page.keyboard.press("Backspace")
        await asyncio.sleep(0.2)

        # 输入消息
        await input_area.type(text, delay=20)
        await asyncio.sleep(0.3)

    async def _submit_message(self):
        """提交已输入的消息。"""
        try:
            send_btn = await self._find_send_button()
            await send_btn.click()
        except GeminiPageError:
            # 回退：按回车键
            await self.page.keyboard.press("Enter")
        await asyncio.sleep(1)

    async def _wait_for_response(self, timeout: int = None) -> str:
        """等待 Gemini 完成响应生成。

        返回响应容器的 innerHTML。
        """
        timeout = timeout or self.config.response_timeout
        timer = Runtimer()
        timer.start_time()
        elapsed = 0

        logger.note("> 等待响应 ...")

        # 先等待响应开始出现
        response_started = False
        while elapsed < timeout:
            # 检查错误消息
            error_el = await self.page.query_selector(SEL_ERROR_MESSAGE)
            if error_el:
                error_text = await error_el.text_content()
                if error_text and error_text.strip():
                    raise GeminiPageError(f"Gemini error: {error_text.strip()}")

            # 检查响应容器
            response_containers = await self.page.query_selector_all(
                SEL_RESPONSE_CONTAINER
            )
            if response_containers:
                last_container = response_containers[-1]
                content = await last_container.inner_html()
                if content and content.strip():
                    response_started = True
                    break

            await asyncio.sleep(GEMINI_POLL_INTERVAL / 1000)
            elapsed = timer.elapsed_time() * 1000

        if not response_started:
            raise GeminiTimeoutError(
                "等待响应开始超时。",
                timeout_ms=timeout,
            )

        # 现在等待响应完成（不再有加载指示器）
        logger.mesg("  响应已开始，等待完成 ...")
        stable_count = 0
        last_content = ""

        while elapsed < timeout:
            # 检查是否仍在加载
            loading = await self.page.query_selector(SEL_LOADING_INDICATOR)
            stop_btn = await self.page.query_selector(SEL_STOP_BUTTON)

            # 获取当前响应内容
            response_containers = await self.page.query_selector_all(
                SEL_RESPONSE_CONTAINER
            )
            if response_containers:
                last_container = response_containers[-1]
                current_content = await last_container.inner_html()
            else:
                current_content = ""

            # 检查稳定性（内容不再变化）
            if current_content == last_content and not loading and not stop_btn:
                stable_count += 1
                if stable_count >= 3:  # 连续 3 次检查稳定
                    break
            else:
                stable_count = 0
                last_content = current_content

            await asyncio.sleep(GEMINI_POLL_INTERVAL / 1000)
            elapsed = timer.elapsed_time() * 1000

        if elapsed >= timeout:
            logger.warn("  ⚠ 响应可能不完整（已超时）")

        logger.okay(f"  ✓ 响应已收到 ({timer.elapsed_time():.1f}s)")
        return last_content

    async def _extract_images(self) -> list[dict]:
        """从最新响应中提取图片数据。"""
        images_data = []
        try:
            response_containers = await self.page.query_selector_all(
                SEL_RESPONSE_CONTAINER
            )
            if not response_containers:
                return images_data

            last_container = response_containers[-1]
            images = await last_container.query_selector_all("img")

            for img in images:
                img_data = await self.page.evaluate(
                    """(el) => ({
                        src: el.src || el.getAttribute('src') || '',
                        alt: el.alt || el.getAttribute('alt') || '',
                        width: el.naturalWidth || el.width || 0,
                        height: el.naturalHeight || el.height || 0,
                    })""",
                    img,
                )
                if img_data.get("src"):
                    images_data.append(img_data)
        except Exception as e:
            logger.warn(f"  × 提取图片出错: {e}")

        return images_data

    async def send_message(self, text: str, image_mode: bool = False) -> GeminiResponse:
        """向 Gemini 发送消息并获取响应。

        参数:
            text: 要发送的消息文本
            image_mode: 是否使用图片生成模式

        返回:
            GeminiResponse 包含解析后的文本、Markdown、图片等
        """
        if not self.is_ready:
            raise GeminiPageError("客户端未启动，请先调用 start()。")

        await self.ensure_logged_in()

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
        images_data = await self._extract_images()

        # 解析响应
        response = self.parser.parse(
            html_content=response_html,
            image_data_list=images_data,
        )

        # 使用后重置图片模式
        if image_mode:
            self._image_mode = False

        logger.mesg(f"  文本长度: {len(response.text)}")
        if response.images:
            logger.mesg(f"  图片数: {len(response.images)}")
        if response.code_blocks:
            logger.mesg(f"  代码块数: {len(response.code_blocks)}")

        return response

    async def generate_image(self, prompt: str) -> GeminiResponse:
        """使用 Gemini 的图片生成工具生成图片。

        参数:
            prompt: 要生成的图片描述

        返回:
            GeminiResponse 包含生成的图片
        """
        logger.note(f"> 生成图片: {logstr.mesg(brk(prompt[:100]))}")
        return await self.send_message(prompt, image_mode=True)

    async def screenshot(self, path: str = None) -> bytes:
        """对当前状态截图。"""
        return await self.browser.screenshot(path=path)

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
        return False
