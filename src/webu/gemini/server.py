"""Gemini FastAPI 服务器。

提供 REST API 接口，封装 GeminiAgency 的浏览器交互功能。
"""

import asyncio
import uvicorn

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from tclogger import logger, logstr
from typing import Optional

from .agency import GeminiAgency
from .config import GeminiConfig, GeminiConfigType
from .errors import (
    GeminiError,
    GeminiLoginRequiredError,
    GeminiTimeoutError,
    GeminiImageGenerationError,
    GeminiPageError,
    GeminiRateLimitError,
)
from ..fastapis.styles import setup_swagger_ui


# ═══════════════════════════════════════════════════════════════
# 请求/响应模型
# ═══════════════════════════════════════════════════════════════


class SwitchChatRequest(BaseModel):
    chat_id: str = Field(..., description="要切换到的聊天会话 ID")


class SetModeRequest(BaseModel):
    mode: str = Field(..., description="模式名称，如 '快速', '思考', 'Pro'")


class SetToolRequest(BaseModel):
    tool: str = Field(
        ..., description="工具名称，如 'Deep Research', '生成图片', '创作音乐'"
    )


class SetInputRequest(BaseModel):
    text: str = Field(..., description="要设置的输入内容")


class AddInputRequest(BaseModel):
    text: str = Field(..., description="要追加的输入内容")


class SendInputRequest(BaseModel):
    wait_response: bool = Field(
        True,
        description="True=等待 Gemini 响应后返回(同步), False=发送后立即返回(异步)",
    )


class AttachRequest(BaseModel):
    file_path: str = Field(..., description="要上传的文件路径")


class ScreenshotRequest(BaseModel):
    path: str = Field(None, description="截图保存路径")


class ImageData(BaseModel):
    url: str = ""
    alt: str = ""
    base64_data: str = ""
    mime_type: str = "image/png"
    width: int = 0
    height: int = 0


class CodeBlockData(BaseModel):
    language: str = ""
    code: str = ""


class ChatResponse(BaseModel):
    success: bool = True
    text: str = ""
    markdown: str = ""
    images: list[ImageData] = []
    code_blocks: list[CodeBlockData] = []
    error: str = ""


class StatusResponse(BaseModel):
    status: str = "ok"
    data: dict = {}


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "2.0.0"


# ═══════════════════════════════════════════════════════════════
# 错误处理辅助
# ═══════════════════════════════════════════════════════════════


def _handle_gemini_error(e: Exception):
    """将 GeminiError 转换为 HTTPException。"""
    if isinstance(e, GeminiLoginRequiredError):
        raise HTTPException(status_code=401, detail=str(e))
    if isinstance(e, GeminiRateLimitError):
        raise HTTPException(status_code=429, detail=str(e))
    if isinstance(e, GeminiTimeoutError):
        raise HTTPException(status_code=504, detail=str(e))
    if isinstance(e, GeminiPageError):
        raise HTTPException(status_code=500, detail=str(e))
    if isinstance(e, GeminiError):
        raise HTTPException(status_code=500, detail=str(e))
    logger.err(f"  × 意外错误: {e}")
    raise HTTPException(status_code=500, detail=f"意外错误: {e}")


# ═══════════════════════════════════════════════════════════════
# 应用工厂
# ═══════════════════════════════════════════════════════════════


def create_gemini_server(
    config: GeminiConfigType = None, config_path: str = None
) -> FastAPI:
    """创建 Gemini 自动化的 FastAPI 应用。"""

    gemini_config = GeminiConfig(config=config, config_path=config_path)
    agency: GeminiAgency = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal agency
        logger.note("> 初始化 Gemini Server ...")
        agency = GeminiAgency(config=gemini_config.config)
        try:
            await agency.start()
            logger.okay("  ✓ Gemini Server 就绪")
        except Exception as e:
            logger.err(f"  × 启动 GeminiAgency 失败: {e}")
            logger.warn("  Server 将启动但 Agency 需要手动初始化")
        yield
        if agency:
            await agency.stop()

    app = FastAPI(
        title="Gemini 自动化 Server",
        description=(
            "通过浏览器自动化 Google Gemini 交互的 API。\n\n"
            "支持：浏览器状态、聊天管理、模式/工具选择、"
            "输入操作、消息发送、文件上传、消息获取。"
        ),
        version="2.0.0",
        lifespan=lifespan,
    )
    setup_swagger_ui(app)

    def _ensure_ready():
        if not agency or not agency.is_ready:
            raise HTTPException(
                status_code=503,
                detail="Gemini Agency 未就绪。请稍后重试或检查浏览器状态。",
            )

    # ── 系统接口 ─────────────────────────────────────────────

    @app.get("/health", response_model=HealthResponse, tags=["系统"])
    async def health_check():
        """健康检查接口。"""
        return HealthResponse(status="ok", version="2.0.0")

    @app.get("/browser_status", tags=["状态"])
    async def browser_status():
        """返回浏览器实例的全面状态信息。

        包括是否已登录、当前页面、模式、工具等。
        """
        _ensure_ready()
        try:
            status = await agency.browser_status()
            return {"status": "ok", "data": status}
        except Exception as e:
            _handle_gemini_error(e)

    # ── 聊天会话管理 ─────────────────────────────────────────

    @app.post("/new_chat", tags=["聊天"])
    async def new_chat():
        """创建新的聊天窗口。"""
        _ensure_ready()
        try:
            result = await agency.new_chat()
            return result
        except Exception as e:
            _handle_gemini_error(e)

    @app.post("/switch_chat", tags=["聊天"])
    async def switch_chat(req: SwitchChatRequest):
        """切换到指定 ID 的聊天窗口。"""
        _ensure_ready()
        try:
            result = await agency.switch_chat(req.chat_id)
            return result
        except Exception as e:
            _handle_gemini_error(e)

    # ── 模式管理 ─────────────────────────────────────────────

    @app.get("/get_mode", tags=["模式"])
    async def get_mode():
        """获取聊天窗口的当前模式。"""
        _ensure_ready()
        try:
            result = await agency.get_mode()
            return result
        except Exception as e:
            _handle_gemini_error(e)

    @app.post("/set_mode", tags=["模式"])
    async def set_mode(req: SetModeRequest):
        """设置聊天窗口的模式（如 '快速', '思考', 'Pro'）。"""
        _ensure_ready()
        try:
            result = await agency.set_mode(req.mode)
            return result
        except Exception as e:
            _handle_gemini_error(e)

    # ── 工具管理 ─────────────────────────────────────────────

    @app.get("/get_tool", tags=["工具"])
    async def get_tool():
        """获取聊天窗口的当前工具。"""
        _ensure_ready()
        try:
            result = await agency.get_tool()
            return result
        except Exception as e:
            _handle_gemini_error(e)

    @app.post("/set_tool", tags=["工具"])
    async def set_tool(req: SetToolRequest):
        """设置聊天窗口的工具（如 'Deep Research', '生成图片', '创作音乐'）。"""
        _ensure_ready()
        try:
            result = await agency.set_tool(req.tool)
            return result
        except Exception as e:
            _handle_gemini_error(e)

    # ── 输入框操作 ───────────────────────────────────────────

    @app.post("/clear_input", tags=["输入"])
    async def clear_input():
        """清空聊天窗口的输入框。"""
        _ensure_ready()
        try:
            result = await agency.clear_input()
            return result
        except Exception as e:
            _handle_gemini_error(e)

    @app.post("/set_input", tags=["输入"])
    async def set_input(req: SetInputRequest):
        """清空输入框并设置新的输入内容。"""
        _ensure_ready()
        try:
            result = await agency.set_input(req.text)
            return result
        except Exception as e:
            _handle_gemini_error(e)

    @app.post("/add_input", tags=["输入"])
    async def add_input(req: AddInputRequest):
        """在输入框中追加输入内容。"""
        _ensure_ready()
        try:
            result = await agency.add_input(req.text)
            return result
        except Exception as e:
            _handle_gemini_error(e)

    @app.get("/get_input", tags=["输入"])
    async def get_input():
        """获取输入框中的当前内容。"""
        _ensure_ready()
        try:
            result = await agency.get_input()
            return result
        except Exception as e:
            _handle_gemini_error(e)

    # ── 消息发送 ─────────────────────────────────────────────

    @app.post("/send_input", tags=["消息"])
    async def send_input(req: SendInputRequest):
        """发送输入框中的内容。

        支持同步和异步两种方式：
        - wait_response=True: 等到 Gemini 返回结果后才返回（同步）
        - wait_response=False: 发送后立即返回（异步）
        """
        _ensure_ready()
        try:
            result = await agency.send_input(wait_response=req.wait_response)
            return result
        except Exception as e:
            _handle_gemini_error(e)

    # ── 文件管理 ─────────────────────────────────────────────

    @app.post("/attach", tags=["文件"])
    async def attach(req: AttachRequest):
        """在聊天窗口中上传一个文件。"""
        _ensure_ready()
        try:
            result = await agency.attach(req.file_path)
            return result
        except Exception as e:
            _handle_gemini_error(e)

    @app.post("/detach", tags=["文件"])
    async def detach():
        """清空聊天窗口中已上传的文件。"""
        _ensure_ready()
        try:
            result = await agency.detach()
            return result
        except Exception as e:
            _handle_gemini_error(e)

    @app.get("/get_attachments", tags=["文件"])
    async def get_attachments():
        """获取聊天窗口中已上传的文件列表。"""
        _ensure_ready()
        try:
            result = await agency.get_attachments()
            return result
        except Exception as e:
            _handle_gemini_error(e)

    # ── 消息获取 ─────────────────────────────────────────────

    @app.get("/get_messages", tags=["消息"])
    async def get_messages():
        """获取聊天窗口中的消息列表。

        包括每条消息的内容、类型、发送者等信息。
        """
        _ensure_ready()
        try:
            result = await agency.get_messages()
            return result
        except Exception as e:
            _handle_gemini_error(e)

    # ── 调试工具 ─────────────────────────────────────────────

    @app.post("/screenshot", tags=["调试"])
    async def take_screenshot(req: ScreenshotRequest = None):
        """对当前浏览器状态截图。"""
        _ensure_ready()
        try:
            path = (req and req.path) or "data/gemini_screenshot.png"
            await agency.screenshot(path=path)
            return {"status": "ok", "path": path}
        except Exception as e:
            _handle_gemini_error(e)

    @app.post("/restart", tags=["系统"])
    async def restart():
        """重启 GeminiAgency。"""
        nonlocal agency
        try:
            if agency:
                await agency.stop()
            agency = GeminiAgency(config=gemini_config.config)
            await agency.start()
            return {"status": "ok", "message": "Agency 已重启"}
        except Exception as e:
            logger.err(f"  × 重启失败: {e}")
            raise HTTPException(status_code=500, detail=f"重启失败: {e}")

    return app


def run_gemini_server(config: GeminiConfigType = None, config_path: str = None):
    """运行 Gemini Server。"""
    gemini_config = GeminiConfig(config=config, config_path=config_path)
    app = create_gemini_server(config=gemini_config.config)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=gemini_config.api_port,
        log_level="info",
    )


if __name__ == "__main__":
    run_gemini_server()

    # python -m webu.gemini.server
