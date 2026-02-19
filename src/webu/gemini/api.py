import asyncio
import uvicorn

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from tclogger import logger, logstr
from typing import Optional

from .client import GeminiClient
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


# ── 请求/响应模型 ───────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str = Field(..., description="发送给 Gemini 的消息文本")
    new_chat: bool = Field(False, description="是否先开始新会话")
    image_mode: bool = Field(False, description="是否使用图片生成模式")
    download_images: bool = Field(True, description="是否将图片下载为 base64")


class ImageRequest(BaseModel):
    prompt: str = Field(..., description="要生成的图片描述")
    new_chat: bool = Field(True, description="是否先开始新会话")


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


class LoginStatusResponse(BaseModel):
    logged_in: bool = False
    is_pro: bool = False
    message: str = ""


class StatusResponse(BaseModel):
    status: str = "ok"
    message: str = ""
    is_ready: bool = False
    is_logged_in: bool = False
    message_count: int = 0


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"


# ── 应用工厂 ────────────────────────────────────────────────────


def create_gemini_app(
    config: GeminiConfigType = None, config_path: str = None
) -> FastAPI:
    """创建 Gemini 自动化的 FastAPI 应用。"""

    gemini_config = GeminiConfig(config=config, config_path=config_path)
    client: GeminiClient = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal client
        logger.note("> 初始化 Gemini API ...")
        client = GeminiClient(config=gemini_config.config)
        try:
            await client.start()
            logger.okay("  ✓ Gemini API 就绪")
        except Exception as e:
            logger.err(f"  × 启动 Gemini 客户端失败: {e}")
            logger.warn("  API 将启动但客户端需要手动初始化")
        yield
        if client:
            await client.stop()

    app = FastAPI(
        title="Gemini 自动化 API",
        description="通过浏览器自动化 Google Gemini 交互的 API。\n\n"
        "支持文本聊天、图片生成、会话管理和状态查询。",
        version="1.0.0",
        lifespan=lifespan,
    )
    setup_swagger_ui(app)

    # ── 辅助函数 ─────────────────────────────────────────────
    def _ensure_client_ready():
        """检查客户端是否就绪，未就绪则抛出 503 错误。"""
        if not client or not client.is_ready:
            raise HTTPException(
                status_code=503,
                detail="Gemini 客户端未就绪。请稍后重试或检查浏览器状态。",
            )

    # ── 接口 ─────────────────────────────────────────────────────

    @app.get("/health", response_model=HealthResponse, tags=["系统"])
    async def health_check():
        """健康检查接口。无需客户端就绪。"""
        return HealthResponse(status="ok", version="1.0.0")

    @app.get("/status", response_model=StatusResponse, tags=["系统"])
    async def get_status():
        """获取 Gemini 客户端的当前状态。"""
        result = StatusResponse(
            status="ok", is_ready=client.is_ready if client else False
        )
        if client and client.is_ready:
            try:
                login_status = await client.check_login_status()
                result.is_logged_in = login_status["logged_in"]
                result.message = login_status["message"]
                result.message_count = client._message_count
            except Exception as e:
                result.message = f"检查状态出错: {e}"
        else:
            result.message = "客户端未就绪"
        return result

    @app.get("/login-status", response_model=LoginStatusResponse, tags=["认证"])
    async def get_login_status():
        """检查用户是否已登录 Gemini。"""
        _ensure_client_ready()
        try:
            status = await client.check_login_status()
            return LoginStatusResponse(**status)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/chat", response_model=ChatResponse, tags=["聊天"])
    async def send_chat(req: ChatRequest):
        """向 Gemini 发送消息并获取响应。

        支持普通文本聊天和图片生成模式。
        可选择是否下载图片为 base64 数据。
        """
        _ensure_client_ready()

        try:
            if req.new_chat:
                await client.new_chat()

            response = await client.send_message(
                text=req.message,
                image_mode=req.image_mode,
                download_images=req.download_images,
            )

            return ChatResponse(
                success=not response.is_error,
                text=response.text,
                markdown=response.markdown,
                images=[ImageData(**img.to_dict()) for img in response.images],
                code_blocks=[
                    CodeBlockData(**cb.to_dict()) for cb in response.code_blocks
                ],
                error=response.error_message,
            )

        except GeminiLoginRequiredError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except GeminiRateLimitError as e:
            raise HTTPException(status_code=429, detail=str(e))
        except GeminiTimeoutError as e:
            raise HTTPException(status_code=504, detail=str(e))
        except GeminiError as e:
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            logger.err(f"  × 意外错误: {e}")
            raise HTTPException(status_code=500, detail=f"意外错误: {e}")

    @app.post("/generate-image", response_model=ChatResponse, tags=["图片"])
    async def generate_image(req: ImageRequest):
        """使用 Gemini 生成图片。

        自动启用图片生成工具并下载生成的图片为 base64 数据。
        """
        _ensure_client_ready()

        try:
            if req.new_chat:
                await client.new_chat()

            response = await client.generate_image(prompt=req.prompt)

            return ChatResponse(
                success=not response.is_error,
                text=response.text,
                markdown=response.markdown,
                images=[ImageData(**img.to_dict()) for img in response.images],
                code_blocks=[
                    CodeBlockData(**cb.to_dict()) for cb in response.code_blocks
                ],
                error=response.error_message,
            )

        except GeminiLoginRequiredError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except GeminiRateLimitError as e:
            raise HTTPException(status_code=429, detail=str(e))
        except GeminiTimeoutError as e:
            raise HTTPException(status_code=504, detail=str(e))
        except GeminiImageGenerationError as e:
            raise HTTPException(status_code=500, detail=str(e))
        except GeminiError as e:
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            logger.err(f"  × 意外错误: {e}")
            raise HTTPException(status_code=500, detail=f"意外错误: {e}")

    @app.post("/new-chat", tags=["聊天"])
    async def start_new_chat():
        """开始新的会话。"""
        _ensure_client_ready()
        try:
            await client.new_chat()
            return {"status": "ok", "message": "新会话已启动"}
        except GeminiError as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/screenshot", tags=["调试"])
    async def take_screenshot(path: str = None):
        """对当前浏览器状态截图。"""
        _ensure_client_ready()
        try:
            save_path = path or "data/gemini_screenshot.png"
            await client.screenshot(path=save_path)
            return {"status": "ok", "path": save_path}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/restart", tags=["系统"])
    async def restart_client():
        """重启 Gemini 客户端。"""
        nonlocal client
        try:
            if client:
                await client.stop()
            client = GeminiClient(config=gemini_config.config)
            await client.start()
            return {"status": "ok", "message": "客户端已重启"}
        except Exception as e:
            logger.err(f"  × 重启失败: {e}")
            raise HTTPException(status_code=500, detail=f"重启失败: {e}")

    return app


def run_gemini_api(config: GeminiConfigType = None, config_path: str = None):
    """运行 Gemini API 服务器。"""
    gemini_config = GeminiConfig(config=config, config_path=config_path)
    app = create_gemini_app(config=gemini_config.config)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=gemini_config.api_port,
        log_level="info",
    )


if __name__ == "__main__":
    run_gemini_api()

    # python -m webu.gemini.api
