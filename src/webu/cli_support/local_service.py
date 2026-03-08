from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LocalServiceSpec:
    name: str
    uvicorn_target: str
    pid_file: Path
    log_file: Path


def _ensure_parent_dir(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def read_pid(pid_file: Path) -> int | None:
    try:
        if pid_file.exists():
            return int(pid_file.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        pass
    return None


def write_pid(pid_file: Path, pid: int):
    _ensure_parent_dir(pid_file)
    pid_file.write_text(str(pid), encoding="utf-8")


def remove_pid(pid_file: Path):
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass


def is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def start_service(
    spec: LocalServiceSpec,
    *,
    host: str,
    port: int,
    extra_env: dict[str, str] | None = None,
) -> int:
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        spec.uvicorn_target,
        "--host",
        str(host),
        "--port",
        str(port),
        "--factory",
    ]
    _ensure_parent_dir(spec.log_file)
    log_fp = open(spec.log_file, "a", encoding="utf-8")
    env = dict(os.environ)
    env.update({key: str(value) for key, value in (extra_env or {}).items()})
    proc = subprocess.Popen(
        command,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
    write_pid(spec.pid_file, proc.pid)
    return proc.pid


def stop_service(
    spec: LocalServiceSpec, *, wait_seconds: float = 15.0
) -> tuple[bool, int | None]:
    pid = read_pid(spec.pid_file)
    if not pid:
        return False, None

    if not is_process_running(pid):
        remove_pid(spec.pid_file)
        return False, pid

    try:
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + max(1.0, float(wait_seconds))
        while time.time() < deadline:
            if not is_process_running(pid):
                remove_pid(spec.pid_file)
                return True, pid
            time.sleep(0.5)
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    remove_pid(spec.pid_file)
    return True, pid


def read_service_log(log_file: Path, *, lines: int = 50) -> str:
    if not log_file.exists():
        return ""
    with open(log_file, "r", encoding="utf-8", errors="replace") as fp:
        return "".join(fp.readlines()[-max(1, int(lines)) :])


def tail_service_log(log_file: Path):
    os.execvp("tail", ["tail", "-f", str(log_file)])
