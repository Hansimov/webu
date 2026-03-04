"""WARP API FastAPI 管理服务 — 查询状态 / IP 检测。"""

import asyncio
import uvicorn

from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel
from tclogger import logger, logstr

from .constants import WARP_API_HOST, WARP_API_PORT, WARP_PROXY_HOST, WARP_PROXY_PORT
from .warp import WarpClient
from .proxy import WarpSocksProxy


# ═══════════════════════════════════════════════════════════════
# 响应模型
# ═══════════════════════════════════════════════════════════════


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"


class WarpStatusResponse(BaseModel):
    connected: bool = False
    status: str = "Unknown"
    network: str = ""
    warp_interface_ip: str = ""
    organization: str = ""


class IpCheckResponse(BaseModel):
    direct_ip: str = ""
    warp_exit_ip: str = ""
    warp_interface_ip: str = ""
    warp_active: bool = False


class ProxyStatsResponse(BaseModel):
    active_connections: int = 0
    total_connections: int = 0
    proxy_address: str = ""


# ═══════════════════════════════════════════════════════════════
# 应用工厂
# ═══════════════════════════════════════════════════════════════

# 全局代理实例的引用（由 CLI 注入）
_proxy_instance: WarpSocksProxy | None = None


def set_proxy_instance(proxy: WarpSocksProxy):
    global _proxy_instance
    _proxy_instance = proxy


def create_warp_server() -> FastAPI:
    """创建 WARP 管理 API FastAPI 应用。"""
    warp = WarpClient()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.note("> Initializing WARP API Server ...")
        logger.okay("  ✓ WARP API Server ready")
        yield

    app = FastAPI(
        title="WARP API",
        description="Cloudflare WARP 管理 API — 状态查询 / IP 检测 / 代理统计",
        version="1.0.0",
        lifespan=lifespan,
    )

    try:
        from ..fastapis.styles import setup_swagger_ui

        setup_swagger_ui(app)
    except ImportError:
        pass

    # ── 系统接口 ──────────────────────────────────────────────

    @app.get("/health", response_model=HealthResponse, tags=["系统"])
    async def health_check():
        return HealthResponse()

    # ── WARP 状态 ─────────────────────────────────────────────

    @app.get("/warp/status", response_model=WarpStatusResponse, tags=["WARP"])
    async def warp_status():
        info = warp.status()
        warp_ip = warp.get_warp_ip() or ""
        org = ""
        try:
            org = warp.organization()
        except Exception:
            pass
        return WarpStatusResponse(
            connected=info.get("connected", False),
            status=info.get("status", "Unknown"),
            network=info.get("network", ""),
            warp_interface_ip=warp_ip,
            organization=org,
        )

    @app.post("/warp/connect", tags=["WARP"])
    async def warp_connect():
        warp.connect()
        return {"message": "connect sent"}

    @app.post("/warp/disconnect", tags=["WARP"])
    async def warp_disconnect():
        warp.disconnect()
        return {"message": "disconnect sent"}

    # ── IP 检测 ───────────────────────────────────────────────

    @app.get("/warp/ip", response_model=IpCheckResponse, tags=["WARP"])
    async def check_ip():
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, warp.check_ip)
        return IpCheckResponse(**result)

    # ── 代理统计 ──────────────────────────────────────────────

    @app.get("/proxy/stats", response_model=ProxyStatsResponse, tags=["代理"])
    async def proxy_stats():
        global _proxy_instance
        stats = _proxy_instance.stats if _proxy_instance else {}
        return ProxyStatsResponse(
            active_connections=stats.get("active_connections", 0),
            total_connections=stats.get("total_connections", 0),
            proxy_address=f"socks5://{WARP_PROXY_HOST}:{WARP_PROXY_PORT}",
        )

    return app


# 给 uvicorn --factory 使用的入口
def app_instance() -> FastAPI:
    return create_warp_server()
