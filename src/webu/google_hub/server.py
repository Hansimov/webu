from __future__ import annotations

import argparse
import os
import uvicorn

from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from webu.fastapis.styles import setup_swagger_ui
from webu.runtime_settings import DEFAULT_GOOGLE_HUB_PORT

from .manager import GoogleHubManager, GoogleHubSettings, resolve_google_hub_settings


class HubHealthResponse(BaseModel):
    status: str = "ok"
    service: str = "google_hub"
    backend_count: int = 0
    healthy_backends: int = 0


class HubSearchResponse(BaseModel):
    success: bool = True
    backend: str = ""
    backend_kind: str = ""
    backend_url: str = ""
    query: str = ""
    results: list[dict] = Field(default_factory=list)
    result_count: int = 0
    total_results_text: str = ""
    has_captcha: bool = False
    error: str = ""


class HubBackendsResponse(BaseModel):
    strategy: str = "least-inflight"
    healthy_backends: int = 0
    enabled_backends: int = 0
    backends: list[dict] = Field(default_factory=list)


def create_google_hub_server(settings: GoogleHubSettings | None = None):
    resolved_settings = settings or resolve_google_hub_settings()
    manager = GoogleHubManager(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await manager.start()
        yield
        await manager.stop()

    app = FastAPI(
        title="Google Hub API",
        description="本地中心化调度服务，用于管理多个 Google API / HF Space 节点。",
        version="0.1.0",
        lifespan=lifespan,
    )
    setup_swagger_ui(app)
    app.state.google_hub_settings = resolved_settings
    app.state.google_hub_manager = manager

    def require_admin(x_admin_token: str | None = Header(default=None)):
        if resolved_settings.admin_token and x_admin_token != resolved_settings.admin_token:
            raise HTTPException(status_code=401, detail="Invalid admin token")

    @app.get("/health", response_model=HubHealthResponse, tags=["系统"])
    async def health_check():
        snapshot = await manager.backend_snapshot()
        return HubHealthResponse(
            backend_count=len(snapshot),
            healthy_backends=sum(1 for item in snapshot if item["healthy"]),
        )

    @app.get("/search", response_model=HubSearchResponse, tags=["搜索"])
    async def search(
        q: str = Query(..., min_length=1),
        num: int = Query(10, ge=1, le=50),
        lang: str = Query("en"),
    ):
        try:
            payload = await manager.search(query=q, num=num, lang=lang)
            return HubSearchResponse(**payload)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc))

    @app.get("/admin/backends", response_model=HubBackendsResponse, tags=["管理"])
    async def admin_backends(x_admin_token: str | None = Header(default=None)):
        require_admin(x_admin_token)
        return HubBackendsResponse(**(await manager.metrics()))

    @app.post("/admin/check", response_model=HubBackendsResponse, tags=["管理"])
    async def admin_check(x_admin_token: str | None = Header(default=None)):
        require_admin(x_admin_token)
        await manager.refresh_all_health()
        return HubBackendsResponse(**(await manager.metrics()))

    return app


def app_instance():
    return create_google_hub_server()


def main():
    parser = argparse.ArgumentParser(description="Run google_hub service")
    parser.add_argument("--host", default=os.getenv("WEBU_HUB_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("WEBU_HUB_PORT", str(DEFAULT_GOOGLE_HUB_PORT))))
    args = parser.parse_args()
    uvicorn.run(
        "webu.google_hub.server:app_instance",
        host=args.host,
        port=args.port,
        factory=True,
    )


if __name__ == "__main__":
    main()