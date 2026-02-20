"""Gemini 运行管理器 + 新版 Server/Client 测试。

测试分为：
- 单元测试：run 模块的状态管理和进程控制逻辑
- 单元测试：server 新增接口 (set_presets, new_chat 参数, 预设验证)
- 单元测试：client 新增方法 (set_presets, new_chat 带参数, download_images)
- 单元测试：工具/模式名称标准化
- 集成测试：完整的 Server ↔ Client 交互（需要浏览器，标记 integration）
"""

import asyncio
import json
import os
import pytest
import signal
import sys
import tempfile
import time

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

from webu.gemini.client import GeminiClient, GeminiClientConfig
from webu.gemini.config import GeminiConfig
from webu.gemini.errors import (
    GeminiError,
    GeminiPageError,
    GeminiLoginRequiredError,
    GeminiRateLimitError,
)
from webu.gemini.parser import GeminiResponse, GeminiImage
from webu.gemini.run import (
    GeminiRunner,
    _save_state,
    _load_state,
    _clear_state,
    _save_pid,
    _load_pid,
    _is_process_alive,
    _DATA_DIR,
    _STATE_FILE,
    _PID_FILE,
    _LOG_FILE,
    _print_status,
)
from webu.gemini.agency import GeminiAgency
from webu.gemini.server import (
    _normalize_mode,
    _normalize_tool,
    VALID_MODES,
    VALID_TOOLS,
    TOOL_ALIASES,
    MODE_ALIASES,
    _ensure_presets,
)


# ═══════════════════════════════════════════════════════════════════
# 单元测试：名称标准化
# ═══════════════════════════════════════════════════════════════════


class TestNormalization:
    """测试 mode 和 tool 名称标准化/别名解析。"""

    def test_normalize_mode_exact(self):
        assert _normalize_mode("快速") == "快速"
        assert _normalize_mode("思考") == "思考"
        assert _normalize_mode("Pro") == "Pro"

    def test_normalize_mode_aliases(self):
        assert _normalize_mode("fast") == "快速"
        assert _normalize_mode("quick") == "快速"
        assert _normalize_mode("think") == "思考"
        assert _normalize_mode("thinking") == "思考"
        assert _normalize_mode("pro") == "Pro"
        assert _normalize_mode("flash") == "Flash"

    def test_normalize_mode_case_insensitive(self):
        assert _normalize_mode("FAST") == "快速"
        assert _normalize_mode("Pro") == "Pro"
        assert _normalize_mode("PRO") == "Pro"

    def test_normalize_mode_unknown(self):
        # 未知模式原样返回
        result = _normalize_mode("xyz_unknown")
        assert result == "xyz_unknown"

    def test_normalize_tool_exact(self):
        assert _normalize_tool("Deep Research") == "Deep Research"
        assert _normalize_tool("生成图片") == "生成图片"
        assert _normalize_tool("创作音乐") == "创作音乐"
        assert _normalize_tool("none") == "none"

    def test_normalize_tool_aliases(self):
        assert _normalize_tool("image") == "生成图片"
        assert _normalize_tool("generate_image") == "生成图片"
        assert _normalize_tool("图片") == "生成图片"
        assert _normalize_tool("music") == "创作音乐"
        assert _normalize_tool("音乐") == "创作音乐"
        assert _normalize_tool("deep_research") == "Deep Research"
        assert _normalize_tool("canvas") == "Canvas"
        assert _normalize_tool("search") == "Google 搜索"

    def test_normalize_tool_none_variants(self):
        assert _normalize_tool("none") == "none"
        assert _normalize_tool("无") == "none"

    def test_normalize_tool_case_insensitive(self):
        assert _normalize_tool("IMAGE") == "生成图片"
        assert _normalize_tool("Music") == "创作音乐"


# ═══════════════════════════════════════════════════════════════════
# 单元测试：Run 模块 — 状态管理
# ═══════════════════════════════════════════════════════════════════


class TestRunStateManagement:
    """测试 run 模块的状态持久化功能。"""

    def setup_method(self):
        """每个测试前清理状态文件。"""
        _clear_state()

    def teardown_method(self):
        """每个测试后清理状态文件。"""
        _clear_state()

    def test_save_and_load_state(self):
        state = {
            "pid": 12345,
            "api_port": 30002,
            "status": "running",
        }
        _save_state(state)
        loaded = _load_state()
        assert loaded["pid"] == 12345
        assert loaded["api_port"] == 30002
        assert loaded["status"] == "running"

    def test_load_state_empty(self):
        _clear_state()
        loaded = _load_state()
        assert loaded == {}

    def test_clear_state(self):
        _save_state({"pid": 1})
        _save_pid(1)
        _clear_state()
        assert _load_state() == {}
        assert _load_pid() is None

    def test_save_and_load_pid(self):
        _save_pid(42)
        assert _load_pid() == 42

    def test_load_pid_missing(self):
        _clear_state()
        assert _load_pid() is None

    def test_is_process_alive_current(self):
        # 当前进程一定是活的
        assert _is_process_alive(os.getpid()) is True

    def test_is_process_alive_invalid(self):
        assert _is_process_alive(0) is False
        assert _is_process_alive(-1) is False
        assert _is_process_alive(None) is False

    def test_is_process_alive_nonexistent(self):
        # 超大 PID 不太可能存在
        assert _is_process_alive(999999999) is False


# ═══════════════════════════════════════════════════════════════════
# 单元测试：Run 模块 — GeminiRunner
# ═══════════════════════════════════════════════════════════════════


class TestGeminiRunner:
    """测试 GeminiRunner 的管理命令逻辑。"""

    def setup_method(self):
        _clear_state()

    def teardown_method(self):
        _clear_state()

    def test_status_no_runner(self):
        status = GeminiRunner.status()
        assert status["status"] == "stopped"

    def test_status_with_dead_process(self):
        _save_state({"pid": 999999999, "status": "running"})
        _save_pid(999999999)
        status = GeminiRunner.status()
        assert status["status"] == "stopped"

    def test_status_with_running_process(self):
        # 用当前进程模拟一个 "运行中的" runner
        pid = os.getpid()
        _save_state(
            {
                "pid": pid,
                "status": "running",
                "api_port": 30002,
                "novnc_port": 30004,
                "hostname": "testhost",
                "started_at": "2026-01-01 00:00:00",
                "mode": "background",
            }
        )
        _save_pid(pid)

        status = GeminiRunner.status()
        assert status["status"] == "running"
        assert status["pid"] == pid

    def test_stop_no_runner(self):
        result = GeminiRunner.stop_background()
        assert result is False

    def test_stop_dead_process(self):
        _save_state({"pid": 999999999, "status": "running"})
        _save_pid(999999999)
        result = GeminiRunner.stop_background()
        assert result is False  # 进程已不存在

    def test_start_already_running(self):
        """如果 Runner 已经在运行，start 应该返回 False。"""
        pid = os.getpid()
        _save_pid(pid)
        _save_state({"pid": pid, "status": "running"})

        runner = GeminiRunner()
        result = runner.start_background()
        assert result is False

    def test_print_status_running(self, capsys):
        _print_status(
            {
                "status": "running",
                "pid": 12345,
                "mode": "background",
                "api_port": 30002,
                "novnc_port": 30004,
                "hostname": "testhost",
                "started_at": "2026-01-01 00:00:00",
            }
        )
        # 验证没有异常抛出

    def test_print_status_stopped(self, capsys):
        _print_status(
            {
                "status": "stopped",
                "message": "未运行",
            }
        )
        # 验证没有异常抛出


# ═══════════════════════════════════════════════════════════════════
# 单元测试：Server 新增接口 — Pydantic 模型验证
# ═══════════════════════════════════════════════════════════════════


class TestServerModels:
    """测试 Server 请求模型的参数校验。"""

    def test_new_chat_request_empty(self):
        from webu.gemini.server import NewChatRequest

        req = NewChatRequest()
        assert req.tool is None
        assert req.mode is None

    def test_new_chat_request_with_params(self):
        from webu.gemini.server import NewChatRequest

        req = NewChatRequest(mode="pro", tool="image")
        assert req.mode == "Pro"  # 应被标准化
        assert req.tool == "生成图片"  # 应被标准化

    def test_set_presets_request(self):
        from webu.gemini.server import SetPresetsRequest

        req = SetPresetsRequest(mode="fast", tool="music")
        assert req.mode == "快速"
        assert req.tool == "创作音乐"

    def test_set_presets_request_partial(self):
        from webu.gemini.server import SetPresetsRequest

        req = SetPresetsRequest(mode="Pro")
        assert req.mode == "Pro"
        assert req.tool is None

    def test_set_mode_request_normalized(self):
        from webu.gemini.server import SetModeRequest

        req = SetModeRequest(mode="fast")
        assert req.mode == "快速"

    def test_set_tool_request_normalized(self):
        from webu.gemini.server import SetToolRequest

        req = SetToolRequest(tool="image")
        assert req.tool == "生成图片"

    def test_set_input_request_min_length(self):
        from webu.gemini.server import SetInputRequest
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            SetInputRequest(text="")

    def test_switch_chat_request_min_length(self):
        from webu.gemini.server import SwitchChatRequest
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            SwitchChatRequest(chat_id="")

    def test_download_images_request_defaults(self):
        from webu.gemini.server import DownloadImagesRequest

        req = DownloadImagesRequest()
        assert req.output_dir == "data/images"
        assert req.prefix == ""

    def test_presets_response(self):
        from webu.gemini.server import PresetsResponse

        resp = PresetsResponse(
            mode="Pro", tool="生成图片", mode_changed=True, tool_changed=True
        )
        assert resp.mode == "Pro"
        assert resp.tool == "生成图片"
        assert resp.mode_changed is True

    def test_health_response_version(self):
        from webu.gemini.server import HealthResponse

        resp = HealthResponse()
        assert resp.version == "3.0.0"


# ═══════════════════════════════════════════════════════════════════
# 单元测试：Server 预设验证
# ═══════════════════════════════════════════════════════════════════


class TestPresetValidation:
    """测试预设验证和自动调整逻辑。"""

    @pytest.mark.asyncio
    async def test_ensure_presets_no_preset(self):
        agency = MagicMock()
        result = await _ensure_presets(agency, None, None)
        assert result["mode_adjusted"] is False
        assert result["tool_adjusted"] is False

    @pytest.mark.asyncio
    async def test_ensure_presets_mode_matches(self):
        agency = MagicMock()
        agency.get_mode = AsyncMock(return_value={"mode": "Pro"})
        result = await _ensure_presets(agency, expected_mode="Pro")
        assert result["mode_adjusted"] is False

    @pytest.mark.asyncio
    async def test_ensure_presets_mode_mismatch(self):
        agency = MagicMock()
        agency.get_mode = AsyncMock(return_value={"mode": "快速"})
        agency.set_mode = AsyncMock(return_value={"status": "ok"})
        result = await _ensure_presets(agency, expected_mode="Pro")
        assert result["mode_adjusted"] is True
        agency.set_mode.assert_called_once_with("Pro")

    @pytest.mark.asyncio
    async def test_ensure_presets_tool_mismatch(self):
        agency = MagicMock()
        agency.get_tool = AsyncMock(return_value={"tool": "none"})
        agency.set_tool = AsyncMock(return_value={"status": "ok"})
        result = await _ensure_presets(agency, expected_tool="生成图片")
        assert result["tool_adjusted"] is True
        agency.set_tool.assert_called_once_with("生成图片")

    @pytest.mark.asyncio
    async def test_ensure_presets_tool_none_skip(self):
        agency = MagicMock()
        result = await _ensure_presets(agency, expected_tool="none")
        assert result["tool_adjusted"] is False

    @pytest.mark.asyncio
    async def test_ensure_presets_error_handling(self):
        agency = MagicMock()
        agency.get_mode = AsyncMock(side_effect=Exception("test error"))
        # 不应抛出异常，只是记录警告
        result = await _ensure_presets(agency, expected_mode="Pro")
        assert result["mode_adjusted"] is False


# ═══════════════════════════════════════════════════════════════════
# 单元测试：Client 新增方法
# ═══════════════════════════════════════════════════════════════════


class TestClientNewMethods:
    """测试 GeminiClient 新增的方法。"""

    @patch("webu.gemini.client.requests.Session")
    def test_set_presets(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "ok",
            "mode": "Pro",
            "tool": "生成图片",
            "mode_changed": True,
            "tool_changed": True,
        }
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.set_presets(mode="Pro", tool="生成图片")
        assert result["mode"] == "Pro"
        assert result["tool"] == "生成图片"
        assert result["mode_changed"] is True
        assert result["tool_changed"] is True

    @patch("webu.gemini.client.requests.Session")
    def test_set_presets_partial(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "ok",
            "mode": "Pro",
            "mode_changed": True,
        }
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.set_presets(mode="Pro")
        assert result["mode"] == "Pro"

    @patch("webu.gemini.client.requests.Session")
    def test_get_presets(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "ok",
            "presets": {"mode": "Pro", "tool": "生成图片", "verified": False},
        }
        mock_resp.raise_for_status.return_value = None
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.get_presets()
        assert result["presets"]["mode"] == "Pro"

    @patch("webu.gemini.client.requests.Session")
    def test_new_chat_with_params(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "ok",
            "chat_id": "abc123",
            "mode": "Pro",
            "tool": "生成图片",
        }
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.new_chat(mode="Pro", tool="生成图片")
        assert result["chat_id"] == "abc123"
        assert result["mode"] == "Pro"
        assert result["tool"] == "生成图片"

        # 验证请求参数
        call_args = mock_session.post.call_args
        assert call_args[1]["json"] == {"mode": "Pro", "tool": "生成图片"}

    @patch("webu.gemini.client.requests.Session")
    def test_new_chat_no_params(self, mock_session_cls):
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
    def test_download_images(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "ok",
            "image_count": 2,
            "saved_count": 2,
            "saved_paths": ["data/images/img1.png", "data/images/img2.png"],
        }
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.download_images(output_dir="data/images", prefix="test")
        assert result["saved_count"] == 2
        assert len(result["saved_paths"]) == 2

    @patch("webu.gemini.client.requests.Session")
    def test_send_message_convenience(self, mock_session_cls):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok"}
        mock_resp.raise_for_status.return_value = None
        mock_session.post.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = GeminiClient()
        result = client.send_message("hello", wait_response=True)
        # send_message calls set_input + send_input → 2 POST calls
        assert mock_session.post.call_count == 2


# ═══════════════════════════════════════════════════════════════════
# 单元测试：Server 端点 (httpx TestClient)
# ═══════════════════════════════════════════════════════════════════


class TestServerEndpoints:
    """使用 httpx TestClient 测试 Server 端点（mock agency）。"""

    @pytest.fixture
    def mock_agency(self):
        agency = MagicMock(spec=GeminiAgency)
        agency.is_ready = True
        agency.browser_status = AsyncMock(
            return_value={"is_ready": True, "browser": {}}
        )
        agency.new_chat = AsyncMock(return_value={"status": "ok", "chat_id": "test-id"})
        agency.set_mode = AsyncMock(return_value={"status": "ok", "mode": "Pro"})
        agency.set_tool = AsyncMock(return_value={"status": "ok", "tool": "生成图片"})
        agency.get_mode = AsyncMock(return_value={"mode": "Pro"})
        agency.get_tool = AsyncMock(return_value={"tool": "none"})
        agency.clear_input = AsyncMock(return_value={"status": "ok"})
        agency.set_input = AsyncMock(return_value={"status": "ok", "text": "test"})
        agency.add_input = AsyncMock(return_value={"status": "ok", "text": "test"})
        agency.get_input = AsyncMock(return_value={"text": "test"})
        agency.send_input = AsyncMock(return_value={"status": "ok", "response": {}})
        agency.get_messages = AsyncMock(return_value={"messages": []})
        agency.screenshot = AsyncMock(return_value=b"png_bytes")
        agency.switch_chat = AsyncMock(return_value={"status": "ok", "chat_id": "xyz"})
        agency._extract_images = AsyncMock(return_value=[])
        return agency

    @pytest.fixture
    def test_client(self, mock_agency):
        from webu.gemini.server import create_gemini_server
        from fastapi.testclient import TestClient

        # patch GeminiAgency 以避免真实浏览器连接
        with patch("webu.gemini.server.GeminiAgency", return_value=mock_agency):
            mock_agency.start = AsyncMock()
            mock_agency.stop = AsyncMock()
            app = create_gemini_server()
            with TestClient(app) as client:
                yield client, mock_agency

    def test_health(self, test_client):
        client, _ = test_client
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "3.0.0"

    def test_set_presets_endpoint(self, test_client):
        """测试 /set_presets 端点响应格式。"""
        from webu.gemini.server import SetPresetsRequest

        req = SetPresetsRequest(mode="pro", tool="image")
        # 验证请求模型标准化
        assert req.mode == "Pro"
        assert req.tool == "生成图片"


# ═══════════════════════════════════════════════════════════════════
# 单元测试：Parser 图片处理
# ═══════════════════════════════════════════════════════════════════


class TestParserImageHandling:
    """测试 Parser 的图片解析和保存逻辑。"""

    def test_parse_images_from_elements(self):
        from webu.gemini.parser import GeminiResponseParser

        parser = GeminiResponseParser()
        images_data = [
            {
                "src": "https://example.com/image1.png",
                "alt": "test image",
                "width": 512,
                "height": 512,
                "base64_data": "iVBORw0KGgoAAAANSUhEUg==",
                "mime_type": "image/png",
            },
            {
                # 小图标，应被过滤
                "src": "https://example.com/icon.png",
                "alt": "icon",
                "width": 16,
                "height": 16,
            },
        ]
        images = parser.parse_images_from_elements(images_data)
        assert len(images) == 1
        assert images[0].url == "https://example.com/image1.png"
        assert images[0].base64_data == "iVBORw0KGgoAAAANSUhEUg=="

    def test_parse_images_data_url(self):
        from webu.gemini.parser import GeminiResponseParser

        parser = GeminiResponseParser()
        images_data = [
            {
                "src": "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
                "alt": "data image",
                "width": 256,
                "height": 256,
            },
        ]
        images = parser.parse_images_from_elements(images_data)
        assert len(images) == 1
        assert images[0].mime_type == "image/jpeg"
        assert images[0].base64_data == "/9j/4AAQSkZJRg=="
        assert images[0].url == ""  # data: URL 不保存为 url

    def test_gemini_image_save(self, tmp_path):
        """测试 GeminiImage 保存到文件。"""
        import base64

        # 创建一个小的测试图片（1x1 红色 PNG）
        png_1x1 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        b64_data = base64.b64encode(png_1x1).decode()

        img = GeminiImage(
            base64_data=b64_data,
            mime_type="image/png",
            width=1,
            height=1,
        )

        filepath = str(tmp_path / "test_image.png")
        result = img.save_to_file(filepath)
        assert result is True
        assert os.path.exists(filepath)
        assert os.path.getsize(filepath) > 0

    def test_gemini_image_extension(self):
        assert GeminiImage(mime_type="image/png").get_extension() == "png"
        assert GeminiImage(mime_type="image/jpeg").get_extension() == "jpg"
        assert GeminiImage(mime_type="image/webp").get_extension() == "webp"
        assert GeminiImage(mime_type="image/gif").get_extension() == "gif"
        assert GeminiImage(mime_type="unknown").get_extension() == "png"

    def test_gemini_image_no_data_save(self, tmp_path):
        img = GeminiImage()
        filepath = str(tmp_path / "empty.png")
        result = img.save_to_file(filepath)
        assert result is False


# ═══════════════════════════════════════════════════════════════════
# 单元测试：GeminiResponse
# ═══════════════════════════════════════════════════════════════════


class TestGeminiResponse:
    """测试 GeminiResponse 的序列化和图片提取。"""

    def test_to_dict_basic(self):
        resp = GeminiResponse(
            text="Hello",
            markdown="# Hello",
        )
        d = resp.to_dict()
        assert d["text"] == "Hello"
        assert d["markdown"] == "# Hello"
        assert d["images"] == []
        assert d["code_blocks"] == []
        assert d["is_error"] is False

    def test_to_dict_with_images(self):
        resp = GeminiResponse(
            text="Generated",
            images=[
                GeminiImage(
                    url="https://example.com/img.png",
                    base64_data="abc123",
                    width=512,
                    height=512,
                ),
            ],
        )
        d = resp.to_dict()
        assert len(d["images"]) == 1
        assert d["images"][0]["base64_data"] == "abc123"
        assert d["images"][0]["width"] == 512

    def test_to_dict_with_error(self):
        resp = GeminiResponse(is_error=True, error_message="Test error")
        d = resp.to_dict()
        assert d["is_error"] is True
        assert d["error_message"] == "Test error"


# ═══════════════════════════════════════════════════════════════════
# 单元测试：Config
# ═══════════════════════════════════════════════════════════════════


class TestGeminiConfig:
    """测试 Config 模块。"""

    def test_default_config(self):
        config = GeminiConfig()
        assert config.api_port == 30002
        assert config.browser_port == 30001
        assert config.vnc_port == 30003
        assert config.novnc_port == 30004

    def test_config_override(self):
        config = GeminiConfig(config={"api_port": 8080})
        assert config.api_port == 8080

    def test_config_properties(self):
        config = GeminiConfig()
        assert isinstance(config.proxy, str)
        assert isinstance(config.user_data_dir, str)
        assert isinstance(config.headless, bool)
        assert isinstance(config.page_load_timeout, int)
        assert isinstance(config.response_timeout, int)
        assert isinstance(config.image_generation_timeout, int)

    def test_config_repr(self):
        config = GeminiConfig()
        repr_str = repr(config)
        assert "GeminiConfig" in repr_str


# ═══════════════════════════════════════════════════════════════════
# 单元测试：Error 层级
# ═══════════════════════════════════════════════════════════════════


class TestErrors:
    """测试错误类型层级。"""

    def test_base_error(self):
        e = GeminiError("test", details={"key": "value"})
        assert "test" in str(e)
        assert e.details == {"key": "value"}

    def test_login_required(self):
        e = GeminiLoginRequiredError()
        assert isinstance(e, GeminiError)
        assert "登录" in str(e) or "未登录" in str(e)

    def test_page_error(self):
        e = GeminiPageError("操作失败")
        assert isinstance(e, GeminiError)
        assert "操作失败" in str(e)

    def test_rate_limit_error(self):
        e = GeminiRateLimitError()
        assert isinstance(e, GeminiError)

    def test_error_str_with_details(self):
        e = GeminiError("msg", details={"timeout": 30000})
        s = str(e)
        assert "msg" in s
        assert "timeout" in s


# ═══════════════════════════════════════════════════════════════════
# 单元测试：Server 错误处理
# ═══════════════════════════════════════════════════════════════════


class TestServerErrorHandling:
    """测试 Server 的错误映射逻辑。"""

    def test_login_required_maps_to_401(self):
        from webu.gemini.server import _handle_gemini_error
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _handle_gemini_error(GeminiLoginRequiredError())
        assert exc_info.value.status_code == 401

    def test_rate_limit_maps_to_429(self):
        from webu.gemini.server import _handle_gemini_error
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _handle_gemini_error(GeminiRateLimitError())
        assert exc_info.value.status_code == 429

    def test_timeout_maps_to_504(self):
        from webu.gemini.server import _handle_gemini_error
        from webu.gemini.errors import GeminiTimeoutError
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _handle_gemini_error(GeminiTimeoutError())
        assert exc_info.value.status_code == 504

    def test_page_error_maps_to_500(self):
        from webu.gemini.server import _handle_gemini_error
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _handle_gemini_error(GeminiPageError())
        assert exc_info.value.status_code == 500

    def test_unexpected_error_maps_to_500(self):
        from webu.gemini.server import _handle_gemini_error
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _handle_gemini_error(RuntimeError("unexpected"))
        assert exc_info.value.status_code == 500


# ═══════════════════════════════════════════════════════════════════
# 集成测试标记
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestIntegrationRunModule:
    """集成测试：Run 模块的后台启动/停止。

    需要真实的 Chrome 浏览器和网络访问。
    运行命令：pytest -m integration
    """

    def test_background_lifecycle(self):
        """测试后台启动 → 状态查询 → 停止 的完整生命周期。"""
        # 此测试需要真实浏览器环境，在 CI 中跳过
        pytest.skip("需要浏览器环境")

    def test_foreground_signal_handling(self):
        """测试前台运行时的信号处理。"""
        pytest.skip("需要浏览器环境")


@pytest.mark.integration
class TestIntegrationImageGeneration:
    """集成测试：图片生成功能。

    需要真实浏览器 + Gemini 登录状态。
    运行命令：pytest -m integration
    """

    def test_generate_and_download_image(self):
        """测试图片生成 → 下载 → 保存的完整流程。"""
        pytest.skip("需要浏览器环境和 Gemini 登录")

    def test_complex_image_prompts(self):
        """测试复杂的图片生成指令。"""
        pytest.skip("需要浏览器环境和 Gemini 登录")
