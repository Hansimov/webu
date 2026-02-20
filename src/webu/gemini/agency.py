"""GeminiAgency: 浏览器交互代理层。

封装所有与 Gemini 网页的浏览器交互逻辑，提供清晰的接口供 FastAPI 服务器调用。
"""

import asyncio
import functools
import time

from pathlib import Path
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
    SEL_TOOL_OPTION,
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
    SEL_FILE_UPLOAD_BUTTON,
    SEL_FILE_UPLOAD_INPUT,
    SEL_ATTACHMENT_CHIP,
    SEL_ATTACHMENT_REMOVE,
    SEL_CHAT_LIST_ITEM,
    SEL_MODE_OPTION,
    SEL_USER_MESSAGE,
    SEL_MODEL_MESSAGE,
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
    GeminiServerRollbackError,
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
                except (
                    GeminiLoginRequiredError,
                    GeminiRateLimitError,
                    GeminiServerRollbackError,
                ):
                    raise  # 不重试认证、限流和回退错误（回退在内部已处理）
                except (GeminiPageError, PlaywrightTimeoutError) as e:
                    last_error = e
                    if attempt < max_retries:
                        logger.warn(f"  ⚠ 操作失败 (尝试 {attempt}/{max_retries}): {e}")
                        await asyncio.sleep(delay * attempt)
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


class GeminiAgency:
    """与 Gemini Web 界面交互的浏览器代理层。

    封装所有页面交互逻辑，为 FastAPI 服务器提供统一接口：
    - 浏览器状态查询
    - 聊天会话管理（新建、切换）
    - 模式和工具管理
    - 输入框操作（清空、设置、追加、读取）
    - 消息发送（同步/异步）
    - 文件上传/管理
    - 聊天消息解析
    """

    def __init__(self, config: GeminiConfigType = None, config_path: str = None):
        self.config = GeminiConfig(config=config, config_path=config_path)
        self.browser = GeminiBrowser(config=self.config)
        self.parser = GeminiResponseParser()
        self.is_ready = False
        self._image_mode = False
        self._message_count = 0

    # ── 生命周期 ──────────────────────────────────────────────

    async def start(self) -> "GeminiAgency":
        """启动 Gemini Agency（启动浏览器并导航）。"""
        logger.note("> 启动 GeminiAgency ...")
        try:
            await self.browser.start()
            await self.browser.navigate_to_gemini()
            await asyncio.sleep(3)
            self.is_ready = True
            self._message_count = 0
            logger.okay("  ✓ GeminiAgency 就绪")
            return self
        except Exception as e:
            logger.err(f"  × GeminiAgency 启动失败: {e}")
            try:
                await self.browser.stop()
            except Exception:
                pass
            raise

    async def stop(self):
        """停止 GeminiAgency。"""
        logger.note("> 停止 GeminiAgency ...")
        self.is_ready = False
        self._message_count = 0
        await self.browser.stop()
        logger.okay("  ✓ GeminiAgency 已停止")

    @property
    def page(self) -> Page:
        return self.browser.page

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
        return False

    # ══════════════════════════════════════════════════════════
    # 浏览器状态
    # ══════════════════════════════════════════════════════════

    async def browser_status(self) -> dict:
        """返回浏览器实例的全面状态信息。

        包括是否已登录、当前页面 URL、当前模式和工具等。
        """
        status = {
            "is_ready": self.is_ready,
            "message_count": self._message_count,
            "image_mode": self._image_mode,
        }

        # 浏览器底层状态
        status["browser"] = self.browser.get_status()

        if not self.is_ready:
            return status

        # 页面信息
        try:
            status["page"] = await self.browser.get_page_info()
        except Exception as e:
            status["page"] = {"error": str(e)}

        # 登录状态
        try:
            login = await self.check_login_status()
            status["login"] = login
        except Exception as e:
            status["login"] = {"error": str(e)}

        # 当前模式
        try:
            mode = await self.get_mode()
            status["mode"] = mode
        except Exception:
            status["mode"] = {"mode": "unknown"}

        # 当前工具
        try:
            tool = await self.get_tool()
            status["tool"] = tool
        except Exception:
            status["tool"] = {"tool": "none"}

        return status

    # ══════════════════════════════════════════════════════════
    # 登录检测
    # ══════════════════════════════════════════════════════════

    async def check_login_status(self) -> dict:
        """检查用户是否已登录 Gemini。

        多策略检测：URL → 头像 → 登录按钮 → 输入框 → 文本搜索。
        """
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动，请先调用 start()。")

        result = {"logged_in": False, "is_pro": False, "message": ""}

        try:
            current_url = self.page.url
            if "consent.google.com" in current_url:
                result["message"] = "在 Google 同意页面，请在浏览器中接受 Cookie。"
                return result
            if "accounts.google.com" in current_url:
                result["message"] = "用户在登录页面，请完成登录。"
                return result

            # 头像检测
            avatar = await self.page.query_selector(SEL_LOGIN_AVATAR)
            if avatar and await avatar.is_visible():
                result["logged_in"] = True
                result["message"] = "用户已登录"
                # Pro 检测
                try:
                    pro_badge = await self.page.query_selector(SEL_PRO_BADGE)
                    if pro_badge:
                        result["is_pro"] = True
                    else:
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
                return result

            # 登录按钮检测
            login_btn = await self.page.query_selector(SEL_LOGIN_BUTTON)
            if login_btn and await login_btn.is_visible():
                result["message"] = "用户未登录，请手动登录。"
                return result

            # 输入框检测（仅登录后可见）
            input_area = await self.page.query_selector(SEL_INPUT_AREA)
            if input_area and await input_area.is_visible():
                result["logged_in"] = True
                result["message"] = "用户已登录"
                return result

            # 文本搜索
            try:
                sign_in_locator = self.page.locator(
                    'a:has-text("Sign in"), a:has-text("登录")'
                ).first
                if await sign_in_locator.is_visible(timeout=3000):
                    result["message"] = "用户未登录，页面显示登录链接。"
                    return result
            except Exception:
                pass

            result["message"] = "无法确定登录状态，请检查浏览器。"
            return result
        except Exception as e:
            result["message"] = f"检查登录状态出错: {e}"
            return result

    async def ensure_logged_in(self):
        """确保用户已登录，未登录则抛出错误。"""
        status = await self.check_login_status()
        if not status["logged_in"]:
            raise GeminiLoginRequiredError(status["message"])
        return status

    # ══════════════════════════════════════════════════════════
    # 聊天会话管理
    # ══════════════════════════════════════════════════════════

    @with_retry(max_retries=2)
    async def new_chat(self) -> dict:
        """开始新的聊天会话。

        通过 URL 导航到 Gemini 首页来创建新会话，避免新标签页问题。
        """
        logger.note("> 创建新会话 ...")
        await self.browser.close_extra_pages()

        try:
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
            await self.browser.close_extra_pages()

            # 提取当前 URL 作为聊天 ID
            chat_id = self._extract_chat_id(self.page.url)
            logger.okay("  ✓ 新会话已创建")
            return {"status": "ok", "chat_id": chat_id}

        except Exception as e:
            logger.warn(f"  ⚠ 新建会话失败: {e}，回退到基础 URL")
            try:
                await self.browser.navigate_to_gemini()
            except Exception:
                pass
            await asyncio.sleep(2)
            self._message_count = 0
            self._image_mode = False
            return {"status": "ok", "chat_id": self._extract_chat_id(self.page.url)}

    @with_retry(max_retries=2)
    async def switch_chat(self, chat_id: str) -> dict:
        """切换到指定 ID 的聊天会话。

        通过 URL 直接导航到 /app/{chat_id}。
        """
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动。")

        logger.note(f"> 切换到会话: {chat_id}")

        target_url = f"https://gemini.google.com/app/{chat_id}"
        try:
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
            logger.okay(f"  ✓ 已切换到会话: {chat_id}")
            return {"status": "ok", "chat_id": chat_id}
        except Exception as e:
            raise GeminiPageError(f"切换会话失败: {e}")

    def _extract_chat_id(self, url: str) -> str:
        """从 Gemini URL 提取聊天会话 ID。"""
        import re

        match = re.search(r"/app/([a-zA-Z0-9_-]+)", url)
        return match.group(1) if match else ""

    # ══════════════════════════════════════════════════════════
    # 模式管理
    # ══════════════════════════════════════════════════════════

    async def get_mode(self) -> dict:
        """获取当前聊天窗口的模式（如 快速/思考/Pro）。

        通过读取模式选择器按钮的文本来确定当前模式。
        """
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动。")

        try:
            # 查找模式选择器并读取当前值
            selector = await self.page.query_selector(SEL_MODEL_SELECTOR)
            if selector:
                text = await selector.text_content()
                if text:
                    mode = text.strip()
                    return {"mode": mode}

            # 回退：搜索包含模式名称的按钮
            for mode_name in ["Pro", "快速", "思考", "Flash", "Think"]:
                try:
                    locator = self.page.locator(f'button:has-text("{mode_name}")').first
                    if await locator.is_visible(timeout=1000):
                        # 检查是否是模式选择器按钮（而非其他按钮）
                        aria = await locator.get_attribute("aria-label")
                        if aria and ("模式" in aria or "mode" in aria.lower()):
                            return {"mode": mode_name}
                except Exception:
                    continue

            return {"mode": "unknown"}
        except Exception as e:
            logger.warn(f"  × 获取模式失败: {e}")
            return {"mode": "unknown", "error": str(e)}

    @with_retry(max_retries=2)
    async def set_mode(self, mode: str) -> dict:
        """设置聊天窗口的模式。

        Args:
            mode: 模式名称，如 "快速", "思考", "Pro"
        """
        logger.note(f"> 设置模式: {mode}")
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动。")

        try:
            # 点击模式选择器打开下拉菜单
            selector_btn = await self._find_element_with_fallback(
                css_selector=SEL_MODEL_SELECTOR,
                text_patterns=["快速", "思考", "Pro", "Flash", "Think"],
                element_types="button",
                description="模式选择器",
            )
            await selector_btn.click()
            await asyncio.sleep(0.8)

            # 在下拉菜单中查找目标模式（实际 DOM 使用 role="menuitemradio"）
            clicked = await self.page.evaluate(
                """(mode) => {
                    // 在 bard-mode-list-button 中查找包含目标模式名的按钮
                    const buttons = document.querySelectorAll(
                        'button[role="menuitemradio"], button.bard-mode-list-button'
                    );
                    for (const btn of buttons) {
                        const title = btn.querySelector('.mode-title');
                        const text = (title || btn).textContent.trim();
                        if (text.includes(mode)) {
                            btn.click();
                            return { found: true, text: text };
                        }
                    }
                    // 回退：在所有 data-test-id 匹配的元素中查找
                    const testBtn = document.querySelector(
                        '[data-test-id="bard-mode-option-' + mode + '"]'
                    );
                    if (testBtn) {
                        testBtn.click();
                        return { found: true, text: mode, via: 'test-id' };
                    }
                    return { found: false };
                }""",
                mode,
            )

            if not clicked or not clicked.get("found"):
                raise GeminiPageError(f"找不到模式选项 '{mode}'")

            await asyncio.sleep(1)
            logger.okay(f"  ✓ 模式已设置为: {mode}")
            return {"status": "ok", "mode": mode}
        except GeminiPageError:
            raise
        except Exception as e:
            raise GeminiPageError(f"设置模式失败: {e}")

    # ══════════════════════════════════════════════════════════
    # 工具管理
    # ══════════════════════════════════════════════════════════

    async def get_tool(self) -> dict:
        """获取当前聊天窗口的活动工具。

        检查 toolbox-drawer 按钮区域的状态来确定当前工具。
        """
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动。")

        try:
            active_tool = await self.page.evaluate(
                """() => {
                // 1. 检查 toolbox-drawer-item-deselect-button（选中工具时出现）
                const deselectBtns = document.querySelectorAll(
                    'button.toolbox-drawer-item-deselect-button'
                );
                for (const btn of deselectBtns) {
                    if (btn.offsetParent !== null || btn.offsetWidth > 0) {
                        const text = (btn.textContent || '').trim();
                        if (text) return text;
                    }
                }

                // 2. 检查 toolbox-drawer-button 是否有 has-selected-item 类
                const drawerBtn = document.querySelector(
                    'button.toolbox-drawer-button.has-selected-item'
                );
                if (drawerBtn) {
                    const label = drawerBtn.getAttribute('aria-label') || '';
                    if (label && label !== '工具') return label;
                }

                return '';
            }"""
            )
            tool = active_tool or "none"
            return {"tool": tool}
        except Exception as e:
            logger.warn(f"  × 获取工具失败: {e}")
            return {"tool": "none", "error": str(e)}

    @with_retry(max_retries=2)
    async def set_tool(self, tool: str) -> dict:
        """设置聊天窗口的工具。

        Args:
            tool: 工具名称，如 "Deep Research", "生成图片", "创作音乐", "Canvas"
        """
        logger.note(f"> 设置工具: {tool}")
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动。")

        try:
            # 点击 toolbox-drawer 按钮打开工具菜单
            tools_btn = await self._find_element_with_fallback(
                css_selector=SEL_TOOLS_BUTTON,
                text_patterns=None,
                description="工具按钮",
            )
            await tools_btn.click()
            await asyncio.sleep(1)

            # 在工具菜单中查找目标工具（实际 DOM 使用 role="menuitemcheckbox"）
            clicked = await self.page.evaluate(
                """(tool) => {
                    const buttons = document.querySelectorAll(
                        'button[role="menuitemcheckbox"], ' +
                        'button.toolbox-drawer-item-list-button'
                    );
                    for (const btn of buttons) {
                        const text = (btn.textContent || '').trim();
                        if (text.includes(tool) || tool.includes(text.split(' ')[0])) {
                            btn.click();
                            return { found: true, text: text };
                        }
                    }
                    return { found: false };
                }""",
                tool,
            )

            if not clicked or not clicked.get("found"):
                raise GeminiPageError(f"找不到工具选项 '{tool}'")

            await asyncio.sleep(1)

            # 如果是图片生成，更新内部状态
            if any(k in tool for k in ["图片", "image", "Image"]):
                self._image_mode = True

            logger.okay(f"  ✓ 工具已设置为: {tool}")
            return {"status": "ok", "tool": tool}
        except GeminiPageError:
            raise
        except Exception as e:
            raise GeminiPageError(f"设置工具失败: {e}")

    # ══════════════════════════════════════════════════════════
    # 输入框操作
    # ══════════════════════════════════════════════════════════

    async def clear_input(self) -> dict:
        """清空聊天窗口的输入框。"""
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动。")

        try:
            input_area = await self._find_input_area()
            await input_area.click()
            await asyncio.sleep(0.2)
            await self.page.keyboard.press("Control+a")
            await self.page.keyboard.press("Backspace")
            await asyncio.sleep(0.2)
            logger.okay("  ✓ 输入框已清空")
            return {"status": "ok"}
        except Exception as e:
            raise GeminiPageError(f"清空输入框失败: {e}")

    async def set_input(self, text: str) -> dict:
        """清空输入框并设置新的输入内容。"""
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动。")

        logger.note(f"> 设置输入: {logstr.mesg(brk(text[:80]))}")
        try:
            await self._type_message(text)
            return {"status": "ok", "text": text}
        except Exception as e:
            raise GeminiPageError(f"设置输入失败: {e}")

    async def add_input(self, text: str) -> dict:
        """在输入框的现有内容后追加内容。"""
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动。")

        logger.note(f"> 追加输入: {logstr.mesg(brk(text[:80]))}")
        try:
            await self._append_text(text)
            return {"status": "ok", "text": text}
        except Exception as e:
            raise GeminiPageError(f"追加输入失败: {e}")

    async def get_input(self) -> dict:
        """获取输入框中的当前内容。"""
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动。")

        try:
            input_area = await self._find_input_area()
            content = await self.page.evaluate(
                "(el) => (el.innerText || el.textContent || '').trim()",
                input_area,
            )
            return {"text": content}
        except Exception as e:
            raise GeminiPageError(f"获取输入内容失败: {e}")

    # ══════════════════════════════════════════════════════════
    # 消息发送
    # ══════════════════════════════════════════════════════════

    @with_retry(max_retries=2)
    async def send_input(self, wait_response: bool = True) -> dict:
        """发送输入框中的当前内容。

        Args:
            wait_response: True=等待 Gemini 响应后返回（同步），
                          False=发送后立即返回（异步）
        """
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动。")

        await self.ensure_logged_in()
        await self.browser.close_extra_pages()

        logger.note("> 发送输入 ...")

        # ── 支持服务器回退自动重试 ──
        # Gemini 后端偶尔因网络/服务器原因处理失败，页面会回退到零状态（
        # 输入框仍有文本，欢迎页面重新显示）。检测到回退后自动重试提交。
        MAX_ROLLBACK_RETRIES = 3
        last_rollback_error = None

        for rollback_attempt in range(1, MAX_ROLLBACK_RETRIES + 1):
            # 快照提交前状态（用于区分新响应和历史消息）
            pre_mr_count = await self._count_response_containers()
            pre_uq_count = await self._count_user_queries()

            # 提交消息（失败会抛异常）
            await self._submit_message()

            if not wait_response:
                self._message_count += 1
                return {"status": "ok", "message": "已发送，不等待响应"}

            # 等待响应（可能因服务器回退抛出 GeminiServerRollbackError）
            timeout = (
                self.config.image_generation_timeout
                if self._image_mode
                else self.config.response_timeout
            )
            try:
                response_html = await self._wait_for_response(
                    timeout=timeout, pre_mr_count=pre_mr_count
                )
                break  # 成功获取响应
            except GeminiServerRollbackError as e:
                last_rollback_error = e
                if rollback_attempt < MAX_ROLLBACK_RETRIES:
                    logger.warn(
                        f"  ⚠ 服务器回退，等待后重试 "
                        f"({rollback_attempt}/{MAX_ROLLBACK_RETRIES})"
                    )
                    # 回退后输入框仍有文本，等一会儿再重新提交
                    await asyncio.sleep(3)
                    # 截图记录回退状态（调试用）
                    try:
                        await self.screenshot(
                            path=f"data/debug/rollback_{rollback_attempt}.png"
                        )
                    except Exception:
                        pass
                    continue
                else:
                    logger.err(f"  × 服务器连续回退 {MAX_ROLLBACK_RETRIES} 次，放弃")
                    raise
        else:
            # 理论上不会执行到这里（上面 raise 了）
            raise last_rollback_error or GeminiServerRollbackError()

        images_data = await self._extract_images(download_base64=True)

        response = self.parser.parse(
            html_content=response_html,
            image_data_list=images_data if images_data else None,
        )

        if self._image_mode:
            self._image_mode = False

        self._message_count += 1

        return {
            "status": "ok",
            "response": response.to_dict(),
        }

    @with_retry(max_retries=2)
    async def send_message(
        self, text: str, image_mode: bool = False, download_images: bool = True
    ) -> GeminiResponse:
        """便捷方法：设置输入并发送，等待响应。

        Args:
            text: 要发送的消息文本
            image_mode: 是否使用图片生成模式
            download_images: 是否将响应中的图片下载为 base64
        """
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动，请先调用 start()。")

        await self.ensure_logged_in()
        await self.browser.close_extra_pages()

        logger.note(f"> 发送消息: {logstr.mesg(brk(text[:100]))}")

        if image_mode and not self._image_mode:
            await self.enable_image_generation()

        # ── 支持服务器回退自动重试 ──
        MAX_ROLLBACK_RETRIES = 3

        for rollback_attempt in range(1, MAX_ROLLBACK_RETRIES + 1):
            # 快照提交前状态
            pre_mr_count = await self._count_response_containers()

            # 回退后无需重新输入，文本仍在输入框中
            if rollback_attempt == 1:
                await self._type_message(text)

            await self._submit_message()

            timeout = (
                self.config.image_generation_timeout
                if image_mode or self._image_mode
                else self.config.response_timeout
            )
            try:
                response_html = await self._wait_for_response(
                    timeout=timeout, pre_mr_count=pre_mr_count
                )
                break  # 成功
            except GeminiServerRollbackError:
                if rollback_attempt < MAX_ROLLBACK_RETRIES:
                    logger.warn(
                        f"  ⚠ 服务器回退，等待后重试 "
                        f"({rollback_attempt}/{MAX_ROLLBACK_RETRIES})"
                    )
                    await asyncio.sleep(3)
                    try:
                        await self.screenshot(
                            path=f"data/debug/rollback_msg_{rollback_attempt}.png"
                        )
                    except Exception:
                        pass
                    continue
                else:
                    raise

        images_data = await self._extract_images(download_base64=download_images)

        response = self.parser.parse(
            html_content=response_html,
            image_data_list=images_data if images_data else None,
        )

        if image_mode:
            self._image_mode = False

        self._message_count += 1

        logger.mesg(f"  文本长度: {len(response.text)}")
        if response.images:
            logger.mesg(f"  图片数: {len(response.images)}")
        if response.code_blocks:
            logger.mesg(f"  代码块数: {len(response.code_blocks)}")

        return response

    async def generate_image(self, prompt: str) -> GeminiResponse:
        """便捷方法：图片生成。"""
        logger.note(f"> 生成图片: {logstr.mesg(brk(prompt[:100]))}")
        return await self.send_message(prompt, image_mode=True, download_images=True)

    # ══════════════════════════════════════════════════════════
    # 文件上传/管理
    # ══════════════════════════════════════════════════════════

    async def attach(self, file_path: str) -> dict:
        """在聊天窗口中上传一个文件。

        Args:
            file_path: 要上传的文件路径
        """
        logger.note(f"> 上传文件: {file_path}")
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动。")

        filepath = Path(file_path)
        if not filepath.exists():
            raise GeminiPageError(f"文件不存在: {file_path}")

        try:
            # 查找文件上传按钮并点击
            upload_btn = await self._find_element_with_fallback(
                css_selector=SEL_FILE_UPLOAD_BUTTON,
                text_patterns=["上传", "Upload", "添加文件", "Add file", "附件"],
                element_types="button",
                description="文件上传按钮",
            )

            # 监听文件选择器对话框
            async with self.page.expect_file_chooser(timeout=10000) as fc_info:
                await upload_btn.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(str(filepath.resolve()))
            await asyncio.sleep(2)

            logger.okay(f"  ✓ 文件已上传: {filepath.name}")
            return {
                "status": "ok",
                "file_name": filepath.name,
                "file_size": filepath.stat().st_size,
            }
        except Exception as e:
            # 回退：直接设置 input[type=file]
            try:
                file_input = await self.page.query_selector(SEL_FILE_UPLOAD_INPUT)
                if file_input:
                    await file_input.set_input_files(str(filepath.resolve()))
                    await asyncio.sleep(2)
                    logger.okay(f"  ✓ 文件已上传 (回退): {filepath.name}")
                    return {
                        "status": "ok",
                        "file_name": filepath.name,
                        "file_size": filepath.stat().st_size,
                    }
            except Exception:
                pass
            raise GeminiPageError(f"上传文件失败: {e}")

    async def detach(self) -> dict:
        """清空聊天窗口中已上传的所有文件。"""
        logger.note("> 清除附件 ...")
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动。")

        try:
            removed = 0
            # 查找所有附件的删除按钮
            chips = await self.page.query_selector_all(SEL_ATTACHMENT_CHIP)
            for chip in chips:
                try:
                    # 每个 chip 内或附近的移除按钮
                    remove_btn = await chip.query_selector(SEL_ATTACHMENT_REMOVE)
                    if remove_btn and await remove_btn.is_visible():
                        await remove_btn.click()
                        removed += 1
                        await asyncio.sleep(0.5)
                except Exception:
                    continue

            # 如果没有通过 chip 内按钮删除，尝试全局查找
            if removed == 0:
                remove_btns = await self.page.query_selector_all(SEL_ATTACHMENT_REMOVE)
                for btn in remove_btns:
                    try:
                        if await btn.is_visible():
                            await btn.click()
                            removed += 1
                            await asyncio.sleep(0.5)
                    except Exception:
                        continue

            logger.okay(f"  ✓ 已移除 {removed} 个附件")
            return {"status": "ok", "removed_count": removed}
        except Exception as e:
            raise GeminiPageError(f"清除附件失败: {e}")

    async def get_attachments(self) -> dict:
        """获取聊天窗口中已上传的文件列表。"""
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动。")

        try:
            attachments = await self.page.evaluate(
                """() => {
                const chips = document.querySelectorAll(
                    '.attachment-chip, [class*="attachment-chip"], ' +
                    '[class*="file-chip"], [class*="upload-chip"], ' +
                    '[class*="uploaded-file"]'
                );
                const results = [];
                for (const chip of chips) {
                    const name = chip.textContent?.trim() || '';
                    const typeEl = chip.querySelector('[class*="type"], [class*="ext"]');
                    const sizeEl = chip.querySelector('[class*="size"]');
                    results.push({
                        name: name,
                        type: typeEl?.textContent?.trim() || '',
                        size: sizeEl?.textContent?.trim() || '',
                    });
                }
                return results;
            }"""
            )
            return {"attachments": attachments or []}
        except Exception as e:
            logger.warn(f"  × 获取附件列表失败: {e}")
            return {"attachments": [], "error": str(e)}

    # ══════════════════════════════════════════════════════════
    # 聊天消息解析
    # ══════════════════════════════════════════════════════════

    async def get_messages(self) -> dict:
        """获取聊天窗口中的所有消息列表。

        解析页面上的用户消息和模型响应，返回结构化数据。
        """
        if not self.is_ready:
            raise GeminiPageError("Agency 未启动。")

        try:
            messages = await self.page.evaluate(
                """() => {
                const results = [];

                // 获取所有会话轮次 (每轮包含 user-query + model-response)
                const turns = document.querySelectorAll(
                    'conversation-turn, .conversation-turn, ' +
                    '[class*="conversation-turn"]'
                );

                if (turns.length > 0) {
                    for (const turn of turns) {
                        // 用户消息
                        const userQuery = turn.querySelector(
                            'user-query, .user-query, [class*="user-message"]'
                        );
                        if (userQuery) {
                            const content = userQuery.querySelector(
                                '.query-text, [class*="query-content"], ' +
                                '[class*="user-text"]'
                            );
                            results.push({
                                role: 'user',
                                content: (content || userQuery).innerText?.trim() || '',
                                html: (content || userQuery).innerHTML || '',
                            });
                        }

                        // 模型响应
                        const modelResp = turn.querySelector(
                            'model-response, .model-response'
                        );
                        if (modelResp) {
                            const msgContent = modelResp.querySelector('message-content');
                            const target = msgContent || modelResp;

                            // 提取图片
                            const images = [];
                            const imgs = target.querySelectorAll('img');
                            for (const img of imgs) {
                                if (img.width > 50 || img.naturalWidth > 50) {
                                    images.push({
                                        src: img.src || '',
                                        alt: img.alt || '',
                                        width: img.naturalWidth || img.width || 0,
                                        height: img.naturalHeight || img.height || 0,
                                    });
                                }
                            }

                            // 提取代码块
                            const codeBlocks = [];
                            const pres = target.querySelectorAll('pre code');
                            for (const code of pres) {
                                let lang = '';
                                for (const cls of code.classList) {
                                    if (cls.startsWith('language-')) {
                                        lang = cls.slice(9);
                                        break;
                                    }
                                }
                                codeBlocks.push({
                                    language: lang,
                                    code: code.textContent || '',
                                });
                            }

                            results.push({
                                role: 'model',
                                content: target.innerText?.trim() || '',
                                html: target.innerHTML || '',
                                images: images,
                                code_blocks: codeBlocks,
                            });
                        }
                    }
                } else {
                    // 回退：分别查找 user-query 和 model-response
                    const userMsgs = document.querySelectorAll(
                        'user-query, .user-query, [class*="user-message"]'
                    );
                    const modelMsgs = document.querySelectorAll(
                        'model-response, .model-response'
                    );

                    const maxLen = Math.max(userMsgs.length, modelMsgs.length);
                    for (let i = 0; i < maxLen; i++) {
                        if (i < userMsgs.length) {
                            results.push({
                                role: 'user',
                                content: userMsgs[i].innerText?.trim() || '',
                                html: userMsgs[i].innerHTML || '',
                            });
                        }
                        if (i < modelMsgs.length) {
                            const mc = modelMsgs[i].querySelector('message-content');
                            const target = mc || modelMsgs[i];
                            results.push({
                                role: 'model',
                                content: target.innerText?.trim() || '',
                                html: target.innerHTML || '',
                            });
                        }
                    }
                }

                return results;
            }"""
            )
            return {"messages": messages or []}
        except Exception as e:
            logger.warn(f"  × 获取消息列表失败: {e}")
            return {"messages": [], "error": str(e)}

    # ══════════════════════════════════════════════════════════
    # 图片生成模式
    # ══════════════════════════════════════════════════════════

    @with_retry(max_retries=2)
    async def enable_image_generation(self):
        """通过选择工具启用图片生成模式。"""
        logger.note("> 启用图片生成模式 ...")
        try:
            result = await self.set_tool("生成图片")
            self._image_mode = True
            logger.okay("  ✓ 图片生成模式已启用")
        except GeminiImageGenerationError:
            raise
        except Exception as e:
            raise GeminiImageGenerationError(f"启用图片生成失败: {e}")

    # ══════════════════════════════════════════════════════════
    # 工具方法
    # ══════════════════════════════════════════════════════════

    async def screenshot(self, path: str = None) -> bytes:
        """对当前状态截图。"""
        return await self.browser.screenshot(path=path)

    def save_images(
        self,
        response: GeminiResponse,
        output_dir: str = "data/images",
        prefix: str = "",
    ) -> list[str]:
        """将响应中的图片保存到磁盘。"""
        if not response.images:
            logger.mesg("  没有图片需要保存")
            return []

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        saved_paths = []
        timestamp = int(time.time())
        for i, img in enumerate(response.images):
            if not img.base64_data:
                continue
            ext = img.get_extension()
            prefix_part = f"{prefix}_" if prefix else ""
            filename = f"{prefix_part}{timestamp}_{i + 1}.{ext}"
            filepath = output_path / filename
            try:
                img.save_to_file(str(filepath))
                saved_paths.append(str(filepath))
                logger.okay(f"  + 图片已保存: {filepath}")
            except Exception as e:
                logger.warn(f"  × 保存图片 #{i + 1} 失败: {e}")

        if saved_paths:
            logger.okay(f"  ✓ 共保存 {len(saved_paths)} 张图片到 {output_dir}")
        return saved_paths

    # ══════════════════════════════════════════════════════════
    # 内部辅助方法
    # ══════════════════════════════════════════════════════════

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
        """
        if css_selector:
            selectors = [s.strip() for s in css_selector.split(",")]
            for sel in selectors:
                try:
                    el = await self.page.query_selector(sel)
                    if el and await el.is_visible():
                        return el
                except Exception:
                    continue

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

    async def _find_input_area(self):
        """查找聊天输入框。"""
        selectors = [s.strip() for s in SEL_INPUT_AREA.split(",")]
        for sel in selectors:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    return el
            except Exception:
                continue

        try:
            el = await self.page.query_selector('[contenteditable="true"]')
            if el and await el.is_visible():
                return el
        except Exception:
            pass

        try:
            locator = self.page.locator('[contenteditable="true"]').first
            if await locator.is_visible(timeout=5000):
                return await locator.element_handle()
        except Exception:
            pass

        raise GeminiPageError("找不到聊天输入框。")

    async def _find_send_button(self):
        """查找发送按钮。"""
        selectors = [s.strip() for s in SEL_SEND_BUTTON.split(",")]
        for sel in selectors:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    return el
            except Exception:
                continue

        try:
            el = await self.page.query_selector('button[type="submit"]')
            if el and await el.is_visible():
                return el
        except Exception:
            pass

        # 回退：在 input area 容器附近查找
        try:
            send_btn = await self.page.evaluate(
                """() => {
                const containers = document.querySelectorAll(
                    '.input-area-container, rich-textarea, .input-buttons-wrapper, ' +
                    '.input-area, [class*="input-area"]'
                );
                for (const c of containers) {
                    const parent = c.closest('.input-area-container') || c.parentElement;
                    if (!parent) continue;
                    const btns = parent.querySelectorAll('button');
                    for (const btn of btns) {
                        if (btn.offsetParent === null && btn.offsetWidth === 0) continue;
                        const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                        const tooltip = (btn.getAttribute('mattooltip') || '').toLowerCase();
                        if (label.includes('send') || label.includes('发送') ||
                            tooltip.includes('send') || tooltip.includes('发送') ||
                            label.includes('submit') || label.includes('提交')) {
                            return {found: true};
                        }
                    }
                }
                return {found: false};
            }"""
            )
            if send_btn and send_btn.get("found"):
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

        for text in ["Send", "发送", "Submit", "提交"]:
            try:
                locator = self.page.locator(f'button[aria-label*="{text}"]').first
                if await locator.is_visible(timeout=3000):
                    return await locator.element_handle()
            except Exception:
                continue

        raise GeminiPageError("找不到发送按钮。")

    async def _verify_input_content(self, input_area, expected_text: str) -> bool:
        """验证输入框是否包含期望的文本。"""
        try:
            actual = await self.page.evaluate(
                "(el) => (el.innerText || el.textContent || '').trim()",
                input_area,
            )
            if not actual:
                return False
            # 将期望文本规范化（去除多余空白和换行）用于比较
            normalized_expected = " ".join(expected_text.split())
            normalized_actual = " ".join(actual.split())
            check_len = min(20, len(normalized_expected) // 2)
            return (
                normalized_expected[:check_len] in normalized_actual
                or len(normalized_actual) >= len(normalized_expected) * 0.5
            )
        except Exception:
            return False

    async def _type_message(self, text: str):
        """在输入框中输入消息（清空后输入），带验证和回退策略。"""
        input_area = await self._find_input_area()
        await input_area.click()
        await asyncio.sleep(0.3)

        # 清空
        await self.page.keyboard.press("Control+a")
        await self.page.keyboard.press("Backspace")
        await asyncio.sleep(0.2)

        # 策略 1: keyboard.type()
        # 注意: Gemini 输入框中 Enter 会提交消息，所以多行文本
        # 需要用 Shift+Enter 来换行
        await input_area.focus()
        await asyncio.sleep(0.1)
        if "\n" in text:
            # 逐行输入，用 Shift+Enter 换行
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if line:
                    await self.page.keyboard.type(line, delay=10)
                if i < len(lines) - 1:
                    await self.page.keyboard.press("Shift+Enter")
                    await asyncio.sleep(0.05)
        else:
            await self.page.keyboard.type(text, delay=10)
        await asyncio.sleep(0.5)

        if await self._verify_input_content(input_area, text):
            return

        # 策略 2: JS innerHTML
        await self.page.evaluate(
            """(args) => {
                const [selector, text] = args;
                const editors = document.querySelectorAll(selector);
                let target = null;
                for (const el of editors) {
                    if (el.offsetParent !== null || el.offsetWidth > 0) {
                        target = el; break;
                    }
                }
                if (!target) {
                    const all = document.querySelectorAll('[contenteditable="true"]');
                    for (const el of all) {
                        if (el.offsetParent !== null || el.offsetWidth > 0) {
                            target = el; break;
                        }
                    }
                }
                if (target) {
                    target.focus();
                    // 多行文本用 <p> 标签分行
                    const lines = text.split('\\n');
                    target.innerHTML = lines.map(l => '<p>' + l + '</p>').join('');
                    target.dispatchEvent(new Event('input', {bubbles: true}));
                    target.dispatchEvent(new Event('change', {bubbles: true}));
                    target.dispatchEvent(new Event('compositionend', {bubbles: true}));
                }
            }""",
            [SEL_INPUT_AREA.replace(", ", ",").split(",")[0], text],
        )
        await asyncio.sleep(0.5)

        input_area = await self._find_input_area()
        if await self._verify_input_content(input_area, text):
            return

        # 策略 3: execCommand
        await input_area.click()
        await asyncio.sleep(0.2)
        await self.page.keyboard.press("Control+a")
        await self.page.keyboard.press("Backspace")
        await asyncio.sleep(0.1)
        await self.page.evaluate(
            "(text) => { document.execCommand('insertText', false, text); }", text
        )
        await asyncio.sleep(0.5)

        input_area = await self._find_input_area()
        if await self._verify_input_content(input_area, text):
            return

        # 策略 4: clipboard paste
        await input_area.click()
        await asyncio.sleep(0.2)
        await self.page.keyboard.press("Control+a")
        await self.page.keyboard.press("Backspace")
        await asyncio.sleep(0.1)
        await self.page.evaluate(
            """async (text) => {
                try { await navigator.clipboard.writeText(text); }
                catch(e) {
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
            return

        raise GeminiPageError("无法将文本输入到聊天输入框，所有策略均失败。")

    async def _append_text(self, text: str):
        """在输入框的现有内容后追加文本（不清空）。"""
        input_area = await self._find_input_area()
        await input_area.click()
        await asyncio.sleep(0.2)

        # 移动光标到末尾
        await self.page.keyboard.press("End")
        await self.page.keyboard.press("Control+End")
        await asyncio.sleep(0.1)

        # 追加文本
        await self.page.keyboard.type(text, delay=10)
        await asyncio.sleep(0.3)

    async def _count_user_queries(self) -> int:
        """计算页面上的用户消息数量。"""
        return await self.page.evaluate(
            "() => document.querySelectorAll('user-query').length"
        )

    async def _verify_submit_success(
        self, pre_submit_content: str, pre_user_query_count: int
    ) -> bool:
        """验证消息是否成功提交。

        检查 3 个信号（任一为 True 即成功）：
        1. 输入框内容已清空
        2. user-query 元素数量增加
        3. 出现加载指示器或停止按钮
        """
        # 信号 1: 输入框清空
        try:
            input_area = await self._find_input_area()
            post_text = await self.page.evaluate(
                "(el) => (el.innerText || el.textContent || '').trim()",
                input_area,
            )
            if not post_text or len(post_text) < len(pre_submit_content) * 0.3:
                return True
        except Exception:
            pass

        # 信号 2: user-query 计数增加
        try:
            current_uq = await self._count_user_queries()
            if current_uq > pre_user_query_count:
                return True
        except Exception:
            pass

        # 信号 3: 加载指示器 / 停止按钮可见
        for selector in [SEL_LOADING_INDICATOR, SEL_STOP_BUTTON]:
            try:
                el = await self.page.query_selector(selector)
                if el and await el.is_visible():
                    return True
            except Exception:
                pass

        return False

    async def _click_send_button(self, send_btn) -> str | None:
        """尝试多种方式点击发送按钮，返回成功方式的名称或 None。

        Angular Material 按钮需要完整的指针事件序列才能可靠触发。
        """
        strategies = [
            # 策略 1: Playwright 原生 click（模拟真实鼠标事件序列，最可靠）
            (
                "playwright_click",
                lambda btn: btn.click(force=True, timeout=3000),
            ),
            # 策略 2: 完整指针事件序列（pointerdown→mousedown→pointerup→mouseup→click）
            (
                "pointer_events",
                lambda btn: self.page.evaluate(
                    """(el) => {
                    const rect = el.getBoundingClientRect();
                    const x = rect.left + rect.width / 2;
                    const y = rect.top + rect.height / 2;
                    const opts = {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0};
                    el.dispatchEvent(new PointerEvent('pointerdown', opts));
                    el.dispatchEvent(new MouseEvent('mousedown', opts));
                    el.dispatchEvent(new PointerEvent('pointerup', opts));
                    el.dispatchEvent(new MouseEvent('mouseup', opts));
                    el.dispatchEvent(new MouseEvent('click', opts));
                }""",
                    btn,
                ),
            ),
            # 策略 3: 简单 JS click
            (
                "js_click",
                lambda btn: self.page.evaluate("(el) => el.click()", btn),
            ),
        ]

        for name, action in strategies:
            try:
                await action(send_btn)
                return name
            except Exception as e:
                logger.warn(f"  ⚠ {name} 失败: {e}")
                continue

        return None

    async def _submit_message(self):
        """提交已输入的消息，带严格验证。

        如果所有提交策略都失败，会抛出 GeminiPageError 而不是静默继续。
        """
        MAX_ATTEMPTS = 3

        # ── 记录提交前状态 ──
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
            logger.warn("  ⚠ 提交前输入框为空")

        pre_uq_count = await self._count_user_queries()

        # ── 尝试提交（最多 MAX_ATTEMPTS 轮） ──
        for attempt in range(1, MAX_ATTEMPTS + 1):
            sent_via = None

            # 第一步：通过 send button 点击
            try:
                send_btn = await self._find_send_button()
                sent_via = await self._click_send_button(send_btn)
            except GeminiPageError:
                logger.warn("  ⚠ 找不到发送按钮")
            except Exception as e:
                logger.warn(f"  ⚠ 发送按钮异常: {e}")

            if sent_via:
                await asyncio.sleep(1.5)
                if await self._verify_submit_success(pre_submit_content, pre_uq_count):
                    logger.mesg(f"  提交方式: {sent_via}")
                    return
                logger.warn(f"  ⚠ {sent_via} 点击后未确认提交成功 (attempt {attempt})")

            # 第二步：DOM 直接查找 + 完整事件序列
            dom_clicked = await self.page.evaluate(
                """() => {
                    const sels = [
                        'button.send-button',
                        'button[aria-label*="发送"]',
                        'button[aria-label*="Send" i]',
                        'button[type="submit"]',
                    ];
                    for (const sel of sels) {
                        const btn = document.querySelector(sel);
                        if (btn && (btn.offsetParent !== null || btn.offsetWidth > 0)) {
                            const rect = btn.getBoundingClientRect();
                            const x = rect.left + rect.width / 2;
                            const y = rect.top + rect.height / 2;
                            const opts = {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0};
                            btn.dispatchEvent(new PointerEvent('pointerdown', opts));
                            btn.dispatchEvent(new MouseEvent('mousedown', opts));
                            btn.dispatchEvent(new PointerEvent('pointerup', opts));
                            btn.dispatchEvent(new MouseEvent('mouseup', opts));
                            btn.dispatchEvent(new MouseEvent('click', opts));
                            return sel;
                        }
                    }
                    return null;
                }"""
            )
            if dom_clicked:
                sent_via = f"dom_events({dom_clicked})"
                await asyncio.sleep(1.5)
                if await self._verify_submit_success(pre_submit_content, pre_uq_count):
                    logger.mesg(f"  提交方式: {sent_via}")
                    return
                logger.warn(f"  ⚠ {sent_via} 后未确认提交成功 (attempt {attempt})")

            # 第三步：Enter 键
            try:
                input_area = await self._find_input_area()
                await input_area.focus()
                await asyncio.sleep(0.2)
            except Exception:
                pass
            await self.page.keyboard.press("Enter")
            await asyncio.sleep(1.5)
            if await self._verify_submit_success(pre_submit_content, pre_uq_count):
                logger.mesg(f"  提交方式: enter (attempt {attempt})")
                return
            logger.warn(f"  ⚠ Enter 键后未确认提交成功 (attempt {attempt})")

            # 等待后重试
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(1)

        # ── 所有策略均失败 ──
        raise GeminiPageError(
            "消息提交失败：所有策略均未能触发发送。"
            "输入框内容未清空，请检查页面状态。"
        )

    async def _count_response_containers(self) -> int:
        """计算页面上的模型响应数量。"""
        return await self.page.evaluate(
            "() => document.querySelectorAll('model-response').length"
        )

    async def _get_latest_response_content(self) -> dict:
        """获取最新模型响应的内容。"""
        return await self.page.evaluate(
            """() => {
            const mrs = document.querySelectorAll('model-response');
            if (mrs.length === 0) return {html: '', text: '', length: 0};
            const last = mrs[mrs.length - 1];
            const mc = last.querySelector('message-content');
            if (mc) {
                return {html: mc.innerHTML, text: (mc.innerText||'').trim(), length: mc.innerHTML.length};
            }
            const md = last.querySelector('.markdown, .markdown-main-panel, .response-text');
            if (md) {
                return {html: md.innerHTML, text: (md.innerText||'').trim(), length: md.innerHTML.length};
            }
            return {html: last.innerHTML, text: (last.innerText||'').trim(), length: last.innerHTML.length};
        }"""
        )

    async def _detect_server_rollback(self) -> bool:
        """检测 Gemini 服务器处理失败后的页面回退。

        当消息提交后，Gemini 后端因网络或服务器原因处理失败时，
        页面会自动回退到发送前的"零状态"：
        - body 含有 zero-state-theme 类
        - 欢迎问候区域（greeting-container）可见
        - 没有 user-query 或 model-response 元素
        - 输入框仍有文本（未被消费）
        - 零状态建议卡片（card-zero-state）可见

        Returns:
            True 表示检测到服务器回退。
        """
        try:
            rollback_info = await self.page.evaluate(
                """() => {
                    const body = document.body;
                    const isZeroState = body?.classList?.contains('zero-state-theme') || false;

                    // 欢迎区域可见
                    const greeting = document.querySelector('.greeting-container');
                    const greetingVisible = greeting ? (greeting.offsetWidth > 0 && greeting.offsetHeight > 0) : false;

                    // 零状态建议卡片可见
                    const zeroCards = document.querySelectorAll('.card-zero-state');
                    let visibleCards = 0;
                    zeroCards.forEach(c => { if (c.offsetWidth > 0) visibleCards++; });

                    // 对话元素计数
                    const userQueries = document.querySelectorAll('user-query').length;
                    const modelResponses = document.querySelectorAll('model-response').length;

                    // 输入框是否有内容
                    const editor = document.querySelector('.ql-editor');
                    const inputText = editor ? (editor.textContent || '').trim() : '';

                    return {
                        isZeroState,
                        greetingVisible,
                        visibleCards,
                        userQueries,
                        modelResponses,
                        hasInputText: inputText.length > 0,
                        inputTextLen: inputText.length
                    };
                }"""
            )

            if not rollback_info:
                return False

            is_zero = rollback_info.get("isZeroState", False)
            greeting_vis = rollback_info.get("greetingVisible", False)
            zero_cards = rollback_info.get("visibleCards", 0)
            uq = rollback_info.get("userQueries", -1)
            mr = rollback_info.get("modelResponses", -1)
            has_input = rollback_info.get("hasInputText", False)

            # 主判定：零状态 + 欢迎可见 + 无对话元素 = 服务器回退
            if is_zero and greeting_vis and uq == 0 and mr == 0:
                logger.warn(
                    f"  ⚠ 检测到服务器回退: zero-state={is_zero}, "
                    f"greeting={greeting_vis}, cards={zero_cards}, "
                    f"uq={uq}, mr={mr}, has_input={has_input}"
                )
                return True

            # 次判定：零状态建议卡片可见 + 无对话 + 输入框有文本
            if zero_cards >= 3 and uq == 0 and mr == 0 and has_input:
                logger.warn(
                    f"  ⚠ 检测到服务器回退(卡片): cards={zero_cards}, "
                    f"uq={uq}, mr={mr}, input_len={rollback_info.get('inputTextLen', 0)}"
                )
                return True

            return False

        except Exception as e:
            logger.warn(f"  ⚠ 回退检测异常: {e}")
            return False

    async def _check_for_errors(self) -> str | None:
        """检查页面上的错误消息或配额警告。"""
        error_el = await self.page.query_selector(SEL_ERROR_MESSAGE)
        if error_el:
            try:
                if await error_el.is_visible():
                    error_text = await error_el.text_content()
                    if error_text and error_text.strip():
                        return error_text.strip()
            except Exception:
                pass

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

    async def _wait_for_response(
        self, timeout: int = None, pre_mr_count: int = None
    ) -> str:
        """等待 Gemini 完成响应生成，使用多信号检测。

        仅依赖可靠的结构性信号进行检测，不使用 innerHTML 比较。

        包含卡顿检测：如果响应内容长时间未变化（> stall_timeout），
        会自动点击停止按钮并返回已收到的内容。

        Args:
            timeout: 超时时间（毫秒）
            pre_mr_count: 提交前 model-response 元素数量，用于检测新响应。
        """
        timeout = timeout or self.config.response_timeout
        # 卡顿超时：内容停止更新超过此时长则视为卡死（毫秒）
        stall_timeout_ms = min(timeout * 0.25, 30000)  # 最多 30s
        t_start = time.time()
        elapsed = 0

        initial_count = (
            pre_mr_count
            if pre_mr_count is not None
            else await self._count_response_containers()
        )
        logger.note(f"> 等待响应 ... (初始 model-response={initial_count})")

        # ── 阶段 1：等待响应开始 ──
        # 仅使用 3 个可靠信号（不使用 innerHTML 比较）：
        #   1. model-response 元素数量增加
        #   2. 加载指示器（mat-progress-bar 等）可见
        #   3. 停止按钮可见
        response_started = False
        start_signal = ""
        while elapsed < timeout:
            error_msg = await self._check_for_errors()
            if error_msg:
                if any(k in error_msg.lower() for k in ["quota", "limit", "配额"]):
                    raise GeminiRateLimitError(error_msg)
                raise GeminiPageError(f"Gemini 错误: {error_msg}")

            # 信号 1: model-response 数量增加
            current_count = await self._count_response_containers()
            if current_count > initial_count:
                response_started = True
                start_signal = f"model-response +{current_count - initial_count}"
                break

            # 信号 2: 加载指示器可见
            try:
                loading = await self.page.query_selector(SEL_LOADING_INDICATOR)
                if loading and await loading.is_visible():
                    response_started = True
                    start_signal = "loading_indicator"
                    break
            except Exception:
                pass

            # 信号 3: 停止按钮可见
            try:
                stop_btn = await self.page.query_selector(SEL_STOP_BUTTON)
                if stop_btn and await stop_btn.is_visible():
                    response_started = True
                    start_signal = "stop_button"
                    break
            except Exception:
                pass

            # 信号 4（负面）: 服务器回退检测
            # 等待至少 3 秒后再检测，避免因页面过渡动画误判
            if elapsed > 3000:
                if await self._detect_server_rollback():
                    raise GeminiServerRollbackError(
                        "Gemini 服务器处理失败，页面已回退到初始状态。"
                    )

            await asyncio.sleep(GEMINI_POLL_INTERVAL / 1000)
            elapsed = (time.time() - t_start) * 1000

        if not response_started:
            raise GeminiTimeoutError(
                "等待响应开始超时，可能输入未成功提交。", timeout_ms=timeout
            )

        # ── 阶段 2：等待响应完成（含卡顿检测） ──
        logger.mesg(f"  响应已开始 ({start_signal})，等待完成 ...")
        stable_count = 0
        last_content = ""
        last_content_length = 0
        last_change_time = time.time()  # 上次内容变化时间
        stalled = False

        while elapsed < timeout:
            error_msg = await self._check_for_errors()
            if error_msg:
                if any(k in error_msg.lower() for k in ["quota", "limit", "配额"]):
                    raise GeminiRateLimitError(error_msg)

            # 服务器回退检测（Phase 2 中也可能发生）
            # 回退会导致 model-response 消失，页面恢复零状态
            if await self._detect_server_rollback():
                raise GeminiServerRollbackError(
                    "Gemini 服务器在生成响应过程中失败，页面已回退。"
                )

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

            resp = await self._get_latest_response_content()
            current_content = resp.get("html", "")
            current_length = len(current_content)

            # 使用长度比较而非精确字符串比较来判定稳定性。
            # Gemini 的 DOM 可能因动画、时间戳等产生微小变化，
            # 导致 innerHTML 不完全相同，但长度不变表示内容实质未变。
            content_stable = current_length == len(last_content) and current_length > 0

            if not content_stable:
                # 内容有变化 → 重置卡顿计时
                last_change_time = time.time()
                stable_count = 0
                last_content = current_content
            else:
                # 内容未变化 → 检查卡顿
                stall_ms = (time.time() - last_change_time) * 1000

                if stall_ms > stall_timeout_ms:
                    if is_loading or is_generating:
                        # 内容长时间未变但仍在"生成中" → 卡死了
                        logger.warn(
                            f"  ⚠ 响应停滞 {stall_ms / 1000:.0f}s"
                            f" (loading={is_loading}, generating={is_generating})"
                        )
                        # 尝试点击停止按钮
                        if is_generating and stop_btn:
                            try:
                                await self.page.evaluate("(el) => el.click()", stop_btn)
                                logger.mesg("  已自动点击停止按钮")
                                await asyncio.sleep(2)
                            except Exception as click_err:
                                logger.warn(f"  × 点击停止按钮失败: {click_err}")
                        stalled = True
                        break
                    else:
                        # 无加载/生成信号且内容稳定 → 正常结束
                        stable_count += 1
                        if stable_count >= 3:
                            break

                elif not is_loading and not is_generating:
                    # 理想情况：内容稳定，无加载、无生成
                    stable_count += 1
                    if stable_count >= 3:
                        break
                elif not is_generating:
                    # 次优情况：内容稳定且停止按钮消失，但 loading 指示器
                    # 仍在（如思考模式的永久 thinking 区域）
                    stable_count += 1
                    if stable_count >= 5:
                        break

            # 长度变化日志
            if current_length > last_content_length + 100:
                logger.mesg(f"  接收中... ({current_length} chars)")
                last_content_length = current_length

            await asyncio.sleep(GEMINI_POLL_INTERVAL / 1000)
            elapsed = (time.time() - t_start) * 1000

        total_s = time.time() - t_start
        if stalled:
            logger.warn(f"  ⚠ 响应因停滞被中断 ({total_s:.1f}s)")
        elif elapsed >= timeout:
            logger.warn("  ⚠ 响应可能不完整（已超时）")
        else:
            logger.okay(f"  ✓ 响应已收到 ({total_s:.1f}s)")

        return last_content

    async def _extract_images(self, download_base64: bool = True) -> list[dict]:
        """从最新响应中提取图片数据。"""
        images_data = []
        try:
            model_responses = await self.page.query_selector_all("model-response")
            if not model_responses:
                return images_data

            last_response = model_responses[-1]

            # 等待图片加载
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

            images_data = await self.page.evaluate(
                """(container) => {
                    const results = [];
                    const imgs = container.querySelectorAll('img');
                    for (const img of imgs) {
                        const src = img.src || img.getAttribute('src') || '';
                        if (!src) continue;
                        const width = img.naturalWidth || img.width || 0;
                        const height = img.naturalHeight || img.height || 0;
                        if (width > 0 && height > 0 && (width < 50 || height < 50)) continue;
                        const entry = {
                            src, alt: img.alt || '', width, height, type: 'img',
                        };
                        if (src.startsWith('data:')) {
                            const parts = src.split(',');
                            if (parts.length >= 2) {
                                const mimeMatch = parts[0].match(/data:([^;]+)/);
                                entry.mime_type = mimeMatch ? mimeMatch[1] : 'image/png';
                                entry.base64_data = parts.slice(1).join(',');
                            }
                        }
                        // 对所有已加载的图片（包括 https/blob）尝试 canvas 提取
                        // 这样可以避免 CORS/网络问题导致的下载失败
                        if (!entry.base64_data && img.complete && img.naturalWidth > 0) {
                            try {
                                const canvas = document.createElement('canvas');
                                canvas.width = img.naturalWidth;
                                canvas.height = img.naturalHeight;
                                canvas.getContext('2d').drawImage(img, 0, 0);
                                const b64 = canvas.toDataURL('image/png').split(',')[1];
                                if (b64 && b64.length > 100) {
                                    entry.base64_data = b64;
                                    entry.mime_type = 'image/png';
                                }
                            } catch(e) {
                                // Canvas tainted (CORS) → 需要单独下载
                                entry.needs_download = true;
                            }
                        }
                        results.push(entry);
                    }
                    const canvases = container.querySelectorAll('canvas');
                    for (const canvas of canvases) {
                        if (canvas.width < 50 || canvas.height < 50) continue;
                        try {
                            const b64 = canvas.toDataURL('image/png').split(',')[1];
                            if (b64 && b64.length > 100) {
                                results.push({
                                    src: '', alt: 'canvas-image',
                                    width: canvas.width, height: canvas.height,
                                    type: 'canvas', base64_data: b64, mime_type: 'image/png',
                                });
                            }
                        } catch(e) {}
                    }
                    return results;
                }""",
                last_response,
            )

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
                            dl = await self.browser.download_image_as_base64(src)
                            if dl.get("base64_data"):
                                img_data["base64_data"] = dl["base64_data"]
                                img_data["mime_type"] = dl.get("mime_type", "image/png")
                        except Exception as dl_err:
                            logger.warn(f"  × 下载图片失败: {dl_err}")
        except Exception as e:
            logger.warn(f"  × 提取图片出错: {e}")

        return images_data

    async def toggle_sidebar(self):
        """切换侧边栏开/关。"""
        try:
            toggle_btn = await self.page.query_selector(SEL_SIDEBAR_TOGGLE)
            if toggle_btn and await toggle_btn.is_visible():
                await toggle_btn.click()
                await asyncio.sleep(0.5)
                return
            toggle_locator = self.page.locator(SEL_SIDEBAR_TOGGLE).first
            await toggle_locator.click(timeout=5000)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warn(f"  × 切换侧边栏失败: {e}")
