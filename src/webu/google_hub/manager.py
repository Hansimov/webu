from __future__ import annotations

import asyncio
import os
import socket
import time

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

import requests
from huggingface_hub import HfApi

from webu.fastapis.request_metrics import RequestMetrics
from webu.runtime_settings import (
    DEFAULT_GOOGLE_API_PORT,
    DEFAULT_GOOGLE_HUB_PORT,
    detect_runtime_environment,
    get_workspace_paths,
    load_json_config,
    resolve_google_api_service_profile,
    resolve_google_docker_settings,
    resolve_hf_space_entries,
    resolve_hf_space_settings,
)

HF_SPACE_RUNNING_STAGES = {"RUNNING"}
HF_SPACE_TRANSITION_STAGES = {
    "BUILDING",
    "RUNNING_BUILDING",
    "APP_STARTING",
    "RUNNING_APP_STARTING",
    "STARTING",
    "RESTARTING",
    "RUNNING_RESTARTING",
}
HF_SPACE_ERROR_STAGES = {
    "NO_APP_FILE",
    "CONFIG_ERROR",
    "BUILD_ERROR",
    "RUNTIME_ERROR",
    "DELETING",
    "STOPPED",
    "PAUSED",
}
HF_SPACE_RUNTIME_REFRESH_TIMEOUT_SEC = 1.5


def _normalize_runtime_stage(stage: str | None) -> str:
    return str(stage or "").strip().upper()


def _classify_backend_status(state: "BackendRuntimeState") -> tuple[str, str, bool]:
    if not state.backend.enabled:
        return ("DISABLED", "neutral", False)

    if state.backend.kind != "hf-space":
        if state.healthy:
            return ("RUNNING", "accent", True)
        return ("UNREACHABLE", "danger", False)

    runtime_stage = _normalize_runtime_stage(state.runtime_stage)
    if state.healthy and runtime_stage in HF_SPACE_RUNNING_STAGES:
        return (runtime_stage, "accent", True)
    if state.healthy and not runtime_stage:
        return ("RUNNING", "accent", True)
    if runtime_stage in HF_SPACE_TRANSITION_STAGES:
        return (runtime_stage, "info", False)
    if runtime_stage in HF_SPACE_ERROR_STAGES:
        return (runtime_stage, "danger", False)
    if state.last_error:
        return ("UNREACHABLE", "danger", False)
    if runtime_stage:
        return (runtime_stage, "danger", False)
    return ("UNKNOWN", "danger", False)


def _should_refresh_runtime_stage(
    state: "BackendRuntimeState", *, fetch_runtime_stage: bool
) -> bool:
    if state.backend.kind != "hf-space":
        return False
    if fetch_runtime_stage:
        return True
    return _normalize_runtime_stage(state.runtime_stage) in HF_SPACE_TRANSITION_STAGES


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
    disabled_reason: str = ""


@dataclass(frozen=True)
class GoogleHubSettings:
    host: str
    port: int
    admin_token: str
    strategy: str
    request_timeout_sec: int
    health_timeout_sec: int
    health_interval_sec: int
    excluded_nodes: list[str]
    backends: list[GoogleHubBackend]
    project_root: str
    config_dir: str


@dataclass
class BackendRuntimeState:
    backend: GoogleHubBackend
    healthy: bool = False
    resolved_ipv4: str = ""
    runtime_stage: str = ""
    runtime_sleep_time: int = 0
    search_cooldown_until_ts: float = 0.0
    last_error: str = ""
    latency_ms: int = 0
    inflight: int = 0
    consecutive_failures: int = 0
    total_successes: int = 0
    total_failures: int = 0
    request_count: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_request_latency_ms: float = 0.0
    min_request_latency_ms: float = 0.0
    max_request_latency_ms: float = 0.0
    last_request_latency_ms: float = 0.0
    latency_ewma_ms: float = 0.0
    selection_score: float = 0.0
    last_checked_ts: float = 0.0
    last_selected_ts: float = 0.0
    last_success_ts: float = 0.0
    last_failure_ts: float = 0.0

    def record_request(self, duration_ms: float, success: bool):
        latency_ms = max(0.0, float(duration_ms))
        self.request_count += 1
        if success:
            self.successful_requests += 1
            self.consecutive_failures = 0
            self.last_success_ts = time.time()
        else:
            self.failed_requests += 1
            self.consecutive_failures += 1
            self.last_failure_ts = time.time()
        self.total_request_latency_ms += latency_ms
        self.last_request_latency_ms = latency_ms
        if self.latency_ewma_ms <= 0:
            self.latency_ewma_ms = latency_ms
        else:
            self.latency_ewma_ms = self.latency_ewma_ms * 0.65 + latency_ms * 0.35
        if self.min_request_latency_ms <= 0:
            self.min_request_latency_ms = latency_ms
        else:
            self.min_request_latency_ms = min(self.min_request_latency_ms, latency_ms)
        self.max_request_latency_ms = max(self.max_request_latency_ms, latency_ms)
        self.selection_score = self.compute_selection_score()

    def success_rate_ratio(self) -> float:
        if self.request_count <= 0:
            return 1.0 if self.healthy else 0.0
        return self.successful_requests / self.request_count

    def avg_request_latency_ms(self) -> float:
        if self.request_count <= 0:
            return float(self.latency_ms)
        return self.total_request_latency_ms / self.request_count

    def estimated_latency_ms(self) -> float:
        candidates = [
            value
            for value in [
                self.latency_ewma_ms,
                self.avg_request_latency_ms(),
                float(self.latency_ms),
            ]
            if value > 0
        ]
        if not candidates:
            return 500.0
        return min(candidates)

    def compute_selection_score(self) -> float:
        success_penalty = (1.0 - self.success_rate_ratio()) * 800.0
        failure_penalty = min(6, self.consecutive_failures) * 180.0
        health_penalty = 0.0 if self.healthy else 320.0
        inflight_penalty = self.inflight * 140.0 / max(1, self.backend.weight)
        latency_component = self.estimated_latency_ms() / max(1, self.backend.weight)
        return (
            latency_component
            + success_penalty
            + failure_penalty
            + health_penalty
            + inflight_penalty
        )

    def to_dict(self) -> dict[str, Any]:
        status_label, status_tone, is_running = _classify_backend_status(self)
        success_rate = (
            (self.successful_requests / self.request_count * 100.0)
            if self.request_count
            else 0.0
        )
        avg_request_latency_ms = (
            (self.total_request_latency_ms / self.request_count)
            if self.request_count
            else 0.0
        )
        return {
            "name": self.backend.name,
            "kind": self.backend.kind,
            "base_url": self.backend.base_url,
            "space_name": self.backend.space_name,
            "resolved_ipv4": self.resolved_ipv4,
            "runtime_stage": self.runtime_stage,
            "runtime_sleep_time": self.runtime_sleep_time,
            "search_cooldown_until_ts": self.search_cooldown_until_ts,
            "enabled": self.backend.enabled,
            "disabled_reason": self.backend.disabled_reason,
            "weight": self.backend.weight,
            "tags": self.backend.tags,
            "healthy": self.healthy,
            "last_error": self.last_error,
            "latency_ms": self.latency_ms,
            "inflight": self.inflight,
            "consecutive_failures": self.consecutive_failures,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "request_count": self.request_count,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": success_rate,
            "avg_request_latency_ms": avg_request_latency_ms,
            "min_request_latency_ms": self.min_request_latency_ms,
            "max_request_latency_ms": self.max_request_latency_ms,
            "last_request_latency_ms": self.last_request_latency_ms,
            "latency_ewma_ms": self.latency_ewma_ms,
            "selection_score": self.compute_selection_score(),
            "status_label": status_label,
            "status_tone": status_tone,
            "is_running": is_running,
            "last_checked_ts": self.last_checked_ts,
            "last_selected_ts": self.last_selected_ts,
            "last_success_ts": self.last_success_ts,
            "last_failure_ts": self.last_failure_ts,
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


def _resolve_backend_ipv4(base_url: str) -> str:
    parsed = urlsplit(str(base_url or "").strip())
    hostname = str(parsed.hostname or "").strip()
    if not hostname:
        return ""
    try:
        return str(socket.gethostbyname(hostname))
    except OSError:
        return ""


def sanitize_hub_search_error(error: str) -> str:
    message = str(error or "").strip()
    if not message:
        return "hub search failed"
    lowered = message.lower()
    if message.startswith("hub search failed across "):
        return message
    if message.startswith("backend '") and " failed: " in message:
        backend_name, _, backend_error = message.partition(" failed: ")
        backend_error = backend_error.strip()
        lowered_backend_error = backend_error.lower()
        if "timeout" in lowered_backend_error or "timed out" in lowered_backend_error:
            return f"{backend_name} failed: timeout"
        if "httpsconnectionpool" in lowered_backend_error:
            return f"{backend_name} failed: upstream request error"
        return f"{backend_name} failed: {backend_error[:96]}"
    if lowered.startswith("all hub backends failed:"):
        if "timeout" in lowered or "timed out" in lowered:
            return "hub search failed across available backends: timeout. Try again or pin another healthy instance."
        if "httpsconnectionpool" in lowered:
            return "hub search failed across available backends: upstream request error. Try again or pin another healthy instance."
        return "hub search failed across available backends. Try again or pin another healthy instance."
    if "httpsconnectionpool" in lowered:
        if "timeout" in lowered or "timed out" in lowered:
            return "hub search failed: timeout"
        return "hub search failed: upstream request error"
    return message


def sanitize_hf_control_error(error: str) -> str:
    message = str(error or "").strip()
    if not message:
        return "HF control request failed"
    lowered = message.lower()
    if "network is unreachable" in lowered:
        return "HF control request failed: network unreachable. Retry later or switch the control endpoint."
    if "httpsconnectionpool" in lowered or "max retries exceeded" in lowered:
        return "HF control request failed: control endpoint unavailable. Retry later or switch the control endpoint."
    if (
        "name or service not known" in lowered
        or "temporary failure in name resolution" in lowered
    ):
        return "HF control request failed: DNS resolution failed. Retry later or switch the control endpoint."
    return f"HF control request failed: {message[:160]}"


def _normalize_backend(
    entry: dict[str, Any],
    default_search_token: str,
    default_admin_token: str,
    runtime_env: str,
    excluded_nodes: set[str],
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
    configured_enabled = bool(entry.get("enabled", True))
    disabled_reason = ""
    if not configured_enabled:
        disabled_reason = "disabled in config"
    elif name in excluded_nodes or (space_name and space_name in excluded_nodes):
        configured_enabled = False
        disabled_reason = "excluded by hub settings"

    return GoogleHubBackend(
        name=name,
        kind=kind,
        base_url=base_url,
        enabled=configured_enabled,
        weight=max(1, int(entry.get("weight", 1))),
        search_api_token=str(
            entry.get("search_api_token", default_search_token)
        ).strip(),
        admin_token=str(entry.get("admin_token", default_admin_token)).strip(),
        space_name=space_name,
        tags=[str(tag).strip() for tag in entry.get("tags", []) if str(tag).strip()],
        disabled_reason=disabled_reason,
    )


def _parse_excluded_nodes(raw_value: Any) -> list[str]:
    if isinstance(raw_value, str):
        items = raw_value.split(",")
    elif isinstance(raw_value, list):
        items = raw_value
    else:
        items = []
    seen: set[str] = set()
    values: list[str] = []
    for item in items:
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        values.append(name)
    return values


def _generate_backend_name(space_name: str, used_names: set[str]) -> str:
    repo_name = space_name.split("/")[-1]
    candidates = [repo_name, space_name.replace("/", "-")]
    for candidate in candidates:
        normalized = str(candidate).strip()
        if normalized and normalized not in used_names:
            return normalized

    suffix = 2
    base_name = space_name.replace("/", "-") or "hf-space"
    while True:
        candidate = f"{base_name}-{suffix}"
        if candidate not in used_names:
            return candidate
        suffix += 1


def _append_missing_hf_space_backends(
    backends: list[GoogleHubBackend],
    *,
    runtime_env: str,
    excluded_nodes: set[str],
    default_search_token: str,
    default_admin_token: str,
):
    declared_spaces = {
        backend.space_name for backend in backends if backend.kind == "hf-space"
    }
    used_names = {backend.name for backend in backends}

    for entry in resolve_hf_space_entries():
        space_name = str(entry.get("space", "")).strip()
        if not space_name or space_name in declared_spaces:
            continue

        backend_name = _generate_backend_name(space_name, used_names)
        used_names.add(backend_name)
        declared_spaces.add(space_name)
        backends.append(
            _normalize_backend(
                {
                    "name": backend_name,
                    "kind": "hf-space",
                    "space": space_name,
                    "enabled": entry.get("enabled", True),
                },
                default_search_token=default_search_token,
                default_admin_token=default_admin_token,
                runtime_env=runtime_env,
                excluded_nodes=excluded_nodes,
            )
        )


def resolve_google_hub_settings() -> GoogleHubSettings:
    config = load_json_config("google_hub") or {}
    paths = get_workspace_paths()
    runtime_env = detect_runtime_environment()
    default_google = resolve_google_api_service_profile(
        runtime_env="local", service_type="local"
    )
    default_hf = resolve_google_api_service_profile(
        runtime_env="hf-space", service_type="hf-space"
    )
    default_admin_token = resolve_google_docker_settings().admin_token
    env_excluded_nodes = _parse_excluded_nodes(os.getenv("WEBU_HUB_EXCLUDE_NODES", ""))
    config_excluded_nodes = _parse_excluded_nodes(config.get("exclude_nodes", []))
    excluded_nodes = list(dict.fromkeys([*config_excluded_nodes, *env_excluded_nodes]))
    excluded_node_set = set(excluded_nodes)

    backends: list[GoogleHubBackend] = []
    for entry in config.get("backends", []):
        if not isinstance(entry, dict):
            continue
        normalized = dict(entry)
        if normalized.get("kind") == "local-google-api" and not normalized.get(
            "base_url"
        ):
            normalized["base_url"] = str(default_google.get("url", "")).strip()
        if normalized.get("kind") == "hf-space" and not normalized.get(
            "search_api_token"
        ):
            normalized["search_api_token"] = str(
                default_hf.get("api_token", "")
            ).strip()
        backends.append(
            _normalize_backend(
                normalized,
                default_search_token=str(normalized.get("search_api_token", "")).strip()
                or str(default_hf.get("api_token", "")).strip(),
                default_admin_token=str(normalized.get("admin_token", "")).strip()
                or str(default_admin_token).strip(),
                runtime_env=runtime_env,
                excluded_nodes=excluded_node_set,
            )
        )

    _append_missing_hf_space_backends(
        backends,
        runtime_env=runtime_env,
        excluded_nodes=excluded_node_set,
        default_search_token=str(default_hf.get("api_token", "")).strip(),
        default_admin_token=str(default_admin_token).strip(),
    )

    if not backends:
        backends = [
            GoogleHubBackend(
                name="local-google-api",
                kind="google-api",
                base_url=_normalize_backend_base_url(
                    str(
                        default_google.get(
                            "url", f"http://127.0.0.1:{DEFAULT_GOOGLE_API_PORT}"
                        )
                    ),
                    runtime_env,
                ),
                enabled=True,
                weight=2,
                search_api_token=str(default_google.get("api_token", "")).strip(),
                admin_token=str(default_admin_token).strip(),
                tags=["local", "primary"],
            )
        ]
        _append_missing_hf_space_backends(
            backends,
            runtime_env=runtime_env,
            excluded_nodes=excluded_node_set,
            default_search_token=str(default_hf.get("api_token", "")).strip(),
            default_admin_token=str(default_admin_token).strip(),
        )

    return GoogleHubSettings(
        host=str(config.get("host", "0.0.0.0")),
        port=int(config.get("port", DEFAULT_GOOGLE_HUB_PORT)),
        admin_token=str(config.get("admin_token", default_admin_token)).strip(),
        strategy=str(config.get("strategy", "adaptive")).strip().lower(),
        request_timeout_sec=int(
            os.getenv(
                "WEBU_HUB_REQUEST_TIMEOUT_SEC",
                str(config.get("request_timeout_sec", 60)),
            )
        ),
        health_timeout_sec=int(config.get("health_timeout_sec", 10)),
        health_interval_sec=int(config.get("health_interval_sec", 30)),
        excluded_nodes=excluded_nodes,
        backends=backends,
        project_root=str(paths.root),
        config_dir=str(paths.config_dir),
    )


class GoogleHubManager:
    _AUTO_SEARCH_ATTEMPT_TIMEOUT_SEC = 18
    _SEARCH_BACKOFF_SECONDS = 45.0

    def __init__(self, settings: GoogleHubSettings):
        self.settings = settings
        self.started_ts = time.time()
        self.states = {
            backend.name: BackendRuntimeState(backend=backend)
            for backend in settings.backends
        }
        self._health_task: asyncio.Task | None = None
        self.request_metrics = RequestMetrics()

    async def start(self):
        await self.refresh_all_health(fetch_runtime_stage=False)
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
                await self.refresh_all_health(fetch_runtime_stage=False)
            finally:
                has_unhealthy = any(
                    s.backend.enabled and not s.healthy for s in self.states.values()
                )
                interval = (
                    min(10, self.settings.health_interval_sec)
                    if has_unhealthy
                    else self.settings.health_interval_sec
                )
                await asyncio.sleep(interval)

    async def refresh_all_health(self, *, fetch_runtime_stage: bool = True):
        for state in self.states.values():
            await self.refresh_backend_health(
                state.backend.name,
                fetch_runtime_stage=fetch_runtime_stage,
            )

    async def refresh_backend_health(
        self,
        backend_name: str,
        *,
        fetch_runtime_stage: bool = True,
    ) -> dict[str, Any]:
        state = self.states[backend_name]
        backend = state.backend
        if not backend.enabled:
            state.healthy = False
            state.resolved_ipv4 = ""
            state.runtime_stage = ""
            state.runtime_sleep_time = 0
            state.last_error = "backend disabled"
            state.last_checked_ts = time.time()
            return state.to_dict()

        started = time.perf_counter()
        runtime_stage_error = ""
        previous_runtime_stage = _normalize_runtime_stage(state.runtime_stage)
        should_refresh_runtime_stage = _should_refresh_runtime_stage(
            state,
            fetch_runtime_stage=fetch_runtime_stage,
        )
        try:
            if should_refresh_runtime_stage:
                try:
                    runtime_stage, sleep_time = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._get_space_runtime_state,
                            backend.space_name,
                        ),
                        timeout=min(
                            float(self.settings.health_timeout_sec),
                            HF_SPACE_RUNTIME_REFRESH_TIMEOUT_SEC,
                        ),
                    )
                    state.runtime_stage = _normalize_runtime_stage(runtime_stage)
                    state.runtime_sleep_time = int(sleep_time or 0)
                except Exception as exc:
                    runtime_stage_error = str(exc)
                    state.runtime_stage = previous_runtime_stage

                runtime_stage = _normalize_runtime_stage(state.runtime_stage)
                if runtime_stage in HF_SPACE_ERROR_STAGES:
                    state.healthy = False
                    state.resolved_ipv4 = ""
                    state.last_error = runtime_stage.lower()
                    state.latency_ms = int((time.perf_counter() - started) * 1000)
                    state.last_checked_ts = time.time()
                    state.selection_score = state.compute_selection_score()
                    return state.to_dict()
                if runtime_stage in HF_SPACE_TRANSITION_STAGES:
                    state.healthy = False
                    state.last_error = runtime_stage.lower()
                    state.latency_ms = int((time.perf_counter() - started) * 1000)
                    state.last_checked_ts = time.time()
                    state.selection_score = state.compute_selection_score()
                    return state.to_dict()
            response = await asyncio.to_thread(
                requests.get,
                f"{backend.base_url}/health",
                timeout=self.settings.health_timeout_sec,
            )
            response.raise_for_status()
            runtime_stage = _normalize_runtime_stage(state.runtime_stage)
            if backend.kind != "hf-space":
                state.healthy = True
            elif runtime_stage in HF_SPACE_RUNNING_STAGES or not runtime_stage:
                state.healthy = True
            else:
                state.healthy = False
            state.last_error = ""
            state.consecutive_failures = 0
            state.latency_ms = int((time.perf_counter() - started) * 1000)
            if backend.kind == "hf-space":
                state.resolved_ipv4 = await asyncio.to_thread(
                    _resolve_backend_ipv4, backend.base_url
                )
            else:
                state.resolved_ipv4 = ""
                state.runtime_stage = ""
                state.runtime_sleep_time = 0
        except Exception as exc:
            runtime_stage = _normalize_runtime_stage(state.runtime_stage)
            can_grace_running = (
                backend.kind == "hf-space"
                and (
                    runtime_stage in HF_SPACE_RUNNING_STAGES
                    or (not runtime_stage and state.healthy)
                )
                and state.consecutive_failures < 1
            )
            state.healthy = can_grace_running
            state.resolved_ipv4 = ""
            state.last_error = runtime_stage_error or str(exc)
            state.consecutive_failures += 1
            state.last_failure_ts = time.time()
            state.latency_ms = int((time.perf_counter() - started) * 1000)
        state.last_checked_ts = time.time()
        state.selection_score = state.compute_selection_score()
        return state.to_dict()

    def _resolve_hf_control_endpoints(self) -> list[str]:
        endpoints: list[str] = []
        for raw_endpoint in [
            os.getenv("WEBU_HF_CONTROL_ENDPOINT", ""),
            os.getenv("HF_ENDPOINT", ""),
            "https://hf-mirror.com",
            "https://huggingface.co",
        ]:
            endpoint = str(raw_endpoint or "").strip().rstrip("/")
            if endpoint and endpoint not in endpoints:
                endpoints.append(endpoint)
        return endpoints

    def _build_hf_api(self, *, token: str, endpoint: str) -> HfApi:
        try:
            return HfApi(token=token, endpoint=endpoint)
        except TypeError:
            return HfApi(token=token)

    def _resolve_hf_api(self, space_name: str) -> tuple[HfApi, Any]:
        settings = resolve_hf_space_settings(space_name)
        if not settings.hf_token:
            raise RuntimeError(f"HF token not configured for {space_name}")
        endpoint = self._resolve_hf_control_endpoints()[0]
        return self._build_hf_api(token=settings.hf_token, endpoint=endpoint), settings

    def _iter_hf_apis(self, space_name: str) -> list[tuple[HfApi, Any, str]]:
        settings = resolve_hf_space_settings(space_name)
        if not settings.hf_token:
            raise RuntimeError(f"HF token not configured for {space_name}")
        return [
            (
                self._build_hf_api(token=settings.hf_token, endpoint=endpoint),
                settings,
                endpoint,
            )
            for endpoint in self._resolve_hf_control_endpoints()
        ]

    def _get_space_runtime_state(self, space_name: str) -> tuple[str, int]:
        last_error: Exception | None = None
        for api, settings, _endpoint in self._iter_hf_apis(space_name):
            try:
                runtime = api.get_space_runtime(
                    settings.repo_id, token=settings.hf_token
                )
                stage = (
                    str(
                        getattr(
                            getattr(runtime, "stage", ""),
                            "value",
                            getattr(runtime, "stage", ""),
                        )
                        or ""
                    )
                    .strip()
                    .upper()
                )
                sleep_time = int(getattr(runtime, "sleep_time", 0) or 0)
                return stage, sleep_time
            except Exception as exc:
                last_error = exc
        raise RuntimeError(sanitize_hf_control_error(str(last_error or "")))

    def _run_hf_space_action(
        self, state: BackendRuntimeState, action: str
    ) -> dict[str, Any]:
        if state.backend.kind != "hf-space" or not state.backend.space_name:
            raise RuntimeError(
                f"backend '{state.backend.name}' does not support HF controls"
            )

        action_name = str(action or "").strip().lower()
        last_error: Exception | None = None
        for api, settings, _endpoint in self._iter_hf_apis(state.backend.space_name):
            try:
                repo_id = settings.repo_id
                runtime = None
                performed = action_name

                if action_name in {"toggle", "start", "stop"}:
                    stage, sleep_time = self._get_space_runtime_state(
                        state.backend.space_name
                    )
                    state.runtime_stage = stage
                    state.runtime_sleep_time = sleep_time
                    if action_name == "start":
                        if stage in {"PAUSED", "STOPPED"}:
                            runtime = api.restart_space(
                                repo_id, token=settings.hf_token, factory_reboot=False
                            )
                    elif action_name == "stop":
                        if stage not in {"PAUSED", "STOPPED"}:
                            runtime = api.pause_space(repo_id, token=settings.hf_token)
                    elif stage in {"PAUSED", "STOPPED"}:
                        runtime = api.restart_space(
                            repo_id, token=settings.hf_token, factory_reboot=False
                        )
                        performed = "start"
                    else:
                        runtime = api.pause_space(repo_id, token=settings.hf_token)
                        performed = "stop"
                elif action_name == "restart":
                    runtime = api.restart_space(
                        repo_id, token=settings.hf_token, factory_reboot=False
                    )
                elif action_name == "rebuild":
                    runtime = api.restart_space(
                        repo_id, token=settings.hf_token, factory_reboot=True
                    )
                elif action_name == "squash":
                    api.super_squash_history(
                        repo_id,
                        branch="main",
                        commit_message="Hub squash history",
                        repo_type="space",
                        token=settings.hf_token,
                    )
                else:
                    raise RuntimeError(f"unsupported control action: {action}")

                if runtime is not None:
                    state.runtime_stage = (
                        str(
                            getattr(
                                getattr(runtime, "stage", ""),
                                "value",
                                getattr(runtime, "stage", ""),
                            )
                            or ""
                        )
                        .strip()
                        .upper()
                    )
                    state.runtime_sleep_time = int(
                        getattr(runtime, "sleep_time", 0) or 0
                    )
                return {
                    "backend": state.backend.name,
                    "space_name": state.backend.space_name,
                    "action": performed,
                    "runtime_stage": state.runtime_stage,
                    "runtime_sleep_time": state.runtime_sleep_time,
                }
            except Exception as exc:
                last_error = exc
        raise RuntimeError(sanitize_hf_control_error(str(last_error or "")))

    async def control_backend(self, backend_name: str, action: str) -> dict[str, Any]:
        state = self.states.get(str(backend_name or "").strip())
        if not state:
            raise RuntimeError(f"backend '{backend_name}' not found")
        result = await asyncio.to_thread(self._run_hf_space_action, state, action)
        refreshed = await self.refresh_backend_health(state.backend.name)
        if str(result.get("runtime_stage", "")).strip():
            refreshed["runtime_stage"] = str(result.get("runtime_stage", "")).strip()
            refreshed["runtime_sleep_time"] = int(
                result.get("runtime_sleep_time", 0) or 0
            )
        return {
            **result,
            "message": f"{result['action']} requested for {result['backend']}",
            "snapshot": refreshed,
        }

    async def control_all_backends(self, action: str) -> dict[str, Any]:
        action_name = str(action or "").strip().lower()
        targets = [
            state.backend.name
            for state in self.states.values()
            if state.backend.kind == "hf-space"
            and state.backend.space_name
            and (
                action_name not in {"restart-bad", "rebuild-bad"}
                or not _classify_backend_status(state)[2]
            )
        ]
        results = []
        backend_action = action_name.replace("-bad", "")
        for backend_name in targets:
            results.append(await self.control_backend(backend_name, backend_action))
        target_label = (
            "non-running HF space(s)"
            if action_name in {"restart-bad", "rebuild-bad"}
            else "HF space(s)"
        )
        return {
            "action": action_name,
            "count": len(results),
            "results": results,
            "message": f"{action_name} requested for {len(results)} {target_label}",
        }

    def _eligible_states(self) -> list[BackendRuntimeState]:
        ready_healthy_states = [
            state
            for state in self.states.values()
            if state.backend.enabled
            and state.healthy
            and not self._is_search_cooling_down(state)
        ]
        if ready_healthy_states:
            return ready_healthy_states
        healthy_states = [
            state
            for state in self.states.values()
            if state.backend.enabled and state.healthy
        ]
        if healthy_states:
            return healthy_states
        return [state for state in self.states.values() if state.backend.enabled]

    def _is_search_cooling_down(self, state: BackendRuntimeState) -> bool:
        return state.search_cooldown_until_ts > time.time()

    def _mark_search_backoff(
        self,
        state: BackendRuntimeState,
        *,
        error: str,
        duration_ms: float,
        attempt_timeout_sec: float,
    ):
        lowered_error = str(error or "").strip().lower()
        timed_out = "timed out" in lowered_error or "timeout" in lowered_error
        captcha_related = "captcha" in lowered_error
        ran_too_long = duration_ms >= max(1.0, attempt_timeout_sec * 1000.0 * 0.92)
        if timed_out or captcha_related or ran_too_long:
            state.search_cooldown_until_ts = max(
                state.search_cooldown_until_ts,
                time.time() + self._SEARCH_BACKOFF_SECONDS,
            )

    def _summarize_backend_failure(self, error: str) -> str:
        lowered_error = str(error or "").strip().lower()
        if not lowered_error:
            return "failed"
        if "temporarily cooling down" in lowered_error:
            return "cooling down"
        if "timed out" in lowered_error or "timeout" in lowered_error:
            return "timeout"
        if "captcha" in lowered_error:
            return "captcha blocked"
        if "not healthy" in lowered_error:
            return "not healthy"
        if "disabled" in lowered_error:
            return "disabled"
        if "http " in lowered_error:
            return "http error"
        compact = str(error).strip().splitlines()[0]
        return compact[:96]

    def _format_auto_search_failure(self, failures: list[tuple[str, str]]) -> str:
        if not failures:
            return "hub search failed: no backend responded"
        parts = [
            f"{name} {self._summarize_backend_failure(error)}"
            for name, error in failures[:4]
        ]
        detail = "; ".join(parts)
        remaining = len(failures) - len(parts)
        if remaining > 0:
            detail = f"{detail}; +{remaining} more"
        return (
            f"hub search failed across {len(failures)} backend(s): {detail}. "
            f"Try again or pin another healthy instance."
        )

    def _state_rank(self, state: BackendRuntimeState) -> tuple:
        strategy = (self.settings.strategy or "adaptive").strip().lower()
        cooldown_penalty = 1 if self._is_search_cooling_down(state) else 0
        if strategy == "least-inflight":
            return (
                cooldown_penalty,
                state.inflight / max(1, state.backend.weight),
                state.consecutive_failures,
                state.last_selected_ts,
                state.latency_ms,
                state.backend.name,
            )

        score = state.compute_selection_score()
        return (
            cooldown_penalty,
            score,
            state.inflight / max(1, state.backend.weight),
            state.consecutive_failures,
            state.last_selected_ts,
            state.backend.name,
        )

    def _resolve_requested_backend(self, backend_name: str) -> BackendRuntimeState:
        requested_name = str(backend_name or "").strip()
        if not requested_name:
            raise RuntimeError("backend name is required")
        state = self.states.get(requested_name)
        if not state:
            raise RuntimeError(f"backend '{requested_name}' not found")
        if not state.backend.enabled:
            raise RuntimeError(f"backend '{requested_name}' is disabled")
        if not state.healthy:
            raise RuntimeError(f"backend '{requested_name}' is not healthy")
        if self._is_search_cooling_down(state):
            raise RuntimeError(
                f"backend '{requested_name}' is temporarily cooling down after recent search failures"
            )
        return state

    def choose_backend(self, backend_name: str = "") -> BackendRuntimeState:
        requested_name = str(backend_name or "").strip()
        if requested_name:
            state = self._resolve_requested_backend(requested_name)
            state.last_selected_ts = time.time()
            state.selection_score = state.compute_selection_score()
            return state

        candidates = self._eligible_states()
        if not candidates:
            raise RuntimeError("no enabled hub backends configured")
        candidates.sort(key=self._state_rank)
        selected = candidates[0]
        selected.last_selected_ts = time.time()
        selected.selection_score = selected.compute_selection_score()
        return selected

    def ordered_backends(self, backend_name: str = "") -> list[BackendRuntimeState]:
        requested_name = str(backend_name or "").strip()
        if requested_name:
            return [self._resolve_requested_backend(requested_name)]

        candidates = self._eligible_states()
        if not candidates:
            return []
        return sorted(candidates, key=self._state_rank)

    async def search(
        self,
        *,
        query: str,
        num: int,
        lang: str,
        backend_name: str = "",
    ) -> dict[str, Any]:
        requested_name = str(backend_name or "").strip()
        ordered = self.ordered_backends(requested_name)
        if not ordered:
            raise RuntimeError("no hub backends available")

        overall_started = time.perf_counter()
        last_error = None
        last_backend_name = ""
        failures: list[tuple[str, str]] = []
        attempt_timeout_sec = float(self.settings.request_timeout_sec)
        if not requested_name and len(ordered) > 1:
            attempt_timeout_sec = min(
                attempt_timeout_sec,
                float(self._AUTO_SEARCH_ATTEMPT_TIMEOUT_SEC),
            )
        for state in ordered:
            state.last_selected_ts = time.time()
            last_backend_name = state.backend.name
            state.inflight += 1
            started = time.perf_counter()
            try:
                headers = {}
                if state.backend.search_api_token:
                    headers["X-Api-Token"] = state.backend.search_api_token
                response = await asyncio.to_thread(
                    requests.get,
                    f"{state.backend.base_url}/search",
                    params={"q": query, "num": num, "lang": lang},
                    headers=headers or None,
                    timeout=attempt_timeout_sec,
                )
                response.raise_for_status()
                payload = response.json()
                if not bool(payload.get("success", True)):
                    raise RuntimeError(
                        str(payload.get("error", "backend search failed")).strip()
                        or "backend search failed"
                    )
                total_duration_ms = (time.perf_counter() - overall_started) * 1000.0
                state.total_successes += 1
                state.healthy = True
                state.search_cooldown_until_ts = 0.0
                state.last_error = ""
                state.record_request(total_duration_ms, True)
                self.request_metrics.record(
                    total_duration_ms,
                    True,
                    query=query,
                    backend=state.backend.name,
                    response_payload=payload,
                )
                return {
                    "backend": state.backend.name,
                    "backend_kind": state.backend.kind,
                    "backend_url": state.backend.base_url,
                    "requested_backend": requested_name,
                    "selection_mode": "manual" if requested_name else "auto",
                    **payload,
                    "latency_ms": round(total_duration_ms, 1),
                }
            except Exception as exc:
                last_error = exc
                duration_ms = (time.perf_counter() - started) * 1000.0
                state.total_failures += 1
                state.last_error = str(exc)
                failures.append((state.backend.name, state.last_error))
                self._mark_search_backoff(
                    state,
                    error=state.last_error,
                    duration_ms=duration_ms,
                    attempt_timeout_sec=attempt_timeout_sec,
                )
                state.record_request(duration_ms, False)
            finally:
                state.inflight = max(0, state.inflight - 1)

        final_error = str(last_error) if last_error else ""
        if requested_name:
            final_error = (
                f"backend '{requested_name}' failed: "
                f"{self._summarize_backend_failure(final_error)}"
            )
        else:
            final_error = self._format_auto_search_failure(failures)
        final_error = sanitize_hub_search_error(final_error)

        self.request_metrics.record(
            (time.perf_counter() - overall_started) * 1000.0,
            False,
            query=query,
            backend=last_backend_name,
            error=final_error,
            response_payload={
                "success": False,
                "error": final_error,
            },
        )
        raise RuntimeError(final_error)

    async def backend_snapshot(self) -> list[dict[str, Any]]:
        return [state.to_dict() for state in self.states.values()]

    async def metrics(self) -> dict[str, Any]:
        states = await self.backend_snapshot()
        return {
            "strategy": self.settings.strategy,
            "started_ts": self.started_ts,
            "healthy_backends": sum(1 for item in states if item["healthy"]),
            "enabled_backends": sum(1 for item in states if item["enabled"]),
            "excluded_nodes": list(self.settings.excluded_nodes),
            "request_stats": self.request_metrics.snapshot().to_dict(),
            "backends": states,
        }
