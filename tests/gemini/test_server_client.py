"""Gemini Server + Client 测试。

测试分为：
- 单元测试：测试 GeminiClient HTTP 客户端逻辑（mock HTTP）
- 单元测试：测试 Server 端点逻辑（mock Agency）
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
        result = client.screenshot("debug.png")
        assert result["path"] == "debug.png"

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


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-m", "not integration"])
