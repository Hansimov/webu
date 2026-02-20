"""GeminiClient: HTTP 客户端。

封装对 Gemini FastAPI 服务器的 HTTP 调用，提供与服务器接口一一对应的方法，
使用户可以通过 Python API 操作 Gemini 聊天窗口，无需关心底层 HTTP 请求细节。

支持：预设管理、聊天管理、图片存储/下载、截图存储/下载、聊天历史数据库。
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

        # 使用预设创建新聊天
        client.new_chat(mode="Pro", tool="生成图片")

        # 同时设置模式和工具
        client.set_presets(mode="Pro", tool="生成图片")
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
            elif method.upper() == "PUT":
                resp = self._session.put(url, json=json_data, timeout=timeout)
            elif method.upper() == "DELETE":
                resp = self._session.delete(url, timeout=timeout)
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
            dict: 包含 is_ready, login, page, mode, tool, presets 等状态信息
        """
        return self._get("/browser_status")

    # ── 预设配置 ─────────────────────────────────────────────

    def set_presets(
        self, mode: Optional[str] = None, tool: Optional[str] = None
    ) -> dict:
        """同时设置 tool 和 mode 的预设配置。

        先设置 mode，再设置 tool。预设会在首次发送消息时自动验证。

        Args:
            mode: 模式名称，如 "快速", "思考", "Pro"
            tool: 工具名称，如 "Deep Research", "生成图片", "none" (清除工具)

        Returns:
            dict: 包含 mode, tool, mode_changed, tool_changed
        """
        data = {}
        if mode is not None:
            data["mode"] = mode
        if tool is not None:
            data["tool"] = tool
        return self._post("/set_presets", data)

    def get_presets(self) -> dict:
        """获取当前预设配置。

        Returns:
            dict: {"presets": {"mode": ..., "tool": ..., "verified": ...}}
        """
        return self._get("/get_presets")

    # ── 聊天会话管理 ─────────────────────────────────────────

    def new_chat(self, mode: Optional[str] = None, tool: Optional[str] = None) -> dict:
        """创建新的聊天窗口。

        支持可选参数 mode 和 tool，在创建新聊天后自动设置。

        Args:
            mode: 可选，创建后设置的模式
            tool: 可选，创建后设置的工具

        Returns:
            dict: {"status": "ok", "chat_id": "...", "mode": ..., "tool": ...}
        """
        data = {}
        if mode is not None:
            data["mode"] = mode
        if tool is not None:
            data["tool"] = tool
        return self._post("/new_chat", data if data else None)

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
            mode: 模式名称，如 "快速", "思考", "Pro"。支持别名：
                  fast→快速, think→思考, pro→Pro

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
            tool: 工具名称，如 "Deep Research", "生成图片", "创作音乐"。
                  支持别名：image→生成图片, music→创作音乐

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

        在新聊天首次发送前，服务器会自动验证 tool/mode 预设。

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

    # ── 图片管理 ─────────────────────────────────────────────

    def store_images(self, output_dir: str = "data/images", prefix: str = "") -> dict:
        """将最新响应中的图片保存到服务器端指定目录。

        Args:
            output_dir: 图片保存目录（服务器端路径）
            prefix: 文件名前缀

        Returns:
            dict: {"status": "ok", "image_count": ..., "saved_count": ..., "saved_paths": [...]}
        """
        return self._post(
            "/store_images",
            {"output_dir": output_dir, "prefix": prefix},
        )

    def download_images(
        self, output_dir: str = "data/images", prefix: str = ""
    ) -> dict:
        """获取最新响应中的图片数据并保存到本地。

        从服务器获取 base64 编码的图片数据，解码后保存到本地目录。

        Args:
            output_dir: 本地保存目录
            prefix: 文件名前缀

        Returns:
            dict: {"status": "ok", "image_count": ..., "saved_count": ..., "saved_paths": [...]}
        """
        import base64
        from pathlib import Path as _Path

        result = self._post("/download_images", {"prefix": prefix})
        images = result.get("images", [])
        if not images:
            return {
                "status": "ok",
                "image_count": 0,
                "saved_count": 0,
                "saved_paths": [],
            }

        # 在本地保存图片
        out_path = _Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        saved_paths = []
        for img_data in images:
            b64 = img_data.get("base64_data", "")
            filename = img_data.get("filename", "image.png")
            if not b64:
                continue
            filepath = out_path / filename
            try:
                raw = base64.b64decode(b64)
                with open(filepath, "wb") as f:
                    f.write(raw)
                saved_paths.append(str(filepath))
            except Exception as e:
                logger.warn(f"  × 保存图片 {filename} 失败: {e}")

        return {
            "status": "ok",
            "image_count": result.get("image_count", 0),
            "saved_count": len(saved_paths),
            "saved_paths": saved_paths,
        }

    # ── 截图管理 ─────────────────────────────────────────────

    def store_screenshot(self, path: str = "data/gemini_screenshot.png") -> dict:
        """对当前浏览器状态截图并保存到服务器端指定路径。

        Args:
            path: 截图保存路径（服务器端路径）

        Returns:
            dict: {"status": "ok", "path": "..."}
        """
        return self._post("/store_screenshot", {"path": path})

    def download_screenshot(self, path: str = "screenshot.png") -> str:
        """对当前浏览器状态截图并下载保存到本地。

        从服务器获取 PNG 截图数据，保存到本地指定路径。

        Args:
            path: 本地保存路径

        Returns:
            str: 本地保存路径
        """
        from pathlib import Path as _Path

        url = f"{self.base_url}/download_screenshot"
        timeout = self.config.timeout

        try:
            resp = self._session.post(url, timeout=timeout)
            resp.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"下载截图失败: {e}") from e

        _Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(resp.content)
        return path

    # ── 聊天历史数据库 ───────────────────────────────────────

    def chatdb_create(self, title: str = "", chat_id: str = None) -> dict:
        """在聊天数据库中创建新的聊天记录。

        Args:
            title: 聊天标题
            chat_id: 自定义聊天 ID（可选）

        Returns:
            dict: {"status": "ok", "chat_id": "..."}
        """
        data = {"title": title}
        if chat_id:
            data["chat_id"] = chat_id
        return self._post("/chatdb/create", data)

    def chatdb_list(self) -> dict:
        """列出所有聊天记录的摘要。

        Returns:
            dict: {"status": "ok", "chats": [...]}
        """
        return self._get("/chatdb/list")

    def chatdb_stats(self) -> dict:
        """获取聊天数据库统计信息。

        Returns:
            dict: {"status": "ok", "chat_count": ..., "total_messages": ...}
        """
        return self._get("/chatdb/stats")

    def chatdb_get(self, chat_id: str) -> dict:
        """获取指定聊天的完整数据。

        Args:
            chat_id: 聊天 ID

        Returns:
            dict: {"status": "ok", "chat": {...}}
        """
        return self._get(f"/chatdb/{chat_id}")

    def chatdb_delete(self, chat_id: str) -> dict:
        """删除指定聊天记录。

        Args:
            chat_id: 聊天 ID

        Returns:
            dict: {"status": "ok", "message": "..."}
        """
        return self._request("DELETE", f"/chatdb/{chat_id}")

    def chatdb_update_title(self, chat_id: str, title: str) -> dict:
        """更新聊天标题。

        Args:
            chat_id: 聊天 ID
            title: 新标题

        Returns:
            dict: {"status": "ok", "chat_id": "...", "title": "..."}
        """
        return self._request("PUT", f"/chatdb/{chat_id}/title", {"title": title})

    def chatdb_get_messages(self, chat_id: str) -> dict:
        """获取指定聊天的所有消息。

        Args:
            chat_id: 聊天 ID

        Returns:
            dict: {"status": "ok", "messages": [...]}
        """
        return self._get(f"/chatdb/{chat_id}/messages")

    def chatdb_add_message(
        self,
        chat_id: str,
        role: str,
        content: str = "",
        files: list[str] = None,
    ) -> dict:
        """向聊天中添加一条消息。

        Args:
            chat_id: 聊天 ID
            role: 消息角色（"user" 或 "model"）
            content: 消息内容
            files: 关联文件路径列表

        Returns:
            dict: {"status": "ok", "message_index": ...}
        """
        data = {"role": role, "content": content, "files": files or []}
        return self._post(f"/chatdb/{chat_id}/messages", data)

    def chatdb_get_message(self, chat_id: str, message_index: int) -> dict:
        """获取指定索引的消息。

        Args:
            chat_id: 聊天 ID
            message_index: 消息索引

        Returns:
            dict: {"status": "ok", "message": {...}}
        """
        return self._get(f"/chatdb/{chat_id}/messages/{message_index}")

    def chatdb_update_message(
        self,
        chat_id: str,
        message_index: int,
        content: str = None,
        files: list[str] = None,
    ) -> dict:
        """更新指定索引的消息。

        Args:
            chat_id: 聊天 ID
            message_index: 消息索引
            content: 新内容（None 则不更新）
            files: 新文件列表（None 则不更新）

        Returns:
            dict: {"status": "ok", "message": "..."}
        """
        data = {}
        if content is not None:
            data["content"] = content
        if files is not None:
            data["files"] = files
        return self._request("PUT", f"/chatdb/{chat_id}/messages/{message_index}", data)

    def chatdb_delete_message(self, chat_id: str, message_index: int) -> dict:
        """删除指定索引的消息。

        Args:
            chat_id: 聊天 ID
            message_index: 消息索引

        Returns:
            dict: {"status": "ok", "message": "..."}
        """
        return self._request("DELETE", f"/chatdb/{chat_id}/messages/{message_index}")

    def chatdb_search(self, query: str) -> dict:
        """搜索包含指定关键字的聊天。

        Args:
            query: 搜索关键字

        Returns:
            dict: {"status": "ok", "results": [...]}
        """
        return self._post("/chatdb/search", {"query": query})

    # ── 调试 ─────────────────────────────────────────────────

    def restart(self) -> dict:
        """重启 GeminiAgency。

        Returns:
            dict: {"status": "ok", "message": "..."}
        """
        return self._post("/restart")
