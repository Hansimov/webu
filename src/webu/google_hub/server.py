from __future__ import annotations

import asyncio
import argparse
import os
import time
import uvicorn

from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from webu.fastapis.request_metrics import (
    format_dashboard_timestamp,
    format_dashboard_timezone,
    format_uptime_human,
    resolve_server_identity,
)
from webu.fastapis.styles import setup_root_redirect_page
from webu.runtime_settings import DEFAULT_GOOGLE_API_PANEL_PATH, DEFAULT_GOOGLE_HUB_PORT

from .manager import (
    GoogleHubManager,
    GoogleHubSettings,
    resolve_google_hub_settings,
    sanitize_hf_control_error,
    sanitize_hub_search_error,
)
from .panel import mount_google_hub_panel


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
    requested_backend: str = ""
    selection_mode: str = "auto"
    latency_ms: float = 0.0
    query: str = ""
    results: list[dict] = Field(default_factory=list)
    result_count: int = 0
    total_results_text: str = ""
    has_captcha: bool = False
    error: str = ""


class HubBackendsResponse(BaseModel):
    strategy: str = "adaptive"
    healthy_backends: int = 0
    enabled_backends: int = 0
    excluded_nodes: list[str] = Field(default_factory=list)
    started_ts: float = 0.0
    started_at_human: str = ""
    uptime_seconds: int = 0
    uptime_human: str = "0s"
    backends: list[dict] = Field(default_factory=list)


class HubControlResponse(BaseModel):
    status: str = "ok"
    message: str = ""
    action: str = ""
    backend: str = ""
    count: int = 0
    results: list[dict] = Field(default_factory=list)


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
    setup_root_redirect_page(app, DEFAULT_GOOGLE_API_PANEL_PATH)
    app.state.google_hub_settings = resolved_settings
    app.state.google_hub_manager = manager

    def require_admin(x_admin_token: str | None = Header(default=None)):
        if (
            resolved_settings.admin_token
            and x_admin_token != resolved_settings.admin_token
        ):
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
        lang: str | None = Query(None),
        locale: str | None = Query(None),
        backend: str = Query(""),
    ):
        try:
            payload = await manager.search(
                query=q,
                num=num,
                lang=lang,
                locale=locale,
                backend_name=backend,
            )
            return HubSearchResponse(**payload)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=sanitize_hub_search_error(str(exc)),
            )

    @app.get("/admin/backends", response_model=HubBackendsResponse, tags=["管理"])
    async def admin_backends(x_admin_token: str | None = Header(default=None)):
        require_admin(x_admin_token)
        return HubBackendsResponse(**(await manager.metrics()))

    @app.post("/admin/check", response_model=HubBackendsResponse, tags=["管理"])
    async def admin_check(x_admin_token: str | None = Header(default=None)):
        require_admin(x_admin_token)
        await manager.refresh_all_health()
        return HubBackendsResponse(**(await manager.metrics()))

    @app.post(
        "/admin/control/backend", response_model=HubControlResponse, tags=["管理"]
    )
    async def admin_control_backend(
        backend: str = Query(..., min_length=1),
        action: str = Query(..., min_length=1),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin(x_admin_token)
        try:
            payload = await manager.control_backend(backend, action)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=sanitize_hf_control_error(str(exc)),
            )
        return HubControlResponse(
            status="ok",
            message=str(payload.get("message", "")).strip(),
            action=str(payload.get("action", action)).strip(),
            backend=str(payload.get("backend", backend)).strip(),
            count=1,
            results=[payload],
        )

    @app.post("/admin/control/all", response_model=HubControlResponse, tags=["管理"])
    async def admin_control_all(
        action: str = Query(..., min_length=1),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin(x_admin_token)
        try:
            payload = await manager.control_all_backends(action)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=sanitize_hf_control_error(str(exc)),
            )
        return HubControlResponse(
            status="ok",
            message=str(payload.get("message", "")).strip(),
            action=str(payload.get("action", action)).strip(),
            backend="",
            count=int(payload.get("count", 0) or 0),
            results=list(payload.get("results", [])),
        )

    def build_snapshot_payload(metrics: dict) -> dict:
        return {
            "updated_at_human": format_dashboard_timestamp(),
            "current_time_human": format_dashboard_timestamp(),
            "timezone_human": format_dashboard_timezone(),
            "strategy": metrics.get("strategy", "adaptive"),
            "started_at_human": format_dashboard_timestamp(
                metrics.get("started_ts", 0.0)
            ),
            "started_ts": float(metrics.get("started_ts", 0.0) or 0.0),
            "uptime_seconds": max(
                0,
                int(time.time() - float(metrics.get("started_ts", 0.0) or 0.0)),
            ),
            "uptime_human": format_uptime_human(metrics.get("started_ts", 0.0)),
            "node": resolve_server_identity(
                os.getenv("WEBU_RUNTIME_ENV", "local").strip().lower() or "local"
            ),
            "health": {
                "backend_count": len(metrics.get("backends", [])),
                "healthy_backends": metrics.get("healthy_backends", 0),
                "enabled_backends": metrics.get("enabled_backends", 0),
            },
            "requests": metrics.get("request_stats", {}),
            "excluded_nodes": metrics.get("excluded_nodes", []),
            "backends": metrics.get("backends", []),
        }

    mount_google_hub_panel(
        app,
        lambda: build_snapshot_payload(asyncio.run(manager.metrics())),
        lambda query, num, lang, backend_name: asyncio.run(
            manager.search(
                query=query,
                num=num,
                lang=lang,
                locale=None,
                backend_name=backend_name,
            )
        ),
        lambda action, backend_name: asyncio.run(
            manager.control_all_backends(action[:-4])
            if action.endswith("-all")
            else manager.control_backend(backend_name, action)
        ),
        admin_token=resolved_settings.admin_token,
    )

    return app


def app_instance():
    return create_google_hub_server()


def main():
    parser = argparse.ArgumentParser(description="Run google_hub service")
    parser.add_argument("--host", default=os.getenv("WEBU_HUB_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("WEBU_HUB_PORT", str(DEFAULT_GOOGLE_HUB_PORT))),
    )
    parser.add_argument(
        "--exclude-nodes",
        default=os.getenv("WEBU_HUB_EXCLUDE_NODES", "local-google-api"),
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=int(os.getenv("WEBU_HUB_REQUEST_TIMEOUT_SEC", "60")),
    )
    args = parser.parse_args()
    os.environ["WEBU_HUB_EXCLUDE_NODES"] = str(args.exclude_nodes).strip()
    os.environ["WEBU_HUB_REQUEST_TIMEOUT_SEC"] = str(max(1, int(args.request_timeout)))
    uvicorn.run(
        "webu.google_hub.server:app_instance",
        host=args.host,
        port=args.port,
        factory=True,
    )


if __name__ == "__main__":
    main()
