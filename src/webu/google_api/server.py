"""Google Search FastAPI 服务 — 搜索 API + 代理状态 API。

使用 ProxyManager 管理固定代理列表（warp + 备用），
不再依赖 MongoDB 代理池。
"""

import asyncio
import os
import tempfile
import uvicorn

from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Query, Response
from pathlib import Path
from pydantic import BaseModel, Field
from tclogger import logger, logstr
from typing import Optional

from webu.runtime_settings import GoogleApiSettings, resolve_google_api_settings

from .profile_assets import DEFAULT_SHARED_PROFILE_SECRET
from .profile_bootstrap import create_encrypted_profile_archive
from .proxy_manager import ProxyManager, DEFAULT_PROXIES
from .scraper import GoogleScraper
from ..fastapis.styles import setup_root_landing_page, setup_swagger_ui


# ═══════════════════════════════════════════════════════════════
# 请求/响应模型
# ═══════════════════════════════════════════════════════════════


class SearchRequest(BaseModel):
    """搜索请求。"""

    query: str = Field(..., description="搜索关键词", min_length=1, max_length=500)
    num: int = Field(10, description="期望的搜索结果数量", ge=1, le=50)
    lang: str = Field("en", description="搜索语言")
    proxy_url: Optional[str] = Field(None, description="指定代理 URL（可选）")


class SearchResultItem(BaseModel):
    """单个搜索结果。"""

    title: str = ""
    url: str = ""
    displayed_url: str = ""
    snippet: str = ""
    position: int = 0


class SearchResponse(BaseModel):
    """搜索响应。"""

    success: bool = True
    query: str = ""
    results: list[SearchResultItem] = []
    result_count: int = 0
    total_results_text: str = ""
    has_captcha: bool = False
    error: str = ""


class ProxyStatusItem(BaseModel):
    """单个代理状态。"""

    url: str = ""
    name: str = ""
    healthy: bool = False
    latency_ms: int = 0
    consecutive_failures: int = 0
    total_successes: int = 0
    total_failures: int = 0
    success_rate: str = ""
    last_check: str = ""


class ProxyStatusResponse(BaseModel):
    """代理状态响应。"""

    total_proxies: int = 0
    healthy_proxies: int = 0
    unhealthy_proxies: int = 0
    proxies: list[ProxyStatusItem] = []


class HealthResponse(BaseModel):
    """健康检查。"""

    status: str = "ok"
    version: str = "1.1.0"


class ProfileStatusResponse(BaseModel):
    profile_dir: str = ""
    exists: bool = False
    file_count: int = 0
    last_modified_ts: float = 0.0
    archive_available: bool = False


def _resolve_admin_token() -> str:
    return os.getenv("WEBU_ADMIN_TOKEN", "").strip()


def _require_admin(x_admin_token: str | None):
    configured_token = _resolve_admin_token()
    if configured_token and x_admin_token != configured_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")


def _profile_status(profile_dir) -> ProfileStatusResponse:
    profile_path = resolved = profile_dir.expanduser()
    if not profile_path.exists():
        return ProfileStatusResponse(profile_dir=str(profile_path), exists=False, file_count=0, last_modified_ts=0.0, archive_available=False)

    file_paths = [path for path in profile_path.rglob("*") if path.is_file()]
    last_modified_ts = max((path.stat().st_mtime for path in file_paths), default=profile_path.stat().st_mtime)
    return ProfileStatusResponse(
        profile_dir=str(profile_path),
        exists=True,
        file_count=len(file_paths),
        last_modified_ts=float(last_modified_ts),
        archive_available=bool(file_paths),
    )


def _resolve_search_api_token(
    header_token: str | None,
    query_token: str | None,
) -> str:
    return (header_token or query_token or "").strip()


# ═══════════════════════════════════════════════════════════════
# 应用工厂
# ═══════════════════════════════════════════════════════════════


def create_google_search_server(
    proxies: list[dict] = None,
    headless: bool | None = None,
    settings: GoogleApiSettings | None = None,
    home_mode: str = "swagger",
) -> FastAPI:
    """创建 Google 搜索 FastAPI 应用。

    Args:
        proxies: 代理列表配置（默认使用 DEFAULT_PROXIES）
        headless: 是否无头浏览器模式
    """

    resolved_settings = settings or resolve_google_api_settings(headless=headless)
    resolved_proxies = proxies if proxies is not None else resolved_settings.proxies

    proxy_manager: ProxyManager = None
    scraper: GoogleScraper = None

    def _proxy_stats() -> dict:
        if not proxy_manager:
            return {
                "total_proxies": 0,
                "healthy_proxies": 0,
                "unhealthy_proxies": 0,
                "proxies": [],
            }
        return proxy_manager.stats()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal proxy_manager, scraper
        logger.note("> Initializing Google Search Server ...")

        # 启动代理管理器
        if resolved_proxies:
            proxy_manager = ProxyManager(
                proxies=resolved_proxies,
                verbose=True,
            )
            await proxy_manager.start()

        # 启动搜索抓取器
        scraper = GoogleScraper(
            proxy_manager=proxy_manager,
            headless=resolved_settings.headless,
            profile_dir=resolved_settings.profile_dir,
            screenshot_dir=resolved_settings.screenshot_dir,
        )
        await scraper.start()

        logger.okay("  ✓ Google Search Server ready")
        yield

        if scraper:
            await scraper.stop()
        if proxy_manager:
            await proxy_manager.stop()

    app = FastAPI(
        title="Google Search API",
        description=(
            "基于 Playwright 的 Google 搜索 API。\n\n"
            "使用固定代理列表（warp + 备用）进行搜索，"
            "支持自动故障转移和健康检查。"
        ),
        version="1.1.0",
        lifespan=lifespan,
    )
    if home_mode == "hidden":
        setup_root_landing_page(
            app,
            title="Workspace Assets",
            message="Static workspace content is available. Interactive routes are not published from this path.",
        )
    else:
        setup_swagger_ui(app)
    app.state.google_api_settings = resolved_settings

    def _require_search_token(
        header_token: str | None,
        query_token: str | None,
    ):
        configured_token = resolved_settings.api_token.strip()
        if not configured_token:
            return
        request_token = _resolve_search_api_token(header_token, query_token)
        if request_token != configured_token:
            raise HTTPException(status_code=401, detail="Invalid api token")

    def _ensure_ready():
        if not scraper:
            raise HTTPException(status_code=503, detail="Server not ready")

    # ── 系统接口 ──────────────────────────────────────────────

    @app.get("/health", response_model=HealthResponse, tags=["系统"])
    async def health_check():
        """健康检查。"""
        return HealthResponse()

    @app.get("/admin/profile/status", response_model=ProfileStatusResponse, tags=["管理"])
    async def admin_profile_status(x_admin_token: str | None = Header(default=None)):
        _require_admin(x_admin_token)
        return _profile_status(resolved_settings.profile_dir)

    @app.get("/admin/profile/archive", tags=["管理"])
    async def admin_profile_archive(
        secret: str = Query(DEFAULT_SHARED_PROFILE_SECRET, min_length=1),
        x_admin_token: str | None = Header(default=None),
    ):
        _require_admin(x_admin_token)
        with tempfile.TemporaryDirectory(prefix="webu-profile-export-") as tempdir:
            archive_path = Path(tempdir) / "google_api_profile.bin"
            created = create_encrypted_profile_archive(resolved_settings.profile_dir, archive_path, secret)
            if not created or not archive_path.exists():
                raise HTTPException(status_code=404, detail="Profile archive is not available")
            status = _profile_status(resolved_settings.profile_dir)
            return Response(
                content=archive_path.read_bytes(),
                media_type="application/octet-stream",
                headers={
                    "X-Profile-Last-Modified-Ts": str(status.last_modified_ts),
                    "Content-Disposition": 'attachment; filename="google_api_profile.bin"',
                },
            )

    # ── 搜索接口 ──────────────────────────────────────────────

    @app.post("/search", response_model=SearchResponse, tags=["搜索"])
    async def search(
        req: SearchRequest,
        api_token: str | None = Query(None, description="搜索接口 token，可选"),
        x_api_token: str | None = Header(default=None, alias="X-Api-Token"),
    ):
        """执行 Google 搜索并返回解析后的结果。"""
        _ensure_ready()
        _require_search_token(x_api_token, api_token)
        try:
            result = await scraper.search(
                query=req.query,
                num=req.num,
                lang=req.lang,
                proxy_url=req.proxy_url,
            )
            return SearchResponse(
                success=bool(result.results) and not result.has_captcha,
                query=result.query,
                results=[
                    SearchResultItem(**r.to_dict()) for r in result.results
                ],
                result_count=len(result.results),
                total_results_text=result.total_results_text,
                has_captcha=result.has_captcha,
                error=result.error,
            )
        except Exception as e:
            logger.err(f"  × Search error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/search", response_model=SearchResponse, tags=["搜索"])
    async def search_get(
        q: str = Query(..., description="搜索关键词", min_length=1),
        num: int = Query(10, description="结果数量", ge=1, le=50),
        lang: str = Query("en", description="搜索语言"),
        api_token: str | None = Query(None, description="搜索接口 token，可选"),
        x_api_token: str | None = Header(default=None, alias="X-Api-Token"),
    ):
        """GET 方式执行 Google 搜索。"""
        req = SearchRequest(query=q, num=num, lang=lang)
        return await search(req, api_token=api_token, x_api_token=x_api_token)

    # ── 代理状态接口 ──────────────────────────────────────────

    @app.get("/proxy/status", response_model=ProxyStatusResponse, tags=["代理"])
    async def proxy_status():
        """获取代理健康状态。"""
        _ensure_ready()
        stats = _proxy_stats()
        return ProxyStatusResponse(
            total_proxies=stats["total_proxies"],
            healthy_proxies=stats["healthy_proxies"],
            unhealthy_proxies=stats["unhealthy_proxies"],
            proxies=[ProxyStatusItem(**p) for p in stats["proxies"]],
        )

    @app.get("/proxy/current", tags=["代理"])
    async def proxy_current():
        """获取当前推荐的代理。"""
        _ensure_ready()
        if not proxy_manager:
            raise HTTPException(status_code=404, detail="Proxy manager disabled")
        proxy_url = proxy_manager.get_proxy()
        if not proxy_url:
            raise HTTPException(status_code=404, detail="No proxy available")
        return {"proxy_url": proxy_url}

    @app.post("/proxy/check", tags=["代理"])
    async def proxy_check_now():
        """立即对所有代理执行健康检查。"""
        _ensure_ready()
        if not proxy_manager:
            return _proxy_stats()
        await proxy_manager._check_all()
        return proxy_manager.stats()

    return app


def app_instance():
    """工厂函数 — 供 uvicorn --factory 使用。"""
    return create_google_search_server()


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════


def main():
    """启动 Google Search API 服务。"""
    import argparse

    argparser = argparse.ArgumentParser(description="Google Search API Server")
    argparser.add_argument("--host", default="0.0.0.0", help="Bind host")
    argparser.add_argument("--port", type=int, default=18200, help="Bind port")
    argparser.add_argument("--no-headless", action="store_true", help="Show browser")
    args = argparser.parse_args()

    app = create_google_search_server(headless=not args.no_headless)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
