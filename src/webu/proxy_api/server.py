"""Proxy API FastAPI 服务 — 代理池管理 API。"""

import asyncio
import uvicorn

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from tclogger import logger, logstr
from typing import Optional

from .constants import MONGO_CONFIGS, MongoConfigsType
from .pool import ProxyPool


# ═══════════════════════════════════════════════════════════════
# 请求/响应模型
# ═══════════════════════════════════════════════════════════════


class ProxyStatsResponse(BaseModel):
    total_ips: int = 0
    total_checked: int = 0
    level1_passed: int = 0
    total_valid: int = 0
    total_abandoned: int = 0
    valid_ratio: str = "N/A"


class ProxyCollectResponse(BaseModel):
    total_fetched: int = 0
    inserted: int = 0
    updated: int = 0
    total: int = 0


class ProxyCheckResponse(BaseModel):
    checked: int = 0
    valid: int = 0
    invalid: int = 0


class ProxyListItem(BaseModel):
    ip: str = ""
    port: int = 0
    protocol: str = ""
    proxy_url: str = ""
    latency_ms: int = 0
    is_valid: bool = False


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"


# ═══════════════════════════════════════════════════════════════
# 应用工厂
# ═══════════════════════════════════════════════════════════════


def create_proxy_server(
    configs: MongoConfigsType = None,
) -> FastAPI:
    """创建 Proxy API FastAPI 应用。"""

    pool: ProxyPool = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal pool
        logger.note("> Initializing Proxy API Server ...")
        pool = ProxyPool(configs=configs)
        logger.okay("  ✓ Proxy API Server ready")
        yield

    app = FastAPI(
        title="Proxy API",
        description="代理池管理 API — 采集/检测/选取代理 IP。",
        version="1.0.0",
        lifespan=lifespan,
    )

    try:
        from ..fastapis.styles import setup_swagger_ui
        setup_swagger_ui(app)
    except ImportError:
        pass

    def _ensure_ready():
        if not pool:
            raise HTTPException(status_code=503, detail="Server not ready")

    # ── 系统接口 ──────────────────────────────────────────────

    @app.get("/health", response_model=HealthResponse, tags=["系统"])
    async def health_check():
        return HealthResponse()

    # ── 代理管理接口 ──────────────────────────────────────────

    @app.get("/proxy/stats", response_model=ProxyStatsResponse, tags=["代理池"])
    async def proxy_stats():
        _ensure_ready()
        stats = pool.stats()
        return ProxyStatsResponse(**stats)

    @app.post("/proxy/collect", response_model=ProxyCollectResponse, tags=["代理池"])
    async def proxy_collect():
        _ensure_ready()
        result = pool.collect()
        return ProxyCollectResponse(**result)

    @app.post("/proxy/check", response_model=ProxyCheckResponse, tags=["代理池"])
    async def proxy_check(
        limit: int = Query(200, description="最大检测数量", ge=1, le=5000),
        mode: str = Query("unchecked", description="检测模式"),
    ):
        _ensure_ready()
        if mode == "unchecked":
            results = await pool.check_unchecked(limit=limit)
        elif mode == "stale":
            results = await pool.check_stale(limit=limit)
        elif mode == "all":
            results = await pool.check_all(limit=limit)
        else:
            raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")

        valid = sum(1 for r in results if r.get("is_valid"))
        return ProxyCheckResponse(
            checked=len(results), valid=valid, invalid=len(results) - valid,
        )

    @app.post("/proxy/refresh", tags=["代理池"])
    async def proxy_refresh(
        check_limit: int = Query(200, description="检测数量上限"),
    ):
        _ensure_ready()
        result = await pool.refresh(check_limit=check_limit)
        return result

    @app.get("/proxy/valid", response_model=list[ProxyListItem], tags=["代理池"])
    async def proxy_valid(
        limit: int = Query(20, description="最大返回数量", ge=1, le=200),
        max_latency_ms: int = Query(10000, description="最大延迟(ms)"),
    ):
        _ensure_ready()
        proxies = pool.store.get_valid_proxies(
            limit=limit, max_latency_ms=max_latency_ms
        )
        return [ProxyListItem(**{k: v for k, v in p.items() if k != "_id"}) for p in proxies]

    @app.get("/proxy/get", tags=["代理池"])
    async def proxy_get():
        _ensure_ready()
        proxy = pool.get_proxy()
        if not proxy:
            raise HTTPException(status_code=404, detail="No valid proxy available")
        return {k: v for k, v in proxy.items() if k != "_id"}

    return app


def app_instance():
    """工厂函数 — 供 uvicorn --factory 使用。"""
    return create_proxy_server()
