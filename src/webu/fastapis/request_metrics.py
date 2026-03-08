from __future__ import annotations

import json
import platform
import socket
import statistics

from collections import deque
from typing import Any
from datetime import datetime
from dataclasses import dataclass
from threading import Lock
from zoneinfo import ZoneInfo


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def format_dashboard_timestamp(ts: float | None = None) -> str:
    if ts is None:
        dt = datetime.now(tz=SHANGHAI_TZ)
    else:
        dt = datetime.fromtimestamp(float(ts), tz=SHANGHAI_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_dashboard_timezone() -> str:
    return "UTC+08 Shanghai"


def format_dashboard_time_label(ts: float | None = None) -> str:
    if ts is None:
        dt = datetime.now(tz=SHANGHAI_TZ)
    else:
        dt = datetime.fromtimestamp(float(ts), tz=SHANGHAI_TZ)
    return dt.strftime("%H:%M")


def format_dashboard_log_label(ts: float | None = None) -> str:
    if ts is None:
        dt = datetime.now(tz=SHANGHAI_TZ)
    else:
        dt = datetime.fromtimestamp(float(ts), tz=SHANGHAI_TZ)
    return dt.strftime("%H:%M:%S")


def format_uptime_human(started_ts: float | None, now_ts: float | None = None) -> str:
    if not started_ts:
        return "0s"

    now_ts = float(now_ts or datetime.now(tz=SHANGHAI_TZ).timestamp())
    elapsed = max(0, int(now_ts - float(started_ts)))
    days, rem = divmod(elapsed, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or parts:
        parts.append(f"{hours}h")
    if minutes or parts:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def _truncate_text(value: str, *, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _serialize_response_payload(response_payload: dict[str, Any] | None) -> str:
    if not isinstance(response_payload, dict) or not response_payload:
        return ""
    try:
        return json.dumps(response_payload, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(response_payload)


def _build_result_preview(response_payload: dict[str, Any] | None) -> str:
    if not isinstance(response_payload, dict):
        return ""

    results = response_payload.get("results")
    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, dict):
            title = _truncate_text(str(first.get("title", "")).strip(), limit=72)
            snippet = _truncate_text(str(first.get("snippet", "")).strip(), limit=100)
            displayed_url = _truncate_text(
                str(first.get("displayed_url", first.get("url", "")).strip()),
                limit=56,
            )
            parts = [part for part in [title, snippet, displayed_url] if part]
            if parts:
                return " | ".join(parts)

    error = _truncate_text(str(response_payload.get("error", "")).strip(), limit=120)
    if error:
        return error

    total_results_text = _truncate_text(
        str(response_payload.get("total_results_text", "")).strip(), limit=80
    )
    if total_results_text:
        return total_results_text

    result_count = int(response_payload.get("result_count", 0) or 0)
    if result_count > 0:
        return f"{result_count} results"
    return ""


@dataclass(frozen=True)
class RequestRecord:
    ts: float
    ts_label: str
    success: bool
    latency_ms: float
    query: str = ""
    backend: str = ""
    error: str = ""
    result_preview: str = ""
    result_detail: str = ""

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "ts_label": self.ts_label,
            "success": self.success,
            "latency_ms": round(self.latency_ms, 1),
            "query": self.query,
            "backend": self.backend,
            "error": self.error,
            "result_preview": self.result_preview,
            "result_detail": self.result_detail,
        }


@dataclass(frozen=True)
class RequestMetricsSnapshot:
    accepted_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    median_latency_ms: float = 0.0
    recent_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    last_latency_ms: float = 0.0
    history: list[dict] | None = None
    request_log: list[dict] | None = None

    def to_dict(self) -> dict:
        return {
            "accepted_requests": self.accepted_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "median_latency_ms": self.median_latency_ms,
            "recent_latency_ms": self.recent_latency_ms,
            "min_latency_ms": self.min_latency_ms,
            "max_latency_ms": self.max_latency_ms,
            "last_latency_ms": self.last_latency_ms,
            "history": list(self.history or []),
            "request_log": list(self.request_log or []),
        }


@dataclass
class RequestWindow:
    start_ts: float
    label: str
    accepted_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    recent_latency_ms: float = 0.0
    latency_samples: list[float] | None = None

    def __post_init__(self):
        if self.latency_samples is None:
            self.latency_samples = []

    def record(self, latency_ms: float, success: bool):
        self.accepted_requests += 1
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
        self.total_latency_ms += latency_ms
        self.recent_latency_ms = latency_ms
        self.latency_samples.append(latency_ms)
        if self.min_latency_ms <= 0:
            self.min_latency_ms = latency_ms
        else:
            self.min_latency_ms = min(self.min_latency_ms, latency_ms)
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)

    def to_dict(self) -> dict:
        success_rate = (
            (self.successful_requests / self.accepted_requests * 100.0)
            if self.accepted_requests
            else 0.0
        )
        avg_latency_ms = (
            (self.total_latency_ms / self.accepted_requests)
            if self.accepted_requests
            else 0.0
        )
        median_latency_ms = (
            float(statistics.median(self.latency_samples))
            if self.latency_samples
            else 0.0
        )
        return {
            "ts": self.start_ts,
            "label": self.label,
            "accepted_requests": self.accepted_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": success_rate,
            "avg_latency_ms": avg_latency_ms,
            "median_latency_ms": median_latency_ms,
            "recent_latency_ms": self.recent_latency_ms,
            "min_latency_ms": self.min_latency_ms,
            "max_latency_ms": self.max_latency_ms,
            "last_latency_ms": self.recent_latency_ms,
            "window_seconds": 60,
        }


class RequestMetrics:
    def __init__(
        self,
        history_limit: int = 60,
        *,
        window_seconds: int = 60,
        recent_latency_limit: int = 32,
    ):
        self._lock = Lock()
        self._accepted_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        self._total_latency_ms = 0.0
        self._min_latency_ms: float | None = None
        self._max_latency_ms: float = 0.0
        self._last_latency_ms: float = 0.0
        self._window_seconds = max(1, int(window_seconds))
        self._history: deque[RequestWindow] = deque(maxlen=max(8, int(history_limit)))
        self._request_log: deque[RequestRecord] = deque(maxlen=50)
        self._recent_latencies: deque[float] = deque(
            maxlen=max(8, int(recent_latency_limit))
        )
        self._advance_windows_locked(datetime.now(tz=SHANGHAI_TZ).timestamp())

    def _window_start(self, sample_ts: float) -> float:
        return float(int(sample_ts // self._window_seconds) * self._window_seconds)

    def _append_window_locked(self, start_ts: float):
        self._history.append(
            RequestWindow(
                start_ts=start_ts,
                label=format_dashboard_time_label(start_ts),
            )
        )

    def _advance_windows_locked(self, sample_ts: float):
        target_start_ts = self._window_start(float(sample_ts))
        if not self._history:
            self._append_window_locked(target_start_ts)
            return

        current_start_ts = self._history[-1].start_ts
        if target_start_ts <= current_start_ts:
            return

        while current_start_ts < target_start_ts:
            current_start_ts += self._window_seconds
            self._append_window_locked(current_start_ts)

    def record(
        self,
        duration_ms: float,
        success: bool,
        *,
        query: str = "",
        backend: str = "",
        error: str = "",
        response_payload: dict[str, Any] | None = None,
        sample_ts: float | None = None,
    ):
        latency_ms = max(0.0, float(duration_ms))
        sample_ts = float(sample_ts or datetime.now(tz=SHANGHAI_TZ).timestamp())
        now = datetime.fromtimestamp(sample_ts, tz=SHANGHAI_TZ)
        result_preview = _build_result_preview(response_payload)
        result_detail = _serialize_response_payload(response_payload)
        with self._lock:
            self._advance_windows_locked(sample_ts)
            self._accepted_requests += 1
            if success:
                self._successful_requests += 1
            else:
                self._failed_requests += 1
            self._total_latency_ms += latency_ms
            self._last_latency_ms = latency_ms
            self._recent_latencies.append(latency_ms)
            if self._min_latency_ms is None:
                self._min_latency_ms = latency_ms
            else:
                self._min_latency_ms = min(self._min_latency_ms, latency_ms)
            self._max_latency_ms = max(self._max_latency_ms, latency_ms)
            self._history[-1].record(latency_ms, success)
            self._request_log.append(
                RequestRecord(
                    ts=now.timestamp(),
                    ts_label=format_dashboard_log_label(now.timestamp()),
                    success=success,
                    latency_ms=latency_ms,
                    query=query,
                    backend=backend,
                    error=error,
                    result_preview=result_preview,
                    result_detail=result_detail,
                )
            )

    def snapshot(self) -> RequestMetricsSnapshot:
        with self._lock:
            accepted_requests = self._accepted_requests
            successful_requests = self._successful_requests
            failed_requests = self._failed_requests
            avg_latency_ms = (
                self._total_latency_ms / accepted_requests if accepted_requests else 0.0
            )
            success_rate = (
                (successful_requests / accepted_requests * 100.0)
                if accepted_requests
                else 0.0
            )
            median_latency_ms = (
                float(statistics.median(self._recent_latencies))
                if self._recent_latencies
                else 0.0
            )
            return RequestMetricsSnapshot(
                accepted_requests=accepted_requests,
                successful_requests=successful_requests,
                failed_requests=failed_requests,
                success_rate=success_rate,
                avg_latency_ms=avg_latency_ms,
                median_latency_ms=median_latency_ms,
                recent_latency_ms=self._last_latency_ms,
                min_latency_ms=self._min_latency_ms or 0.0,
                max_latency_ms=self._max_latency_ms,
                last_latency_ms=self._last_latency_ms,
                history=[window.to_dict() for window in self._history],
                request_log=[r.to_dict() for r in self._request_log],
            )


def resolve_server_identity(runtime_env: str) -> dict[str, str]:
    hostname = platform.node() or socket.gethostname() or "unknown-host"
    if runtime_env == "local":
        return {
            "label": "Host name",
            "value": hostname,
        }

    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(
            hostname, None, family=socket.AF_INET, type=socket.SOCK_STREAM
        ):
            address = str(info[4][0]).strip()
            if address and not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass

    return {
        "label": "Server IP",
        "value": ", ".join(sorted(addresses)) or hostname,
    }
