from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from webu.cf_tunnel.schema import infer_zone_name, list_domains, load_cf_tunnel_config
from webu.schema import ConfigSpec, load_json_config, save_json_config


_ALLOWED_COVERAGES = {"domestic", "global", "overseas"}
_ALLOWED_ACCESS_TYPES = {"NS", "CNAME"}


ALI_ESA_CONFIG = ConfigSpec(
    name="ali_esa",
    file_name="ali_esa.json",
    purpose=[
        "管理阿里云 ESA 的站点、计划实例、DNS 切换和公开暴露配置。",
        "让 aesa 能完成站点创建、Cloudflare DNS 迁移、ESA 记录和回源规则同步。",
    ],
    notes=[
        "如果 aliyun_access_id / aliyun_access_secret 留空，aesa 会回退读取 configs/cf_tunnel.json 里的阿里云凭据。",
        "如果 cf_api_token / cf_account_id 留空，aesa 会回退读取 configs/cf_tunnel.json 里的 Cloudflare 工作凭据。",
        "默认建议先把站点 coverage 设为 overseas；如果要用 domestic 或 global，请先确认域名已经完成备案。",
        "default_public_origin_ipv4 / default_public_origin_ipv6 和 sites[].public_origin_address 用于保存真实回源地址；这些值只应存在于本地 ali_esa.json，不应硬编码进公开源码。",
        "sites[].cloudflare_zone_id 用于从当前 Cloudflare zone 导入 DNS 记录；如果为空，aesa 会尝试按 site_name 匹配 cf_tunnel.json 中的 zone 元数据。",
        "本文件包含敏感信息和控制面状态，不应出现在公开文档、测试断言或日志输出中。",
    ],
    sample={
        "region_id": "cn-hangzhou",
        "default_instance_id": "",
        "default_coverage": "overseas",
        "default_access_type": "NS",
        "public_origin_detection_url": "https://ifconfig.me/ip",
        "default_public_origin_ipv4": "",
        "default_public_origin_ipv6": "",
        "aliyun_access_id": "",
        "aliyun_access_secret": "",
        "cf_api_token": "",
        "cf_account_id": "",
        "sites": [
            {
                "site_name": "example.com",
                "coverage": "overseas",
                "access_type": "NS",
                "instance_id": "",
                "site_id": 0,
                "status": "",
                "verify_code": "",
                "name_server_list": [],
                "current_ns": [],
                "public_origin_address": "",
                "cloudflare_zone_id": "",
                "registrar_task_no": "",
                "last_verified_at": "",
                "last_cloudflare_sync_at": "",
                "last_exposure_applied_at": "",
            }
        ],
    },
    schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "region_id": {"type": "string"},
            "default_instance_id": {"type": "string"},
            "default_coverage": {
                "type": "string",
                "enum": ["domestic", "global", "overseas"],
            },
            "default_access_type": {
                "type": "string",
                "enum": ["NS", "CNAME"],
            },
            "public_origin_detection_url": {"type": "string"},
            "default_public_origin_ipv4": {"type": "string"},
            "default_public_origin_ipv6": {"type": "string"},
            "aliyun_access_id": {"type": "string"},
            "aliyun_access_secret": {"type": "string"},
            "cf_api_token": {"type": "string"},
            "cf_account_id": {"type": "string"},
            "sites": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "site_name": {"type": "string", "minLength": 1},
                        "coverage": {
                            "type": "string",
                            "enum": ["domestic", "global", "overseas"],
                        },
                        "access_type": {
                            "type": "string",
                            "enum": ["NS", "CNAME"],
                        },
                        "instance_id": {"type": "string"},
                        "site_id": {"type": "integer"},
                        "status": {"type": "string"},
                        "verify_code": {"type": "string"},
                        "name_server_list": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "current_ns": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "public_origin_address": {"type": "string"},
                        "cloudflare_zone_id": {"type": "string"},
                        "registrar_task_no": {"type": "string"},
                        "last_verified_at": {"type": "string"},
                        "last_cloudflare_sync_at": {"type": "string"},
                        "last_exposure_applied_at": {"type": "string"},
                    },
                    "required": ["site_name"],
                },
            },
        },
    },
)


@dataclass(frozen=True)
class SiteConfig:
    site_name: str
    coverage: str
    access_type: str
    instance_id: str
    site_id: int | None
    status: str
    verify_code: str
    name_server_list: list[str]
    current_ns: list[str]
    public_origin_address: str
    cloudflare_zone_id: str
    registrar_task_no: str
    last_verified_at: str
    last_cloudflare_sync_at: str
    last_exposure_applied_at: str
    raw: dict[str, Any]


def _normalize_string_list(raw_value: object) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    values: list[str] = []
    for item in raw_value:
        value = str(item or "").strip()
        if value:
            values.append(value)
    return values


def normalize_coverage(value: object, *, fallback: str = "overseas") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _ALLOWED_COVERAGES:
        return normalized
    return fallback


def normalize_access_type(value: object, *, fallback: str = "NS") -> str:
    normalized = str(value or "").strip().upper()
    if normalized in _ALLOWED_ACCESS_TYPES:
        return normalized
    return fallback


def infer_site_name(hostname: str) -> str:
    return infer_zone_name(hostname)


def load_ali_esa_config(*, validate: bool = True) -> dict[str, Any]:
    payload = load_json_config(ALI_ESA_CONFIG, validate=validate)
    return payload if isinstance(payload, dict) else {}


def save_ali_esa_config(payload: dict[str, Any]) -> Path:
    return save_json_config(ALI_ESA_CONFIG, payload)


def list_sites(payload: dict[str, Any]) -> list[SiteConfig]:
    configured = payload.get("sites", [])
    items: list[SiteConfig] = []
    for raw_item in configured if isinstance(configured, list) else []:
        if not isinstance(raw_item, dict):
            continue
        site_name = str(raw_item.get("site_name", "")).strip()
        if not site_name:
            continue
        site_id = raw_item.get("site_id")
        items.append(
            SiteConfig(
                site_name=site_name,
                coverage=normalize_coverage(
                    raw_item.get("coverage"),
                    fallback=normalize_coverage(payload.get("default_coverage")),
                ),
                access_type=normalize_access_type(
                    raw_item.get("access_type"),
                    fallback=normalize_access_type(
                        payload.get("default_access_type"),
                    ),
                ),
                instance_id=str(raw_item.get("instance_id", "")).strip(),
                site_id=site_id if isinstance(site_id, int) and site_id > 0 else None,
                status=str(raw_item.get("status", "")).strip(),
                verify_code=str(raw_item.get("verify_code", "")).strip(),
                name_server_list=_normalize_string_list(
                    raw_item.get("name_server_list")
                ),
                current_ns=_normalize_string_list(raw_item.get("current_ns")),
                public_origin_address=str(
                    raw_item.get("public_origin_address", "")
                ).strip(),
                cloudflare_zone_id=str(raw_item.get("cloudflare_zone_id", "")).strip(),
                registrar_task_no=str(raw_item.get("registrar_task_no", "")).strip(),
                last_verified_at=str(raw_item.get("last_verified_at", "")).strip(),
                last_cloudflare_sync_at=str(
                    raw_item.get("last_cloudflare_sync_at", "")
                ).strip(),
                last_exposure_applied_at=str(
                    raw_item.get("last_exposure_applied_at", "")
                ).strip(),
                raw=dict(raw_item),
            )
        )
    return items


def find_site(payload: dict[str, Any], site_name: str) -> SiteConfig | None:
    normalized_site_name = str(site_name or "").strip().lower()
    for site in list_sites(payload):
        if site.site_name.lower() == normalized_site_name:
            return site
    return None


def upsert_site(payload: dict[str, Any], site: SiteConfig) -> dict[str, Any]:
    sites = payload.setdefault("sites", [])
    if not isinstance(sites, list):
        sites = []
        payload["sites"] = sites

    new_raw = {
        **site.raw,
        "site_name": site.site_name,
        "coverage": site.coverage,
        "access_type": site.access_type,
        "instance_id": site.instance_id,
        "status": site.status,
        "verify_code": site.verify_code,
        "name_server_list": site.name_server_list,
        "current_ns": site.current_ns,
        "public_origin_address": site.public_origin_address,
        "cloudflare_zone_id": site.cloudflare_zone_id,
        "registrar_task_no": site.registrar_task_no,
        "last_verified_at": site.last_verified_at,
        "last_cloudflare_sync_at": site.last_cloudflare_sync_at,
        "last_exposure_applied_at": site.last_exposure_applied_at,
    }
    if site.site_id is not None:
        new_raw["site_id"] = site.site_id
    else:
        new_raw.pop("site_id", None)

    for index, item in enumerate(sites):
        if (
            isinstance(item, dict)
            and str(item.get("site_name", "")).strip().lower() == site.site_name.lower()
        ):
            sites[index] = new_raw
            return payload

    sites.append(new_raw)
    return payload


def resolve_credentials(payload: dict[str, Any]) -> dict[str, str]:
    try:
        cf_tunnel_payload = load_cf_tunnel_config()
    except Exception:
        cf_tunnel_payload = {}

    return {
        "region_id": str(payload.get("region_id") or "cn-hangzhou").strip()
        or "cn-hangzhou",
        "aliyun_access_id": str(
            payload.get("aliyun_access_id")
            or cf_tunnel_payload.get("aliyun_access_id")
            or ""
        ).strip(),
        "aliyun_access_secret": str(
            payload.get("aliyun_access_secret")
            or cf_tunnel_payload.get("aliyun_access_secret")
            or ""
        ).strip(),
        "cf_api_token": str(
            payload.get("cf_api_token") or cf_tunnel_payload.get("cf_api_token") or ""
        ).strip(),
        "cf_bootstrap_token": str(
            cf_tunnel_payload.get("cf_account_api_tokens_edit_token") or ""
        ).strip(),
        "cf_account_id": str(
            payload.get("cf_account_id") or cf_tunnel_payload.get("cf_account_id") or ""
        ).strip(),
    }


def resolve_cloudflare_zone_id(payload: dict[str, Any], site_name: str) -> str:
    site = find_site(payload, site_name)
    if site is not None and site.cloudflare_zone_id:
        return site.cloudflare_zone_id

    try:
        cf_tunnel_payload = load_cf_tunnel_config()
    except Exception:
        return ""

    normalized_site_name = str(site_name or "").strip().lower()
    for domain in list_domains(cf_tunnel_payload):
        if domain.zone_name.lower() == normalized_site_name and domain.zone_id:
            return domain.zone_id
    return ""
