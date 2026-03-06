from __future__ import annotations

import asyncio
import time

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

import requests

from webu.runtime_settings import (
    DEFAULT_GOOGLE_API_PORT,
    DEFAULT_GOOGLE_HUB_PORT,
    detect_runtime_environment,
    get_workspace_paths,
    load_json_config,
    resolve_google_api_service_profile,
    resolve_google_docker_settings,
    resolve_hf_space_settings,
)


@dataclass(frozen=True)
class GoogleHubBackend:
    name: str
    kind: str
    base_url: str
    enabled: bool
    weight: int
    search_api_token: str = ""
    admin_token: str = ""
    space_name: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GoogleHubSettings:
    host: str
    port: int
    admin_token: str
    strategy: str
    request_timeout_sec: int
    health_timeout_sec: int
    health_interval_sec: int
    backends: list[GoogleHubBackend]
    project_root: str
    config_dir: str


@dataclass
class BackendRuntimeState:
    backend: GoogleHubBackend
    healthy: bool = False
    last_error: str = ""
    latency_ms: int = 0
    inflight: int = 0
    consecutive_failures: int = 0
    total_successes: int = 0
    total_failures: int = 0
    last_checked_ts: float = 0.0
    last_selected_ts: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.backend.name,
            "kind": self.backend.kind,
            "base_url": self.backend.base_url,
            "space_name": self.backend.space_name,
            "enabled": self.backend.enabled,
            "weight": self.backend.weight,
            "tags": self.backend.tags,
            "healthy": self.healthy,
            "last_error": self.last_error,
            "latency_ms": self.latency_ms,
            "inflight": self.inflight,
            "consecutive_failures": self.consecutive_failures,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "last_checked_ts": self.last_checked_ts,
            "last_selected_ts": self.last_selected_ts,
        }


def _normalize_backend_base_url(base_url: str, runtime_env: str) -> str:
    normalized = str(base_url).strip().rstrip("/")
    if runtime_env != "docker" or not normalized:
        return normalized

    parts = urlsplit(normalized)
    if parts.hostname not in {"127.0.0.1", "localhost", "0.0.0.0"}:
        return normalized

    docker_host = "host.docker.internal"
    netloc = docker_host
    if parts.port:
        netloc = f"{docker_host}:{parts.port}"
    rebuilt = SplitResult(
        scheme=parts.scheme,
        netloc=netloc,
        path=parts.path,
        query=parts.query,
        fragment=parts.fragment,
    )
    return urlunsplit(rebuilt).rstrip("/")


def _normalize_backend(
    entry: dict[str, Any],
    default_search_token: str,
    default_admin_token: str,
    runtime_env: str,
) -> GoogleHubBackend:
    kind = str(entry.get("kind", "")).strip().lower()
    name = str(entry.get("name", "")).strip()
    space_name = str(entry.get("space", "")).strip()
    base_url = str(entry.get("base_url", "")).strip().rstrip("/")
    if kind == "hf-space":
        if not space_name:
            raise ValueError(f"hub backend '{name or entry}' requires 'space'")
        if not name:
            name = space_name.split("/")[-1]
        if not base_url:
            base_url = resolve_hf_space_settings(space_name).space_host.rstrip("/")
    elif kind in {"google-api", "local-google-api"}:
        if not name:
            name = kind
        if not base_url:
            raise ValueError(f"hub backend '{name}' requires 'base_url'")
        kind = "google-api"
    else:
        raise ValueError(f"unsupported hub backend kind: {kind!r}")

    base_url = _normalize_backend_base_url(base_url, runtime_env)

    return GoogleHubBackend(
        name=name,
        kind=kind,
        base_url=base_url,
        enabled=bool(entry.get("enabled", True)),
        weight=max(1, int(entry.get("weight", 1))),
        search_api_token=str(entry.get("search_api_token", default_search_token)).strip(),
        admin_token=str(entry.get("admin_token", default_admin_token)).strip(),
        space_name=space_name,
        tags=[str(tag).strip() for tag in entry.get("tags", []) if str(tag).strip()],
    )


def resolve_google_hub_settings() -> GoogleHubSettings:
    config = load_json_config("google_hub") or {}
    paths = get_workspace_paths()
    runtime_env = detect_runtime_environment()
    default_google = resolve_google_api_service_profile(runtime_env="local", service_type="local")
    default_hf = resolve_google_api_service_profile(runtime_env="hf-space", service_type="hf-space")
    default_admin_token = resolve_google_docker_settings().admin_token

    backends: list[GoogleHubBackend] = []
    for entry in config.get("backends", []):
        if not isinstance(entry, dict):
            continue
        normalized = dict(entry)
        if normalized.get("kind") == "local-google-api" and not normalized.get("base_url"):
            normalized["base_url"] = str(default_google.get("url", "")).strip()
        if normalized.get("kind") == "hf-space" and not normalized.get("search_api_token"):
            normalized["search_api_token"] = str(default_hf.get("api_token", "")).strip()
        backends.append(
            _normalize_backend(
                normalized,
                default_search_token=str(normalized.get("search_api_token", "")).strip() or str(default_hf.get("api_token", "")).strip(),
                default_admin_token=str(normalized.get("admin_token", "")).strip() or str(default_admin_token).strip(),
                runtime_env=runtime_env,
            )
        )

    if not backends:
        backends = [
            GoogleHubBackend(
                name="local-google-api",
                kind="google-api",
                base_url=_normalize_backend_base_url(str(default_google.get("url", f"http://127.0.0.1:{DEFAULT_GOOGLE_API_PORT}")), runtime_env),
                enabled=True,
                weight=2,
                search_api_token=str(default_google.get("api_token", "")).strip(),
                admin_token=str(default_admin_token).strip(),
                tags=["local", "primary"],
            )
        ]
        for entry in load_json_config("hf_spaces") or []:
            if not isinstance(entry, dict):
                continue
            space_name = str(entry.get("space", "")).strip()
            if not space_name:
                continue
            backends.append(
                GoogleHubBackend(
                    name=space_name.split("/")[-1],
                    kind="hf-space",
                    base_url=_normalize_backend_base_url(resolve_hf_space_settings(space_name).space_host.rstrip("/"), runtime_env),
                    enabled=bool(entry.get("enabled", True)),
                    weight=max(1, int(entry.get("weight", 1))),
                    search_api_token=str(default_hf.get("api_token", "")).strip(),
                    admin_token=str(default_admin_token).strip(),
                    space_name=space_name,
                    tags=[str(tag).strip() for tag in entry.get("tags", []) if str(tag).strip()],
                )
            )

    return GoogleHubSettings(
        host=str(config.get("host", "0.0.0.0")),
        port=int(config.get("port", DEFAULT_GOOGLE_HUB_PORT)),
        admin_token=str(config.get("admin_token", default_admin_token)).strip(),
        strategy=str(config.get("strategy", "least-inflight")).strip().lower(),
        request_timeout_sec=int(config.get("request_timeout_sec", 90)),
        health_timeout_sec=int(config.get("health_timeout_sec", 10)),
        health_interval_sec=int(config.get("health_interval_sec", 30)),
        backends=backends,
        project_root=str(paths.root),
        config_dir=str(paths.config_dir),
    )


class GoogleHubManager:
    def __init__(self, settings: GoogleHubSettings):
        self.settings = settings
        self.states = {backend.name: BackendRuntimeState(backend=backend) for backend in settings.backends}
        self._health_task: asyncio.Task | None = None

    async def start(self):
        await self.refresh_all_health()
        self._health_task = asyncio.create_task(self._health_loop())

    async def stop(self):
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

    async def _health_loop(self):
        while True:
            try:
                await self.refresh_all_health()
            finally:
                await asyncio.sleep(self.settings.health_interval_sec)

    async def refresh_all_health(self):
        for state in self.states.values():
            await self.refresh_backend_health(state.backend.name)

    async def refresh_backend_health(self, backend_name: str) -> dict[str, Any]:
        state = self.states[backend_name]
        backend = state.backend
        if not backend.enabled:
            state.healthy = False
            state.last_error = "backend disabled"
            state.last_checked_ts = time.time()
            return state.to_dict()

        started = time.perf_counter()
        try:
            response = await asyncio.to_thread(requests.get, f"{backend.base_url}/health", timeout=self.settings.health_timeout_sec)
            response.raise_for_status()
            state.healthy = True
            state.last_error = ""
            state.consecutive_failures = 0
            state.latency_ms = int((time.perf_counter() - started) * 1000)
        except Exception as exc:
            state.healthy = False
            state.last_error = str(exc)
            state.consecutive_failures += 1
            state.latency_ms = int((time.perf_counter() - started) * 1000)
        state.last_checked_ts = time.time()
        return state.to_dict()

    def _eligible_states(self) -> list[BackendRuntimeState]:
        states = [state for state in self.states.values() if state.backend.enabled and state.healthy]
        if states:
            return states
        return [state for state in self.states.values() if state.backend.enabled]

    def choose_backend(self) -> BackendRuntimeState:
        candidates = self._eligible_states()
        if not candidates:
            raise RuntimeError("no enabled hub backends configured")
        candidates.sort(
            key=lambda state: (
                state.inflight / max(1, state.backend.weight),
                state.consecutive_failures,
                state.last_selected_ts,
                state.latency_ms,
                state.backend.name,
            )
        )
        selected = candidates[0]
        selected.last_selected_ts = time.time()
        return selected

    def ordered_backends(self) -> list[BackendRuntimeState]:
        candidates = self._eligible_states()
        if not candidates:
            return []
        return sorted(
            candidates,
            key=lambda state: (
                state.inflight / max(1, state.backend.weight),
                state.consecutive_failures,
                state.last_selected_ts,
                state.latency_ms,
                state.backend.name,
            ),
        )

    async def search(self, *, query: str, num: int, lang: str) -> dict[str, Any]:
        ordered = self.ordered_backends()
        if not ordered:
            raise RuntimeError("no hub backends available")

        last_error = None
        for state in ordered:
            state.last_selected_ts = time.time()
            state.inflight += 1
            try:
                headers = {}
                if state.backend.search_api_token:
                    headers["X-Api-Token"] = state.backend.search_api_token
                response = await asyncio.to_thread(
                    requests.get,
                    f"{state.backend.base_url}/search",
                    params={"q": query, "num": num, "lang": lang},
                    headers=headers or None,
                    timeout=self.settings.request_timeout_sec,
                )
                response.raise_for_status()
                payload = response.json()
                state.total_successes += 1
                state.healthy = True
                state.last_error = ""
                return {
                    "backend": state.backend.name,
                    "backend_kind": state.backend.kind,
                    "backend_url": state.backend.base_url,
                    **payload,
                }
            except Exception as exc:
                last_error = exc
                state.total_failures += 1
                state.consecutive_failures += 1
                state.healthy = False
                state.last_error = str(exc)
            finally:
                state.inflight = max(0, state.inflight - 1)

        raise RuntimeError(f"all hub backends failed: {last_error}")

    async def backend_snapshot(self) -> list[dict[str, Any]]:
        return [state.to_dict() for state in self.states.values()]

    async def metrics(self) -> dict[str, Any]:
        states = await self.backend_snapshot()
        return {
            "strategy": self.settings.strategy,
            "healthy_backends": sum(1 for item in states if item["healthy"]),
            "enabled_backends": sum(1 for item in states if item["enabled"]),
            "backends": states,
        }