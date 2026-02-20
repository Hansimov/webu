"""Gemini Server + Client 测试。

测试分为：
- 单元测试：测试 GeminiClient HTTP 客户端逻辑（mock HTTP）
- 单元测试：测试 Server 端点逻辑（mock Agency）
- 单元测试：测试新增的 store/download 图片和截图端点
- 单元测试：测试聊天数据库 API 端点
- 集成测试：测试完整的 Server ↔ Client 交互（需要浏览器）
"""

import asyncio
import json
import pytest
import tempfile
import threading
import time

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from webu.gemini.agency import GeminiAgency
from webu.gemini.client import GeminiClient, GeminiClientConfig
from webu.gemini.config import GeminiConfig
from webu.gemini.errors import (
    GeminiError,
    GeminiPageError,
    GeminiLoginRequiredError,
    GeminiRateLimitError,
)
from webu.gemini.parser import GeminiResponse


# ═══════════════════════════════════════════════════════════════════
# 单元测试：GeminiClientConfig
# ═══════════════════════════════════════════════════════════════════


class TestClientConfig:
    def test_default_config(self):
        config = GeminiClientConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 30002
        assert config.timeout == 300
        assert config.scheme == "http"

    def test_base_url(self):
        config = GeminiClientConfig(host="192.168.1.100", port=8080)
        assert config.base_url == "http://192.168.1.100:8080"

    def test_custom_scheme(self):
        config = GeminiClientConfig(scheme="https", host="example.com", port=443)
        assert config.base_url == "https://example.com:443"


# ═══════════════════════════════════════════════════════════════════
# 单元测试：GeminiClient (mock HTTP)
# ═══════════════════════════════════════════════════════════════════


class TestClientMethods:
    """测试 GeminiClient 的方法确保正确构造 HTTP 请求。"""

    def _make_client(self):
        return GeminiClient(GeminiClientConfig())

    @patch("webu.gemini.client.requests.Session")
    def test_health(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "version": "3.0.0"}
        mock_resp.raise_for_status.return_value = None
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.health()
        assert result["status"] == "ok"

    @patch("webu.gemini.client.requests.Session")
    def test_browser_status(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "data": {"is_ready": True}}
        mock_resp.raise_for_status.return_value = None
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.browser_status()
        assert result["data"]["is_ready"] is True

    @patch("webu.gemini.client.requests.Session")
    def test_new_chat(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "chat_id": "abc123"}
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.new_chat()
        assert result["chat_id"] == "abc123"

    @patch("webu.gemini.client.requests.Session")
    def test_switch_chat(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "chat_id": "xyz789"}
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.switch_chat("xyz789")
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        assert "switch_chat" in call_args[0][0]

    @patch("webu.gemini.client.requests.Session")
    def test_set_mode(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "mode": "Pro"}
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.set_mode("Pro")
        assert result["mode"] == "Pro"

    @patch("webu.gemini.client.requests.Session")
    def test_get_mode(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"mode": "快速"}
        mock_resp.raise_for_status.return_value = None
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.get_mode()
        assert result["mode"] == "快速"

    @patch("webu.gemini.client.requests.Session")
    def test_set_tool(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "tool": "生成图片"}
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.set_tool("生成图片")
        assert result["tool"] == "生成图片"

    @patch("webu.gemini.client.requests.Session")
    def test_get_tool(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"tool": "none"}
        mock_resp.raise_for_status.return_value = None
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.get_tool()
        assert result["tool"] == "none"

    @patch("webu.gemini.client.requests.Session")
    def test_clear_input(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok"}
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.clear_input()
        assert result["status"] == "ok"

    @patch("webu.gemini.client.requests.Session")
    def test_set_input(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "text": "hello"}
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.set_input("hello")
        assert result["text"] == "hello"

    @patch("webu.gemini.client.requests.Session")
    def test_add_input(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "text": " world"}
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.add_input(" world")
        assert result["text"] == " world"

    @patch("webu.gemini.client.requests.Session")
    def test_get_input(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"text": "current input"}
        mock_resp.raise_for_status.return_value = None
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.get_input()
        assert result["text"] == "current input"

    @patch("webu.gemini.client.requests.Session")
    def test_send_input_sync(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "ok",
            "response": {"text": "Hello!", "markdown": "Hello!"},
        }
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.send_input(wait_response=True)
        assert result["status"] == "ok"
        assert "response" in result

    @patch("webu.gemini.client.requests.Session")
    def test_send_input_async(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "message": "已发送"}
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.send_input(wait_response=False)
        assert result["status"] == "ok"

    @patch("webu.gemini.client.requests.Session")
    def test_send_message_convenience(self, mock_session_cls):
        """send_message 应该依次调用 set_input + send_input。"""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok"}
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.send_message("test")
        # 应调用两次 POST: set_input + send_input
        assert mock_session.post.call_count == 2

    @patch("webu.gemini.client.requests.Session")
    def test_attach(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "ok",
            "file_name": "test.pdf",
            "file_size": 1024,
        }
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.attach("/path/to/test.pdf")
        assert result["file_name"] == "test.pdf"

    @patch("webu.gemini.client.requests.Session")
    def test_detach(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "removed_count": 2}
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.detach()
        assert result["removed_count"] == 2

    @patch("webu.gemini.client.requests.Session")
    def test_get_attachments(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "attachments": [{"name": "file.pdf", "type": "pdf", "size": "1KB"}]
        }
        mock_resp.raise_for_status.return_value = None
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.get_attachments()
        assert len(result["attachments"]) == 1

    @patch("webu.gemini.client.requests.Session")
    def test_get_messages(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "model", "content": "hello"},
            ]
        }
        mock_resp.raise_for_status.return_value = None
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.get_messages()
        assert len(result["messages"]) == 2
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][1]["role"] == "model"

    @patch("webu.gemini.client.requests.Session")
    def test_screenshot(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "path": "debug.png"}
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.store_screenshot("debug.png")
        assert result["path"] == "debug.png"

    @patch("webu.gemini.client.requests.Session")
    def test_store_images(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "ok",
            "image_count": 2,
            "saved_count": 2,
            "saved_paths": ["data/images/img_1.png", "data/images/img_2.png"],
        }
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.store_images(output_dir="data/images", prefix="test")
        assert result["saved_count"] == 2

    @patch("webu.gemini.client.requests.Session")
    def test_download_images_empty(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "ok",
            "image_count": 0,
            "download_count": 0,
            "images": [],
        }
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.download_images(output_dir="/tmp/test_images")
        assert result["saved_count"] == 0

    @patch("webu.gemini.client.requests.Session")
    def test_download_images_with_data(self, mock_session_cls):
        import base64

        # 创建一个假的 1x1 PNG 的 base64
        fake_png = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "ok",
            "image_count": 1,
            "download_count": 1,
            "images": [
                {
                    "filename": "test_001.png",
                    "base64_data": fake_png,
                    "mime_type": "image/png",
                    "width": 100,
                    "height": 100,
                }
            ],
        }
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = client.download_images(output_dir=tmpdir, prefix="test")
            assert result["saved_count"] == 1
            assert len(result["saved_paths"]) == 1
            assert Path(result["saved_paths"][0]).exists()

    @patch("webu.gemini.client.requests.Session")
    def test_download_screenshot(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = b"\x89PNG\r\n\x1a\nfake_screenshot"
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "screenshot.png")
            result = client.download_screenshot(path)
            assert result == path
            assert Path(path).exists()
            with open(path, "rb") as f:
                assert f.read() == b"\x89PNG\r\n\x1a\nfake_screenshot"

    @patch("webu.gemini.client.requests.Session")
    def test_restart(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "message": "Agency 已重启"}
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.restart()
        assert result["status"] == "ok"


class TestClientContext:
    """测试 GeminiClient 的上下文管理器。"""

    def test_context_manager(self):
        with GeminiClient() as client:
            assert client is not None
            assert isinstance(client, GeminiClient)

    def test_close(self):
        client = GeminiClient()
        client.close()  # 不应抛出异常


class TestClientErrors:
    """测试客户端的错误处理。"""

    @patch("webu.gemini.client.requests.Session")
    def test_connection_error(self, mock_session_cls):
        import requests

        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.ConnectionError("refused")
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        with pytest.raises(ConnectionError, match="无法连接"):
            client.health()

    @patch("webu.gemini.client.requests.Session")
    def test_timeout_error(self, mock_session_cls):
        import requests

        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.Timeout("timeout")
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        with pytest.raises(TimeoutError, match="请求超时"):
            client.health()

    @patch("webu.gemini.client.requests.Session")
    def test_http_error(self, mock_session_cls):
        import requests

        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"
        mock_resp.json.return_value = {"detail": "Agency 未就绪"}
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_resp
        )
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        with pytest.raises(RuntimeError, match="服务器错误"):
            client.browser_status()


# ═══════════════════════════════════════════════════════════════════
# 单元测试：Server 端点 (mock Agency)
# ═══════════════════════════════════════════════════════════════════


class TestServerEndpoints:
    """使用 FastAPI TestClient 测试 Server 端点（mock Agency）。

    通过 mock GeminiAgency 来避免创建真实浏览器实例。
    使用单个 TestClient 避免重复触发 lifespan。
    """

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from webu.gemini.server import create_gemini_server

        # 完全替换 GeminiAgency 类，避免创建真实 GeminiBrowser
        mock_agency = MagicMock()
        mock_agency.start = AsyncMock()
        mock_agency.stop = AsyncMock()
        mock_agency.is_ready = False  # 默认未就绪
        mock_agency._image_mode = False
        mock_agency._message_count = 0

        with patch("webu.gemini.server.GeminiAgency", return_value=mock_agency):
            app = create_gemini_server(config={"headless": True})
            with TestClient(app) as tc:
                yield tc

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_browser_status_not_ready(self, client):
        """Agency 未就绪（start 被 mock，is_ready=False）时应返回 503。"""
        resp = client.get("/browser_status")
        assert resp.status_code == 503

    def test_new_chat_not_ready(self, client):
        """Agency 未就绪时所有操作端点应返回 503。"""
        resp = client.post("/new_chat")
        assert resp.status_code == 503

    def test_get_mode_not_ready(self, client):
        resp = client.get("/get_mode")
        assert resp.status_code == 503

    def test_send_input_not_ready(self, client):
        resp = client.post("/send_input", json={"wait_response": True})
        assert resp.status_code == 503

    def test_store_images_not_ready(self, client):
        resp = client.post("/store_images")
        assert resp.status_code == 503

    def test_download_images_not_ready(self, client):
        resp = client.post("/download_images")
        assert resp.status_code == 503

    def test_store_screenshot_not_ready(self, client):
        resp = client.post("/store_screenshot")
        assert resp.status_code == 503

    def test_download_screenshot_not_ready(self, client):
        resp = client.post("/download_screenshot")
        assert resp.status_code == 503


# ═══════════════════════════════════════════════════════════════════
# 单元测试：ChatDB API 端点
# ═══════════════════════════════════════════════════════════════════


class TestChatDBEndpoints:
    """测试聊天数据库的 REST API 端点。"""

    @pytest.fixture
    def client(self, tmp_path):
        from fastapi.testclient import TestClient
        from webu.gemini.server import create_gemini_server

        mock_agency = MagicMock()
        mock_agency.start = AsyncMock()
        mock_agency.stop = AsyncMock()
        mock_agency.is_ready = False
        mock_agency._image_mode = False
        mock_agency._message_count = 0

        # ChatDatabase is instantiated inside create_gemini_server.
        # Patch the ChatDatabase class so it uses a temp directory.
        from webu.gemini.chatdb import ChatDatabase

        original_init = ChatDatabase.__init__

        def patched_init(self_db, data_dir=None):
            original_init(self_db, data_dir=str(tmp_path / "test_chats"))

        with patch("webu.gemini.server.GeminiAgency", return_value=mock_agency):
            with patch.object(ChatDatabase, "__init__", patched_init):
                app = create_gemini_server(config={"headless": True})
                with TestClient(app) as tc:
                    yield tc

    def test_create_chat(self, client):
        resp = client.post("/chatdb/create", json={"title": "Test Chat"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "chat_id" in data

    def test_list_chats_empty(self, client):
        resp = client.get("/chatdb/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chats"] == []

    def test_create_and_list_chats(self, client):
        client.post("/chatdb/create", json={"title": "Chat 1"})
        client.post("/chatdb/create", json={"title": "Chat 2"})
        resp = client.get("/chatdb/list")
        data = resp.json()
        assert len(data["chats"]) == 2

    def test_get_chat(self, client):
        resp = client.post("/chatdb/create", json={"title": "Get Me"})
        chat_id = resp.json()["chat_id"]

        resp = client.get(f"/chatdb/{chat_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chat"]["title"] == "Get Me"

    def test_get_chat_not_found(self, client):
        resp = client.get("/chatdb/nonexistent_id")
        assert resp.status_code == 404

    def test_delete_chat(self, client):
        resp = client.post("/chatdb/create", json={"title": "Delete Me"})
        chat_id = resp.json()["chat_id"]

        resp = client.delete(f"/chatdb/{chat_id}")
        assert resp.status_code == 200

        resp = client.get(f"/chatdb/{chat_id}")
        assert resp.status_code == 404

    def test_delete_chat_not_found(self, client):
        resp = client.delete("/chatdb/nonexistent_id")
        assert resp.status_code == 404

    def test_update_title(self, client):
        resp = client.post("/chatdb/create", json={"title": "Old"})
        chat_id = resp.json()["chat_id"]

        resp = client.put(f"/chatdb/{chat_id}/title", json={"title": "New"})
        assert resp.status_code == 200

        resp = client.get(f"/chatdb/{chat_id}")
        assert resp.json()["chat"]["title"] == "New"

    def test_add_message(self, client):
        resp = client.post("/chatdb/create", json={"title": "Msgs"})
        chat_id = resp.json()["chat_id"]

        resp = client.post(
            f"/chatdb/{chat_id}/messages",
            json={"role": "user", "content": "Hello!"},
        )
        assert resp.status_code == 200
        assert resp.json()["message_index"] == 0

    def test_get_messages(self, client):
        resp = client.post("/chatdb/create", json={"title": "Msgs"})
        chat_id = resp.json()["chat_id"]

        client.post(
            f"/chatdb/{chat_id}/messages",
            json={"role": "user", "content": "Q"},
        )
        client.post(
            f"/chatdb/{chat_id}/messages",
            json={"role": "model", "content": "A", "files": ["img.png"]},
        )

        resp = client.get(f"/chatdb/{chat_id}/messages")
        data = resp.json()
        assert len(data["messages"]) == 2
        assert data["messages"][0]["content"] == "Q"
        assert data["messages"][1]["files"] == ["img.png"]

    def test_get_single_message(self, client):
        resp = client.post("/chatdb/create")
        chat_id = resp.json()["chat_id"]
        client.post(
            f"/chatdb/{chat_id}/messages",
            json={"role": "user", "content": "Hello"},
        )
        resp = client.get(f"/chatdb/{chat_id}/messages/0")
        assert resp.status_code == 200
        assert resp.json()["message"]["content"] == "Hello"

    def test_update_message(self, client):
        resp = client.post("/chatdb/create")
        chat_id = resp.json()["chat_id"]
        client.post(
            f"/chatdb/{chat_id}/messages",
            json={"role": "user", "content": "old"},
        )
        resp = client.put(
            f"/chatdb/{chat_id}/messages/0",
            json={"content": "new"},
        )
        assert resp.status_code == 200

        resp = client.get(f"/chatdb/{chat_id}/messages/0")
        assert resp.json()["message"]["content"] == "new"

    def test_delete_message(self, client):
        resp = client.post("/chatdb/create")
        chat_id = resp.json()["chat_id"]
        client.post(
            f"/chatdb/{chat_id}/messages",
            json={"role": "user", "content": "A"},
        )
        client.post(
            f"/chatdb/{chat_id}/messages",
            json={"role": "model", "content": "B"},
        )
        resp = client.delete(f"/chatdb/{chat_id}/messages/0")
        assert resp.status_code == 200

        resp = client.get(f"/chatdb/{chat_id}/messages")
        assert len(resp.json()["messages"]) == 1
        assert resp.json()["messages"][0]["content"] == "B"

    def test_search(self, client):
        resp = client.post("/chatdb/create", json={"title": "Python 学习"})
        id1 = resp.json()["chat_id"]
        resp = client.post("/chatdb/create", json={"title": "Java 入门"})
        id2 = resp.json()["chat_id"]

        resp = client.post("/chatdb/search", json={"query": "Python"})
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["chat_id"] == id1

    def test_stats(self, client):
        client.post("/chatdb/create")
        resp = client.get("/chatdb/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chat_count"] == 1


# ═══════════════════════════════════════════════════════════════════
# 单元测试：GeminiAgency 方法（mock browser）
# ═══════════════════════════════════════════════════════════════════


class TestAgencyMethods:
    """测试 GeminiAgency 的公共方法（mock 浏览器交互）。"""

    def _make_agency(self):
        """创建一个 mock Agency 实例。"""
        agency = GeminiAgency.__new__(GeminiAgency)
        agency.config = GeminiConfig()
        agency.browser = MagicMock()
        agency.parser = MagicMock()
        agency.is_ready = True
        agency._image_mode = False
        agency._message_count = 0
        # Mock page
        agency.browser.page = AsyncMock()
        agency.browser.get_status.return_value = {"is_started": True}
        agency.browser.get_page_info = AsyncMock(
            return_value={"url": "https://gemini.google.com/app", "title": "Gemini"}
        )
        return agency

    @pytest.mark.asyncio
    async def test_browser_status_not_ready(self):
        agency = self._make_agency()
        agency.is_ready = False
        status = await agency.browser_status()
        assert status["is_ready"] is False

    @pytest.mark.asyncio
    async def test_browser_status_ready(self):
        agency = self._make_agency()
        # Mock check_login_status
        agency.check_login_status = AsyncMock(
            return_value={"logged_in": True, "is_pro": True, "message": "ok"}
        )
        agency.get_mode = AsyncMock(return_value={"mode": "Pro"})
        agency.get_tool = AsyncMock(return_value={"tool": "none"})

        status = await agency.browser_status()
        assert status["is_ready"] is True
        assert "browser" in status
        assert "page" in status
        assert "login" in status

    @pytest.mark.asyncio
    async def test_check_login_not_ready(self):
        agency = self._make_agency()
        agency.is_ready = False
        with pytest.raises(GeminiPageError):
            await agency.check_login_status()

    @pytest.mark.asyncio
    async def test_ensure_logged_in_raises(self):
        agency = self._make_agency()
        agency.check_login_status = AsyncMock(
            return_value={"logged_in": False, "message": "not logged in"}
        )
        with pytest.raises(GeminiLoginRequiredError):
            await agency.ensure_logged_in()

    def test_extract_chat_id(self):
        agency = GeminiAgency.__new__(GeminiAgency)
        assert (
            agency._extract_chat_id("https://gemini.google.com/app/abc123") == "abc123"
        )
        assert agency._extract_chat_id("https://gemini.google.com/app") == ""
        assert (
            agency._extract_chat_id("https://gemini.google.com/app/a-b_c/extra")
            == "a-b_c"
        )

    def test_save_images_empty(self):
        agency = self._make_agency()
        response = GeminiResponse()
        paths = agency.save_images(response)
        assert paths == []

    def test_save_images_with_data(self):
        import base64
        from webu.gemini.parser import GeminiImage

        agency = self._make_agency()
        b64 = base64.b64encode(b"fake png data").decode()
        response = GeminiResponse(
            images=[
                GeminiImage(
                    base64_data=b64, mime_type="image/png", width=100, height=100
                )
            ]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = agency.save_images(response, output_dir=tmpdir)
            assert len(paths) == 1
            assert Path(paths[0]).exists()


# ═══════════════════════════════════════════════════════════════════
# 单元测试：Run 模块
# ═══════════════════════════════════════════════════════════════════


class TestRunModule:
    def test_runner_status_no_state(self):
        from webu.gemini.run import GeminiRunner

        runner = GeminiRunner()
        status = runner.status()
        assert status["status"] in ("not_running", "stopped", "running")


# ═══════════════════════════════════════════════════════════════════
# 集成测试（需要浏览器 + 服务器）
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
async def shared_agency(request):
    """模块级别共享的 GeminiAgency（仅在集成测试时创建）。"""
    # 检查是否有集成测试要运行，避免在 -m "not integration" 时启动浏览器
    markers = [item.get_closest_marker("integration") for item in request.session.items]
    if not any(markers):
        pytest.skip("No integration tests selected")
    agency = GeminiAgency(config={"headless": False})
    await agency.start()
    yield agency
    await agency.stop()


@pytest.mark.integration
class TestAgencyIntegration:
    """GeminiAgency 集成测试 — 需要运行中的浏览器。"""

    @pytest.mark.asyncio
    async def test_browser_status(self, shared_agency):
        status = await shared_agency.browser_status()
        assert status["is_ready"] is True
        assert "browser" in status

    @pytest.mark.asyncio
    async def test_new_chat(self, shared_agency):
        result = await shared_agency.new_chat()
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_get_mode(self, shared_agency):
        result = await shared_agency.get_mode()
        assert "mode" in result

    @pytest.mark.asyncio
    async def test_get_tool(self, shared_agency):
        result = await shared_agency.get_tool()
        assert "tool" in result

    @pytest.mark.asyncio
    async def test_clear_input(self, shared_agency):
        result = await shared_agency.clear_input()
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_set_and_get_input(self, shared_agency):
        await shared_agency.set_input("Hello test")
        result = await shared_agency.get_input()
        # 输入框应该有内容（可能因策略不同而有差异）
        assert "text" in result

    @pytest.mark.asyncio
    async def test_add_input(self, shared_agency):
        await shared_agency.clear_input()
        await shared_agency.set_input("Part 1")
        await shared_agency.add_input(" Part 2")
        result = await shared_agency.get_input()
        assert "text" in result

    @pytest.mark.asyncio
    async def test_get_messages_empty_chat(self, shared_agency):
        await shared_agency.new_chat()
        result = await shared_agency.get_messages()
        assert "messages" in result

    @pytest.mark.asyncio
    async def test_get_attachments_empty(self, shared_agency):
        result = await shared_agency.get_attachments()
        assert "attachments" in result

    @pytest.mark.asyncio
    async def test_send_simple_message(self, shared_agency):
        """发送简单消息并验证响应。"""
        await shared_agency.new_chat()
        response = await shared_agency.send_message("Say 'Hi' in one word.")
        assert response is not None
        assert len(response.text) > 0
        assert not response.is_error

    @pytest.mark.asyncio
    async def test_send_input_sync(self, shared_agency):
        """通过 set_input + send_input 发送消息（同步等待响应）。"""
        await shared_agency.new_chat()
        await shared_agency.set_input("What is 2+2? Reply with just the number.")
        result = await shared_agency.send_input(wait_response=True)
        assert result["status"] == "ok"
        assert "response" in result

    @pytest.mark.asyncio
    async def test_send_input_async(self, shared_agency):
        """通过 send_input 异步模式发送消息。"""
        await shared_agency.new_chat()
        await shared_agency.set_input("Hello async test")
        result = await shared_agency.send_input(wait_response=False)
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_get_messages_after_chat(self, shared_agency):
        """发送消息后获取消息列表。"""
        await shared_agency.new_chat()
        await shared_agency.send_message("Say 'test response'")
        result = await shared_agency.get_messages()
        assert "messages" in result
        assert len(result["messages"]) > 0

    @pytest.mark.asyncio
    async def test_screenshot(self, shared_agency):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test.png")
            data = await shared_agency.screenshot(path=path)
            assert data is not None
            assert Path(path).exists()

    @pytest.mark.asyncio
    async def test_save_images_empty(self, shared_agency):
        """未生成图片时 save_images 返回空列表。"""
        await shared_agency.new_chat()
        await shared_agency.send_message("Say 'hello'")
        from webu.gemini.parser import GeminiResponse

        response = GeminiResponse()
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = shared_agency.save_images(response, output_dir=tmpdir)
            assert len(paths) == 0


@pytest.mark.integration
class TestClientIntegration:
    """GeminiClient 集成测试 — 连接到运行中的服务器。

    需要先启动服务器: python -m webu.gemini.run start
    运行: pytest tests/gemini/test_server_client.py -m integration -k TestClientIntegration -v
    """

    @pytest.fixture(autouse=True)
    def setup_client(self):
        """在每个测试前创建 client。"""
        self.client = GeminiClient(
            GeminiClientConfig(host="127.0.0.1", port=30002, timeout=300)
        )
        yield
        self.client.close()

    def test_health(self):
        result = self.client.health()
        assert result["status"] == "ok"
        assert result["version"] == "4.0.0"

    def test_browser_status(self):
        result = self.client.browser_status()
        assert result["status"] == "ok"
        assert "data" in result
        assert result["data"]["is_ready"] is True

    def test_store_screenshot(self):
        """服务器端截图保存。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test_store.png")
            result = self.client.store_screenshot(path)
            assert result["status"] == "ok"
            assert Path(result["path"]).exists()

    def test_download_screenshot(self):
        """下载截图到本地。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test_download.png")
            result = self.client.download_screenshot(path)
            assert result == path
            assert Path(path).exists()
            assert Path(path).stat().st_size > 1000  # PNG 应该有一定大小

    def test_store_images_no_images(self):
        """无图片时 store_images 返回空。"""
        self.client.new_chat()
        import time

        time.sleep(1)
        self.client.send_message("Say 'hello' in one word", wait_response=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.client.store_images(output_dir=tmpdir, prefix="test")
            assert result["status"] == "ok"
            assert result["image_count"] == 0

    def test_download_images_no_images(self):
        """无图片时 download_images 返回空。"""
        self.client.new_chat()
        import time

        time.sleep(1)
        self.client.send_message("Say 'hello' in one word", wait_response=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.client.download_images(output_dir=tmpdir, prefix="test")
            assert result["status"] == "ok"
            assert result["image_count"] == 0
            assert result["saved_count"] == 0
            assert result["saved_paths"] == []

    def test_chatdb_full_lifecycle(self):
        """聊天数据库完整生命周期测试。"""
        # 创建聊天
        create_result = self.client.chatdb_create(title="集成测试聊天")
        assert create_result["status"] == "ok"
        chat_id = create_result["chat_id"]
        assert len(chat_id) > 0

        try:
            # 添加消息
            msg1 = self.client.chatdb_add_message(chat_id, role="user", content="你好")
            assert msg1["status"] == "ok"
            assert msg1["message_index"] == 0

            msg2 = self.client.chatdb_add_message(
                chat_id, role="model", content="你好！有什么可以帮您的？"
            )
            assert msg2["status"] == "ok"
            assert msg2["message_index"] == 1

            # 获取聊天
            chat = self.client.chatdb_get(chat_id)
            assert chat["status"] == "ok"
            assert chat["chat"]["title"] == "集成测试聊天"
            assert len(chat["chat"]["messages"]) == 2

            # 获取消息
            msgs = self.client.chatdb_get_messages(chat_id)
            assert msgs["status"] == "ok"
            assert len(msgs["messages"]) == 2
            assert msgs["messages"][0]["role"] == "user"
            assert msgs["messages"][1]["role"] == "model"

            # 获取单条消息
            single = self.client.chatdb_get_message(chat_id, 0)
            assert single["status"] == "ok"
            assert single["message"]["content"] == "你好"

            # 更新消息
            self.client.chatdb_update_message(chat_id, 0, content="你好世界")
            updated = self.client.chatdb_get_message(chat_id, 0)
            assert updated["message"]["content"] == "你好世界"

            # 更新标题
            self.client.chatdb_update_title(chat_id, title="更新后的标题")
            chat2 = self.client.chatdb_get(chat_id)
            assert chat2["chat"]["title"] == "更新后的标题"

            # 列出聊天
            chats = self.client.chatdb_list()
            assert chats["status"] == "ok"
            found = any(c["chat_id"] == chat_id for c in chats["chats"])
            assert found, f"聊天 {chat_id} 未在列表中找到"

            # 搜索
            search = self.client.chatdb_search(query="你好")
            assert search["status"] == "ok"
            assert len(search["results"]) > 0

            # 统计
            stats = self.client.chatdb_stats()
            assert stats["status"] == "ok"
            assert stats["total_chats"] >= 1
            assert stats["total_messages"] >= 2

            # 删除消息
            del_msg = self.client.chatdb_delete_message(chat_id, 1)
            assert del_msg["status"] == "ok"
            msgs_after = self.client.chatdb_get_messages(chat_id)
            assert len(msgs_after["messages"]) == 1

        finally:
            # 清理：删除聊天
            self.client.chatdb_delete(chat_id)

        # 验证删除
        chats_after = self.client.chatdb_list()
        not_found = all(c["chat_id"] != chat_id for c in chats_after["chats"])
        assert not_found, f"聊天 {chat_id} 删除后仍在列表中"

    def test_chatdb_custom_id(self):
        """使用自定义 chat_id 创建聊天。"""
        import uuid

        custom_id = f"test_{uuid.uuid4().hex[:8]}"
        result = self.client.chatdb_create(title="自定义ID测试", chat_id=custom_id)
        assert result["status"] == "ok"
        assert result["chat_id"] == custom_id

        try:
            chat = self.client.chatdb_get(custom_id)
            assert chat["chat"]["title"] == "自定义ID测试"
        finally:
            self.client.chatdb_delete(custom_id)

    def test_chatdb_message_with_files(self):
        """消息带文件路径引用。"""
        create = self.client.chatdb_create(title="文件引用测试")
        chat_id = create["chat_id"]

        try:
            self.client.chatdb_add_message(
                chat_id,
                role="user",
                content="请看这张图片",
                files=["data/images/test.png", "data/images/test2.png"],
            )
            msg = self.client.chatdb_get_message(chat_id, 0)
            assert msg["message"]["files"] == [
                "data/images/test.png",
                "data/images/test2.png",
            ]
        finally:
            self.client.chatdb_delete(chat_id)

    def test_send_message_and_record(self):
        """发送消息并保存到 ChatDB。"""
        import time

        # 新建浏览器聊天并发送消息
        self.client.new_chat()
        time.sleep(1)
        result = self.client.send_message("Say 'test' in one word", wait_response=True)
        assert result["status"] == "ok"

        response_text = result.get("response", {}).get("text", "")
        assert len(response_text) > 0

        # 保存到 ChatDB
        create = self.client.chatdb_create(title="自动保存测试")
        chat_id = create["chat_id"]

        try:
            self.client.chatdb_add_message(
                chat_id, role="user", content="Say 'test' in one word"
            )
            self.client.chatdb_add_message(chat_id, role="model", content=response_text)

            # 验证
            chat = self.client.chatdb_get(chat_id)
            assert len(chat["chat"]["messages"]) == 2
            assert chat["chat"]["messages"][0]["role"] == "user"
            assert chat["chat"]["messages"][1]["role"] == "model"
            assert len(chat["chat"]["messages"][1]["content"]) > 0
        finally:
            self.client.chatdb_delete(chat_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-m", "not integration"])
