"""Gemini FastAPI 服务器。

提供 REST API 接口，封装 GeminiAgency 的浏览器交互功能。
支持：预设管理、图片存储/下载、截图存储/下载、聊天历史数据库。
"""

import asyncio
import base64
import uvicorn

from contextlib import asynccontextmanager
from enum import Enum
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from tclogger import logger, logstr
from typing import Optional, Literal

from .agency import GeminiAgency
from .chatdb import ChatDatabase
from .config import GeminiConfig, GeminiConfigType
from .errors import (
    GeminiError,
    GeminiLoginRequiredError,
    GeminiTimeoutError,
    GeminiImageGenerationError,
    GeminiPageError,
    GeminiRateLimitError,
    GeminiServerRollbackError,
)
from ..fastapis.styles import setup_swagger_ui


# ═══════════════════════════════════════════════════════════════
# 常量 & 枚举
# ═══════════════════════════════════════════════════════════════

# 有效的模式名称
VALID_MODES = {"快速", "思考", "Pro", "Flash", "Think", "Deep Think"}

# 有效的工具名称
VALID_TOOLS = {
    "none",
    "Deep Research",
    "生成图片",
    "创作音乐",
    "Canvas",
    "Google 搜索",
    "代码执行",
}

# 工具名称别名映射（兼容不同写法）
TOOL_ALIASES: dict[str, str] = {
    "deep_research": "Deep Research",
    "deep research": "Deep Research",
    "image": "生成图片",
    "generate_image": "生成图片",
    "generate image": "生成图片",
    "图片": "生成图片",
    "music": "创作音乐",
    "音乐": "创作音乐",
    "canvas": "Canvas",
    "search": "Google 搜索",
    "搜索": "Google 搜索",
    "google搜索": "Google 搜索",
    "code": "代码执行",
    "代码": "代码执行",
}

# 模式名称别名映射
MODE_ALIASES: dict[str, str] = {
    "fast": "快速",
    "quick": "快速",
    "think": "思考",
    "thinking": "思考",
    "pro": "Pro",
    "deep_think": "Deep Think",
    "deep think": "Deep Think",
    "flash": "Flash",
}


def _normalize_mode(mode: str) -> str:
    """标准化模式名称，支持别名。"""
    if mode in VALID_MODES:
        return mode
    lower = mode.lower().strip()
    if lower in MODE_ALIASES:
        return MODE_ALIASES[lower]
    # 模糊匹配
    for valid in VALID_MODES:
        if lower in valid.lower() or valid.lower() in lower:
            return valid
    return mode  # 原样返回，由 agency 处理


def _normalize_tool(tool: str) -> str:
    """标准化工具名称，支持别名。"""
    if tool in VALID_TOOLS:
        return tool
    lower = tool.lower().strip()
    if lower in TOOL_ALIASES:
        return TOOL_ALIASES[lower]
    if lower == "none" or lower == "无":
        return "none"
    # 模糊匹配
    for valid in VALID_TOOLS:
        if lower in valid.lower() or valid.lower() in lower:
            return valid
    return tool


# ═══════════════════════════════════════════════════════════════
# 请求/响应模型
# ═══════════════════════════════════════════════════════════════


class SwitchChatRequest(BaseModel):
    """切换聊天会话请求。"""

    chat_id: str = Field(
        ..., description="要切换到的聊天会话 ID", min_length=1, max_length=200
    )


class NewChatRequest(BaseModel):
    """创建新聊天请求（支持可选的 tool 和 mode 参数）。"""

    tool: Optional[str] = Field(
        None,
        description="创建新聊天后要设置的工具，如 'Deep Research', '生成图片', '创作音乐'",
    )
    mode: Optional[str] = Field(
        None,
        description="创建新聊天后要设置的模式，如 '快速', '思考', 'Pro'",
    )

    @field_validator("tool", mode="before")
    @classmethod
    def normalize_tool(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _normalize_tool(v)
        return v

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _normalize_mode(v)
        return v


class SetModeRequest(BaseModel):
    """设置模式请求。"""

    mode: str = Field(
        ..., description="模式名称，如 '快速', '思考', 'Pro'", min_length=1
    )

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, v: str) -> str:
        return _normalize_mode(v)


class SetToolRequest(BaseModel):
    """设置工具请求。"""

    tool: str = Field(
        ...,
        description="工具名称，如 'Deep Research', '生成图片', '创作音乐'",
        min_length=1,
    )

    @field_validator("tool", mode="before")
    @classmethod
    def normalize_tool(cls, v: str) -> str:
        return _normalize_tool(v)


class SetPresetsRequest(BaseModel):
    """同时设置 tool 和 mode 的预设请求。"""

    tool: Optional[str] = Field(
        None,
        description="工具名称，如 'Deep Research', '生成图片', 'none' (清除工具)",
    )
    mode: Optional[str] = Field(
        None,
        description="模式名称，如 '快速', '思考', 'Pro'",
    )

    @field_validator("tool", mode="before")
    @classmethod
    def normalize_tool(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _normalize_tool(v)
        return v

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _normalize_mode(v)
        return v


class SetInputRequest(BaseModel):
    """设置输入请求。"""

    text: str = Field(..., description="要设置的输入内容", min_length=1)


class AddInputRequest(BaseModel):
    """追加输入请求。"""

    text: str = Field(..., description="要追加的输入内容", min_length=1)


class SendInputRequest(BaseModel):
    """发送输入请求。"""

    wait_response: bool = Field(
        True,
        description=("True=等待 Gemini 响应后返回(同步), False=发送后立即返回(异步)"),
    )


class AttachRequest(BaseModel):
    """文件上传请求。"""

    file_path: str = Field(..., description="要上传的文件路径", min_length=1)


class StoreScreenshotRequest(BaseModel):
    """保存截图到服务器请求。"""

    path: str = Field(
        "data/gemini_screenshot.png", description="截图保存路径（服务器端）"
    )


class StoreImagesRequest(BaseModel):
    """保存图片到服务器请求。"""

    output_dir: str = Field("data/images", description="图片保存目录（服务器端）")
    prefix: str = Field("", description="文件名前缀")


class DownloadImagesRequest(BaseModel):
    """下载图片数据请求（返回 base64 数据供客户端保存）。"""

    prefix: str = Field("", description="建议的文件名前缀")


class ImageData(BaseModel):
    """图片数据。"""

    url: str = ""
    alt: str = ""
    base64_data: str = ""
    mime_type: str = "image/png"
    width: int = 0
    height: int = 0


class CodeBlockData(BaseModel):
    """代码块数据。"""

    language: str = ""
    code: str = ""


class ChatResponse(BaseModel):
    """聊天响应。"""

    success: bool = True
    text: str = ""
    markdown: str = ""
    images: list[ImageData] = []
    code_blocks: list[CodeBlockData] = []
    error: str = ""


class StatusResponse(BaseModel):
    """状态响应。"""

    status: str = "ok"
    data: dict = {}


class HealthResponse(BaseModel):
    """健康检查响应。"""

    status: str = "ok"
    version: str = "4.0.0"


class PresetsResponse(BaseModel):
    """预设配置响应。"""

    status: str = "ok"
    mode: Optional[str] = None
    tool: Optional[str] = None
    mode_changed: bool = False
    tool_changed: bool = False


# ═══════════════════════════════════════════════════════════════
# 错误处理辅助
# ═══════════════════════════════════════════════════════════════


def _handle_gemini_error(e: Exception):
    """将 GeminiError 转换为 HTTPException。"""
    if isinstance(e, GeminiLoginRequiredError):
        raise HTTPException(status_code=401, detail=str(e))
    if isinstance(e, GeminiRateLimitError):
        raise HTTPException(status_code=429, detail=str(e))
    if isinstance(e, GeminiServerRollbackError):
        raise HTTPException(status_code=503, detail=str(e))
    if isinstance(e, GeminiTimeoutError):
        raise HTTPException(status_code=504, detail=str(e))
    if isinstance(e, GeminiPageError):
        raise HTTPException(status_code=500, detail=str(e))
    if isinstance(e, GeminiError):
        raise HTTPException(status_code=500, detail=str(e))
    logger.err(f"  × 意外错误: {e}")
    raise HTTPException(status_code=500, detail=f"意外错误: {e}")


# ═══════════════════════════════════════════════════════════════
# 预设验证辅助
# ═══════════════════════════════════════════════════════════════


async def _ensure_presets(
    agency: GeminiAgency,
    expected_mode: Optional[str] = None,
    expected_tool: Optional[str] = None,
) -> dict:
    """验证并纠正当前 mode 和 tool 是否符合预设。

    在首次发送消息前调用，确保浏览器状态与预设一致。

    Returns:
        dict 包含调整结果
    """
    result = {"mode_adjusted": False, "tool_adjusted": False}

    if expected_mode:
        try:
            current_mode = await agency.get_mode()
            current = current_mode.get("mode", "unknown")
            normalized_expected = _normalize_mode(expected_mode)

            if current.lower() != normalized_expected.lower():
                logger.mesg(
                    f"  模式不匹配: 当前={current}, 预设={normalized_expected},"
                    f" 自动调整 ..."
                )
                await agency.set_mode(normalized_expected)
                result["mode_adjusted"] = True
                result["mode"] = normalized_expected
            else:
                result["mode"] = current
        except Exception as e:
            logger.warn(f"  × 验证/调整模式失败: {e}")

    if expected_tool:
        try:
            normalized_expected = _normalize_tool(expected_tool)
            if normalized_expected != "none":
                current_tool = await agency.get_tool()
                current = current_tool.get("tool", "none")
                # 对当前工具也做标准化（浏览器可能返回缩写，如"图片"而非"生成图片"）
                current_normalized = _normalize_tool(current)

                if current_normalized.lower() != normalized_expected.lower():
                    logger.mesg(
                        f"  工具不匹配: 当前={current}({current_normalized}),"
                        f" 预设={normalized_expected}, 自动调整 ..."
                    )
                    await agency.set_tool(normalized_expected)
                    result["tool_adjusted"] = True
                    result["tool"] = normalized_expected
                else:
                    result["tool"] = normalized_expected
        except Exception as e:
            logger.warn(f"  × 验证/调整工具失败: {e}")

    return result


# ═══════════════════════════════════════════════════════════════
# 应用工厂
# ═══════════════════════════════════════════════════════════════


def create_gemini_server(
    config: GeminiConfigType = None, config_path: str = None
) -> FastAPI:
    """创建 Gemini 自动化的 FastAPI 应用。"""

    gemini_config = GeminiConfig(config=config, config_path=config_path)
    agency: GeminiAgency = None

    # 存储当前预设（在新聊天时设置，在首次发送消息时验证）
    presets: dict = {"mode": None, "tool": None, "verified": False}

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
            "支持：浏览器状态、聊天管理、模式/工具选择、预设配置、"
            "输入操作、消息发送、文件上传、消息获取、\n"
            "图片存储/下载、截图存储/下载、聊天历史数据库。"
        ),
        version="4.0.0",
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
        return HealthResponse(status="ok", version="4.0.0")

    @app.get("/browser_status", tags=["状态"])
    async def browser_status():
        """返回浏览器实例的全面状态信息。

        包括是否已登录、当前页面、模式、工具、预设配置等。
        """
        _ensure_ready()
        try:
            status = await agency.browser_status()
            status["presets"] = {**presets}
            return {"status": "ok", "data": status}
        except Exception as e:
            _handle_gemini_error(e)

    # ── 预设配置 ─────────────────────────────────────────────

    @app.post("/set_presets", response_model=PresetsResponse, tags=["预设"])
    async def set_presets(req: SetPresetsRequest):
        """同时设置 tool 和 mode 的预设配置。

        先设置 mode，再设置 tool。返回实际设置结果。
        预设会被记录，并在新聊天首次发送消息时自动验证。
        """
        _ensure_ready()
        result = PresetsResponse()

        try:
            # 先设置模式
            if req.mode:
                mode_result = await agency.set_mode(req.mode)
                result.mode = req.mode
                result.mode_changed = True
                presets["mode"] = req.mode

            # 再设置工具
            if req.tool and req.tool != "none":
                tool_result = await agency.set_tool(req.tool)
                result.tool = req.tool
                result.tool_changed = True
                presets["tool"] = req.tool
            elif req.tool == "none":
                presets["tool"] = None
                result.tool = "none"

            presets["verified"] = False
            return result
        except Exception as e:
            _handle_gemini_error(e)

    @app.get("/get_presets", tags=["预设"])
    async def get_presets():
        """获取当前预设配置。"""
        return {
            "status": "ok",
            "presets": {**presets},
        }

    # ── 聊天会话管理 ─────────────────────────────────────────

    @app.post("/new_chat", tags=["聊天"])
    async def new_chat(req: NewChatRequest = None):
        """创建新的聊天窗口。

        支持可选参数 tool 和 mode，在创建新聊天后自动设置。
        设置顺序：新建聊天 → 设置 mode → 设置 tool。
        """
        _ensure_ready()
        try:
            # 创建新聊天
            chat_result = await agency.new_chat()

            # 如果请求体提供了参数，
            # 使用请求体的参数；否则使用已保存的预设
            target_mode = None
            target_tool = None

            if req:
                target_mode = req.mode
                target_tool = req.tool

            # 设置模式
            if target_mode:
                try:
                    await agency.set_mode(target_mode)
                    presets["mode"] = target_mode
                    chat_result["mode"] = target_mode
                except Exception as e:
                    logger.warn(f"  ⚠ 设置模式失败: {e}")
                    chat_result["mode_error"] = str(e)

            # 设置工具
            if target_tool and target_tool != "none":
                try:
                    await agency.set_tool(target_tool)
                    presets["tool"] = target_tool
                    chat_result["tool"] = target_tool
                except Exception as e:
                    logger.warn(f"  ⚠ 设置工具失败: {e}")
                    chat_result["tool_error"] = str(e)

            presets["verified"] = False
            return chat_result
        except Exception as e:
            _handle_gemini_error(e)

    @app.post("/switch_chat", tags=["聊天"])
    async def switch_chat(req: SwitchChatRequest):
        """切换到指定 ID 的聊天窗口。"""
        _ensure_ready()
        try:
            result = await agency.switch_chat(req.chat_id)
            presets["verified"] = False
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
        """设置聊天窗口的模式（如 '快速', '思考', 'Pro'）。

        支持别名：fast→快速, think→思考, pro→Pro 等。
        """
        _ensure_ready()
        try:
            result = await agency.set_mode(req.mode)
            presets["mode"] = req.mode
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
        """设置聊天窗口的工具（如 'Deep Research', '生成图片', '创作音乐'）。

        支持别名：image→生成图片, music→创作音乐 等。
        传入 'none' 或 '无' 可取消当前工具。
        """
        _ensure_ready()
        try:
            result = await agency.set_tool(req.tool)
            if req.tool.lower() in ("none", "无"):
                presets["tool"] = None
            else:
                presets["tool"] = req.tool
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

        在新聊天的首次发送前，会自动验证 tool 和 mode 是否符合预设要求。
        如果不符合，会自动调整到正确的 tool 和 mode。

        支持同步和异步两种方式：
        - wait_response=True: 等到 Gemini 返回结果后才返回（同步）
        - wait_response=False: 发送后立即返回（异步）
        """
        _ensure_ready()
        try:
            # 首次发送前验证预设
            if not presets["verified"]:
                adjustment = await _ensure_presets(
                    agency,
                    expected_mode=presets.get("mode"),
                    expected_tool=presets.get("tool"),
                )
                presets["verified"] = True
                if adjustment.get("mode_adjusted") or adjustment.get("tool_adjusted"):
                    logger.mesg(f"  预设已自动调整: {adjustment}")

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

    # ── 图片管理 ─────────────────────────────────────────────

    async def _get_parsed_images():
        """提取并解析最新响应中的图片（内部共享逻辑）。"""
        from .parser import GeminiResponseParser

        images_data = await agency._extract_images(download_base64=True)
        if not images_data:
            return []
        parser = GeminiResponseParser()
        return parser.parse_images_from_elements(images_data)

    @app.post("/store_images", tags=["图片"])
    async def store_images(req: StoreImagesRequest = None):
        """将最新响应中的图片保存到服务器指定目录。

        从最新模型响应中提取图片数据，保存到服务器端指定目录。
        返回保存的文件路径列表。
        """
        _ensure_ready()
        try:
            output_dir = (req and req.output_dir) or "data/images"
            prefix = (req and req.prefix) or ""

            images = await _get_parsed_images()
            if not images:
                return {
                    "status": "ok",
                    "message": "没有找到图片",
                    "image_count": 0,
                    "saved_count": 0,
                    "saved_paths": [],
                }

            from .parser import GeminiResponse

            response = GeminiResponse(images=images)
            saved_paths = agency.save_images(
                response, output_dir=output_dir, prefix=prefix
            )

            return {
                "status": "ok",
                "image_count": len(images),
                "saved_count": len(saved_paths),
                "saved_paths": saved_paths,
            }
        except Exception as e:
            _handle_gemini_error(e)

    @app.post("/download_images", tags=["图片"])
    async def download_images(req: DownloadImagesRequest = None):
        """获取最新响应中的图片数据（base64），供客户端下载保存。

        返回 JSON 包含所有图片的 base64 编码数据、MIME 类型和建议文件名，
        客户端接收后可自行解码保存到本地。
        """
        _ensure_ready()
        try:
            prefix = (req and req.prefix) or ""
            images = await _get_parsed_images()
            if not images:
                return {
                    "status": "ok",
                    "message": "没有找到图片",
                    "image_count": 0,
                    "images": [],
                }

            import time as _time

            timestamp = int(_time.time())
            image_list = []
            for i, img in enumerate(images):
                if not img.base64_data:
                    continue
                prefix_part = f"{prefix}_" if prefix else ""
                ext = img.get_extension()
                filename = f"{prefix_part}{timestamp}_{i + 1}.{ext}"
                image_list.append(
                    {
                        "filename": filename,
                        "base64_data": img.base64_data,
                        "mime_type": img.mime_type,
                        "width": img.width,
                        "height": img.height,
                        "alt": img.alt,
                    }
                )

            return {
                "status": "ok",
                "image_count": len(images),
                "download_count": len(image_list),
                "images": image_list,
            }
        except Exception as e:
            _handle_gemini_error(e)

    # ── 截图管理 ─────────────────────────────────────────────

    @app.post("/store_screenshot", tags=["截图"])
    async def store_screenshot(req: StoreScreenshotRequest = None):
        """对当前浏览器状态截图并保存到服务器指定路径。"""
        _ensure_ready()
        try:
            path = (req and req.path) or "data/gemini_screenshot.png"
            await agency.screenshot(path=path)
            return {"status": "ok", "path": path}
        except Exception as e:
            _handle_gemini_error(e)

    @app.post("/download_screenshot", tags=["截图"])
    async def download_screenshot():
        """对当前浏览器状态截图并返回 PNG 图片数据，供客户端下载保存。"""
        _ensure_ready()
        try:
            png_data = await agency.screenshot()
            return Response(
                content=png_data,
                media_type="image/png",
                headers={"Content-Disposition": "attachment; filename=screenshot.png"},
            )
        except Exception as e:
            _handle_gemini_error(e)

    # ── 聊天历史数据库 ────────────────────────────────────────

    chatdb = ChatDatabase()

    class CreateChatDBRequest(BaseModel):
        title: str = Field("", description="聊天标题")
        chat_id: Optional[str] = Field(None, description="自定义聊天 ID（可选）")

    class AddChatMessageRequest(BaseModel):
        role: str = Field(..., description="消息角色：user 或 model")
        content: str = Field("", description="消息内容")
        files: list[str] = Field(default_factory=list, description="关联文件路径")

    class UpdateChatTitleRequest(BaseModel):
        title: str = Field(..., description="新标题")

    class UpdateChatMessageRequest(BaseModel):
        content: Optional[str] = Field(None, description="新内容（null 则不更新）")
        files: Optional[list[str]] = Field(
            None, description="新文件列表（null 则不更新）"
        )

    class SearchChatsRequest(BaseModel):
        query: str = Field(..., description="搜索关键字")

    @app.post("/chatdb/create", tags=["聊天数据库"])
    async def chatdb_create(req: CreateChatDBRequest = None):
        """创建新的聊天记录。"""
        title = (req and req.title) or ""
        chat_id_arg = (req and req.chat_id) or None
        chat_id = chatdb.create_chat(title=title, chat_id=chat_id_arg)
        return {"status": "ok", "chat_id": chat_id}

    @app.get("/chatdb/list", tags=["聊天数据库"])
    async def chatdb_list():
        """列出所有聊天记录的摘要。"""
        chats = chatdb.list_chats()
        return {"status": "ok", "chats": chats}

    @app.get("/chatdb/stats", tags=["聊天数据库"])
    async def chatdb_stats():
        """获取聊天数据库统计信息。"""
        stats = chatdb.stats()
        return {"status": "ok", **stats}

    @app.get("/chatdb/{chat_id}", tags=["聊天数据库"])
    async def chatdb_get(chat_id: str):
        """获取指定聊天的完整数据。"""
        session = chatdb.get_chat(chat_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"聊天 {chat_id} 不存在")
        return {"status": "ok", "chat": session.to_dict()}

    @app.delete("/chatdb/{chat_id}", tags=["聊天数据库"])
    async def chatdb_delete(chat_id: str):
        """删除指定聊天记录。"""
        ok = chatdb.delete_chat(chat_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"聊天 {chat_id} 不存在")
        return {"status": "ok", "message": f"聊天 {chat_id} 已删除"}

    @app.put("/chatdb/{chat_id}/title", tags=["聊天数据库"])
    async def chatdb_update_title(chat_id: str, req: UpdateChatTitleRequest):
        """更新聊天标题。"""
        ok = chatdb.update_chat_title(chat_id, req.title)
        if not ok:
            raise HTTPException(status_code=404, detail=f"聊天 {chat_id} 不存在")
        return {"status": "ok", "chat_id": chat_id, "title": req.title}

    @app.get("/chatdb/{chat_id}/messages", tags=["聊天数据库"])
    async def chatdb_get_messages(chat_id: str):
        """获取指定聊天的所有消息。"""
        messages = chatdb.get_messages(chat_id)
        if messages is None:
            raise HTTPException(status_code=404, detail=f"聊天 {chat_id} 不存在")
        return {"status": "ok", "messages": messages}

    @app.post("/chatdb/{chat_id}/messages", tags=["聊天数据库"])
    async def chatdb_add_message(chat_id: str, req: AddChatMessageRequest):
        """向聊天中添加一条消息。"""
        index = chatdb.add_message(
            chat_id, role=req.role, content=req.content, files=req.files
        )
        if index is None:
            raise HTTPException(status_code=404, detail=f"聊天 {chat_id} 不存在")
        return {"status": "ok", "message_index": index}

    @app.get("/chatdb/{chat_id}/messages/{message_index}", tags=["聊天数据库"])
    async def chatdb_get_message(chat_id: str, message_index: int):
        """获取指定索引的消息。"""
        msg = chatdb.get_message(chat_id, message_index)
        if msg is None:
            raise HTTPException(
                status_code=404, detail=f"消息不存在: {chat_id}[{message_index}]"
            )
        return {"status": "ok", "message": msg}

    @app.put("/chatdb/{chat_id}/messages/{message_index}", tags=["聊天数据库"])
    async def chatdb_update_message(
        chat_id: str, message_index: int, req: UpdateChatMessageRequest
    ):
        """更新指定索引的消息。"""
        ok = chatdb.update_message(
            chat_id, message_index, content=req.content, files=req.files
        )
        if not ok:
            raise HTTPException(
                status_code=404, detail=f"消息不存在: {chat_id}[{message_index}]"
            )
        return {"status": "ok", "message": f"消息 {message_index} 已更新"}

    @app.delete("/chatdb/{chat_id}/messages/{message_index}", tags=["聊天数据库"])
    async def chatdb_delete_message(chat_id: str, message_index: int):
        """删除指定索引的消息。"""
        ok = chatdb.delete_message(chat_id, message_index)
        if not ok:
            raise HTTPException(
                status_code=404, detail=f"消息不存在: {chat_id}[{message_index}]"
            )
        return {"status": "ok", "message": f"消息 {message_index} 已删除"}

    @app.post("/chatdb/search", tags=["聊天数据库"])
    async def chatdb_search(req: SearchChatsRequest):
        """搜索包含指定关键字的聊天。"""
        results = chatdb.search_chats(req.query)
        return {"status": "ok", "results": results}

    @app.post("/restart", tags=["系统"])
    async def restart():
        """重启 GeminiAgency。"""
        nonlocal agency
        try:
            if agency:
                await agency.stop()
            agency = GeminiAgency(config=gemini_config.config)
            await agency.start()
            presets["verified"] = False
            return {"status": "ok", "message": "Agency 已重启"}
        except Exception as e:
            logger.err(f"  × 重启失败: {e}")
            raise HTTPException(status_code=500, detail=f"重启失败: {e}")

    # ── 调试: JS 执行 ────────────────────────────────────────

    class EvaluateRequest(BaseModel):
        js: str = Field(..., description="要在页面中执行的 JavaScript 代码")

    @app.post("/evaluate", tags=["调试"])
    async def evaluate_js(req: EvaluateRequest):
        """在浏览器页面中执行 JavaScript 并返回结果（仅用于调试）。"""
        _ensure_ready()
        try:
            result = await agency.page.evaluate(req.js)
            return {"status": "ok", "result": result}
        except Exception as e:
            return {"status": "error", "error": str(e)}

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
