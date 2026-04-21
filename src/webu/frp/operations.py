from __future__ import annotations

import json
import re
import shlex
import subprocess
import tempfile

from pathlib import Path
from typing import Any

from webu.schema import (
    find_project_root,
    render_template_json,
    validate_payload_against_schema,
)
from webu.ssh.operations import copy_to as ssh_copy_to
from webu.ssh.operations import exec_host as ssh_exec_host
from webu.ssh.schema import find_host, load_ssh_config
from webu.sudo import run as sudo_run

from .schema import (
    DEFAULT_FRPC_BINARY,
    DEFAULT_FRPC_CONFIG_DIR,
    DEFAULT_FRPC_LOCAL_HOST,
    DEFAULT_FRP_PROTOCOL,
    DEFAULT_FRPS_BIND_PORT,
    DEFAULT_PROXY_BIND_ADDR,
    FRP_CONFIG,
    FrpClientConfig,
    FrpServerConfig,
    find_client,
    find_server,
    list_clients,
    list_servers,
    load_frp_config,
    normalize_protocol,
    save_frp_config,
    upsert_client,
    upsert_server,
)


DEFAULT_FRPC_RUN_TIMEOUT_SECONDS = 15
FRPC_SERVICE_PREFIX = "webu-frpc"


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


def _resolve_server(payload: dict[str, Any], name: str) -> FrpServerConfig:
    server = find_server(payload, name)
    if server is None:
        raise ValueError(f"frp server '{name}' not found in configs/frp.json")
    return server


def _resolve_client(payload: dict[str, Any], name: str) -> FrpClientConfig:
    client = find_client(payload, name)
    if client is None:
        raise ValueError(f"frp client '{name}' not found in configs/frp.json")
    return client


def _resolve_ssh_host_name(server: FrpServerConfig) -> str:
    return _require_text(server.ssh_host_name, "ssh_host_name")


def _resolve_client_server_address(
    server: FrpServerConfig, client: FrpClientConfig
) -> str:
    if client.server_addr:
        return client.server_addr
    ssh_payload = load_ssh_config(validate=False)
    ssh_host = find_host(ssh_payload, _resolve_ssh_host_name(server))
    if ssh_host is None:
        raise ValueError(
            f"ssh host '{server.ssh_host_name}' referenced by frp server '{server.name}' is missing"
        )
    return str(ssh_host.hostname or ssh_host.ip or "").strip() or "127.0.0.1"


def _client_config_path(client: FrpClientConfig) -> Path:
    default_path = Path(DEFAULT_FRPC_CONFIG_DIR) / f"{client.name}.frpc.toml"
    return _resolve_path(client.config_path, default=default_path)


def _frpc_service_name(client: FrpClientConfig) -> str:
    return (
        client.service_name
        or f"{FRPC_SERVICE_PREFIX}-{_safe_systemd_token(client.name)}.service"
    )


def _frpc_service_path(client: FrpClientConfig) -> Path:
    return Path("/etc/systemd/system") / _frpc_service_name(client)


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


def _render_frps_toml(server: FrpServerConfig) -> str:
    return "\n".join(
        [
            f"bindPort = {server.bind_port}",
            f'proxyBindAddr = "{server.proxy_bind_addr}"',
            f'auth.token = "{server.auth_token}"',
            "",
        ]
    )


def _render_frpc_toml(server: FrpServerConfig, client: FrpClientConfig) -> str:
    server_addr = _resolve_client_server_address(server, client)
    auth_token = client.auth_token or server.auth_token
    return "\n".join(
        [
            f'serverAddr = "{server_addr}"',
            f"serverPort = {client.server_port or server.bind_port}",
            f'auth.token = "{auth_token}"',
            "",
            "[[proxies]]",
            f'name = "{client.name}"',
            f'type = "{client.protocol}"',
            f'localIP = "{client.local_host}"',
            f"localPort = {client.local_port}",
            f"remotePort = {client.remote_port}",
            "",
        ]
    )


def _render_frps_service_unit(server: FrpServerConfig) -> str:
    exec_start = shlex.join(
        [server.remote_binary_path, "-c", server.remote_config_path]
    )
    service_name = (
        server.remote_service_name
        or f"webu-frps-{_safe_systemd_token(server.name)}.service"
    )
    return "\n".join(
        [
            "[Unit]",
            f"Description=webu frps for {server.name}",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"ExecStart={exec_start}",
            "Restart=always",
            "RestartSec=3s",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )


def _render_frpc_service_unit(client: FrpClientConfig, config_path: Path) -> str:
    binary_path = _resolve_path(client.binary_path, default=Path(DEFAULT_FRPC_BINARY))
    exec_start = shlex.join([str(binary_path), "-c", str(config_path)])
    return "\n".join(
        [
            "[Unit]",
            f"Description=webu frpc for {client.name}",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"ExecStart={exec_start}",
            "Restart=always",
            "RestartSec=3s",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )


def config_schema_json() -> dict[str, Any]:
    return FRP_CONFIG.schema


def config_check() -> list[str]:
    payload = load_frp_config(validate=False)
    return validate_payload_against_schema(payload, FRP_CONFIG.schema, FRP_CONFIG.name)


def config_init(*, force: bool) -> str:
    config_path = _project_root() / "configs" / FRP_CONFIG.file_name
    if config_path.exists() and not force:
        raise FileExistsError(
            f"{config_path} already exists; rerun with --force to overwrite"
        )
    payload = json.loads(render_template_json(FRP_CONFIG))
    return str(save_frp_config(payload))


def server_list() -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    items = list_servers(payload)
    return {
        "count": len(items),
        "servers": [
            {
                "name": item.name,
                "ssh_host_name": item.ssh_host_name,
                "bind_port": item.bind_port,
                "proxy_bind_addr": item.proxy_bind_addr,
                "remote_binary_path": item.remote_binary_path,
                "remote_config_path": item.remote_config_path,
                "remote_service_name": item.remote_service_name,
                "notes": item.notes,
            }
            for item in items
        ],
    }


def client_list() -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    items = list_clients(payload)
    return {
        "count": len(items),
        "clients": [
            {
                "name": item.name,
                "server_name": item.server_name,
                "server_addr": item.server_addr,
                "server_port": item.server_port,
                "protocol": item.protocol,
                "local_host": item.local_host,
                "local_port": item.local_port,
                "remote_port": item.remote_port,
                "binary_path": item.binary_path,
                "config_path": item.config_path,
                "service_name": _frpc_service_name(item),
                "enabled": item.enabled,
                "notes": item.notes,
            }
            for item in items
        ],
    }


def server_upsert(
    *,
    name: str,
    ssh_host_name: str,
    bind_port: int = DEFAULT_FRPS_BIND_PORT,
    proxy_bind_addr: str = DEFAULT_PROXY_BIND_ADDR,
    auth_token: str,
    remote_binary_path: str,
    remote_config_path: str,
    remote_service_name: str = "",
    notes: str = "",
    save_config: bool = False,
) -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    server = FrpServerConfig(
        name=_require_text(name, "name"),
        ssh_host_name=_require_text(ssh_host_name, "ssh_host_name"),
        bind_port=max(1, int(bind_port)),
        proxy_bind_addr=str(proxy_bind_addr or DEFAULT_PROXY_BIND_ADDR).strip()
        or DEFAULT_PROXY_BIND_ADDR,
        auth_token=_require_text(auth_token, "auth_token"),
        remote_binary_path=_require_text(remote_binary_path, "remote_binary_path"),
        remote_config_path=_require_text(remote_config_path, "remote_config_path"),
        remote_service_name=str(remote_service_name or "").strip(),
        notes=str(notes or "").strip(),
        raw=(find_server(payload, name).raw if find_server(payload, name) else {}),
    )
    upsert_server(payload, server)
    saved_path = str(save_frp_config(payload)) if save_config else ""
    return {
        "server": {
            "name": server.name,
            "ssh_host_name": server.ssh_host_name,
            "bind_port": server.bind_port,
            "proxy_bind_addr": server.proxy_bind_addr,
            "remote_binary_path": server.remote_binary_path,
            "remote_config_path": server.remote_config_path,
            "remote_service_name": server.remote_service_name,
            "notes": server.notes,
        },
        "saved": bool(save_config),
        "config_path": saved_path,
    }


def client_upsert(
    *,
    name: str,
    server_name: str,
    server_addr: str = "",
    server_port: int = DEFAULT_FRPS_BIND_PORT,
    auth_token: str = "",
    protocol: str = DEFAULT_FRP_PROTOCOL,
    local_host: str = DEFAULT_FRPC_LOCAL_HOST,
    local_port: int,
    remote_port: int,
    binary_path: str = DEFAULT_FRPC_BINARY,
    config_path: str = "",
    service_name: str = "",
    enabled: bool | None = None,
    notes: str = "",
    save_config: bool = False,
) -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    existing = find_client(payload, name)
    raw = dict(existing.raw) if existing is not None else {}
    client = FrpClientConfig(
        name=_require_text(name, "name"),
        server_name=_require_text(server_name, "server_name"),
        server_addr=str(
            server_addr or (existing.server_addr if existing else "")
        ).strip(),
        server_port=max(
            1,
            int(
                server_port
                or (existing.server_port if existing else DEFAULT_FRPS_BIND_PORT)
            ),
        ),
        auth_token=str(auth_token or (existing.auth_token if existing else "")).strip(),
        protocol=normalize_protocol(
            protocol or (existing.protocol if existing else DEFAULT_FRP_PROTOCOL)
        ),
        local_host=str(
            local_host or (existing.local_host if existing else DEFAULT_FRPC_LOCAL_HOST)
        ).strip()
        or DEFAULT_FRPC_LOCAL_HOST,
        local_port=max(1, int(local_port or (existing.local_port if existing else 0))),
        remote_port=max(
            1, int(remote_port or (existing.remote_port if existing else 0))
        ),
        binary_path=str(
            binary_path or (existing.binary_path if existing else DEFAULT_FRPC_BINARY)
        ).strip()
        or DEFAULT_FRPC_BINARY,
        config_path=str(
            config_path or (existing.config_path if existing else "")
        ).strip(),
        service_name=str(
            service_name or (existing.service_name if existing else "")
        ).strip(),
        enabled=(
            bool(existing.enabled if existing is not None else True)
            if enabled is None
            else bool(enabled)
        ),
        notes=str(notes or (existing.notes if existing else "")).strip(),
        raw=raw,
    )
    upsert_client(payload, client)
    saved_path = str(save_frp_config(payload)) if save_config else ""
    return {
        "client": {
            "name": client.name,
            "server_name": client.server_name,
            "server_addr": client.server_addr,
            "server_port": client.server_port,
            "protocol": client.protocol,
            "local_host": client.local_host,
            "local_port": client.local_port,
            "remote_port": client.remote_port,
            "binary_path": client.binary_path,
            "config_path": client.config_path,
            "service_name": _frpc_service_name(client),
            "enabled": client.enabled,
            "notes": client.notes,
        },
        "saved": bool(save_config),
        "config_path": saved_path,
    }


def server_render(*, name: str) -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    server = _resolve_server(payload, name)
    return {
        "server": server.name,
        "remote_config_path": server.remote_config_path,
        "service_name": server.remote_service_name
        or f"webu-frps-{_safe_systemd_token(server.name)}.service",
        "content": _render_frps_toml(server),
    }


def client_render(*, name: str) -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    client = _resolve_client(payload, name)
    server = _resolve_server(payload, client.server_name)
    config_path = _client_config_path(client)
    return {
        "client": client.name,
        "server": server.name,
        "config_path": str(config_path),
        "service_name": _frpc_service_name(client),
        "content": _render_frpc_toml(server, client),
    }


def server_deploy(*, name: str, install_service: bool = False) -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    server = _resolve_server(payload, name)
    service_name = (
        server.remote_service_name
        or f"webu-frps-{_safe_systemd_token(server.name)}.service"
    )
    rendered = _render_frps_toml(server)
    remote_tmp_config = f"/tmp/{_safe_systemd_token(server.name)}.frps.toml"

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp_file:
        tmp_file.write(rendered)
        tmp_config_path = Path(tmp_file.name)

    try:
        upload_result = ssh_copy_to(
            name=server.ssh_host_name,
            local_path=str(tmp_config_path),
            remote_path=remote_tmp_config,
        )
        install_script = (
            f"mkdir -p {shlex.quote(str(Path(server.remote_config_path).parent))} && "
            f"install -m 0600 {shlex.quote(remote_tmp_config)} {shlex.quote(server.remote_config_path)} && "
            f"rm -f {shlex.quote(remote_tmp_config)}"
        )
        remote_install = ssh_exec_host(
            name=server.ssh_host_name, command=install_script, timeout_seconds=60
        )
        if remote_install["returncode"] != 0:
            raise RuntimeError(
                remote_install["stderr"]
                or remote_install["stdout"]
                or "remote frps config install failed"
            )

        service_unit_result: dict[str, Any] | None = None
        if install_service:
            unit_text = _render_frps_service_unit(server)
            remote_tmp_unit = f"/tmp/{service_name}"
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", delete=False
            ) as tmp_unit:
                tmp_unit.write(unit_text)
                tmp_unit_path = Path(tmp_unit.name)
            try:
                unit_upload = ssh_copy_to(
                    name=server.ssh_host_name,
                    local_path=str(tmp_unit_path),
                    remote_path=remote_tmp_unit,
                )
                service_script = " && ".join(
                    [
                        f"install -m 0644 {shlex.quote(remote_tmp_unit)} /etc/systemd/system/{shlex.quote(service_name)}",
                        f"rm -f {shlex.quote(remote_tmp_unit)}",
                        "systemctl daemon-reload",
                        f"systemctl enable {shlex.quote(service_name)}",
                        f"systemctl restart {shlex.quote(service_name)}",
                        f"systemctl show {shlex.quote(service_name)} --no-pager --property=ActiveState,SubState,UnitFileState,FragmentPath",
                    ]
                )
                service_unit_result = ssh_exec_host(
                    name=server.ssh_host_name,
                    command=service_script,
                    timeout_seconds=120,
                )
                service_unit_result["unit_upload"] = unit_upload
                if service_unit_result["returncode"] != 0:
                    raise RuntimeError(
                        service_unit_result["stderr"]
                        or service_unit_result["stdout"]
                        or "remote frps service install failed"
                    )
            finally:
                tmp_unit_path.unlink(missing_ok=True)
        return {
            "server": server.name,
            "ssh_host_name": server.ssh_host_name,
            "remote_config_path": server.remote_config_path,
            "service_name": service_name,
            "config_upload": upload_result,
            "config_install": remote_install,
            "service": service_unit_result,
        }
    finally:
        tmp_config_path.unlink(missing_ok=True)


def server_status(*, name: str) -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    server = _resolve_server(payload, name)
    service_name = (
        server.remote_service_name
        or f"webu-frps-{_safe_systemd_token(server.name)}.service"
    )
    return ssh_exec_host(
        name=server.ssh_host_name,
        command=f"systemctl show {shlex.quote(service_name)} --no-pager --property=ActiveState,SubState,UnitFileState,FragmentPath,ExecMainStatus",
        timeout_seconds=60,
    )


def server_logs(*, name: str, lines: int = 100) -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    server = _resolve_server(payload, name)
    service_name = (
        server.remote_service_name
        or f"webu-frps-{_safe_systemd_token(server.name)}.service"
    )
    return ssh_exec_host(
        name=server.ssh_host_name,
        command=f"journalctl -u {shlex.quote(service_name)} -n {max(1, int(lines))} --no-pager",
        timeout_seconds=60,
    )


def server_restart(*, name: str) -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    server = _resolve_server(payload, name)
    service_name = (
        server.remote_service_name
        or f"webu-frps-{_safe_systemd_token(server.name)}.service"
    )
    return ssh_exec_host(
        name=server.ssh_host_name,
        command=f"systemctl restart {shlex.quote(service_name)} && systemctl show {shlex.quote(service_name)} --no-pager --property=ActiveState,SubState,UnitFileState,FragmentPath",
        timeout_seconds=90,
    )


def server_disable(*, name: str, purge_unit_file: bool = False) -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    server = _resolve_server(payload, name)
    service_name = (
        server.remote_service_name
        or f"webu-frps-{_safe_systemd_token(server.name)}.service"
    )
    commands = [
        f"systemctl stop {shlex.quote(service_name)} || true",
        f"systemctl disable {shlex.quote(service_name)} || true",
    ]
    if purge_unit_file:
        commands.extend(
            [
                f"rm -f /etc/systemd/system/{shlex.quote(service_name)}",
                "systemctl daemon-reload || true",
            ]
        )
    return ssh_exec_host(
        name=server.ssh_host_name,
        command=" && ".join(commands),
        timeout_seconds=90,
    )


def client_prepare(*, name: str) -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    client = _resolve_client(payload, name)
    server = _resolve_server(payload, client.server_name)
    config_path = _client_config_path(client)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_text = _render_frpc_toml(server, client)
    config_path.write_text(config_text, encoding="utf-8")
    return {
        "client": client.name,
        "server": server.name,
        "config_path": str(config_path),
        "content": config_text,
    }


def client_run_once(
    *, name: str, timeout_seconds: int = DEFAULT_FRPC_RUN_TIMEOUT_SECONDS
) -> dict[str, Any]:
    prepared = client_prepare(name=name)
    payload = load_frp_config(validate=False)
    client = _resolve_client(payload, name)
    binary_path = _resolve_path(client.binary_path, default=Path(DEFAULT_FRPC_BINARY))
    if not binary_path.exists():
        raise FileNotFoundError(f"frpc binary not found: {binary_path}")
    completed = subprocess.run(
        [str(binary_path), "-c", prepared["config_path"]],
        check=False,
        capture_output=True,
        timeout=max(1, int(timeout_seconds)),
    )
    return {
        "client": client.name,
        "config_path": prepared["config_path"],
        **_summarize_completed_process(completed),
    }


def client_service_install(*, name: str) -> dict[str, Any]:
    prepared = client_prepare(name=name)
    payload = load_frp_config(validate=False)
    client = _resolve_client(payload, name)
    config_path = Path(prepared["config_path"])
    service_name = _frpc_service_name(client)
    service_path = _frpc_service_path(client)
    unit_text = _render_frpc_service_unit(client, config_path)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp_file:
        tmp_file.write(unit_text)
        tmp_path = Path(tmp_file.name)
    try:
        install_result = _ensure_success(
            sudo_run(
                ["install", "-m", "0644", str(tmp_path), str(service_path)],
                check=False,
                capture_output=True,
            ),
            label=f"install systemd unit {service_name}",
        )
        daemon_reload = _ensure_success(
            sudo_run(["systemctl", "daemon-reload"], check=False, capture_output=True),
            label="systemctl daemon-reload",
        )
        enable_result = _ensure_success(
            sudo_run(
                ["systemctl", "enable", service_name], check=False, capture_output=True
            ),
            label=f"systemctl enable {service_name}",
        )
        restart_result = _ensure_success(
            sudo_run(
                ["systemctl", "restart", service_name], check=False, capture_output=True
            ),
            label=f"systemctl restart {service_name}",
        )
        show_result = _ensure_success(
            sudo_run(
                [
                    "systemctl",
                    "show",
                    service_name,
                    "--no-pager",
                    "--property=ActiveState,SubState,UnitFileState,FragmentPath",
                ],
                check=False,
                capture_output=True,
            ),
            label=f"systemctl show {service_name}",
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    return {
        "client": client.name,
        "service_name": service_name,
        "service_path": str(service_path),
        "config_path": str(config_path),
        "install": install_result,
        "daemon_reload": daemon_reload,
        "enable": enable_result,
        "restart": restart_result,
        "show": show_result,
    }


def client_service_status(*, name: str) -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    client = _resolve_client(payload, name)
    service_name = _frpc_service_name(client)
    show_result = _summarize_completed_process(
        sudo_run(
            [
                "systemctl",
                "show",
                service_name,
                "--no-pager",
                "--property=ActiveState,SubState,UnitFileState,FragmentPath,ExecMainStatus",
            ],
            check=False,
            capture_output=True,
        )
    )
    active_result = _summarize_completed_process(
        sudo_run(
            ["systemctl", "is-active", service_name], check=False, capture_output=True
        )
    )
    enabled_result = _summarize_completed_process(
        sudo_run(
            ["systemctl", "is-enabled", service_name], check=False, capture_output=True
        )
    )
    return {
        "client": client.name,
        "service_name": service_name,
        "is_active": active_result["returncode"] == 0,
        "is_enabled": enabled_result["returncode"] == 0,
        "systemctl_show": show_result,
        "systemctl_is_active": active_result,
        "systemctl_is_enabled": enabled_result,
    }


def client_service_logs(*, name: str, lines: int = 100) -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    client = _resolve_client(payload, name)
    service_name = _frpc_service_name(client)
    completed = sudo_run(
        ["journalctl", "-u", service_name, "-n", str(max(1, int(lines))), "--no-pager"],
        check=False,
        capture_output=True,
    )
    return {
        "client": client.name,
        "service_name": service_name,
        **_summarize_completed_process(completed),
    }


def client_service_restart(*, name: str) -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    client = _resolve_client(payload, name)
    service_name = _frpc_service_name(client)
    restart_result = _ensure_success(
        sudo_run(
            ["systemctl", "restart", service_name], check=False, capture_output=True
        ),
        label=f"systemctl restart {service_name}",
    )
    show_result = _ensure_success(
        sudo_run(
            [
                "systemctl",
                "show",
                service_name,
                "--no-pager",
                "--property=ActiveState,SubState,UnitFileState,FragmentPath",
            ],
            check=False,
            capture_output=True,
        ),
        label=f"systemctl show {service_name}",
    )
    return {
        "client": client.name,
        "service_name": service_name,
        "restart": restart_result,
        "show": show_result,
    }


def client_service_disable(
    *, name: str, purge_unit_file: bool = False
) -> dict[str, Any]:
    payload = load_frp_config(validate=False)
    client = _resolve_client(payload, name)
    service_name = _frpc_service_name(client)
    service_path = _frpc_service_path(client)
    stop_result = _summarize_completed_process(
        sudo_run(["systemctl", "stop", service_name], check=False, capture_output=True)
    )
    disable_result = _summarize_completed_process(
        sudo_run(
            ["systemctl", "disable", service_name], check=False, capture_output=True
        )
    )
    removed = False
    purge_result: dict[str, Any] | None = None
    daemon_reload_result: dict[str, Any] | None = None
    if purge_unit_file:
        purge_result = _summarize_completed_process(
            sudo_run(["rm", "-f", str(service_path)], check=False, capture_output=True)
        )
        removed = purge_result["returncode"] == 0 and not service_path.exists()
        daemon_reload_result = _summarize_completed_process(
            sudo_run(["systemctl", "daemon-reload"], check=False, capture_output=True)
        )
    return {
        "client": client.name,
        "service_name": service_name,
        "stop": stop_result,
        "disable": disable_result,
        "purged": bool(purge_unit_file and removed),
        "purge": purge_result,
        "daemon_reload": daemon_reload_result,
    }
