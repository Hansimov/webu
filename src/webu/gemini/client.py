"""GeminiClient: HTTP 客户端。

封装对 Gemini FastAPI 服务器的 HTTP 调用，提供与服务器接口一一对应的方法，
使用户可以通过 Python API 操作 Gemini 聊天窗口，无需关心底层 HTTP 请求细节。
"""

import json
import requests

from dataclasses import dataclass, field
from tclogger import logger, logstr
from typing import Optional


@dataclass
class GeminiClientConfig:
    """GeminiClient 的配置。"""

    host: str = "127.0.0.1"
    port: int = 30002
    timeout: int = 300  # 请求超时（秒），send_input 可能需要较长时间
    scheme: str = "http"

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


class GeminiClient:
    """Gemini FastAPI 服务器的 HTTP 客户端。

    封装所有与服务器端点对应的方法，通过 HTTP 请求与远程
    GeminiAgency 进行交互。

    用法:
        config = GeminiClientConfig(host="192.168.1.100", port=30002)
        client = GeminiClient(config)

        # 检查状态
        status = client.browser_status()
        print(status)

        # 发送消息
        client.set_input("你好，Gemini")
        result = client.send_input(wait_response=True)
        print(result)
    """

    def __init__(self, config: GeminiClientConfig = None):
        self.config = config or GeminiClientConfig()
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    @property
    def base_url(self) -> str:
        return self.config.base_url

    def close(self):
        """关闭 HTTP 会话。"""
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    # ── HTTP 请求基础 ────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        json_data: dict = None,
        timeout: int = None,
    ) -> dict:
        """发送 HTTP 请求并返回 JSON 响应。"""
        url = f"{self.base_url}{path}"
        timeout = timeout or self.config.timeout

        try:
            if method.upper() == "GET":
                resp = self._session.get(url, timeout=timeout)
            elif method.upper() == "POST":
                resp = self._session.post(url, json=json_data, timeout=timeout)
            else:
                raise ValueError(f"不支持的 HTTP 方法: {method}")

            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"无法连接到 Gemini 服务器 ({url}): {e}") from e
        except requests.exceptions.Timeout as e:
            raise TimeoutError(f"请求超时 ({timeout}s): {url}") from e
        except requests.exceptions.HTTPError as e:
            # 尝试提取服务器返回的错误详情
            try:
                detail = e.response.json().get("detail", str(e))
            except Exception:
                detail = e.response.text or str(e)
            raise RuntimeError(
                f"服务器错误 [{e.response.status_code}]: {detail}"
            ) from e

    def _get(self, path: str, **kwargs) -> dict:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, json_data: dict = None, **kwargs) -> dict:
        return self._request("POST", path, json_data=json_data, **kwargs)

    # ── 系统接口 ─────────────────────────────────────────────

    def health(self) -> dict:
        """健康检查。"""
        return self._get("/health")

    # ── 状态 ─────────────────────────────────────────────────

    def browser_status(self) -> dict:
        """获取浏览器实例的全面状态信息。

        Returns:
            dict: 包含 is_ready, login, page, mode, tool 等状态信息
        """
        return self._get("/browser_status")

    # ── 聊天会话管理 ─────────────────────────────────────────

    def new_chat(self) -> dict:
        """创建新的聊天窗口。

        Returns:
            dict: {"status": "ok", "chat_id": "..."}
        """
        return self._post("/new_chat")

    def switch_chat(self, chat_id: str) -> dict:
        """切换到指定 ID 的聊天窗口。

        Args:
            chat_id: 聊天会话 ID

        Returns:
            dict: {"status": "ok", "chat_id": "..."}
        """
        return self._post("/switch_chat", {"chat_id": chat_id})

    # ── 模式管理 ─────────────────────────────────────────────

    def get_mode(self) -> dict:
        """获取聊天窗口的当前模式。

        Returns:
            dict: {"mode": "快速"} 或 {"mode": "Pro"} 等
        """
        return self._get("/get_mode")

    def set_mode(self, mode: str) -> dict:
        """设置聊天窗口的模式。

        Args:
            mode: 模式名称，如 "快速", "思考", "Pro"

        Returns:
            dict: {"status": "ok", "mode": "..."}
        """
        return self._post("/set_mode", {"mode": mode})

    # ── 工具管理 ─────────────────────────────────────────────

    def get_tool(self) -> dict:
        """获取聊天窗口的当前工具。

        Returns:
            dict: {"tool": "none"} 或 {"tool": "生成图片"} 等
        """
        return self._get("/get_tool")

    def set_tool(self, tool: str) -> dict:
        """设置聊天窗口的工具。

        Args:
            tool: 工具名称，如 "Deep Research", "生成图片", "创作音乐"

        Returns:
            dict: {"status": "ok", "tool": "..."}
        """
        return self._post("/set_tool", {"tool": tool})

    # ── 输入框操作 ───────────────────────────────────────────

    def clear_input(self) -> dict:
        """清空聊天窗口的输入框。

        Returns:
            dict: {"status": "ok"}
        """
        return self._post("/clear_input")

    def set_input(self, text: str) -> dict:
        """清空输入框并设置新的输入内容。

        Args:
            text: 要设置的输入内容

        Returns:
            dict: {"status": "ok", "text": "..."}
        """
        return self._post("/set_input", {"text": text})

    def add_input(self, text: str) -> dict:
        """在输入框中追加输入内容。

        Args:
            text: 要追加的输入内容

        Returns:
            dict: {"status": "ok", "text": "..."}
        """
        return self._post("/add_input", {"text": text})

    def get_input(self) -> dict:
        """获取输入框中的当前内容。

        Returns:
            dict: {"text": "..."}
        """
        return self._get("/get_input")

    # ── 消息发送 ─────────────────────────────────────────────

    def send_input(self, wait_response: bool = True) -> dict:
        """发送输入框中的内容。

        Args:
            wait_response: True=等待 Gemini 响应后返回（同步），
                          False=发送后立即返回（异步）

        Returns:
            dict: 如果 wait_response=True，包含 response 字段；
                  否则仅包含 status 字段。
        """
        # 等待响应时可能需要更长的超时
        timeout = self.config.timeout if wait_response else 30
        return self._post(
            "/send_input",
            {"wait_response": wait_response},
            timeout=timeout,
        )

    # ── 便捷方法 ─────────────────────────────────────────────

    def send_message(self, text: str, wait_response: bool = True) -> dict:
        """设置输入并发送（便捷方法）。

        等同于: set_input(text) + send_input(wait_response)

        Args:
            text: 要发送的消息文本
            wait_response: 是否等待响应

        Returns:
            dict: send_input 的返回值
        """
        self.set_input(text)
        return self.send_input(wait_response=wait_response)

    # ── 文件管理 ─────────────────────────────────────────────

    def attach(self, file_path: str) -> dict:
        """上传文件到聊天窗口。

        Args:
            file_path: 要上传的文件路径（服务器端路径）

        Returns:
            dict: {"status": "ok", "file_name": "...", "file_size": ...}
        """
        return self._post("/attach", {"file_path": file_path})

    def detach(self) -> dict:
        """清空聊天窗口中已上传的文件。

        Returns:
            dict: {"status": "ok", "removed_count": ...}
        """
        return self._post("/detach")

    def get_attachments(self) -> dict:
        """获取聊天窗口中已上传的文件列表。

        Returns:
            dict: {"attachments": [...]}
        """
        return self._get("/get_attachments")

    # ── 消息获取 ─────────────────────────────────────────────

    def get_messages(self) -> dict:
        """获取聊天窗口中的消息列表。

        Returns:
            dict: {"messages": [{role, content, html, images, code_blocks}, ...]}
        """
        return self._get("/get_messages")

    # ── 调试 ─────────────────────────────────────────────────

    def screenshot(self, path: str = None) -> dict:
        """对当前浏览器状态截图。

        Args:
            path: 截图保存路径（服务器端路径）

        Returns:
            dict: {"status": "ok", "path": "..."}
        """
        return self._post("/screenshot", {"path": path} if path else None)

    def restart(self) -> dict:
        """重启 GeminiAgency。

        Returns:
            dict: {"status": "ok", "message": "..."}
        """
        return self._post("/restart")
