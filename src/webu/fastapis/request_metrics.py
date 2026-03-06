from __future__ import annotations

import platform
import socket

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class RequestMetricsSnapshot:
    accepted_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    last_latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "accepted_requests": self.accepted_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "min_latency_ms": self.min_latency_ms,
            "max_latency_ms": self.max_latency_ms,
            "last_latency_ms": self.last_latency_ms,
        }


class RequestMetrics:
    def __init__(self):
        self._lock = Lock()
        self._accepted_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        self._total_latency_ms = 0.0
        self._min_latency_ms: float | None = None
        self._max_latency_ms: float = 0.0
        self._last_latency_ms: float = 0.0

    def record(self, duration_ms: float, success: bool):
        latency_ms = max(0.0, float(duration_ms))
        with self._lock:
            self._accepted_requests += 1
            if success:
                self._successful_requests += 1
            else:
                self._failed_requests += 1
            self._total_latency_ms += latency_ms
            self._last_latency_ms = latency_ms
            if self._min_latency_ms is None:
                self._min_latency_ms = latency_ms
            else:
                self._min_latency_ms = min(self._min_latency_ms, latency_ms)
            self._max_latency_ms = max(self._max_latency_ms, latency_ms)

    def snapshot(self) -> RequestMetricsSnapshot:
        with self._lock:
            accepted_requests = self._accepted_requests
            successful_requests = self._successful_requests
            failed_requests = self._failed_requests
            avg_latency_ms = self._total_latency_ms / accepted_requests if accepted_requests else 0.0
            success_rate = (successful_requests / accepted_requests * 100.0) if accepted_requests else 0.0
            return RequestMetricsSnapshot(
                accepted_requests=accepted_requests,
                successful_requests=successful_requests,
                failed_requests=failed_requests,
                success_rate=success_rate,
                avg_latency_ms=avg_latency_ms,
                min_latency_ms=self._min_latency_ms or 0.0,
                max_latency_ms=self._max_latency_ms,
                last_latency_ms=self._last_latency_ms,
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
        for info in socket.getaddrinfo(hostname, None, family=socket.AF_INET, type=socket.SOCK_STREAM):
            address = str(info[4][0]).strip()
            if address and not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass

    return {
        "label": "Server IP",
        "value": ", ".join(sorted(addresses)) or hostname,
    }