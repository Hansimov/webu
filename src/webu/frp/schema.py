from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from webu.schema import ConfigSpec, load_json_config, save_json_config


DEFAULT_FRPS_BIND_PORT = 7000
DEFAULT_PROXY_BIND_ADDR = "127.0.0.1"
DEFAULT_FRP_PROTOCOL = "tcp"
DEFAULT_FRPC_LOCAL_HOST = "127.0.0.1"
DEFAULT_FRPC_BINARY = "debugs/frp/bin/frpc"
DEFAULT_FRPC_CONFIG_DIR = "debugs/frp"
_ALLOWED_PROTOCOLS = {"tcp"}


FRP_CONFIG = ConfigSpec(
    name="frp",
    file_name="frp.json",
    purpose=[
        "管理 webu 使用的 frps/frpc 配置、systemd 服务和远端部署目标。",
        "让 wfrp 可以生成 TOML、把 frps 配置部署到远端 VPS，并在本地托管 frpc。",
    ],
    notes=[
        "servers[].ssh_host_name 必须对应 configs/ssh.json 中已配置的远端主机。",
        "server_addr 留空时，wfrp 会回退读取关联 ssh host 的 hostname/ip。",
        "proxy_bind_addr 默认为 127.0.0.1，适合与远端 nginx/openresty 本机反代组合使用。",
        "本文件包含 token 和公网端口规划，属于本地敏感运行时配置，不应提交进 git。",
    ],
    sample={
        "servers": [
            {
                "name": "relay-frps",
                "ssh_host_name": "relay-vps",
                "bind_port": 7000,
                "proxy_bind_addr": "127.0.0.1",
                "auth_token": "replace-me",
                "remote_binary_path": "/root/downloads/frp_0.58.1_linux_amd64/frps",
                "remote_config_path": "/root/downloads/frp_0.58.1_linux_amd64/frps.toml",
                "remote_service_name": "webu-frps-relay.service",
                "notes": "Edge relay FRP server",
            }
        ],
        "clients": [
            {
                "name": "relay-public-web",
                "server_name": "relay-frps",
                "server_addr": "127.0.0.1",
                "server_port": 7000,
                "auth_token": "",
                "protocol": "tcp",
                "local_host": "127.0.0.1",
                "local_port": 20002,
                "remote_port": 32002,
                "binary_path": "debugs/frp/bin/frpc",
                "config_path": "debugs/frp/relay-public-web.frpc.toml",
                "service_name": "",
                "enabled": True,
                "notes": "Expose the local web service to the relay host.",
            }
        ],
    },
    schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "servers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "ssh_host_name": {"type": "string", "minLength": 1},
                        "bind_port": {"type": "integer"},
                        "proxy_bind_addr": {"type": "string"},
                        "auth_token": {"type": "string", "minLength": 1},
                        "remote_binary_path": {"type": "string", "minLength": 1},
                        "remote_config_path": {"type": "string", "minLength": 1},
                        "remote_service_name": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": [
                        "name",
                        "ssh_host_name",
                        "auth_token",
                        "remote_binary_path",
                        "remote_config_path",
                    ],
                },
            },
            "clients": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "server_name": {"type": "string", "minLength": 1},
                        "server_addr": {"type": "string"},
                        "server_port": {"type": "integer"},
                        "auth_token": {"type": "string"},
                        "protocol": {"type": "string", "enum": ["tcp"]},
                        "local_host": {"type": "string", "minLength": 1},
                        "local_port": {"type": "integer"},
                        "remote_port": {"type": "integer"},
                        "binary_path": {"type": "string"},
                        "config_path": {"type": "string"},
                        "service_name": {"type": "string"},
                        "enabled": {"type": "boolean"},
                        "notes": {"type": "string"},
                    },
                    "required": [
                        "name",
                        "server_name",
                        "local_port",
                        "remote_port",
                    ],
                },
            },
        },
    },
)


@dataclass(frozen=True)
class FrpServerConfig:
    name: str
    ssh_host_name: str
    bind_port: int
    proxy_bind_addr: str
    auth_token: str
    remote_binary_path: str
    remote_config_path: str
    remote_service_name: str
    notes: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class FrpClientConfig:
    name: str
    server_name: str
    server_addr: str
    server_port: int
    auth_token: str
    protocol: str
    local_host: str
    local_port: int
    remote_port: int
    binary_path: str
    config_path: str
    service_name: str
    enabled: bool
    notes: str
    raw: dict[str, Any]


def normalize_protocol(value: object, *, fallback: str = DEFAULT_FRP_PROTOCOL) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _ALLOWED_PROTOCOLS:
        return normalized
    return fallback


def load_frp_config(*, validate: bool = True) -> dict[str, Any]:
    payload = load_json_config(FRP_CONFIG, validate=validate)
    return payload if isinstance(payload, dict) else {"servers": [], "clients": []}


def save_frp_config(payload: dict[str, Any]) -> Path:
    normalized = dict(payload or {})
    normalized.setdefault("servers", [])
    normalized.setdefault("clients", [])
    return save_json_config(FRP_CONFIG, normalized)


def list_servers(payload: dict[str, Any]) -> list[FrpServerConfig]:
    configured = payload.get("servers", [])
    items: list[FrpServerConfig] = []
    for raw_item in configured if isinstance(configured, list) else []:
        if not isinstance(raw_item, dict):
            continue
        name = str(raw_item.get("name") or "").strip()
        ssh_host_name = str(raw_item.get("ssh_host_name") or "").strip()
        auth_token = str(raw_item.get("auth_token") or "").strip()
        remote_binary_path = str(raw_item.get("remote_binary_path") or "").strip()
        remote_config_path = str(raw_item.get("remote_config_path") or "").strip()
        if not all(
            [name, ssh_host_name, auth_token, remote_binary_path, remote_config_path]
        ):
            continue
        bind_port = raw_item.get("bind_port")
        items.append(
            FrpServerConfig(
                name=name,
                ssh_host_name=ssh_host_name,
                bind_port=(
                    int(bind_port)
                    if isinstance(bind_port, int) and bind_port > 0
                    else DEFAULT_FRPS_BIND_PORT
                ),
                proxy_bind_addr=str(
                    raw_item.get("proxy_bind_addr") or DEFAULT_PROXY_BIND_ADDR
                ).strip()
                or DEFAULT_PROXY_BIND_ADDR,
                auth_token=auth_token,
                remote_binary_path=remote_binary_path,
                remote_config_path=remote_config_path,
                remote_service_name=str(
                    raw_item.get("remote_service_name") or ""
                ).strip(),
                notes=str(raw_item.get("notes") or "").strip(),
                raw=dict(raw_item),
            )
        )
    return items


def find_server(payload: dict[str, Any], name: str) -> FrpServerConfig | None:
    normalized_name = str(name or "").strip().lower()
    for item in list_servers(payload):
        if item.name.lower() == normalized_name:
            return item
    return None


def upsert_server(payload: dict[str, Any], server: FrpServerConfig) -> dict[str, Any]:
    servers = payload.setdefault("servers", [])
    if not isinstance(servers, list):
        servers = []
        payload["servers"] = servers
    new_raw = {
        **server.raw,
        "name": server.name,
        "ssh_host_name": server.ssh_host_name,
        "bind_port": server.bind_port,
        "proxy_bind_addr": server.proxy_bind_addr,
        "auth_token": server.auth_token,
        "remote_binary_path": server.remote_binary_path,
        "remote_config_path": server.remote_config_path,
        "remote_service_name": server.remote_service_name,
        "notes": server.notes,
    }
    for index, raw_item in enumerate(servers):
        if (
            str(getattr(raw_item, "get", lambda _k, _d=None: "")("name") or "")
            .strip()
            .lower()
            == server.name.lower()
        ):
            servers[index] = new_raw
            break
    else:
        servers.append(new_raw)
    return payload


def list_clients(payload: dict[str, Any]) -> list[FrpClientConfig]:
    configured = payload.get("clients", [])
    items: list[FrpClientConfig] = []
    for raw_item in configured if isinstance(configured, list) else []:
        if not isinstance(raw_item, dict):
            continue
        name = str(raw_item.get("name") or "").strip()
        server_name = str(raw_item.get("server_name") or "").strip()
        if not name or not server_name:
            continue
        local_port = raw_item.get("local_port")
        remote_port = raw_item.get("remote_port")
        if not isinstance(local_port, int) or local_port <= 0:
            continue
        if not isinstance(remote_port, int) or remote_port <= 0:
            continue
        server_port = raw_item.get("server_port")
        items.append(
            FrpClientConfig(
                name=name,
                server_name=server_name,
                server_addr=str(raw_item.get("server_addr") or "").strip(),
                server_port=(
                    int(server_port)
                    if isinstance(server_port, int) and server_port > 0
                    else DEFAULT_FRPS_BIND_PORT
                ),
                auth_token=str(raw_item.get("auth_token") or "").strip(),
                protocol=normalize_protocol(raw_item.get("protocol")),
                local_host=str(
                    raw_item.get("local_host") or DEFAULT_FRPC_LOCAL_HOST
                ).strip()
                or DEFAULT_FRPC_LOCAL_HOST,
                local_port=local_port,
                remote_port=remote_port,
                binary_path=str(
                    raw_item.get("binary_path") or DEFAULT_FRPC_BINARY
                ).strip()
                or DEFAULT_FRPC_BINARY,
                config_path=str(raw_item.get("config_path") or "").strip(),
                service_name=str(raw_item.get("service_name") or "").strip(),
                enabled=bool(raw_item.get("enabled", True)),
                notes=str(raw_item.get("notes") or "").strip(),
                raw=dict(raw_item),
            )
        )
    return items


def find_client(payload: dict[str, Any], name: str) -> FrpClientConfig | None:
    normalized_name = str(name or "").strip().lower()
    for item in list_clients(payload):
        if item.name.lower() == normalized_name:
            return item
    return None


def upsert_client(payload: dict[str, Any], client: FrpClientConfig) -> dict[str, Any]:
    clients = payload.setdefault("clients", [])
    if not isinstance(clients, list):
        clients = []
        payload["clients"] = clients
    new_raw = {
        **client.raw,
        "name": client.name,
        "server_name": client.server_name,
        "server_addr": client.server_addr,
        "server_port": client.server_port,
        "auth_token": client.auth_token,
        "protocol": client.protocol,
        "local_host": client.local_host,
        "local_port": client.local_port,
        "remote_port": client.remote_port,
        "binary_path": client.binary_path,
        "config_path": client.config_path,
        "service_name": client.service_name,
        "enabled": client.enabled,
        "notes": client.notes,
    }
    for index, raw_item in enumerate(clients):
        if (
            str(getattr(raw_item, "get", lambda _k, _d=None: "")("name") or "")
            .strip()
            .lower()
            == client.name.lower()
        ):
            clients[index] = new_raw
            break
    else:
        clients.append(new_raw)
    return payload
