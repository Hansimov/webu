from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from webu.schema import ConfigSpec, load_json_config, save_json_config


_TUNNEL_ORIGIN_REQUEST_TEXT_FIELDS = {
    "http_host_header",
}
_TUNNEL_ORIGIN_REQUEST_BOOL_FIELDS = {
    "disable_chunked_encoding",
    "no_happy_eyeballs",
}
_TUNNEL_ORIGIN_REQUEST_INT_FIELDS = {
    "connect_timeout",
    "keep_alive_connections",
    "keep_alive_timeout",
    "tcp_keep_alive",
}


CF_TUNNEL_CONFIG = ConfigSpec(
    name="cf_tunnel",
    file_name="cf_tunnel.json",
    purpose=[
        "管理 Cloudflare zone、API token、remote-managed tunnel 和阿里云注册商凭据。",
        "让 cftn 能在命令行完成 DNS 迁移、Tunnel 创建、Tunnel 安装与状态查询。",
    ],
    notes=[
        "cf_account_api_tokens_edit_token 是可选的 bootstrap token，仅用于自动创建后续更小权限的工作 token。",
        "cf_api_token 可直接作为工作 token 使用；若为空且选择 --cf-token-mode auto，则优先尝试自动创建。",
        "复杂公共后缀域名请显式填写 zone_name，不要依赖自动推断。",
        "domains[].zone_id、domains[].cloudflare_nameservers、domains[].aliyun_task_no 会在 dns-migrate 成功后自动回写。",
        "cf_tunnels[].tunnel_id、cf_tunnels[].tunnel_token 会在 tunnel-apply 成功后自动回写。",
        "本文件包含敏感信息，不应出现在公开文档、测试断言或日志输出中。",
    ],
    sample={
        "cf_account_id": "<cloudflare-account-id>",
        "cf_api_token": "",
        "cf_account_api_tokens_edit_token": "",
        "domains": [
            {
                "domain_name": "example.com",
                "zone_name": "example.com",
                "zone_id": "",
                "cloudflare_nameservers": [],
                "aliyun_task_no": "",
            }
        ],
        "cf_tunnels": [
            {
                "tunnel_name": "dev.example.com",
                "zone_name": "example.com",
                "domain_name": "dev.example.com",
                "local_url": "http://127.0.0.1:21002",
                "origin_request": {
                    "connect_timeout": 5,
                    "keep_alive_connections": 256,
                    "keep_alive_timeout": 120,
                },
                "tunnel_id": "",
                "tunnel_token": "",
            }
        ],
        "aliyun_access_id": "",
        "aliyun_access_secret": "",
    },
    schema={
        "type": "object",
        "properties": {
            "cf_account_id": {"type": "string"},
            "cf_api_token": {"type": "string"},
            "cf_account_api_tokens_edit_token": {"type": "string"},
            "aliyun_access_id": {"type": "string"},
            "aliyun_access_secret": {"type": "string"},
            "domains": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "domain_name": {"type": "string", "minLength": 1},
                        "zone_name": {"type": "string"},
                        "zone_id": {"type": "string"},
                        "cloudflare_nameservers": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "aliyun_task_no": {"type": "string"},
                    },
                    "required": ["domain_name"],
                },
            },
            "cf_tunnels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tunnel_name": {"type": "string", "minLength": 1},
                        "zone_name": {"type": "string"},
                        "domain_name": {"type": "string", "minLength": 1},
                        "local_url": {"type": "string", "minLength": 1},
                        "origin_request": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "connect_timeout": {
                                    "type": "integer",
                                    "minimum": 1,
                                },
                                "keep_alive_connections": {
                                    "type": "integer",
                                    "minimum": 1,
                                },
                                "keep_alive_timeout": {
                                    "type": "integer",
                                    "minimum": 1,
                                },
                                "tcp_keep_alive": {
                                    "type": "integer",
                                    "minimum": 1,
                                },
                                "http_host_header": {
                                    "type": "string",
                                    "minLength": 1,
                                },
                                "disable_chunked_encoding": {"type": "boolean"},
                                "no_happy_eyeballs": {"type": "boolean"},
                            },
                        },
                        "tunnel_id": {"type": "string"},
                        "tunnel_token": {"type": "string"},
                    },
                    "required": ["tunnel_name", "domain_name", "local_url"],
                },
            },
        },
    },
)


@dataclass(frozen=True)
class DomainConfig:
    domain_name: str
    zone_name: str
    zone_id: str
    cloudflare_nameservers: list[str]
    aliyun_task_no: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class TunnelConfig:
    tunnel_name: str
    domain_name: str
    local_url: str
    zone_name: str
    origin_request: dict[str, Any]
    tunnel_id: str
    tunnel_token: str
    raw: dict[str, Any]


def _normalize_tunnel_origin_request(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}

    normalized: dict[str, Any] = {}
    for field in _TUNNEL_ORIGIN_REQUEST_TEXT_FIELDS:
        value = str(raw.get(field, "")).strip()
        if value:
            normalized[field] = value

    for field in _TUNNEL_ORIGIN_REQUEST_BOOL_FIELDS:
        value = raw.get(field)
        if isinstance(value, bool):
            normalized[field] = value

    for field in _TUNNEL_ORIGIN_REQUEST_INT_FIELDS:
        value = raw.get(field)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value > 0:
            normalized[field] = value

    return normalized


def infer_zone_name(hostname: str) -> str:
    labels = [part for part in str(hostname).strip().split(".") if part]
    if len(labels) <= 2:
        return ".".join(labels)
    return ".".join(labels[-2:])


def load_cf_tunnel_config() -> dict[str, Any]:
    payload = load_json_config(CF_TUNNEL_CONFIG)
    return payload if isinstance(payload, dict) else {}


def save_cf_tunnel_config(payload: dict[str, Any]) -> Path:
    return save_json_config(CF_TUNNEL_CONFIG, payload)


def list_domains(payload: dict[str, Any]) -> list[DomainConfig]:
    configured = payload.get("domains", [])
    items: list[DomainConfig] = []
    for raw_item in configured if isinstance(configured, list) else []:
        if not isinstance(raw_item, dict):
            continue
        domain_name = str(raw_item.get("domain_name", "")).strip()
        if not domain_name:
            continue
        zone_name = str(raw_item.get("zone_name", "")).strip() or infer_zone_name(
            domain_name
        )
        nameservers = raw_item.get("cloudflare_nameservers", [])
        items.append(
            DomainConfig(
                domain_name=domain_name,
                zone_name=zone_name,
                zone_id=str(raw_item.get("zone_id", "")).strip(),
                cloudflare_nameservers=[
                    str(item).strip() for item in nameservers if str(item).strip()
                ],
                aliyun_task_no=str(raw_item.get("aliyun_task_no", "")).strip(),
                raw=dict(raw_item),
            )
        )
    return items


def list_tunnels(payload: dict[str, Any]) -> list[TunnelConfig]:
    configured = payload.get("cf_tunnels", [])
    items: list[TunnelConfig] = []
    for raw_item in configured if isinstance(configured, list) else []:
        if not isinstance(raw_item, dict):
            continue
        tunnel_name = str(raw_item.get("tunnel_name", "")).strip()
        domain_name = str(raw_item.get("domain_name", "")).strip()
        local_url = str(raw_item.get("local_url", "")).strip()
        if not tunnel_name or not domain_name or not local_url:
            continue
        zone_name = str(raw_item.get("zone_name", "")).strip() or infer_zone_name(
            domain_name
        )
        items.append(
            TunnelConfig(
                tunnel_name=tunnel_name,
                domain_name=domain_name,
                local_url=local_url,
                zone_name=zone_name,
                origin_request=_normalize_tunnel_origin_request(
                    raw_item.get("origin_request", {})
                ),
                tunnel_id=str(raw_item.get("tunnel_id", "")).strip(),
                tunnel_token=str(raw_item.get("tunnel_token", "")).strip(),
                raw=dict(raw_item),
            )
        )
    return items


def upsert_domain(payload: dict[str, Any], domain: DomainConfig) -> dict[str, Any]:
    domains = payload.setdefault("domains", [])
    if not isinstance(domains, list):
        domains = []
        payload["domains"] = domains
    new_raw = {
        **domain.raw,
        "domain_name": domain.domain_name,
        "zone_name": domain.zone_name,
        "zone_id": domain.zone_id,
        "cloudflare_nameservers": domain.cloudflare_nameservers,
        "aliyun_task_no": domain.aliyun_task_no,
    }
    for index, item in enumerate(domains):
        if (
            isinstance(item, dict)
            and str(item.get("domain_name", "")).strip() == domain.domain_name
        ):
            domains[index] = new_raw
            return payload
    domains.append(new_raw)
    return payload


def upsert_tunnel(payload: dict[str, Any], tunnel: TunnelConfig) -> dict[str, Any]:
    tunnels = payload.setdefault("cf_tunnels", [])
    if not isinstance(tunnels, list):
        tunnels = []
        payload["cf_tunnels"] = tunnels
    new_raw = {
        **tunnel.raw,
        "tunnel_name": tunnel.tunnel_name,
        "zone_name": tunnel.zone_name,
        "domain_name": tunnel.domain_name,
        "local_url": tunnel.local_url,
        "tunnel_id": tunnel.tunnel_id,
        "tunnel_token": tunnel.tunnel_token,
    }
    if tunnel.origin_request:
        new_raw["origin_request"] = tunnel.origin_request
    else:
        new_raw.pop("origin_request", None)
    for index, item in enumerate(tunnels):
        if (
            isinstance(item, dict)
            and str(item.get("tunnel_name", "")).strip() == tunnel.tunnel_name
        ):
            tunnels[index] = new_raw
            return payload
    tunnels.append(new_raw)
    return payload
