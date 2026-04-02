from __future__ import annotations

import os
import signal
import subprocess

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PreparedCommand:
    argv: list[str]
    stdin_data: bytes | None


def _sudo_password() -> str:
    return os.environ.get("SUDOPASS", "")


def has_password() -> bool:
    return bool(_sudo_password())


def build_command(
    command: list[str],
    *,
    use_sudo: bool = True,
    preserve_env: dict[str, str] | None = None,
) -> PreparedCommand:
    if not use_sudo or os.geteuid() == 0:
        return PreparedCommand(argv=list(command), stdin_data=None)

    sudo_password = _sudo_password()
    argv = ["sudo"] + (["-S"] if sudo_password else [])
    if preserve_env:
        argv += ["env"] + [f"{key}={value}" for key, value in preserve_env.items()]
    argv += list(command)
    stdin_data = (sudo_password + "\n").encode() if sudo_password else None
    return PreparedCommand(argv=argv, stdin_data=stdin_data)


def _merge_input(
    stdin_data: bytes | None,
    user_input: Any,
    *,
    text_mode: bool = False,
) -> bytes | str | None:
    if stdin_data is None:
        merged_input = user_input
    elif user_input is None:
        merged_input = stdin_data
    elif isinstance(user_input, str):
        merged_input = stdin_data + user_input.encode()
    else:
        merged_input = stdin_data + user_input

    if text_mode and isinstance(merged_input, (bytes, bytearray)):
        return merged_input.decode()
    return merged_input


def run(
    command: list[str],
    *,
    use_sudo: bool = True,
    preserve_env: dict[str, str] | None = None,
    check: bool = False,
    timeout: int | float | None = None,
    capture_output: bool = True,
    text: bool = False,
    input: Any = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    prepared = build_command(command, use_sudo=use_sudo, preserve_env=preserve_env)
    return subprocess.run(
        prepared.argv,
        input=_merge_input(prepared.stdin_data, input, text_mode=text),
        check=check,
        timeout=timeout,
        capture_output=capture_output,
        text=text,
        **kwargs,
    )


def popen(
    command: list[str],
    *,
    use_sudo: bool = True,
    preserve_env: dict[str, str] | None = None,
    **kwargs: Any,
) -> subprocess.Popen:
    prepared = build_command(command, use_sudo=use_sudo, preserve_env=preserve_env)
    stdin = kwargs.get("stdin")
    if stdin is None and prepared.stdin_data is not None:
        kwargs["stdin"] = subprocess.PIPE
    proc = subprocess.Popen(prepared.argv, **kwargs)
    if prepared.stdin_data and proc.stdin is not None:
        try:
            proc.stdin.write(prepared.stdin_data)
            proc.stdin.flush()
            proc.stdin.close()
        except Exception:
            pass
    return proc


def signal_process(pid: int, sig: int, *, process_group: bool = False) -> None:
    target = -pid if process_group else pid
    try:
        os.kill(target, sig)
        return
    except ProcessLookupError:
        return
    except PermissionError:
        pass

    command = ["kill", f"-{sig}"]
    if process_group:
        command += ["--", f"-{pid}"]
    else:
        command.append(str(pid))
    run(command, check=False)
