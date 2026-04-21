from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from webu.schema import (
    ConfigSpec,
    load_json_config,
    save_json_config,
    validate_payload_against_schema,
)


DEFAULT_SSH_PORT = 22
DEFAULT_TUNNEL_MODE = "remote"
DEFAULT_TUNNEL_LOCAL_HOST = "127.0.0.1"
DEFAULT_TUNNEL_REMOTE_HOST = "127.0.0.1"
DEFAULT_SERVER_ALIVE_INTERVAL_SECONDS = 30
DEFAULT_SERVER_ALIVE_COUNT_MAX = 3
_ALLOWED_TUNNEL_MODES = {"remote", "local"}


SSH_CONFIG = ConfigSpec(
    name="ssh",
    file_name="ssh.json",
    purpose=[
        "管理 webu 需要连接的远程 SSH 主机和复用的 SSH 隧道定义。",
        "让 wssh 可以读取主机凭据、执行远端命令、传输文件，并把 SSH 端口转发固化成 systemd 服务。",
    ],
    notes=[
        "兼容旧版仅由 host 列表组成的 configs/ssh.json；新版结构会把 hosts 和 tunnels 放进同一个对象。",
        "如果同时填写 hostname 和 ip，SSH 连接优先使用 hostname。",
        "如果 identity_file 为空且 password 非空，wssh 会使用 sshpass。",
        "本文件包含密码或私钥路径，属于本地敏感运行时配置，不应提交进 git。",
    ],
    sample={
        "hosts": [
            {
                "name": "example-vps",
                "ip": "203.0.113.10",
                "hostname": "",
                "port": 22,
                "username": "root",
                "password": "",
                "identity_file": "",
                "notes": "example remote host",
            }
        ],
        "tunnels": [
            {
                "name": "example-remote-web",
                "host_name": "example-vps",
                "mode": "remote",
                "local_host": "127.0.0.1",
                "local_port": 20002,
                "remote_host": "127.0.0.1",
                "remote_port": 32002,
                "enabled": True,
                "server_alive_interval_seconds": 30,
                "server_alive_count_max": 3,
                "service_name": "",
                "notes": "Expose the local service onto the remote VPS loopback.",
            }
        ],
    },
    schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "hosts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "ip": {"type": "string"},
                        "hostname": {"type": "string"},
                        "port": {"type": "integer"},
                        "username": {"type": "string", "minLength": 1},
                        "password": {"type": "string"},
                        "identity_file": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["name", "username"],
                },
            },
            "tunnels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "host_name": {"type": "string", "minLength": 1},
                        "mode": {
                            "type": "string",
                            "enum": ["remote", "local"],
                        },
                        "local_host": {"type": "string", "minLength": 1},
                        "local_port": {"type": "integer"},
                        "remote_host": {"type": "string", "minLength": 1},
                        "remote_port": {"type": "integer"},
                        "enabled": {"type": "boolean"},
                        "server_alive_interval_seconds": {"type": "integer"},
                        "server_alive_count_max": {"type": "integer"},
                        "service_name": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": [
                        "name",
                        "host_name",
                        "local_port",
                        "remote_port",
                    ],
                },
            },
        },
    },
)


@dataclass(frozen=True)
class SshHostConfig:
    name: str
    ip: str
    hostname: str
    port: int
    username: str
    password: str
    identity_file: str
    notes: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class SshTunnelConfig:
    name: str
    host_name: str
    mode: str
    local_host: str
    local_port: int
    remote_host: str
    remote_port: int
    enabled: bool
    server_alive_interval_seconds: int
    server_alive_count_max: int
    service_name: str
    notes: str
    raw: dict[str, Any]


def normalize_tunnel_mode(value: object, *, fallback: str = DEFAULT_TUNNEL_MODE) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _ALLOWED_TUNNEL_MODES:
        return normalized
    return fallback


def _normalize_payload(raw_payload: Any) -> dict[str, Any]:
    if isinstance(raw_payload, list):
        return {"hosts": raw_payload, "tunnels": []}
    if not isinstance(raw_payload, dict):
        return {"hosts": [], "tunnels": []}
    normalized = dict(raw_payload)
    hosts = normalized.get("hosts")
    if isinstance(hosts, list):
        normalized["hosts"] = hosts
    else:
        normalized["hosts"] = []
    tunnels = normalized.get("tunnels")
    if isinstance(tunnels, list):
        normalized["tunnels"] = tunnels
    else:
        normalized["tunnels"] = []
    return normalized


def load_ssh_config(*, validate: bool = True) -> dict[str, Any]:
    raw_payload = load_json_config(SSH_CONFIG, validate=False)
    payload = _normalize_payload(raw_payload)
    if validate:
        errors = validate_payload_against_schema(
            payload, SSH_CONFIG.schema, SSH_CONFIG.name
        )
        if errors:
            raise ValueError("; ".join(errors))
    return payload


def save_ssh_config(payload: dict[str, Any]) -> Path:
    return save_json_config(SSH_CONFIG, _normalize_payload(payload))


def list_hosts(payload: dict[str, Any]) -> list[SshHostConfig]:
    configured = payload.get("hosts", [])
    items: list[SshHostConfig] = []
    for raw_item in configured if isinstance(configured, list) else []:
        if not isinstance(raw_item, dict):
            continue
        name = str(raw_item.get("name") or "").strip()
        username = str(raw_item.get("username") or "").strip()
        if not name or not username:
            continue
        port = raw_item.get("port")
        items.append(
            SshHostConfig(
                name=name,
                ip=str(raw_item.get("ip") or raw_item.get("host") or "").strip(),
                hostname=str(raw_item.get("hostname") or "").strip(),
                port=(
                    int(port)
                    if isinstance(port, int) and port > 0
                    else DEFAULT_SSH_PORT
                ),
                username=username,
                password=str(raw_item.get("password") or "").strip(),
                identity_file=str(raw_item.get("identity_file") or "").strip(),
                notes=str(raw_item.get("notes") or "").strip(),
                raw=dict(raw_item),
            )
        )
    return items


def find_host(payload: dict[str, Any], name: str) -> SshHostConfig | None:
    normalized_name = str(name or "").strip().lower()
    for item in list_hosts(payload):
        if item.name.lower() == normalized_name:
            return item
    return None


def upsert_host(payload: dict[str, Any], host: SshHostConfig) -> dict[str, Any]:
    hosts = payload.setdefault("hosts", [])
    if not isinstance(hosts, list):
        hosts = []
        payload["hosts"] = hosts

    new_raw = {
        **host.raw,
        "name": host.name,
        "ip": host.ip,
        "hostname": host.hostname,
        "port": host.port,
        "username": host.username,
        "password": host.password,
        "identity_file": host.identity_file,
        "notes": host.notes,
    }
    for index, raw_item in enumerate(hosts):
        if (
            str(getattr(raw_item, "get", lambda _k, _d=None: "")("name") or "")
            .strip()
            .lower()
            == host.name.lower()
        ):
            hosts[index] = new_raw
            break
    else:
        hosts.append(new_raw)
    return payload


def list_tunnels(payload: dict[str, Any]) -> list[SshTunnelConfig]:
    configured = payload.get("tunnels", [])
    items: list[SshTunnelConfig] = []
    for raw_item in configured if isinstance(configured, list) else []:
        if not isinstance(raw_item, dict):
            continue
        name = str(raw_item.get("name") or "").strip()
        host_name = str(raw_item.get("host_name") or "").strip()
        if not name or not host_name:
            continue
        local_port = raw_item.get("local_port")
        remote_port = raw_item.get("remote_port")
        if not isinstance(local_port, int) or local_port <= 0:
            continue
        if not isinstance(remote_port, int) or remote_port <= 0:
            continue
        items.append(
            SshTunnelConfig(
                name=name,
                host_name=host_name,
                mode=normalize_tunnel_mode(raw_item.get("mode")),
                local_host=str(
                    raw_item.get("local_host") or DEFAULT_TUNNEL_LOCAL_HOST
                ).strip()
                or DEFAULT_TUNNEL_LOCAL_HOST,
                local_port=local_port,
                remote_host=str(
                    raw_item.get("remote_host") or DEFAULT_TUNNEL_REMOTE_HOST
                ).strip()
                or DEFAULT_TUNNEL_REMOTE_HOST,
                remote_port=remote_port,
                enabled=bool(raw_item.get("enabled", True)),
                server_alive_interval_seconds=(
                    int(raw_item.get("server_alive_interval_seconds"))
                    if isinstance(raw_item.get("server_alive_interval_seconds"), int)
                    and int(raw_item.get("server_alive_interval_seconds")) > 0
                    else DEFAULT_SERVER_ALIVE_INTERVAL_SECONDS
                ),
                server_alive_count_max=(
                    int(raw_item.get("server_alive_count_max"))
                    if isinstance(raw_item.get("server_alive_count_max"), int)
                    and int(raw_item.get("server_alive_count_max")) > 0
                    else DEFAULT_SERVER_ALIVE_COUNT_MAX
                ),
                service_name=str(raw_item.get("service_name") or "").strip(),
                notes=str(raw_item.get("notes") or "").strip(),
                raw=dict(raw_item),
            )
        )
    return items


def find_tunnel(payload: dict[str, Any], name: str) -> SshTunnelConfig | None:
    normalized_name = str(name or "").strip().lower()
    for item in list_tunnels(payload):
        if item.name.lower() == normalized_name:
            return item
    return None


def upsert_tunnel(payload: dict[str, Any], tunnel: SshTunnelConfig) -> dict[str, Any]:
    tunnels = payload.setdefault("tunnels", [])
    if not isinstance(tunnels, list):
        tunnels = []
        payload["tunnels"] = tunnels

    new_raw = {
        **tunnel.raw,
        "name": tunnel.name,
        "host_name": tunnel.host_name,
        "mode": tunnel.mode,
        "local_host": tunnel.local_host,
        "local_port": tunnel.local_port,
        "remote_host": tunnel.remote_host,
        "remote_port": tunnel.remote_port,
        "enabled": tunnel.enabled,
        "server_alive_interval_seconds": tunnel.server_alive_interval_seconds,
        "server_alive_count_max": tunnel.server_alive_count_max,
        "service_name": tunnel.service_name,
        "notes": tunnel.notes,
    }
    for index, raw_item in enumerate(tunnels):
        if (
            str(getattr(raw_item, "get", lambda _k, _d=None: "")("name") or "")
            .strip()
            .lower()
            == tunnel.name.lower()
        ):
            tunnels[index] = new_raw
            break
    else:
        tunnels.append(new_raw)
    return payload
