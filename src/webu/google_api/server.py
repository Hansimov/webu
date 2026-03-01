"""Google Search FastAPI 服务 — 搜索 API + 代理管理 API。"""

import asyncio
import uvicorn

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from tclogger import logger, logstr
from typing import Optional

from .constants import MONGO_CONFIGS, MongoConfigsType
from .proxy_pool import ProxyPool
from .scraper import GoogleScraper
from ..fastapis.styles import setup_swagger_ui


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


class ProxyStatsResponse(BaseModel):
    """代理池统计响应。"""

    total_ips: int = 0
    total_checked: int = 0
    level1_passed: int = 0
    total_valid: int = 0
    valid_ratio: str = "N/A"


class ProxyCollectResponse(BaseModel):
    """代理采集响应。"""

    total_fetched: int = 0
    inserted: int = 0
    updated: int = 0
    total: int = 0


class ProxyCheckResponse(BaseModel):
    """代理检测响应。"""

    checked: int = 0
    valid: int = 0
    invalid: int = 0


class ProxyListItem(BaseModel):
    """代理列表项。"""

    ip: str = ""
    port: int = 0
    protocol: str = ""
    proxy_url: str = ""
    latency_ms: int = 0
    is_valid: bool = False


class HealthResponse(BaseModel):
    """健康检查。"""

    status: str = "ok"
    version: str = "1.0.0"


# ═══════════════════════════════════════════════════════════════
# 应用工厂
# ═══════════════════════════════════════════════════════════════


def create_google_search_server(
    configs: MongoConfigsType = None,
    headless: bool = True,
) -> FastAPI:
    """创建 Google 搜索 FastAPI 应用。"""

    pool: ProxyPool = None
    scraper: GoogleScraper = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal pool, scraper
        logger.note("> Initializing Google Search Server ...")
        pool = ProxyPool(configs=configs)
        scraper = GoogleScraper(proxy_pool=pool, headless=headless)
        await scraper.start()
        logger.okay("  ✓ Google Search Server ready")
        yield
        if scraper:
            await scraper.stop()

    app = FastAPI(
        title="Google Search API",
        description=(
            "基于 Playwright 的 Google 搜索 API。\n\n"
            "支持：搜索接口、代理池管理（采集/检测/选取）。"
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    setup_swagger_ui(app)

    def _ensure_ready():
        if not pool or not scraper:
            raise HTTPException(status_code=503, detail="Server not ready")

    # ── 系统接口 ──────────────────────────────────────────────

    @app.get("/health", response_model=HealthResponse, tags=["系统"])
    async def health_check():
        """健康检查。"""
        return HealthResponse()

    # ── 搜索接口 ──────────────────────────────────────────────

    @app.post("/search", response_model=SearchResponse, tags=["搜索"])
    async def search(req: SearchRequest):
        """执行 Google 搜索并返回解析后的结果。"""
        _ensure_ready()
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
    ):
        """GET 方式执行 Google 搜索。"""
        req = SearchRequest(query=q, num=num, lang=lang)
        return await search(req)

    # ── 代理管理接口 ──────────────────────────────────────────

    @app.get("/proxy/stats", response_model=ProxyStatsResponse, tags=["代理池"])
    async def proxy_stats():
        """获取代理池统计信息。"""
        _ensure_ready()
        stats = pool.stats()
        return ProxyStatsResponse(**stats)

    @app.post("/proxy/collect", response_model=ProxyCollectResponse, tags=["代理池"])
    async def proxy_collect():
        """从所有代理源采集 IP。"""
        _ensure_ready()
        result = pool.collect()
        return ProxyCollectResponse(**result)

    @app.post("/proxy/check", response_model=ProxyCheckResponse, tags=["代理池"])
    async def proxy_check(
        limit: int = Query(200, description="最大检测数量", ge=1, le=5000),
        mode: str = Query(
            "unchecked",
            description="检测模式: unchecked=未检测的, stale=过期的, all=全部",
        ),
        level: str = Query(
            "all",
            description="检测级别: 1=快速检测, 2=Google搜索, all=全部",
        ),
    ):
        """检测代理 IP 可用性（支持两级检测）。"""
        _ensure_ready()
        if mode == "unchecked":
            results = await pool.check_unchecked(limit=limit, level=level)
        elif mode == "stale":
            results = await pool.check_stale(limit=limit)
        elif mode == "all":
            results = await pool.check_all(limit=limit)
        else:
            raise HTTPException(
                status_code=400, detail=f"Invalid mode: {mode}"
            )

        valid = sum(1 for r in results if r.get("is_valid"))
        return ProxyCheckResponse(
            checked=len(results),
            valid=valid,
            invalid=len(results) - valid,
        )

    @app.post("/proxy/refresh", tags=["代理池"])
    async def proxy_refresh(
        check_limit: int = Query(200, description="检测数量上限"),
    ):
        """一键刷新：采集 + 检测未检测的 IP。"""
        _ensure_ready()
        result = await pool.refresh(check_limit=check_limit)
        return result

    @app.get("/proxy/valid", response_model=list[ProxyListItem], tags=["代理池"])
    async def proxy_valid(
        limit: int = Query(20, description="最大返回数量", ge=1, le=200),
        max_latency_ms: int = Query(10000, description="最大延迟(ms)"),
    ):
        """获取当前可用的代理列表。"""
        _ensure_ready()
        proxies = pool.store.get_valid_proxies(
            limit=limit, max_latency_ms=max_latency_ms
        )
        return [ProxyListItem(**{k: v for k, v in p.items() if k != "_id"}) for p in proxies]

    @app.get("/proxy/get", tags=["代理池"])
    async def proxy_get():
        """获取一个推荐的可用代理。"""
        _ensure_ready()
        proxy = pool.get_proxy()
        if not proxy:
            raise HTTPException(status_code=404, detail="No valid proxy available")
        return {k: v for k, v in proxy.items() if k != "_id"}

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
    argparser.add_argument("--port", type=int, default=18000, help="Bind port")
    argparser.add_argument("--no-headless", action="store_true", help="Show browser")
    args = argparser.parse_args()

    app = create_google_search_server(headless=not args.no_headless)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
