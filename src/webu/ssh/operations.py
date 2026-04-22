from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import tempfile

from pathlib import Path
from typing import Any

from webu.schema import (
    find_project_root,
    render_template_json,
    validate_payload_against_schema,
)
from webu.sudo import run as sudo_run

from .schema import (
    DEFAULT_SERVER_ALIVE_COUNT_MAX,
    DEFAULT_SERVER_ALIVE_INTERVAL_SECONDS,
    DEFAULT_SSH_PORT,
    DEFAULT_TUNNEL_LOCAL_HOST,
    DEFAULT_TUNNEL_MODE,
    DEFAULT_TUNNEL_REMOTE_HOST,
    SSH_CONFIG,
    SshHostConfig,
    SshTunnelConfig,
    find_host,
    find_tunnel,
    list_hosts,
    list_tunnels,
    load_ssh_config,
    normalize_tunnel_mode,
    save_ssh_config,
    upsert_host,
    upsert_tunnel,
)


DEFAULT_SSH_EXEC_TIMEOUT_SECONDS = 60
SSH_TUNNEL_SERVICE_PREFIX = "webu-ssh-tunnel"


def _require_text(value: object, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


def _safe_systemd_token(value: str) -> str:
    safe = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return safe or "default"


def _project_root() -> Path:
    return Path(find_project_root()).expanduser().resolve()


def _resolve_path(raw_value: str, *, default: Path | None = None) -> Path:
    candidate = (
        Path(raw_value).expanduser() if str(raw_value or "").strip() else default
    )
    if candidate is None:
        raise ValueError("path is required")
    if candidate.is_absolute():
        return candidate.resolve()
    return (_project_root() / candidate).resolve()


def _resolve_host(payload: dict[str, Any], host_name: str) -> SshHostConfig:
    host = find_host(payload, host_name)
    if host is None:
        raise ValueError(f"ssh host '{host_name}' not found in configs/ssh.json")
    return host


def _resolve_tunnel(
    payload: dict[str, Any], tunnel_name: str
) -> tuple[SshTunnelConfig, SshHostConfig]:
    tunnel = find_tunnel(payload, tunnel_name)
    if tunnel is None:
        raise ValueError(f"ssh tunnel '{tunnel_name}' not found in configs/ssh.json")
    host = _resolve_host(payload, tunnel.host_name)
    return tunnel, host


def _resolved_host_address(host: SshHostConfig) -> str:
    candidate = str(host.hostname or host.ip or "").strip()
    if candidate:
        return candidate
    raise ValueError(f"ssh host '{host.name}' must define hostname or ip")


def _ssh_connection_target(host: SshHostConfig) -> str:
    return f"{host.username}@{_resolved_host_address(host)}"


def _ssh_base_parts(
    host: SshHostConfig,
    *,
    allocate_tty: bool = False,
    exit_on_forward_failure: bool = False,
    server_alive_interval_seconds: int = DEFAULT_SERVER_ALIVE_INTERVAL_SECONDS,
    server_alive_count_max: int = DEFAULT_SERVER_ALIVE_COUNT_MAX,
) -> list[str]:
    parts = [shutil.which("ssh") or "ssh"]
    if host.port and int(host.port) != DEFAULT_SSH_PORT:
        parts.extend(["-p", str(host.port)])
    if host.identity_file:
        parts.extend(["-i", host.identity_file])
    if allocate_tty:
        parts.append("-tt")
    parts.extend(
        [
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            f"ServerAliveInterval={max(1, int(server_alive_interval_seconds))}",
            "-o",
            f"ServerAliveCountMax={max(1, int(server_alive_count_max))}",
        ]
    )
    if exit_on_forward_failure:
        parts.extend(["-o", "ExitOnForwardFailure=yes"])
    parts.append(_ssh_connection_target(host))
    return parts


def _scp_base_parts(host: SshHostConfig) -> list[str]:
    parts = [shutil.which("scp") or "scp"]
    if host.port and int(host.port) != DEFAULT_SSH_PORT:
        parts.extend(["-P", str(host.port)])
    if host.identity_file:
        parts.extend(["-i", host.identity_file])
    parts.extend(
        [
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
        ]
    )
    return parts


def _wrap_with_sshpass(
    host: SshHostConfig, command_parts: list[str], *, for_tunnel_unit: bool = False
) -> list[str]:
    if host.identity_file or not host.password:
        return list(command_parts)
    sshpass_bin = shutil.which("sshpass")
    if not sshpass_bin:
        raise FileNotFoundError(
            "sshpass is required when configs/ssh.json uses password authentication"
        )
    if for_tunnel_unit:
        return [
            "/usr/bin/env",
            f"SSHPASS={host.password}",
            sshpass_bin,
            "-e",
            *command_parts,
        ]
    return [sshpass_bin, "-p", host.password, *command_parts]


def _summarize_completed_process(
    completed: subprocess.CompletedProcess[bytes],
) -> dict[str, Any]:
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.decode(errors="replace").strip(),
        "stderr": completed.stderr.decode(errors="replace").strip(),
    }


def _ensure_success(
    completed: subprocess.CompletedProcess[bytes], *, label: str
) -> dict[str, Any]:
    summary = _summarize_completed_process(completed)
    if completed.returncode != 0:
        details = summary["stderr"] or summary["stdout"] or "unknown error"
        raise RuntimeError(f"{label} failed: {details}")
    return summary


def _tunnel_service_name(tunnel: SshTunnelConfig) -> str:
    return (
        tunnel.service_name
        or f"{SSH_TUNNEL_SERVICE_PREFIX}-{_safe_systemd_token(tunnel.name)}.service"
    )


def _user_systemd_unit_dir() -> Path:
    return Path.home() / ".config/systemd/user"


def _tunnel_service_path(
    tunnel: SshTunnelConfig, *, use_user_systemd: bool = False
) -> Path:
    base_dir = (
        _user_systemd_unit_dir() if use_user_systemd else Path("/etc/systemd/system")
    )
    return base_dir / _tunnel_service_name(tunnel)


def _systemctl_parts(*args: str, use_user_systemd: bool = False) -> list[str]:
    command = ["systemctl"]
    if use_user_systemd:
        command.append("--user")
    command.extend(args)
    return command


def _journalctl_parts(*args: str, use_user_systemd: bool = False) -> list[str]:
    command = ["journalctl"]
    if use_user_systemd:
        command.append("--user")
    command.extend(args)
    return command


def _tunnel_forward_spec(tunnel: SshTunnelConfig) -> str:
    local_host = tunnel.local_host or DEFAULT_TUNNEL_LOCAL_HOST
    remote_host = tunnel.remote_host or DEFAULT_TUNNEL_REMOTE_HOST
    if tunnel.mode == "local":
        return f"{local_host}:{tunnel.local_port}:{remote_host}:{tunnel.remote_port}"
    return f"{remote_host}:{tunnel.remote_port}:{local_host}:{tunnel.local_port}"


def _tunnel_exec_parts(
    tunnel: SshTunnelConfig, host: SshHostConfig, *, for_tunnel_unit: bool = False
) -> list[str]:
    parts = _ssh_base_parts(
        host,
        allocate_tty=False,
        exit_on_forward_failure=True,
        server_alive_interval_seconds=tunnel.server_alive_interval_seconds,
        server_alive_count_max=tunnel.server_alive_count_max,
    )
    forward_flag = "-L" if tunnel.mode == "local" else "-R"
    parts.insert(-1, forward_flag)
    parts.insert(-1, _tunnel_forward_spec(tunnel))
    parts.insert(-1, "-N")
    return _wrap_with_sshpass(host, parts, for_tunnel_unit=for_tunnel_unit)


def _remote_tunnel_cleanup_command(tunnel: SshTunnelConfig) -> str:
    port = max(1, int(tunnel.remote_port))
    return (
        f"port={port}; "
        "if command -v ss >/dev/null 2>&1; then "
        'pids=$(ss -lntpH "( sport = :$port )" 2>/dev/null '
        "| sed -n 's/.*users:((\\\"sshd\\\",pid=\\([0-9][0-9]*\\).*/\\1/p' | sort -u); "
        'if [ -n "$pids" ]; then kill $pids || true; fi; '
        "fi"
    )


def _tunnel_cleanup_exec_parts(
    tunnel: SshTunnelConfig, host: SshHostConfig, *, for_tunnel_unit: bool = False
) -> list[str]:
    if tunnel.mode != "remote":
        return []
    ssh_parts = _ssh_base_parts(host, allocate_tty=False)
    return _wrap_with_sshpass(
        host,
        [*ssh_parts, _remote_tunnel_cleanup_command(tunnel)],
        for_tunnel_unit=for_tunnel_unit,
    )


def _render_tunnel_service_unit(tunnel: SshTunnelConfig, host: SshHostConfig) -> str:
    exec_start_pre_parts = _tunnel_cleanup_exec_parts(
        tunnel, host, for_tunnel_unit=True
    )
    exec_start = shlex.join(_tunnel_exec_parts(tunnel, host, for_tunnel_unit=True))
    lines = [
        "[Unit]",
        f"Description=webu SSH tunnel for {tunnel.name}",
    ]
    lines.extend(
        [
            "After=network-online.target",
            "Wants=network-online.target",
        ]
    )
    lines.extend(
        [
            "",
            "[Service]",
            "Type=simple",
            *(
                [f"ExecStartPre={shlex.join(exec_start_pre_parts)}"]
                if exec_start_pre_parts
                else []
            ),
            f"ExecStart={exec_start}",
            "Restart=always",
            "RestartSec=3s",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )
    return "\n".join(lines)


def _render_user_tunnel_service_unit(
    tunnel: SshTunnelConfig, host: SshHostConfig
) -> str:
    exec_start_pre_parts = _tunnel_cleanup_exec_parts(
        tunnel, host, for_tunnel_unit=True
    )
    exec_start = shlex.join(_tunnel_exec_parts(tunnel, host, for_tunnel_unit=True))
    return "\n".join(
        [
            "[Unit]",
            f"Description=webu SSH tunnel for {tunnel.name}",
            "",
            "[Service]",
            "Type=simple",
            *(
                [f"ExecStartPre={shlex.join(exec_start_pre_parts)}"]
                if exec_start_pre_parts
                else []
            ),
            f"ExecStart={exec_start}",
            "Restart=always",
            "RestartSec=3s",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def config_schema_json() -> dict[str, Any]:
    return SSH_CONFIG.schema


def config_check() -> list[str]:
    payload = load_ssh_config(validate=False)
    return validate_payload_against_schema(payload, SSH_CONFIG.schema, SSH_CONFIG.name)


def config_init(*, force: bool) -> str:
    config_path = _project_root() / "configs" / SSH_CONFIG.file_name
    if config_path.exists() and not force:
        raise FileExistsError(
            f"{config_path} already exists; rerun with --force to overwrite"
        )
    payload = json.loads(render_template_json(SSH_CONFIG))
    return str(save_ssh_config(payload))


def host_list() -> dict[str, Any]:
    payload = load_ssh_config(validate=False)
    hosts = list_hosts(payload)
    return {
        "count": len(hosts),
        "hosts": [
            {
                "name": item.name,
                "ip": item.ip,
                "hostname": item.hostname,
                "port": item.port,
                "username": item.username,
                "identity_file": item.identity_file,
                "notes": item.notes,
            }
            for item in hosts
        ],
    }


def host_upsert(
    *,
    name: str,
    ip: str = "",
    hostname: str = "",
    port: int = DEFAULT_SSH_PORT,
    username: str,
    password: str = "",
    identity_file: str = "",
    notes: str = "",
    save_config: bool = False,
) -> dict[str, Any]:
    payload = load_ssh_config(validate=False)
    existing = find_host(payload, name)
    raw = dict(existing.raw) if existing is not None else {}
    host = SshHostConfig(
        name=_require_text(name, "name"),
        ip=str(ip or (existing.ip if existing else "")).strip(),
        hostname=str(hostname or (existing.hostname if existing else "")).strip(),
        port=max(1, int(port or (existing.port if existing else DEFAULT_SSH_PORT))),
        username=_require_text(
            username or (existing.username if existing else ""), "username"
        ),
        password=str(password or (existing.password if existing else "")).strip(),
        identity_file=str(
            identity_file or (existing.identity_file if existing else "")
        ).strip(),
        notes=str(notes or (existing.notes if existing else "")).strip(),
        raw=raw,
    )
    if not host.ip and not host.hostname:
        raise ValueError("ip or hostname is required")
    upsert_host(payload, host)
    saved_path = str(save_ssh_config(payload)) if save_config else ""
    return {
        "host": {
            "name": host.name,
            "ip": host.ip,
            "hostname": host.hostname,
            "port": host.port,
            "username": host.username,
            "identity_file": host.identity_file,
            "notes": host.notes,
        },
        "saved": bool(save_config),
        "config_path": saved_path,
    }


def probe_host(*, name: str, timeout_seconds: int = 15) -> dict[str, Any]:
    return exec_host(
        name=name, command="echo ssh-ok && uname -a", timeout_seconds=timeout_seconds
    )


def exec_host(
    *,
    name: str,
    command: str,
    timeout_seconds: int = DEFAULT_SSH_EXEC_TIMEOUT_SECONDS,
    allocate_tty: bool = False,
) -> dict[str, Any]:
    payload = load_ssh_config(validate=False)
    host = _resolve_host(payload, name)
    ssh_parts = _ssh_base_parts(host, allocate_tty=allocate_tty)
    command_parts = _wrap_with_sshpass(
        host, [*ssh_parts, _require_text(command, "command")]
    )
    completed = subprocess.run(
        command_parts,
        check=False,
        capture_output=True,
        timeout=max(1, int(timeout_seconds)),
    )
    return {
        "host": host.name,
        "target": _ssh_connection_target(host),
        **_summarize_completed_process(completed),
    }


def copy_to(*, name: str, local_path: str, remote_path: str) -> dict[str, Any]:
    payload = load_ssh_config(validate=False)
    host = _resolve_host(payload, name)
    source = _resolve_path(local_path)
    if not source.exists():
        raise FileNotFoundError(f"local path does not exist: {source}")
    scp_parts = _scp_base_parts(host)
    command_parts = _wrap_with_sshpass(
        host,
        [
            *scp_parts,
            str(source),
            f"{_ssh_connection_target(host)}:{_require_text(remote_path, 'remote_path')}",
        ],
    )
    completed = subprocess.run(command_parts, check=False, capture_output=True)
    summary = _ensure_success(completed, label=f"copy to {host.name}")
    return {
        "host": host.name,
        "source": str(source),
        "destination": remote_path,
        **summary,
    }


def copy_from(*, name: str, remote_path: str, local_path: str) -> dict[str, Any]:
    payload = load_ssh_config(validate=False)
    host = _resolve_host(payload, name)
    destination = _resolve_path(local_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    scp_parts = _scp_base_parts(host)
    command_parts = _wrap_with_sshpass(
        host,
        [
            *scp_parts,
            f"{_ssh_connection_target(host)}:{_require_text(remote_path, 'remote_path')}",
            str(destination),
        ],
    )
    completed = subprocess.run(command_parts, check=False, capture_output=True)
    summary = _ensure_success(completed, label=f"copy from {host.name}")
    return {
        "host": host.name,
        "source": remote_path,
        "destination": str(destination),
        **summary,
    }


def tunnel_list() -> dict[str, Any]:
    payload = load_ssh_config(validate=False)
    tunnels = list_tunnels(payload)
    return {
        "count": len(tunnels),
        "tunnels": [
            {
                "name": item.name,
                "host_name": item.host_name,
                "mode": item.mode,
                "local_host": item.local_host,
                "local_port": item.local_port,
                "remote_host": item.remote_host,
                "remote_port": item.remote_port,
                "enabled": item.enabled,
                "server_alive_interval_seconds": item.server_alive_interval_seconds,
                "server_alive_count_max": item.server_alive_count_max,
                "service_name": _tunnel_service_name(item),
                "notes": item.notes,
            }
            for item in tunnels
        ],
    }


def tunnel_upsert(
    *,
    name: str,
    host_name: str,
    mode: str = DEFAULT_TUNNEL_MODE,
    local_host: str = DEFAULT_TUNNEL_LOCAL_HOST,
    local_port: int,
    remote_host: str = DEFAULT_TUNNEL_REMOTE_HOST,
    remote_port: int,
    enabled: bool | None = None,
    server_alive_interval_seconds: int = DEFAULT_SERVER_ALIVE_INTERVAL_SECONDS,
    server_alive_count_max: int = DEFAULT_SERVER_ALIVE_COUNT_MAX,
    service_name: str = "",
    notes: str = "",
    save_config: bool = False,
) -> dict[str, Any]:
    payload = load_ssh_config(validate=False)
    existing = find_tunnel(payload, name)
    raw = dict(existing.raw) if existing is not None else {}
    host = _resolve_host(payload, host_name)
    tunnel = SshTunnelConfig(
        name=_require_text(name, "name"),
        host_name=host.name,
        mode=normalize_tunnel_mode(
            mode or (existing.mode if existing else DEFAULT_TUNNEL_MODE)
        ),
        local_host=str(
            local_host
            or (existing.local_host if existing else DEFAULT_TUNNEL_LOCAL_HOST)
        ).strip()
        or DEFAULT_TUNNEL_LOCAL_HOST,
        local_port=max(1, int(local_port or (existing.local_port if existing else 0))),
        remote_host=str(
            remote_host
            or (existing.remote_host if existing else DEFAULT_TUNNEL_REMOTE_HOST)
        ).strip()
        or DEFAULT_TUNNEL_REMOTE_HOST,
        remote_port=max(
            1, int(remote_port or (existing.remote_port if existing else 0))
        ),
        enabled=(
            bool(existing.enabled if existing is not None else True)
            if enabled is None
            else bool(enabled)
        ),
        server_alive_interval_seconds=max(
            1,
            int(
                server_alive_interval_seconds
                or (
                    existing.server_alive_interval_seconds
                    if existing
                    else DEFAULT_SERVER_ALIVE_INTERVAL_SECONDS
                )
            ),
        ),
        server_alive_count_max=max(
            1,
            int(
                server_alive_count_max
                or (
                    existing.server_alive_count_max
                    if existing
                    else DEFAULT_SERVER_ALIVE_COUNT_MAX
                )
            ),
        ),
        service_name=str(
            service_name or (existing.service_name if existing else "")
        ).strip(),
        notes=str(notes or (existing.notes if existing else "")).strip(),
        raw=raw,
    )
    upsert_tunnel(payload, tunnel)
    saved_path = str(save_ssh_config(payload)) if save_config else ""
    return {
        "tunnel": {
            "name": tunnel.name,
            "host_name": tunnel.host_name,
            "mode": tunnel.mode,
            "local_host": tunnel.local_host,
            "local_port": tunnel.local_port,
            "remote_host": tunnel.remote_host,
            "remote_port": tunnel.remote_port,
            "enabled": tunnel.enabled,
            "service_name": _tunnel_service_name(tunnel),
            "notes": tunnel.notes,
        },
        "saved": bool(save_config),
        "config_path": saved_path,
    }


def tunnel_command(*, name: str) -> dict[str, Any]:
    payload = load_ssh_config(validate=False)
    tunnel, host = _resolve_tunnel(payload, name)
    return {
        "tunnel": tunnel.name,
        "host": host.name,
        "mode": tunnel.mode,
        "forward_spec": _tunnel_forward_spec(tunnel),
        "service_name": _tunnel_service_name(tunnel),
        "command": shlex.join(_tunnel_exec_parts(tunnel, host, for_tunnel_unit=True)),
    }


def tunnel_service_install(
    *, name: str, use_user_systemd: bool = False
) -> dict[str, Any]:
    payload = load_ssh_config(validate=False)
    tunnel, host = _resolve_tunnel(payload, name)
    service_name = _tunnel_service_name(tunnel)
    service_path = _tunnel_service_path(tunnel, use_user_systemd=use_user_systemd)
    unit_text = (
        _render_user_tunnel_service_unit(tunnel, host)
        if use_user_systemd
        else _render_tunnel_service_unit(tunnel, host)
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp_file:
        tmp_file.write(unit_text)
        tmp_path = Path(tmp_file.name)

    try:
        mkdir_result = _ensure_success(
            sudo_run(
                ["mkdir", "-p", str(service_path.parent)],
                use_sudo=not use_user_systemd,
                check=False,
                capture_output=True,
            ),
            label=f"mkdir -p {service_path.parent}",
        )
        install_result = _ensure_success(
            sudo_run(
                ["install", "-m", "0644", str(tmp_path), str(service_path)],
                use_sudo=not use_user_systemd,
                check=False,
                capture_output=True,
            ),
            label=f"install systemd unit {service_name}",
        )
        daemon_reload = _ensure_success(
            sudo_run(
                _systemctl_parts("daemon-reload", use_user_systemd=use_user_systemd),
                use_sudo=not use_user_systemd,
                check=False,
                capture_output=True,
            ),
            label=f"systemctl{' --user' if use_user_systemd else ''} daemon-reload",
        )
        enable_result = _ensure_success(
            sudo_run(
                _systemctl_parts(
                    "enable", service_name, use_user_systemd=use_user_systemd
                ),
                use_sudo=not use_user_systemd,
                check=False,
                capture_output=True,
            ),
            label=f"systemctl{' --user' if use_user_systemd else ''} enable {service_name}",
        )
        restart_result = _ensure_success(
            sudo_run(
                _systemctl_parts(
                    "restart", service_name, use_user_systemd=use_user_systemd
                ),
                use_sudo=not use_user_systemd,
                check=False,
                capture_output=True,
            ),
            label=f"systemctl{' --user' if use_user_systemd else ''} restart {service_name}",
        )
        show_result = _ensure_success(
            sudo_run(
                _systemctl_parts(
                    "show",
                    service_name,
                    "--no-pager",
                    "--property=ActiveState,SubState,UnitFileState,FragmentPath",
                    use_user_systemd=use_user_systemd,
                ),
                use_sudo=not use_user_systemd,
                check=False,
                capture_output=True,
            ),
            label=f"systemctl{' --user' if use_user_systemd else ''} show {service_name}",
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    return {
        "tunnel": tunnel.name,
        "service_name": service_name,
        "systemd_scope": "user" if use_user_systemd else "system",
        "service_path": str(service_path),
        "mkdir": mkdir_result,
        "install": install_result,
        "daemon_reload": daemon_reload,
        "enable": enable_result,
        "restart": restart_result,
        "show": show_result,
    }


def tunnel_service_status(
    *, name: str, use_user_systemd: bool = False
) -> dict[str, Any]:
    payload = load_ssh_config(validate=False)
    tunnel, _host = _resolve_tunnel(payload, name)
    service_name = _tunnel_service_name(tunnel)
    show_result = _summarize_completed_process(
        sudo_run(
            _systemctl_parts(
                "show",
                service_name,
                "--no-pager",
                "--property=ActiveState,SubState,UnitFileState,FragmentPath,ExecMainStatus",
                use_user_systemd=use_user_systemd,
            ),
            use_sudo=not use_user_systemd,
            check=False,
            capture_output=True,
        )
    )
    active_result = _summarize_completed_process(
        sudo_run(
            _systemctl_parts(
                "is-active", service_name, use_user_systemd=use_user_systemd
            ),
            use_sudo=not use_user_systemd,
            check=False,
            capture_output=True,
        )
    )
    enabled_result = _summarize_completed_process(
        sudo_run(
            _systemctl_parts(
                "is-enabled", service_name, use_user_systemd=use_user_systemd
            ),
            use_sudo=not use_user_systemd,
            check=False,
            capture_output=True,
        )
    )
    return {
        "tunnel": tunnel.name,
        "service_name": service_name,
        "systemd_scope": "user" if use_user_systemd else "system",
        "is_active": active_result["returncode"] == 0,
        "is_enabled": enabled_result["returncode"] == 0,
        "systemctl_show": show_result,
        "systemctl_is_active": active_result,
        "systemctl_is_enabled": enabled_result,
    }


def tunnel_service_logs(
    *, name: str, lines: int = 100, use_user_systemd: bool = False
) -> dict[str, Any]:
    payload = load_ssh_config(validate=False)
    tunnel, _host = _resolve_tunnel(payload, name)
    service_name = _tunnel_service_name(tunnel)
    completed = sudo_run(
        _journalctl_parts(
            "-u",
            service_name,
            "-n",
            str(max(1, int(lines))),
            "--no-pager",
            use_user_systemd=use_user_systemd,
        ),
        use_sudo=not use_user_systemd,
        check=False,
        capture_output=True,
    )
    summary = _summarize_completed_process(completed)
    return {
        "tunnel": tunnel.name,
        "service_name": service_name,
        "systemd_scope": "user" if use_user_systemd else "system",
        **summary,
    }


def tunnel_service_restart(
    *, name: str, use_user_systemd: bool = False
) -> dict[str, Any]:
    payload = load_ssh_config(validate=False)
    tunnel, _host = _resolve_tunnel(payload, name)
    service_name = _tunnel_service_name(tunnel)
    restart_result = _ensure_success(
        sudo_run(
            _systemctl_parts(
                "restart", service_name, use_user_systemd=use_user_systemd
            ),
            use_sudo=not use_user_systemd,
            check=False,
            capture_output=True,
        ),
        label=f"systemctl{' --user' if use_user_systemd else ''} restart {service_name}",
    )
    show_result = _ensure_success(
        sudo_run(
            _systemctl_parts(
                "show",
                service_name,
                "--no-pager",
                "--property=ActiveState,SubState,UnitFileState,FragmentPath",
                use_user_systemd=use_user_systemd,
            ),
            use_sudo=not use_user_systemd,
            check=False,
            capture_output=True,
        ),
        label=f"systemctl{' --user' if use_user_systemd else ''} show {service_name}",
    )
    return {
        "tunnel": tunnel.name,
        "service_name": service_name,
        "systemd_scope": "user" if use_user_systemd else "system",
        "restart": restart_result,
        "show": show_result,
    }


def tunnel_service_disable(
    *, name: str, purge_unit_file: bool = False, use_user_systemd: bool = False
) -> dict[str, Any]:
    payload = load_ssh_config(validate=False)
    tunnel, _host = _resolve_tunnel(payload, name)
    service_name = _tunnel_service_name(tunnel)
    service_path = _tunnel_service_path(tunnel, use_user_systemd=use_user_systemd)
    stop_result = _summarize_completed_process(
        sudo_run(
            _systemctl_parts("stop", service_name, use_user_systemd=use_user_systemd),
            use_sudo=not use_user_systemd,
            check=False,
            capture_output=True,
        )
    )
    disable_result = _summarize_completed_process(
        sudo_run(
            _systemctl_parts(
                "disable", service_name, use_user_systemd=use_user_systemd
            ),
            use_sudo=not use_user_systemd,
            check=False,
            capture_output=True,
        )
    )
    removed = False
    purge_result: dict[str, Any] | None = None
    daemon_reload_result: dict[str, Any] | None = None
    if purge_unit_file:
        purge_result = _summarize_completed_process(
            sudo_run(
                ["rm", "-f", str(service_path)],
                use_sudo=not use_user_systemd,
                check=False,
                capture_output=True,
            )
        )
        removed = purge_result["returncode"] == 0 and not service_path.exists()
        daemon_reload_result = _summarize_completed_process(
            sudo_run(
                _systemctl_parts("daemon-reload", use_user_systemd=use_user_systemd),
                use_sudo=not use_user_systemd,
                check=False,
                capture_output=True,
            )
        )
    return {
        "tunnel": tunnel.name,
        "service_name": service_name,
        "systemd_scope": "user" if use_user_systemd else "system",
        "stop": stop_result,
        "disable": disable_result,
        "purged": bool(purge_unit_file and removed),
        "purge": purge_result,
        "daemon_reload": daemon_reload_result,
    }
