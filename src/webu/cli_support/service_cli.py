from __future__ import annotations

import time

from dataclasses import dataclass
from pathlib import Path

from webu.cli_support.local_service import (
    LocalServiceSpec,
    is_process_running,
    read_pid,
    read_service_log,
    remove_pid,
    start_service,
    stop_service,
    tail_service_log,
)


@dataclass(frozen=True)
class ManagedServiceSpec:
    name: str
    service: LocalServiceSpec
    default_host: str | None = None
    default_port: int | None = None


class LocalServiceManager:
    def __init__(self, spec: ManagedServiceSpec):
        self.spec = spec

    @property
    def pid_file(self) -> Path:
        return self.spec.service.pid_file

    @property
    def log_file(self) -> Path:
        return self.spec.service.log_file

    def read_pid(self) -> int | None:
        return read_pid(self.pid_file)

    def is_running(self) -> bool:
        pid = self.read_pid()
        return bool(pid and is_process_running(pid))

    def start(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> dict:
        pid = self.read_pid()
        if pid and is_process_running(pid):
            return {"status": "already_running", "pid": pid}

        resolved_host = host or self.spec.default_host
        resolved_port = int(port or self.spec.default_port or 0)
        pid = start_service(
            self.spec.service,
            host=resolved_host,
            port=resolved_port,
            extra_env=extra_env,
        )
        return {
            "status": "started",
            "pid": pid,
            "host": resolved_host,
            "port": resolved_port,
            "log_file": str(self.log_file),
        }

    def stop(self) -> dict:
        pid = self.read_pid()
        if not pid:
            return {"status": "not_running", "pid": None}
        if not is_process_running(pid):
            remove_pid(self.pid_file)
            return {"status": "stale_pid", "pid": pid}

        stopped, _ = stop_service(self.spec.service)
        return {
            "status": "stopped" if stopped else "not_running",
            "pid": pid,
        }

    def restart(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        extra_env: dict[str, str] | None = None,
        delay_seconds: float = 1.0,
    ) -> dict:
        stop_result = self.stop()
        time.sleep(max(0.0, float(delay_seconds)))
        start_result = self.start(host=host, port=port, extra_env=extra_env)
        return {"stop": stop_result, "start": start_result}

    def status(self) -> dict:
        pid = self.read_pid()
        if not pid:
            return {
                "status": "not_running",
                "pid": None,
                "log_file": str(self.log_file),
            }
        if is_process_running(pid):
            return {
                "status": "running",
                "pid": pid,
                "log_file": str(self.log_file),
            }

        remove_pid(self.pid_file)
        return {
            "status": "dead",
            "pid": pid,
            "log_file": str(self.log_file),
        }

    def read_logs(self, *, lines: int = 50) -> str:
        return read_service_log(self.log_file, lines=lines)

    def tail_logs(self):
        tail_service_log(self.log_file)
