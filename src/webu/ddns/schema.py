from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from webu.schema import ConfigSpec, load_json_config, save_json_config


_ALLOWED_PROVIDERS = {"aliesa-origin-pool"}
_ALLOWED_IPV6_SOURCE_MODES = {"cmd", "url"}

DEFAULT_PROVIDER = "aliesa-origin-pool"
DEFAULT_DDNS_GO_BINARY = "debugs/ddns-go/bin/ddns-go"
DEFAULT_DDNS_GO_CONFIG_DIR = "debugs/ddns-go"
DEFAULT_TARGET_TTL = 600
DEFAULT_TARGET_SEED_IPV6 = "2001:db8::1"
DEFAULT_RUN_INTERVAL_SECONDS = 300
DEFAULT_CACHE_TIMES = 1


DDNS_CONFIG = ConfigSpec(
    name="ddns",
    file_name="ddns.json",
    purpose=[
        "管理 ddns-go 在本地的运行配置和 systemd 服务。",
        "让 wdns 可以为阿里云 ESA origin pool 生成配置、执行单次更新并管理常驻 DDNS 服务。",
    ],
    notes=[
        "当前支持的 provider 是 aliesa-origin-pool，用于维护阿里云 ESA origin pool 中的 origin 地址。",
        "如果 target_ipv6 留空，wdns 会回退读取 configs/ali_esa.json 中的 default_public_origin_ipv6 或站点级 public_origin_address。",
        "如果 binary_path 留空，wdns 会优先尝试使用 ddns_go_binary，然后回退到 debugs/ddns-go/bin/ddns-go 或 PATH 中的 ddns-go。",
        "本文件属于本地运行时配置，不应提交真实站点、origin 或公网地址。",
    ],
    sample={
        "ddns_go_binary": DEFAULT_DDNS_GO_BINARY,
        "default_run_interval_seconds": DEFAULT_RUN_INTERVAL_SECONDS,
        "default_cache_times": DEFAULT_CACHE_TIMES,
        "targets": [],
    },
    schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "ddns_go_binary": {"type": "string"},
            "default_run_interval_seconds": {"type": "integer"},
            "default_cache_times": {"type": "integer"},
            "targets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "provider": {
                            "type": "string",
                            "enum": ["aliesa-origin-pool"],
                        },
                        "site_name": {"type": "string", "minLength": 1},
                        "pool_name": {"type": "string", "minLength": 1},
                        "origin_name": {"type": "string", "minLength": 1},
                        "enabled": {"type": "boolean"},
                        "target_ipv6": {"type": "string"},
                        "seed_ipv6": {"type": "string"},
                        "ipv6_source_mode": {
                            "type": "string",
                            "enum": ["cmd", "url"],
                        },
                        "ipv6_url": {"type": "string"},
                        "ttl": {"type": "integer"},
                        "binary_path": {"type": "string"},
                        "config_path": {"type": "string"},
                        "run_interval_seconds": {"type": "integer"},
                        "cache_times": {"type": "integer"},
                        "service_name": {"type": "string"},
                    },
                    "required": [
                        "name",
                        "provider",
                        "site_name",
                        "pool_name",
                        "origin_name",
                    ],
                },
            },
        },
    },
)


@dataclass(frozen=True)
class DdnsTargetConfig:
    name: str
    provider: str
    site_name: str
    pool_name: str
    origin_name: str
    enabled: bool
    target_ipv6: str
    seed_ipv6: str
    ipv6_source_mode: str
    ipv6_url: str
    ttl: int
    binary_path: str
    config_path: str
    run_interval_seconds: int
    cache_times: int
    service_name: str
    raw: dict[str, Any]


def normalize_provider(value: object, *, fallback: str = DEFAULT_PROVIDER) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _ALLOWED_PROVIDERS:
        return normalized
    return fallback


def normalize_ipv6_source_mode(value: object, *, fallback: str = "cmd") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _ALLOWED_IPV6_SOURCE_MODES:
        return normalized
    return fallback


def load_ddns_config(*, validate: bool = True) -> dict[str, Any]:
    payload = load_json_config(DDNS_CONFIG, validate=validate)
    return payload if isinstance(payload, dict) else {}


def save_ddns_config(payload: dict[str, Any]) -> Path:
    return save_json_config(DDNS_CONFIG, payload)


def list_targets(payload: dict[str, Any]) -> list[DdnsTargetConfig]:
    configured = payload.get("targets", [])
    items: list[DdnsTargetConfig] = []
    default_interval = payload.get("default_run_interval_seconds")
    default_cache_times = payload.get("default_cache_times")

    for raw_item in configured if isinstance(configured, list) else []:
        if not isinstance(raw_item, dict):
            continue
        name = str(raw_item.get("name") or "").strip()
        site_name = str(raw_item.get("site_name") or "").strip()
        pool_name = str(raw_item.get("pool_name") or "").strip()
        origin_name = str(raw_item.get("origin_name") or "").strip()
        if not name or not site_name or not pool_name or not origin_name:
            continue
        ttl = raw_item.get("ttl")
        run_interval_seconds = raw_item.get("run_interval_seconds")
        cache_times = raw_item.get("cache_times")
        items.append(
            DdnsTargetConfig(
                name=name,
                provider=normalize_provider(raw_item.get("provider")),
                site_name=site_name,
                pool_name=pool_name,
                origin_name=origin_name,
                enabled=bool(raw_item.get("enabled", True)),
                target_ipv6=str(raw_item.get("target_ipv6") or "").strip(),
                seed_ipv6=str(
                    raw_item.get("seed_ipv6") or DEFAULT_TARGET_SEED_IPV6
                ).strip()
                or DEFAULT_TARGET_SEED_IPV6,
                ipv6_source_mode=normalize_ipv6_source_mode(
                    raw_item.get("ipv6_source_mode")
                ),
                ipv6_url=str(
                    raw_item.get("ipv6_url") or "https://api6.ipify.org"
                ).strip()
                or "https://api6.ipify.org",
                ttl=(
                    int(ttl) if isinstance(ttl, int) and ttl > 0 else DEFAULT_TARGET_TTL
                ),
                binary_path=str(raw_item.get("binary_path") or "").strip(),
                config_path=str(raw_item.get("config_path") or "").strip(),
                run_interval_seconds=(
                    int(run_interval_seconds)
                    if isinstance(run_interval_seconds, int)
                    and run_interval_seconds > 0
                    else (
                        int(default_interval)
                        if isinstance(default_interval, int) and default_interval > 0
                        else DEFAULT_RUN_INTERVAL_SECONDS
                    )
                ),
                cache_times=(
                    int(cache_times)
                    if isinstance(cache_times, int) and cache_times > 0
                    else (
                        int(default_cache_times)
                        if isinstance(default_cache_times, int)
                        and default_cache_times > 0
                        else DEFAULT_CACHE_TIMES
                    )
                ),
                service_name=str(raw_item.get("service_name") or "").strip(),
                raw=dict(raw_item),
            )
        )
    return items


def find_target(payload: dict[str, Any], name: str) -> DdnsTargetConfig | None:
    normalized_name = str(name or "").strip().lower()
    for target in list_targets(payload):
        if target.name.lower() == normalized_name:
            return target
    return None


def upsert_target(payload: dict[str, Any], target: DdnsTargetConfig) -> dict[str, Any]:
    targets = payload.setdefault("targets", [])
    if not isinstance(targets, list):
        targets = []
        payload["targets"] = targets

    new_raw = {
        **target.raw,
        "name": target.name,
        "provider": target.provider,
        "site_name": target.site_name,
        "pool_name": target.pool_name,
        "origin_name": target.origin_name,
        "enabled": target.enabled,
        "target_ipv6": target.target_ipv6,
        "seed_ipv6": target.seed_ipv6,
        "ipv6_source_mode": target.ipv6_source_mode,
        "ipv6_url": target.ipv6_url,
        "ttl": target.ttl,
        "binary_path": target.binary_path,
        "config_path": target.config_path,
        "run_interval_seconds": target.run_interval_seconds,
        "cache_times": target.cache_times,
        "service_name": target.service_name,
    }

    for index, item in enumerate(targets):
        if (
            isinstance(item, dict)
            and str(item.get("name") or "").strip().lower() == target.name.lower()
        ):
            targets[index] = new_raw
            return payload

    targets.append(new_raw)
    return payload


def delete_target(
    payload: dict[str, Any], name: str
) -> tuple[dict[str, Any], DdnsTargetConfig | None]:
    targets = payload.get("targets", [])
    if not isinstance(targets, list):
        payload["targets"] = []
        return payload, None

    removed = find_target(payload, name)
    normalized_name = str(name or "").strip().lower()
    payload["targets"] = [
        item
        for item in targets
        if not (
            isinstance(item, dict)
            and str(item.get("name") or "").strip().lower() == normalized_name
        )
    ]
    return payload, removed
