from __future__ import annotations

import argparse
import os
import uvicorn

from pathlib import Path
from fastapi import Header, HTTPException, Query
from pydantic import BaseModel, Field

from webu.runtime_settings import (
    DEFAULT_GOOGLE_API_PORT,
    GoogleApiSettings,
    GoogleDockerSettings,
    resolve_google_api_settings,
    resolve_google_docker_settings,
)
from webu.google_api.server import create_google_search_server


class RuntimeInfoResponse(BaseModel):
    service: str = "google_docker"
    runtime_env: str = "local"
    host: str = "0.0.0.0"
    port: int = DEFAULT_GOOGLE_API_PORT
    app_port: int = DEFAULT_GOOGLE_API_PORT
    headless: bool = True
    proxy_mode: str = "auto"
    proxy_count: int = 0
    service_url: str = ""
    service_type: str = "local"
    api_token_configured: bool = False
    config_dir: str = ""
    project_root: str = ""
    service_log_path: str = ""


class LogsResponse(BaseModel):
    path: str = ""
    lines: int = 0
    content: str = ""
    exists: bool = False


class ConfigResponse(BaseModel):
    runtime_env: str = "local"
    host: str = "0.0.0.0"
    port: int = DEFAULT_GOOGLE_API_PORT
    image_name: str = ""
    container_name: str = ""
    proxy_mode: str = "auto"
    proxies: list[dict] = Field(default_factory=list)
    service_url: str = ""
    service_type: str = "local"
    api_token_configured: bool = False
    config_dir: str = ""
    project_root: str = ""
    service_log_path: str = ""
    admin_token_configured: bool = False


def _read_tail(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as fp:
        content = fp.readlines()
    return "".join(content[-lines:])


def create_google_docker_server(
    *,
    google_api_settings: GoogleApiSettings | None = None,
    docker_settings: GoogleDockerSettings | None = None,
    admin_token: str | None = None,
):
    resolved_docker = docker_settings or resolve_google_docker_settings()
    resolved_google = google_api_settings or resolve_google_api_settings(
        host=resolved_docker.host,
        port=resolved_docker.port,
    )
    resolved_admin_token = (
        admin_token if admin_token is not None else resolved_docker.admin_token
    )
    home_mode = "panel" if resolved_docker.runtime_env == "hf-space" else "swagger"

    app = create_google_search_server(settings=resolved_google, home_mode=home_mode)
    app.state.google_docker_settings = resolved_docker
    app.state.google_api_settings = resolved_google

    def require_admin(x_admin_token: str | None = Header(default=None)):
        if resolved_admin_token and x_admin_token != resolved_admin_token:
            raise HTTPException(status_code=401, detail="Invalid admin token")

    @app.get("/admin/runtime", response_model=RuntimeInfoResponse, tags=["管理"])
    async def admin_runtime(x_admin_token: str | None = Header(default=None)):
        require_admin(x_admin_token)
        return RuntimeInfoResponse(
            runtime_env=resolved_docker.runtime_env,
            host=resolved_google.host,
            port=resolved_google.port,
            app_port=resolved_docker.app_port,
            headless=resolved_google.headless,
            proxy_mode=resolved_google.proxy_mode,
            proxy_count=len(resolved_google.proxies),
            service_url=resolved_google.service_url,
            service_type=resolved_google.service_type,
            api_token_configured=bool(resolved_google.api_token),
            config_dir=str(resolved_docker.config_dir),
            project_root=str(resolved_docker.project_root),
            service_log_path=str(resolved_docker.service_log_path),
        )

    @app.get("/admin/logs", response_model=LogsResponse, tags=["管理"])
    async def admin_logs(
        lines: int = Query(200, ge=1, le=2000),
        x_admin_token: str | None = Header(default=None),
    ):
        require_admin(x_admin_token)
        log_path = resolved_docker.service_log_path
        return LogsResponse(
            path=str(log_path),
            lines=lines,
            content=_read_tail(log_path, lines),
            exists=log_path.exists(),
        )

    @app.get("/admin/config", response_model=ConfigResponse, tags=["管理"])
    async def admin_config(x_admin_token: str | None = Header(default=None)):
        require_admin(x_admin_token)
        return ConfigResponse(
            runtime_env=resolved_docker.runtime_env,
            host=resolved_google.host,
            port=resolved_google.port,
            image_name=resolved_docker.image_name,
            container_name=resolved_docker.container_name,
            proxy_mode=resolved_google.proxy_mode,
            proxies=resolved_google.proxies,
            service_url=resolved_google.service_url,
            service_type=resolved_google.service_type,
            api_token_configured=bool(resolved_google.api_token),
            config_dir=str(resolved_docker.config_dir),
            project_root=str(resolved_docker.project_root),
            service_log_path=str(resolved_docker.service_log_path),
            admin_token_configured=bool(resolved_admin_token),
        )

    return app


def app_instance():
    return create_google_docker_server()


def main():
    parser = argparse.ArgumentParser(description="Run google_docker service")
    parser.add_argument("--host", default=os.getenv("WEBU_DOCKER_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("WEBU_DOCKER_PORT", str(DEFAULT_GOOGLE_API_PORT))),
    )
    args = parser.parse_args()
    uvicorn.run(
        "webu.google_docker.server:app_instance",
        host=args.host,
        port=args.port,
        factory=True,
    )


if __name__ == "__main__":
    main()
