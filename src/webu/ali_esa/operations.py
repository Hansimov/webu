from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time

from datetime import UTC, datetime
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from webu.cf_tunnel.clients import (
    AliyunApiError,
    AliyunDomainClient,
    CloudflareApiError,
    CloudflareClient,
)
from webu.cf_tunnel.schema import list_domains, load_cf_tunnel_config
from webu.schema import (
    find_project_root,
    render_template_json,
    validate_payload_against_schema,
)

from .clients import AliyunEsaApiError, AliyunEsaClient
from .schema import (
    ALI_ESA_CONFIG,
    SiteConfig,
    find_site,
    infer_site_name,
    list_sites,
    load_ali_esa_config,
    normalize_access_type,
    normalize_coverage,
    resolve_cloudflare_zone_id,
    resolve_credentials,
    save_ali_esa_config,
    upsert_site,
)


DEFAULT_SNAPSHOT_OUTPUT_DIR = Path("debugs/ali-esa-snapshots")
DEFAULT_PUBLIC_IP_DETECTION_URL = "https://ifconfig.me/ip"
DEFAULT_SITE_VERIFY_ATTEMPTS = 10
DEFAULT_SITE_VERIFY_INTERVAL_SECONDS = 15
DEFAULT_EXPOSURE_RECORD_MODE = "direct"
DEFAULT_EXPOSURE_RETRY_ATTEMPTS = 3
DEFAULT_EXPOSURE_RETRY_DELAY_SECONDS = 1.0
SUPPORTED_CLOUDFLARE_IMPORT_RECORD_TYPES = {
    "A",
    "AAAA",
    "CNAME",
    "TXT",
    "MX",
    "NS",
    "CAA",
    "SRV",
}
_PUBLIC_EDGE_REASON_CODES = {
    "dns_lookup_failed",
    "dns_mismatch",
    "recursive_dns_mismatch",
}
_ESA_ADDRESS_RECORD_TYPE = "A/AAAA"
_IPV6_UNIQUE_LOCAL_NETWORK = ip_network("fc00::/7")


def _require_text(value: object, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _safe_token(value: str) -> str:
    return (
        re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
        or "default"
    )


def _normalize_nameservers(raw_value: object) -> list[str]:
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    if isinstance(raw_value, str):
        return [item.strip() for item in raw_value.split(",") if item.strip()]
    return []


def _project_relative_output_dir(output_dir: Path | str | None) -> Path:
    candidate = Path(output_dir or DEFAULT_SNAPSHOT_OUTPUT_DIR).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (find_project_root() / candidate).resolve()


def _serialize_site(site: SiteConfig | dict[str, Any] | None) -> dict[str, Any] | None:
    if site is None:
        return None
    if isinstance(site, dict):
        payload = dict(site)
    else:
        payload = {
            "site_name": site.site_name,
            "coverage": site.coverage,
            "access_type": site.access_type,
            "instance_id": site.instance_id,
            "site_id": site.site_id,
            "status": site.status,
            "verify_code": site.verify_code,
            "name_server_list": site.name_server_list,
            "current_ns": site.current_ns,
            "cloudflare_name_server_list": site.cloudflare_name_server_list,
            "public_origin_address": site.public_origin_address,
            "cloudflare_zone_id": site.cloudflare_zone_id,
            "registrar_task_no": site.registrar_task_no,
            "last_verified_at": site.last_verified_at,
            "last_cloudflare_sync_at": site.last_cloudflare_sync_at,
            "last_exposure_applied_at": site.last_exposure_applied_at,
        }
    if payload.get("site_id") in {0, "0", None, ""}:
        payload.pop("site_id", None)
    return payload


def _build_esa_client(config_payload: dict[str, Any]) -> AliyunEsaClient:
    credentials = resolve_credentials(config_payload)
    access_key_id = _require_text(
        credentials.get("aliyun_access_id"), "aliyun_access_id"
    )
    access_key_secret = _require_text(
        credentials.get("aliyun_access_secret"),
        "aliyun_access_secret",
    )
    return AliyunEsaClient(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        region_id=str(credentials.get("region_id") or "cn-hangzhou").strip()
        or "cn-hangzhou",
    )


def _build_registrar_client(config_payload: dict[str, Any]) -> AliyunDomainClient:
    credentials = resolve_credentials(config_payload)
    access_key_id = _require_text(
        credentials.get("aliyun_access_id"), "aliyun_access_id"
    )
    access_key_secret = _require_text(
        credentials.get("aliyun_access_secret"),
        "aliyun_access_secret",
    )
    return AliyunDomainClient(access_key_id, access_key_secret)


def _build_cloudflare_client(config_payload: dict[str, Any]) -> CloudflareClient:
    credentials = resolve_credentials(config_payload)
    candidate_tokens: list[str] = []
    for raw_value in [
        credentials.get("cf_api_token"),
        credentials.get("cf_bootstrap_token"),
    ]:
        normalized = str(raw_value or "").strip()
        if normalized and normalized not in candidate_tokens:
            candidate_tokens.append(normalized)
    if not candidate_tokens:
        raise ValueError(
            "Neither cf_api_token nor cf_account_api_tokens_edit_token is available"
        )

    last_error: Exception | None = None
    for token in candidate_tokens:
        client = CloudflareClient(token)
        try:
            client.verify_token()
        except CloudflareApiError as exc:
            last_error = exc
            continue
        return client

    detail = str(last_error or "Cloudflare authentication failed").strip()
    raise ValueError(detail or "Cloudflare authentication failed")


def _pick_plan_instance(
    plan_instances: list[dict[str, Any]],
    *,
    requested_instance_id: str | None,
    coverage: str,
) -> dict[str, Any]:
    normalized_requested_instance_id = str(requested_instance_id or "").strip()
    filtered = [
        item
        for item in plan_instances
        if not normalized_requested_instance_id
        or str(item.get("InstanceId") or "").strip() == normalized_requested_instance_id
    ]
    if normalized_requested_instance_id and not filtered:
        raise ValueError(
            f"ESA plan instance '{normalized_requested_instance_id}' is not available"
        )

    coverage_matches = [
        item
        for item in filtered
        if coverage
        in {
            part.strip()
            for part in str(item.get("Coverages") or "").split(",")
            if part.strip()
        }
    ]
    if coverage_matches:
        filtered = coverage_matches

    if not filtered:
        raise ValueError(
            f"No online ESA plan instance with remaining site quota matches coverage '{coverage}'"
        )

    if normalized_requested_instance_id:
        return filtered[0]
    if len(filtered) == 1:
        return filtered[0]
    raise ValueError(
        "Multiple ESA plan instances match the requested coverage; please specify --instance-id or set default_instance_id in configs/ali_esa.json"
    )


def _upsert_site_payload(
    config_payload: dict[str, Any],
    *,
    site_name: str,
    coverage: str,
    access_type: str,
    instance_id: str,
    site_data: dict[str, Any],
    current_ns: list[str] | None = None,
    cloudflare_name_server_list: list[str] | None = None,
    public_origin_address: str | None = None,
    registrar_task_no: str | None = None,
    last_verified_at: str | None = None,
    last_cloudflare_sync_at: str | None = None,
    last_exposure_applied_at: str | None = None,
) -> SiteConfig:
    existing = find_site(config_payload, site_name)
    raw = dict(existing.raw) if existing is not None else {}
    site_id = site_data.get("SiteId") or site_data.get("site_id")
    status = str(site_data.get("Status") or site_data.get("status") or "").strip()
    verify_code = str(
        site_data.get("VerifyCode") or site_data.get("verify_code") or ""
    ).strip()
    name_server_list = _normalize_nameservers(
        site_data.get("NameServerList")
        or site_data.get("name_server_list")
        or (existing.name_server_list if existing is not None else [])
    )

    site = SiteConfig(
        site_name=site_name,
        coverage=coverage,
        access_type=access_type,
        instance_id=instance_id,
        site_id=site_id if isinstance(site_id, int) and site_id > 0 else None,
        status=status or (existing.status if existing is not None else ""),
        verify_code=verify_code
        or (existing.verify_code if existing is not None else ""),
        name_server_list=name_server_list,
        current_ns=(
            current_ns
            if current_ns is not None
            else (existing.current_ns if existing is not None else [])
        ),
        cloudflare_name_server_list=(
            cloudflare_name_server_list
            if cloudflare_name_server_list is not None
            else (existing.cloudflare_name_server_list if existing is not None else [])
        ),
        public_origin_address=str(
            public_origin_address
            or (existing.public_origin_address if existing is not None else "")
        ).strip(),
        cloudflare_zone_id=(
            str(site_data.get("cloudflare_zone_id") or "").strip()
            or (existing.cloudflare_zone_id if existing is not None else "")
            or resolve_cloudflare_zone_id(config_payload, site_name)
        ),
        registrar_task_no=str(
            registrar_task_no
            or (existing.registrar_task_no if existing is not None else "")
        ).strip(),
        last_verified_at=str(
            last_verified_at
            or (existing.last_verified_at if existing is not None else "")
        ).strip(),
        last_cloudflare_sync_at=str(
            last_cloudflare_sync_at
            or (existing.last_cloudflare_sync_at if existing is not None else "")
        ).strip(),
        last_exposure_applied_at=str(
            last_exposure_applied_at
            or (existing.last_exposure_applied_at if existing is not None else "")
        ).strip(),
        raw=raw,
    )
    upsert_site(config_payload, site)
    return site


def _persist_config_if_requested(
    config_payload: dict[str, Any],
    *,
    save_config: bool,
) -> str | None:
    if not save_config:
        return None
    return str(save_ali_esa_config(config_payload))


def _parse_origin(local_url: str) -> dict[str, Any]:
    parsed = urlparse(_require_text(local_url, "local_url"))
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("local_url must use http or https")
    if parsed.port is None:
        raise ValueError("local_url must include an explicit port")
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname or "",
        "port": parsed.port,
        "path": parsed.path or "/",
    }


def _detect_public_ip(config_payload: dict[str, Any], *, family: str = "ipv4") -> str:
    detection_url = (
        str(
            config_payload.get("public_origin_detection_url")
            or DEFAULT_PUBLIC_IP_DETECTION_URL
        ).strip()
        or DEFAULT_PUBLIC_IP_DETECTION_URL
    )
    response = requests.get(detection_url, timeout=10)
    response.raise_for_status()
    value = response.text.strip()
    candidate = ip_address(value)
    if family == "ipv4" and candidate.version != 4:
        raise ValueError(
            f"Public origin detection returned {value}, but an IPv4 origin address is required"
        )
    if family == "ipv6" and candidate.version != 6:
        raise ValueError(
            f"Public origin detection returned {value}, but an IPv6 origin address is required"
        )
    return str(candidate)


def _configured_public_origin_address(
    config_payload: dict[str, Any],
    site_payload: dict[str, Any],
    *,
    family: int | None = None,
) -> str:
    candidate_values = [
        site_payload.get("public_origin_address"),
        (
            config_payload.get(
                "default_public_origin_ipv6"
                if family == 6
                else "default_public_origin_ipv4"
            )
            if family in {4, 6}
            else None
        ),
    ]
    if family is None:
        candidate_values.extend(
            [
                config_payload.get("default_public_origin_ipv4"),
                config_payload.get("default_public_origin_ipv6"),
            ]
        )

    for raw_value in candidate_values:
        normalized = str(raw_value or "").strip()
        if not normalized:
            continue
        parsed = ip_address(normalized)
        if family is not None and parsed.version != family:
            continue
        return str(parsed)
    return ""


def _default_ipv6_route_interface() -> str:
    completed = subprocess.run(
        ["ip", "-j", "-6", "route", "show", "default"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    try:
        payload = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, list):
        return ""
    for item in payload:
        if not isinstance(item, dict):
            continue
        dev = str(item.get("dev") or "").strip()
        if dev:
            return dev
    return ""


def _list_global_ipv6_candidates() -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["ip", "-j", "-6", "addr", "show", "scope", "global", "up"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return []
    try:
        payload = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []

    default_interface = _default_ipv6_route_interface()
    candidates: list[dict[str, Any]] = []
    for interface in payload:
        if not isinstance(interface, dict):
            continue
        interface_name = str(interface.get("ifname") or "").strip()
        for addr_info in interface.get("addr_info") or []:
            if not isinstance(addr_info, dict):
                continue
            if str(addr_info.get("family") or "") != "inet6":
                continue
            if str(addr_info.get("scope") or "") != "global":
                continue
            local = str(addr_info.get("local") or "").strip()
            if not local:
                continue
            parsed = ip_address(local)
            if (
                parsed.is_loopback
                or parsed.is_link_local
                or parsed.is_multicast
                or parsed in _IPV6_UNIQUE_LOCAL_NETWORK
            ):
                continue
            candidates.append(
                {
                    "address": str(parsed),
                    "interface": interface_name,
                    "default_route": interface_name == default_interface,
                    "temporary": bool(addr_info.get("temporary")),
                    "deprecated": bool(addr_info.get("deprecated")),
                    "mngtmpaddr": bool(addr_info.get("mngtmpaddr")),
                }
            )

    return sorted(
        candidates,
        key=lambda item: (
            not bool(item.get("default_route")),
            bool(item.get("temporary")),
            bool(item.get("deprecated")),
            not bool(item.get("mngtmpaddr")),
            str(item.get("address") or ""),
        ),
    )


def _detect_public_ipv6(
    config_payload: dict[str, Any],
    site_payload: dict[str, Any],
) -> str:
    configured = _configured_public_origin_address(
        config_payload,
        site_payload,
        family=6,
    )
    if configured:
        return configured

    candidates = _list_global_ipv6_candidates()
    if not candidates:
        raise ValueError(
            "Could not determine a global IPv6 origin address; set sites[].public_origin_address or default_public_origin_ipv6 in configs/ali_esa.json"
        )
    return str(candidates[0]["address"])


def _resolve_origin_address(
    config_payload: dict[str, Any],
    site_payload: dict[str, Any],
    *,
    origin_address: str,
) -> dict[str, str]:
    normalized = str(origin_address or "").strip().lower()
    if normalized in {"", "auto"}:
        configured = _configured_public_origin_address(config_payload, site_payload)
        if configured:
            parsed = ip_address(configured)
            return {
                "address": str(parsed),
                "family": f"ipv{parsed.version}",
                "source": "config",
            }
        detected = _detect_public_ip(config_payload, family="ipv4")
        return {"address": detected, "family": "ipv4", "source": "auto4"}
    if normalized == "auto4":
        configured = _configured_public_origin_address(
            config_payload,
            site_payload,
            family=4,
        )
        if configured:
            return {"address": configured, "family": "ipv4", "source": "config"}
        detected = _detect_public_ip(config_payload, family="ipv4")
        return {"address": detected, "family": "ipv4", "source": "auto4"}
    if normalized == "auto6":
        detected = _detect_public_ipv6(config_payload, site_payload)
        return {"address": detected, "family": "ipv6", "source": "auto6"}

    parsed = ip_address(str(origin_address).strip())
    return {
        "address": str(parsed),
        "family": f"ipv{parsed.version}",
        "source": "explicit",
    }


def _normalize_exposure_record_mode(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if not normalized:
        return DEFAULT_EXPOSURE_RECORD_MODE
    aliases = {
        "originpool": "origin-pool",
        "origin-pool-cname": "origin-pool",
        "op": "origin-pool",
        "pool": "origin-pool",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"direct", "origin-pool"}:
        raise ValueError("record_mode must be one of: direct, origin-pool")
    return normalized


def _serialize_record_result(record_result: dict[str, Any]) -> dict[str, Any]:
    record_payload = record_result.get("record")
    return {
        "record": record_payload,
        "created": bool(record_result.get("created")),
        "updated": bool(record_result.get("updated")),
        "deleted_conflicts": list(record_result.get("deleted_conflicts") or []),
    }


def _normalize_record_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().rstrip(".")


def _normalize_esa_record_type(record_type: str) -> str:
    normalized = str(record_type or "").strip().upper()
    if normalized in {"A", "AAAA", _ESA_ADDRESS_RECORD_TYPE}:
        return _ESA_ADDRESS_RECORD_TYPE
    return normalized


def _normalize_esa_record_data_value(record_type: str, data_value: str) -> str:
    normalized_type = _normalize_esa_record_type(record_type)
    if normalized_type != _ESA_ADDRESS_RECORD_TYPE:
        return _normalize_record_value(data_value)

    entries: list[tuple[int, str]] = []
    seen: set[str] = set()
    for raw_part in str(data_value or "").split(","):
        part = raw_part.strip()
        if not part:
            continue
        parsed = ip_address(part)
        normalized_part = str(parsed)
        if normalized_part in seen:
            continue
        seen.add(normalized_part)
        entries.append((parsed.version, normalized_part))

    entries.sort(key=lambda item: (item[0] != 4, item[1]))
    return ",".join(value for _, value in entries)


def _resolve_exposure_record(
    config_payload: dict[str, Any],
    site_payload: dict[str, Any],
    *,
    hostname: str,
    origin_address: str,
) -> dict[str, Any]:
    raw_origin_address = str(origin_address or "").strip()
    if raw_origin_address.lower() == "cloudflare":
        return _resolve_cloudflare_bridge_record(site_payload, hostname=hostname)

    if "," in raw_origin_address:
        explicit_addresses = _normalize_esa_record_data_value(
            _ESA_ADDRESS_RECORD_TYPE,
            raw_origin_address,
        )
        record_addresses = [item for item in explicit_addresses.split(",") if item]
        record_versions = {
            ip_address(item).version for item in record_addresses if item.strip()
        }
        if 4 not in record_versions:
            raise ValueError(
                "Alibaba Cloud ESA proxied A/AAAA records require at least one IPv4 origin address; set default_public_origin_ipv4 in configs/ali_esa.json or use an IPv4 origin."
            )
        preferred_address = next(
            (item for item in record_addresses if ip_address(item).version == 6),
            record_addresses[0],
        )
        preferred_family = f"ipv{ip_address(preferred_address).version}"
        return {
            "address": preferred_address,
            "family": preferred_family,
            "source": "explicit-dual",
            "record_type": _ESA_ADDRESS_RECORD_TYPE,
            "record_value": explicit_addresses,
            "record_addresses": record_addresses,
            "record_family": (
                "dual-stack" if len(record_versions) > 1 else preferred_family
            ),
        }

    resolved = _resolve_origin_address(
        config_payload,
        site_payload,
        origin_address=origin_address,
    )
    primary_address = str(resolved["address"])
    record_addresses = [primary_address]
    companion_ipv4 = ""

    if resolved["family"] == "ipv6":
        companion_ipv4 = _configured_public_origin_address(
            config_payload,
            site_payload,
            family=4,
        )
        if not companion_ipv4:
            try:
                companion_ipv4 = _detect_public_ip(config_payload, family="ipv4")
            except ValueError as exc:
                raise ValueError(
                    "Alibaba Cloud ESA proxied A/AAAA records require at least one IPv4 origin address; set default_public_origin_ipv4 in configs/ali_esa.json or use an IPv4 origin."
                ) from exc
        companion_ipv4 = str(ip_address(companion_ipv4))
        record_addresses = [companion_ipv4, primary_address]

    record_value = _normalize_esa_record_data_value(
        _ESA_ADDRESS_RECORD_TYPE,
        ",".join(record_addresses),
    )
    record_versions = {
        ip_address(item).version for item in record_value.split(",") if item.strip()
    }
    if 4 not in record_versions:
        raise ValueError(
            "Alibaba Cloud ESA proxied A/AAAA records require at least one IPv4 origin address; set default_public_origin_ipv4 in configs/ali_esa.json or use an IPv4 origin."
        )

    return {
        **resolved,
        "record_type": _ESA_ADDRESS_RECORD_TYPE,
        "record_value": record_value,
        "record_addresses": [item for item in record_value.split(",") if item],
        "record_family": (
            "dual-stack"
            if resolved["family"] == "ipv6" and bool(companion_ipv4)
            else resolved["family"]
        ),
    }


def _cloudflare_authoritative_nameservers(site_payload: dict[str, Any]) -> list[str]:
    configured = _normalize_nameservers(
        site_payload.get("cloudflare_name_server_list")
        or site_payload.get("current_ns")
    )
    return [item for item in configured if item.lower().endswith(".cloudflare.com")]


def _query_authoritative_dns(
    *,
    nameserver: str,
    hostname: str,
    record_type: str,
) -> list[str]:
    completed = subprocess.run(
        [
            "dig",
            "-4",
            f"@{nameserver}",
            hostname,
            record_type,
            "+short",
            "+time=2",
            "+tries=1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 and not str(completed.stdout or "").strip():
        return []

    expected_version = 4 if str(record_type).upper() == "A" else 6
    resolved: list[str] = []
    for line in str(completed.stdout or "").splitlines():
        candidate = str(line or "").strip()
        if not candidate:
            continue
        try:
            parsed = ip_address(candidate)
        except ValueError:
            continue
        if parsed.version == expected_version:
            resolved.append(str(parsed))
    return resolved


def _resolve_cloudflare_bridge_record(
    site_payload: dict[str, Any],
    *,
    hostname: str,
) -> dict[str, Any]:
    nameservers = _cloudflare_authoritative_nameservers(site_payload)
    if not nameservers:
        raise ValueError(
            "origin_address=cloudflare requires sites[].cloudflare_name_server_list or current_ns with Cloudflare authoritative nameservers in configs/ali_esa.json"
        )

    resolved_a: list[str] = []
    resolved_aaaa: list[str] = []
    for nameserver in nameservers:
        if not resolved_a:
            resolved_a = _query_authoritative_dns(
                nameserver=nameserver,
                hostname=hostname,
                record_type="A",
            )
        if not resolved_aaaa:
            resolved_aaaa = _query_authoritative_dns(
                nameserver=nameserver,
                hostname=hostname,
                record_type="AAAA",
            )
        if resolved_a and resolved_aaaa:
            break

    if not resolved_a:
        raise ValueError(
            f"Could not resolve Cloudflare authoritative A records for {hostname}"
        )

    record_value = _normalize_esa_record_data_value(
        _ESA_ADDRESS_RECORD_TYPE,
        ",".join(resolved_a + resolved_aaaa),
    )
    record_addresses = [item for item in record_value.split(",") if item]
    preferred_address = next(
        (item for item in record_addresses if ip_address(item).version == 6),
        record_addresses[0],
    )
    preferred_family = f"ipv{ip_address(preferred_address).version}"
    return {
        "address": preferred_address,
        "family": preferred_family,
        "source": "cloudflare-authoritative",
        "record_type": _ESA_ADDRESS_RECORD_TYPE,
        "record_value": record_value,
        "record_addresses": record_addresses,
        "record_family": ("dual-stack" if bool(resolved_aaaa) else "ipv4"),
    }


def _record_data_value(record: dict[str, Any]) -> str:
    data = record.get("Data")
    if isinstance(data, dict):
        return _normalize_esa_record_data_value(
            str(record.get("RecordType") or ""),
            str(data.get("Value") or ""),
        )
    return ""


def _record_matches(
    record: dict[str, Any],
    *,
    record_type: str,
    data_value: str,
    ttl: int,
    proxied: bool | None,
    biz_name: str | None = None,
    source_type: str | None = None,
    host_policy: str | None = None,
    data_extra: dict[str, Any] | None = None,
) -> bool:
    if _normalize_esa_record_type(
        str(record.get("RecordType") or "")
    ) != _normalize_esa_record_type(record_type):
        return False
    if _record_data_value(record) != _normalize_esa_record_data_value(
        record_type, data_value
    ):
        return False
    if int(record.get("Ttl") or 0) != int(ttl):
        return False
    if proxied is not None and bool(record.get("Proxied")) != bool(proxied):
        return False
    if (
        biz_name is not None
        and str(record.get("BizName") or "").strip() != str(biz_name or "").strip()
    ):
        return False
    if (
        source_type is not None
        and str(record.get("RecordSourceType") or "").strip()
        != str(source_type or "").strip()
    ):
        return False
    if (
        host_policy is not None
        and str(record.get("HostPolicy") or "").strip()
        != str(host_policy or "").strip()
    ):
        return False
    data_payload = record.get("Data") if isinstance(record.get("Data"), dict) else {}
    if data_extra:
        for key, value in data_extra.items():
            if key == "Value":
                continue
            if data_payload.get(key) != value:
                return False
    return True


def _is_retryable_service_busy_error(exc: Exception) -> bool:
    detail = str(exc or "").strip().lower()
    return "site.servicebusy" in detail or "servicebusy" in detail


def _is_invalid_site_icp_error(exc: Exception) -> bool:
    detail = str(exc or "").strip().lower()
    return "invalidsiteicp" in detail


def _restorable_public_record_snapshot(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []
    for item in records:
        normalized_type = _normalize_esa_record_type(str(item.get("RecordType") or ""))
        if normalized_type not in {_ESA_ADDRESS_RECORD_TYPE, "CNAME"}:
            continue

        data_value = _record_data_value(item)
        if not data_value:
            continue

        data_payload = item.get("Data") if isinstance(item.get("Data"), dict) else {}
        snapshot.append(
            {
                "record_name": str(item.get("RecordName") or "").strip(),
                "record_type": normalized_type,
                "ttl": max(1, int(item.get("Ttl") or 1)),
                "data_value": data_value,
                "proxied": (
                    bool(item.get("Proxied"))
                    if item.get("Proxied") is not None
                    else None
                ),
                "biz_name": str(item.get("BizName") or "").strip() or None,
                "source_type": (
                    str(item.get("RecordSourceType") or "").strip() or None
                ),
                "comment": str(item.get("Comment") or "").strip() or None,
                "host_policy": str(item.get("HostPolicy") or "").strip() or None,
                "data_extra": {
                    str(key): value
                    for key, value in data_payload.items()
                    if str(key) != "Value"
                }
                or None,
            }
        )
    return snapshot


def _restore_public_record_snapshot(
    client: AliyunEsaClient,
    *,
    site_id: int,
    record_name: str,
    snapshot: list[dict[str, Any]],
) -> dict[str, Any]:
    current_records = client.list_records(site_id=site_id, record_name=record_name)
    deleted_current: list[dict[str, Any]] = []
    for item in current_records:
        normalized_type = _normalize_esa_record_type(str(item.get("RecordType") or ""))
        if normalized_type not in {_ESA_ADDRESS_RECORD_TYPE, "CNAME"}:
            continue
        record_id = item.get("RecordId")
        if not isinstance(record_id, int) or record_id <= 0:
            continue
        client.delete_record(record_id=record_id)
        deleted_current.append(
            {
                "record_id": record_id,
                "record_name": item.get("RecordName"),
                "record_type": normalized_type,
            }
        )

    recreated: list[dict[str, Any]] = []
    for item in snapshot:
        created = client.create_record(
            site_id=site_id,
            record_name=str(item["record_name"]),
            record_type=str(item["record_type"]),
            ttl=int(item["ttl"]),
            data_value=str(item["data_value"]),
            proxied=item.get("proxied"),
            biz_name=item.get("biz_name"),
            source_type=item.get("source_type"),
            comment=item.get("comment"),
            host_policy=item.get("host_policy"),
            data_extra=item.get("data_extra"),
        )
        recreated.append(
            {
                "record_name": item["record_name"],
                "record_type": item["record_type"],
                "created": created,
            }
        )

    return {
        "deleted_current": deleted_current,
        "recreated": recreated,
        "records": client.list_records(site_id=site_id, record_name=record_name),
    }


def _ensure_record(
    client: AliyunEsaClient,
    *,
    site_id: int,
    record_name: str,
    record_type: str,
    data_value: str,
    ttl: int,
    proxied: bool | None,
    biz_name: str | None,
    source_type: str | None = None,
    comment: str | None = None,
    host_policy: str | None = None,
    data_extra: dict[str, Any] | None = None,
    purge_conflicts: bool = False,
    retry_attempts: int = DEFAULT_EXPOSURE_RETRY_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_EXPOSURE_RETRY_DELAY_SECONDS,
    restore_on_failure: bool = True,
) -> dict[str, Any]:
    normalized_record_type = _normalize_esa_record_type(record_type)
    normalized_data_value = _normalize_esa_record_data_value(record_type, data_value)
    attempts = max(1, int(retry_attempts or 1))
    delay_seconds = max(0.0, float(retry_delay_seconds or 0.0))
    initial_snapshot: list[dict[str, Any]] | None = None
    deleted_conflicts_by_id: dict[int, dict[str, Any]] = {}

    for attempt in range(1, attempts + 1):
        try:
            existing_records = client.list_records(
                site_id=site_id,
                record_name=record_name,
            )
            if initial_snapshot is None and restore_on_failure:
                initial_snapshot = _restorable_public_record_snapshot(existing_records)

            if purge_conflicts:
                for item in existing_records:
                    existing_type = _normalize_esa_record_type(
                        str(item.get("RecordType") or "")
                    )
                    if existing_type == normalized_record_type:
                        continue
                    if existing_type not in {_ESA_ADDRESS_RECORD_TYPE, "CNAME"}:
                        continue
                    record_id = item.get("RecordId")
                    if not isinstance(record_id, int) or record_id <= 0:
                        continue
                    client.delete_record(record_id=record_id)
                    deleted_conflicts_by_id[record_id] = {
                        "record_id": record_id,
                        "record_name": item.get("RecordName"),
                        "record_type": existing_type,
                    }
                if deleted_conflicts_by_id:
                    existing_records = client.list_records(
                        site_id=site_id, record_name=record_name
                    )

            matching_type_records = [
                item
                for item in existing_records
                if _normalize_esa_record_type(str(item.get("RecordType") or ""))
                == normalized_record_type
            ]

            for item in matching_type_records:
                if _record_matches(
                    item,
                    record_type=record_type,
                    data_value=normalized_data_value,
                    ttl=ttl,
                    proxied=proxied,
                    biz_name=biz_name,
                    source_type=source_type,
                    host_policy=host_policy,
                    data_extra=data_extra,
                ):
                    return {
                        "record": item,
                        "created": False,
                        "updated": False,
                        "deleted_conflicts": list(deleted_conflicts_by_id.values()),
                    }

            if matching_type_records:
                record_id = matching_type_records[0].get("RecordId")
                if not isinstance(record_id, int):
                    raise ValueError(
                        f"ESA record '{record_name}' exists but does not include a numeric RecordId"
                    )
                updated = client.update_record(
                    record_id=record_id,
                    record_type=normalized_record_type,
                    ttl=ttl,
                    data_value=normalized_data_value,
                    proxied=proxied,
                    biz_name=biz_name,
                    source_type=source_type,
                    comment=comment,
                    host_policy=host_policy,
                    data_extra=data_extra,
                )
                refreshed = client.list_records(
                    site_id=site_id,
                    record_name=record_name,
                    record_type=normalized_record_type,
                )
                return {
                    "record": refreshed[0] if refreshed else updated,
                    "created": False,
                    "updated": True,
                    "deleted_conflicts": list(deleted_conflicts_by_id.values()),
                }

            created = client.create_record(
                site_id=site_id,
                record_name=record_name,
                record_type=normalized_record_type,
                ttl=ttl,
                data_value=normalized_data_value,
                proxied=proxied,
                biz_name=biz_name,
                source_type=source_type,
                comment=comment,
                host_policy=host_policy,
                data_extra=data_extra,
            )
            refreshed = client.list_records(
                site_id=site_id,
                record_name=record_name,
                record_type=normalized_record_type,
            )
            return {
                "record": refreshed[0] if refreshed else created,
                "created": True,
                "updated": False,
                "deleted_conflicts": list(deleted_conflicts_by_id.values()),
            }
        except AliyunEsaApiError as exc:
            if _is_retryable_service_busy_error(exc) and attempt < attempts:
                if delay_seconds > 0:
                    time.sleep(delay_seconds)
                continue

            if restore_on_failure and initial_snapshot is not None:
                try:
                    _restore_public_record_snapshot(
                        client,
                        site_id=site_id,
                        record_name=record_name,
                        snapshot=initial_snapshot,
                    )
                except AliyunEsaApiError as restore_exc:
                    raise AliyunEsaApiError(
                        f"{exc}; restore_failed: {restore_exc}"
                    ) from exc
                raise AliyunEsaApiError(
                    f"{exc}; original public records restored"
                ) from exc
            raise


def _origin_rule_name(hostname: str) -> str:
    return f"bldash-{_safe_token(hostname)}"


def _origin_rule_expression(hostname: str) -> str:
    escaped = str(hostname).replace('"', '\\"')
    return f'(http.host eq "{escaped}")'


def _ensure_origin_rule(
    client: AliyunEsaClient,
    *,
    site_id: int,
    hostname: str,
    origin_scheme: str,
    origin_port: int,
    origin_host: str,
    origin_sni: str | None = None,
    origin_verify: str | None = None,
    origin_read_timeout: int | None = None,
) -> dict[str, Any]:
    rule_name = _origin_rule_name(hostname)
    rule = _origin_rule_expression(hostname)
    existing_rules = client.list_origin_rules(
        site_id=site_id,
        rule_name=rule_name,
        config_type="rule",
    )
    existing = existing_rules[0] if existing_rules else None

    origin_http_port = str(origin_port) if origin_scheme == "http" else None
    origin_https_port = str(origin_port) if origin_scheme == "https" else None
    desired = {
        "RuleName": rule_name,
        "Rule": rule,
        "RuleEnable": "on",
        "OriginScheme": origin_scheme,
        "OriginHost": origin_host,
        "OriginHttpPort": origin_http_port,
        "OriginHttpsPort": origin_https_port,
        "OriginSni": origin_sni,
        "OriginVerify": origin_verify,
        "OriginReadTimeout": (
            str(int(origin_read_timeout))
            if isinstance(origin_read_timeout, int)
            else None
        ),
    }

    def same_rule(item: dict[str, Any]) -> bool:
        for key, value in desired.items():
            if value is None:
                continue
            if str(item.get(key) or "").strip() != str(value).strip():
                return False
        return True

    if isinstance(existing, dict) and same_rule(existing):
        return {"rule": existing, "created": False, "updated": False}

    if isinstance(existing, dict):
        config_id = existing.get("ConfigId")
        if not isinstance(config_id, int):
            raise ValueError(
                f"ESA origin rule '{rule_name}' exists but does not include a numeric ConfigId"
            )
        updated = client.update_origin_rule(
            site_id=site_id,
            config_id=config_id,
            rule_name=rule_name,
            rule=rule,
            rule_enable="on",
            origin_scheme=origin_scheme,
            origin_host=origin_host,
            origin_http_port=origin_http_port,
            origin_https_port=origin_https_port,
            origin_sni=origin_sni,
            origin_verify=origin_verify,
            origin_read_timeout=(
                str(int(origin_read_timeout))
                if isinstance(origin_read_timeout, int)
                else None
            ),
            sequence=1,
        )
        refreshed_rules = client.list_origin_rules(
            site_id=site_id,
            rule_name=rule_name,
            config_type="rule",
        )
        return {
            "rule": refreshed_rules[0] if refreshed_rules else updated,
            "created": False,
            "updated": True,
        }

    created = client.create_origin_rule(
        site_id=site_id,
        rule_name=rule_name,
        rule=rule,
        rule_enable="on",
        origin_scheme=origin_scheme,
        origin_host=origin_host,
        origin_http_port=origin_http_port,
        origin_https_port=origin_https_port,
        origin_sni=origin_sni,
        origin_verify=origin_verify,
        origin_read_timeout=(
            str(int(origin_read_timeout))
            if isinstance(origin_read_timeout, int)
            else None
        ),
        sequence=1,
    )
    refreshed_rules = client.list_origin_rules(
        site_id=site_id,
        rule_name=rule_name,
        config_type="rule",
    )
    return {
        "rule": refreshed_rules[0] if refreshed_rules else created,
        "created": True,
        "updated": False,
    }


def _bootstrap_config_from_cf_tunnel() -> dict[str, Any]:
    payload = json.loads(render_template_json(ALI_ESA_CONFIG))
    try:
        cf_payload = load_cf_tunnel_config()
    except Exception:
        cf_payload = {}

    payload["aliyun_access_id"] = str(cf_payload.get("aliyun_access_id") or "").strip()
    payload["aliyun_access_secret"] = str(
        cf_payload.get("aliyun_access_secret") or ""
    ).strip()
    payload["cf_api_token"] = str(cf_payload.get("cf_api_token") or "").strip()
    payload["cf_account_id"] = str(cf_payload.get("cf_account_id") or "").strip()

    sites: list[dict[str, Any]] = []
    seen: set[str] = set()
    for domain in list_domains(cf_payload):
        key = domain.zone_name.lower()
        if key in seen:
            continue
        seen.add(key)
        sites.append(
            {
                "site_name": domain.zone_name,
                "coverage": payload.get("default_coverage") or "overseas",
                "access_type": payload.get("default_access_type") or "NS",
                "instance_id": payload.get("default_instance_id") or "",
                "cloudflare_zone_id": domain.zone_id,
                "name_server_list": [],
                "current_ns": [],
                "verify_code": "",
                "status": "",
                "registrar_task_no": "",
                "last_verified_at": "",
                "last_cloudflare_sync_at": "",
            }
        )
    if sites:
        payload["sites"] = sites
    return payload


def config_schema_json() -> dict[str, Any]:
    return ALI_ESA_CONFIG.schema


def config_check() -> list[str]:
    payload = load_ali_esa_config()
    return validate_payload_against_schema(
        payload,
        ALI_ESA_CONFIG.schema,
        ALI_ESA_CONFIG.name,
    )


def config_init(*, force: bool, from_cf_tunnel: bool = False) -> str:
    config_path = find_project_root() / "configs" / ALI_ESA_CONFIG.file_name
    if config_path.exists() and not force:
        raise FileExistsError(
            f"{config_path} already exists; rerun with --force to overwrite"
        )
    payload = (
        _bootstrap_config_from_cf_tunnel()
        if from_cf_tunnel
        else json.loads(render_template_json(ALI_ESA_CONFIG))
    )
    save_ali_esa_config(payload)
    return str(config_path)


def list_plan_instances() -> dict[str, Any]:
    config_payload = load_ali_esa_config(validate=False)
    client = _build_esa_client(config_payload)
    items = client.list_user_rate_plan_instances()
    return {
        "count": len(items),
        "instances": items,
    }


def site_check(*, site_name: str) -> dict[str, Any]:
    normalized_site_name = _require_text(site_name, "site_name")
    config_payload = load_ali_esa_config(validate=False)
    client = _build_esa_client(config_payload)
    return {
        "site_name": normalized_site_name,
        "check": client.check_site_name(site_name=normalized_site_name),
        "existing_site": client.get_site(site_name=normalized_site_name),
        "config_site": _serialize_site(find_site(config_payload, normalized_site_name)),
    }


def ensure_site(
    *,
    site_name: str,
    coverage: str = "",
    access_type: str = "",
    instance_id: str = "",
    save_config: bool = False,
) -> dict[str, Any]:
    normalized_site_name = _require_text(site_name, "site_name")
    config_payload = load_ali_esa_config(validate=False)
    client = _build_esa_client(config_payload)
    normalized_coverage = normalize_coverage(
        coverage or config_payload.get("default_coverage") or "overseas"
    )
    normalized_access_type = normalize_access_type(
        access_type or config_payload.get("default_access_type") or "NS"
    )

    existing_remote_site = client.get_site(site_name=normalized_site_name)
    selected_instance: dict[str, Any] | None = None
    created = False
    updated = False

    if existing_remote_site is None:
        plan_items = client.list_user_rate_plan_instances()
        selected_instance = _pick_plan_instance(
            plan_items,
            requested_instance_id=(
                instance_id or config_payload.get("default_instance_id") or ""
            ),
            coverage=normalized_coverage,
        )
        created_payload = client.create_site(
            site_name=normalized_site_name,
            coverage=normalized_coverage,
            access_type=normalized_access_type,
            instance_id=_require_text(
                selected_instance.get("InstanceId"), "InstanceId"
            ),
        )
        existing_remote_site = client.get_site(site_name=normalized_site_name) or {
            "SiteName": normalized_site_name,
            "SiteId": created_payload.get("SiteId"),
            "Coverage": normalized_coverage,
            "AccessType": normalized_access_type,
            "InstanceId": str(selected_instance.get("InstanceId") or "").strip(),
            "NameServerList": created_payload.get("NameServerList"),
            "VerifyCode": created_payload.get("VerifyCode"),
            "Status": "pending",
        }
        created = True

    site_id = (
        existing_remote_site.get("SiteId")
        if isinstance(existing_remote_site, dict)
        else None
    )
    if isinstance(site_id, int) and site_id > 0:
        current_coverage = normalize_coverage(
            (existing_remote_site or {}).get("Coverage") or normalized_coverage
        )
        current_access_type = normalize_access_type(
            (existing_remote_site or {}).get("AccessType") or normalized_access_type
        )

        if str(coverage or "").strip() and current_coverage != normalized_coverage:
            try:
                client.update_site_coverage(
                    site_id=site_id,
                    coverage=normalized_coverage,
                )
            except AliyunEsaApiError as exc:
                if _is_invalid_site_icp_error(exc):
                    raise ValueError(
                        f"ESA site '{normalized_site_name}' cannot switch to coverage '{normalized_coverage}' without a valid ICP filing"
                    ) from exc
                raise
            updated = True
        if (
            str(access_type or "").strip()
            and current_access_type != normalized_access_type
        ):
            client.update_site_access_type(
                site_id=site_id,
                access_type=normalized_access_type,
            )
            updated = True

        if updated:
            existing_remote_site = client.get_site(site_name=normalized_site_name) or {
                **(existing_remote_site or {}),
                "Coverage": normalized_coverage,
                "AccessType": normalized_access_type,
            }

    resolved_current_ns: list[str] = []
    site_id = (
        existing_remote_site.get("SiteId")
        if isinstance(existing_remote_site, dict)
        else None
    )
    if isinstance(site_id, int) and site_id > 0:
        try:
            resolved_current_ns = client.get_site_current_ns(site_id=site_id)
        except AliyunEsaApiError:
            resolved_current_ns = []

    resolved_instance_id = str(
        (existing_remote_site or {}).get("InstanceId")
        or (selected_instance or {}).get("InstanceId")
        or instance_id
        or config_payload.get("default_instance_id")
        or ""
    ).strip()

    persisted_site = _upsert_site_payload(
        config_payload,
        site_name=normalized_site_name,
        coverage=normalize_coverage(
            (existing_remote_site or {}).get("Coverage") or normalized_coverage
        ),
        access_type=normalize_access_type(
            (existing_remote_site or {}).get("AccessType") or normalized_access_type
        ),
        instance_id=resolved_instance_id,
        site_data=existing_remote_site or {},
        current_ns=resolved_current_ns,
    )
    saved_config_path = _persist_config_if_requested(
        config_payload,
        save_config=save_config,
    )
    return {
        "site_name": normalized_site_name,
        "created": created,
        "updated": updated,
        "selected_instance": selected_instance,
        "site": _serialize_site(persisted_site),
        "config_saved": saved_config_path,
    }


def site_status(*, site_name: str) -> dict[str, Any]:
    context = _resolve_site_context(site_name, require_site_id=False)
    return {
        "site_name": context["site_name"],
        "remote_site": context["remote_site"],
        "current_ns": context["current_ns"],
        "config_site": context["config_site"],
    }


def _resolve_site_context(
    site_name: str,
    *,
    require_site_id: bool,
) -> dict[str, Any]:
    normalized_site_name = _require_text(site_name, "site_name")
    config_payload = load_ali_esa_config(validate=False)
    client = _build_esa_client(config_payload)
    remote_site = client.get_site(site_name=normalized_site_name)
    site_id = remote_site.get("SiteId") if isinstance(remote_site, dict) else None
    if require_site_id and (not isinstance(site_id, int) or site_id <= 0):
        raise ValueError(
            f"ESA site '{normalized_site_name}' does not exist or does not have a valid SiteId"
        )

    current_ns: list[str] = []
    if isinstance(site_id, int) and site_id > 0:
        try:
            current_ns = client.get_site_current_ns(site_id=site_id)
        except AliyunEsaApiError:
            current_ns = []
    return {
        "site_name": normalized_site_name,
        "config_payload": config_payload,
        "client": client,
        "site_id": site_id if isinstance(site_id, int) and site_id > 0 else None,
        "remote_site": remote_site,
        "current_ns": current_ns,
        "config_site": _serialize_site(find_site(config_payload, normalized_site_name)),
    }


def site_records(
    *,
    site_name: str,
    record_name: str = "",
    record_type: str = "",
) -> dict[str, Any]:
    context = _resolve_site_context(site_name, require_site_id=True)

    records = context["client"].list_records(
        site_id=int(context["site_id"]),
        record_name=str(record_name or "").strip() or None,
        record_type=str(record_type or "").strip() or None,
    )
    return {
        "site_name": context["site_name"],
        "remote_site": context["remote_site"],
        "current_ns": context["current_ns"],
        "config_site": context["config_site"],
        "count": len(records),
        "records": records,
    }


def site_record_apply(
    *,
    site_name: str,
    record_name: str,
    record_type: str,
    data_value: str,
    ttl: int = 60,
    proxied: bool | None = False,
    biz_name: str = "",
    comment: str = "",
    purge_conflicts: bool = False,
    retry_attempts: int = DEFAULT_EXPOSURE_RETRY_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_EXPOSURE_RETRY_DELAY_SECONDS,
    restore_on_failure: bool = True,
) -> dict[str, Any]:
    context = _resolve_site_context(site_name, require_site_id=True)
    normalized_record_name = _normalize_subdomain_under_site(
        record_name,
        site_name=context["site_name"],
        label="record_name",
        allow_apex=True,
    )
    normalized_record_type = _normalize_esa_record_type(
        _require_text(record_type, "record_type")
    )
    normalized_data_value = _normalize_esa_record_data_value(
        normalized_record_type,
        _require_text(data_value, "data_value"),
    )
    record_result = _ensure_record(
        context["client"],
        site_id=int(context["site_id"]),
        record_name=normalized_record_name,
        record_type=normalized_record_type,
        data_value=normalized_data_value,
        ttl=max(1, int(ttl or 60)),
        proxied=proxied,
        biz_name=str(biz_name or "").strip() or None,
        comment=str(comment or "").strip() or None,
        purge_conflicts=purge_conflicts,
        retry_attempts=retry_attempts,
        retry_delay_seconds=retry_delay_seconds,
        restore_on_failure=restore_on_failure,
    )
    return {
        "site_name": context["site_name"],
        "remote_site": context["remote_site"],
        "current_ns": context["current_ns"],
        "config_site": context["config_site"],
        "record_name": normalized_record_name,
        "record_type": normalized_record_type,
        "data_value": normalized_data_value,
        "ttl": max(1, int(ttl or 60)),
        "proxied": proxied,
        "record": _serialize_record_result(record_result),
    }


def _dns01_domain(domain: str) -> str:
    normalized = _require_text(domain, "domain").strip().lower()
    if normalized.startswith("*."):
        normalized = normalized[2:]
    return normalized


def _dns01_record_name(domain: str) -> str:
    return f"_acme-challenge.{_dns01_domain(domain)}"


def _dns01_value_from_env_or_arg(
    value: str, *, label: str, env_names: list[str]
) -> str:
    normalized = str(value or "").strip()
    if normalized:
        return normalized
    for env_name in env_names:
        candidate = str(os.environ.get(env_name) or "").strip()
        if candidate:
            return candidate
    raise ValueError(f"{label} is required")


def _resolve_dns01_request(
    *,
    site_name: str = "",
    domain: str = "",
    validation: str = "",
) -> dict[str, Any]:
    raw_domain = _dns01_value_from_env_or_arg(
        domain,
        label="domain",
        env_names=["CERTBOT_DOMAIN", "CERTBOT_IDENTIFIER"],
    )
    normalized_domain = _dns01_domain(raw_domain)
    normalized_site_name = (
        _require_text(site_name, "site_name").strip().lower()
        if str(site_name or "").strip()
        else infer_site_name(normalized_domain)
    )
    context = _resolve_site_context(normalized_site_name, require_site_id=True)
    record_name = _normalize_subdomain_under_site(
        _dns01_record_name(normalized_domain),
        site_name=context["site_name"],
        label="record_name",
    )
    normalized_validation = _dns01_value_from_env_or_arg(
        validation,
        label="validation",
        env_names=["CERTBOT_VALIDATION"],
    )
    return {
        "context": context,
        "site_name": context["site_name"],
        "domain": normalized_domain,
        "record_name": record_name,
        "validation": normalized_validation,
    }


def dns01_auth(
    *,
    site_name: str = "",
    domain: str = "",
    validation: str = "",
    ttl: int = 60,
    wait_seconds: int = 30,
    comment: str = "",
) -> dict[str, Any]:
    request = _resolve_dns01_request(
        site_name=site_name,
        domain=domain,
        validation=validation,
    )
    context = request["context"]
    client = context["client"]
    site_id = int(context["site_id"])
    normalized_ttl = max(1, int(ttl))
    normalized_wait_seconds = max(0, int(wait_seconds))
    normalized_comment = str(comment or "").strip() or "certbot dns-01"

    existing_records = [
        item
        for item in client.list_records(
            site_id=site_id,
            record_name=str(request["record_name"]),
            record_type="TXT",
        )
        if isinstance(item, dict)
        and _normalize_esa_record_type(str(item.get("RecordType") or "")) == "TXT"
        and _record_data_value(item)
        == _normalize_record_value(str(request["validation"]))
    ]

    created = False
    created_result: dict[str, Any] | None = None
    if not existing_records:
        created_result = client.create_record(
            site_id=site_id,
            record_name=str(request["record_name"]),
            record_type="TXT",
            ttl=normalized_ttl,
            data_value=str(request["validation"]),
            comment=normalized_comment,
        )
        created = True

    refreshed_records = [
        item
        for item in client.list_records(
            site_id=site_id,
            record_name=str(request["record_name"]),
            record_type="TXT",
        )
        if isinstance(item, dict)
        and _normalize_esa_record_type(str(item.get("RecordType") or "")) == "TXT"
        and _record_data_value(item)
        == _normalize_record_value(str(request["validation"]))
    ]
    active_record = refreshed_records[0] if refreshed_records else None

    if normalized_wait_seconds > 0:
        time.sleep(normalized_wait_seconds)

    return {
        "site_name": str(request["site_name"]),
        "domain": str(request["domain"]),
        "record_name": str(request["record_name"]),
        "validation": str(request["validation"]),
        "ttl": normalized_ttl,
        "wait_seconds": normalized_wait_seconds,
        "created": created,
        "create_result": created_result,
        "record": active_record,
        "matching_count": len(refreshed_records),
    }


def dns01_cleanup(
    *,
    site_name: str = "",
    domain: str = "",
    validation: str = "",
) -> dict[str, Any]:
    request = _resolve_dns01_request(
        site_name=site_name,
        domain=domain,
        validation=validation,
    )
    context = request["context"]
    client = context["client"]
    site_id = int(context["site_id"])

    existing_records = [
        item
        for item in client.list_records(
            site_id=site_id,
            record_name=str(request["record_name"]),
            record_type="TXT",
        )
        if isinstance(item, dict)
        and _normalize_esa_record_type(str(item.get("RecordType") or "")) == "TXT"
        and _record_data_value(item)
        == _normalize_record_value(str(request["validation"]))
    ]

    deleted: list[dict[str, Any]] = []
    for item in existing_records:
        record_id = item.get("RecordId")
        if not isinstance(record_id, int) or record_id <= 0:
            continue
        deleted.append(
            {
                "record": item,
                "delete_result": client.delete_record(record_id=record_id),
            }
        )

    remaining_records = [
        item
        for item in client.list_records(
            site_id=site_id,
            record_name=str(request["record_name"]),
            record_type="TXT",
        )
        if isinstance(item, dict)
        and _normalize_esa_record_type(str(item.get("RecordType") or "")) == "TXT"
        and _record_data_value(item)
        == _normalize_record_value(str(request["validation"]))
    ]

    return {
        "site_name": str(request["site_name"]),
        "domain": str(request["domain"]),
        "record_name": str(request["record_name"]),
        "validation": str(request["validation"]),
        "deleted": deleted,
        "deleted_count": len(deleted),
        "remaining_count": len(remaining_records),
    }


def site_origin_pools(
    *,
    site_name: str,
    name: str = "",
    match_type: str = "exact",
) -> dict[str, Any]:
    context = _resolve_site_context(site_name, require_site_id=True)

    normalized_match_type = str(match_type or "exact").strip().lower() or "exact"
    if normalized_match_type not in {"exact", "fuzzy"}:
        raise ValueError("match_type must be one of: exact, fuzzy")

    origin_pools = context["client"].list_origin_pools(
        site_id=int(context["site_id"]),
        name=str(name or "").strip() or None,
        match_type=normalized_match_type,
    )
    return {
        "site_name": context["site_name"],
        "remote_site": context["remote_site"],
        "current_ns": context["current_ns"],
        "config_site": context["config_site"],
        "count": len(origin_pools),
        "origin_pools": origin_pools,
    }


def site_origin_pool_upsert(
    *,
    site_name: str,
    pool_name: str,
    origin_name: str,
    origin_address: str,
    weight: int = 100,
    enabled: bool = True,
) -> dict[str, Any]:
    context = _resolve_site_context(site_name, require_site_id=True)
    client = context["client"]
    site_id = int(context["site_id"])
    normalized_pool_name = _require_text(pool_name, "pool_name")
    normalized_origin_name = _require_text(origin_name, "origin_name")
    normalized_origin_address = _require_text(origin_address, "origin_address")
    normalized_weight = max(1, int(weight or 100))

    existing_pool = None
    for item in client.list_origin_pools(
        site_id=site_id,
        name=normalized_pool_name,
        match_type="exact",
    ):
        if str(item.get("Name") or "").strip().lower() != normalized_pool_name.lower():
            continue
        pool_id = item.get("Id")
        if isinstance(pool_id, int) and pool_id > 0:
            existing_pool = client.get_origin_pool(
                site_id=site_id, origin_pool_id=pool_id
            )
            break

    def _build_origin(existing: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(existing or {})
        payload["Name"] = normalized_origin_name
        payload["Address"] = normalized_origin_address
        payload["Type"] = str(payload.get("Type") or "ip_domain").strip() or "ip_domain"
        payload["Enabled"] = bool(payload.get("Enabled", True))
        payload["Weight"] = normalized_weight
        return payload

    if existing_pool is None:
        created = client.create_origin_pool(
            site_id=site_id,
            name=normalized_pool_name,
            enabled=enabled,
            origins=[_build_origin()],
        )
        created_id = created.get("Id") if isinstance(created, dict) else None
        refreshed = (
            client.get_origin_pool(site_id=site_id, origin_pool_id=created_id)
            if isinstance(created_id, int) and created_id > 0
            else None
        )
        return {
            "site_name": context["site_name"],
            "remote_site": context["remote_site"],
            "current_ns": context["current_ns"],
            "config_site": context["config_site"],
            "action": "created",
            "origin_pool": refreshed or created,
        }

    pool_id = existing_pool.get("Id")
    if not isinstance(pool_id, int) or pool_id <= 0:
        raise ValueError(
            f"ESA origin pool '{normalized_pool_name}' does not have a valid Id"
        )

    changed = False
    origins: list[dict[str, Any]] = []
    matched = False
    for item in existing_pool.get("Origins") or []:
        origin = dict(item) if isinstance(item, dict) else {}
        if str(origin.get("Name") or "").strip() != normalized_origin_name:
            origins.append(origin)
            continue
        matched = True
        updated_origin = _build_origin(origin)
        if updated_origin != origin:
            changed = True
        origins.append(updated_origin)

    if not matched:
        changed = True
        origins.append(_build_origin())

    current_enabled = bool(existing_pool.get("Enabled", True))
    if current_enabled != bool(enabled):
        changed = True

    if changed:
        client.update_origin_pool(
            site_id=site_id,
            origin_pool_id=pool_id,
            enabled=enabled,
            origins=origins,
        )

    refreshed = client.get_origin_pool(site_id=site_id, origin_pool_id=pool_id)
    return {
        "site_name": context["site_name"],
        "remote_site": context["remote_site"],
        "current_ns": context["current_ns"],
        "config_site": context["config_site"],
        "action": "updated" if changed else "unchanged",
        "origin_pool": refreshed,
    }


def site_load_balancers(
    *,
    site_name: str,
    name: str = "",
    match_type: str = "exact",
) -> dict[str, Any]:
    context = _resolve_site_context(site_name, require_site_id=True)

    normalized_match_type = str(match_type or "exact").strip().lower() or "exact"
    if normalized_match_type not in {"exact", "fuzzy"}:
        raise ValueError("match_type must be one of: exact, fuzzy")

    load_balancers = context["client"].list_load_balancers(
        site_id=int(context["site_id"]),
        name=str(name or "").strip() or None,
        match_type=normalized_match_type,
    )
    return {
        "site_name": context["site_name"],
        "remote_site": context["remote_site"],
        "current_ns": context["current_ns"],
        "config_site": context["config_site"],
        "count": len(load_balancers),
        "load_balancers": load_balancers,
    }


def site_load_balancer_origin_status(
    *,
    site_name: str,
    load_balancer_ids: list[int] | None = None,
    pool_type: str = "",
) -> dict[str, Any]:
    context = _resolve_site_context(site_name, require_site_id=True)

    normalized_ids = [
        int(item)
        for item in (load_balancer_ids or [])
        if isinstance(item, int) and int(item) > 0
    ]
    if not normalized_ids:
        normalized_ids = [
            int(item.get("Id"))
            for item in context["client"].list_load_balancers(
                site_id=int(context["site_id"])
            )
            if isinstance(item, dict) and isinstance(item.get("Id"), int)
        ]

    origin_status = context["client"].list_load_balancer_origin_status(
        site_id=int(context["site_id"]),
        load_balancer_ids=normalized_ids,
        pool_type=str(pool_type or "").strip() or None,
    )
    return {
        "site_name": context["site_name"],
        "remote_site": context["remote_site"],
        "current_ns": context["current_ns"],
        "config_site": context["config_site"],
        "load_balancer_ids": normalized_ids,
        "pool_type": str(pool_type or "").strip(),
        "count": len(origin_status),
        "origin_status": origin_status,
    }


def _normalize_load_balancer_name(value: str, *, site_name: str) -> str:
    normalized = _normalize_subdomain_under_site(
        value, site_name=site_name, label="name"
    )

    return normalized


def _normalize_subdomain_under_site(
    value: str,
    *,
    site_name: str,
    label: str,
    allow_apex: bool = False,
) -> str:
    normalized = _require_text(value, label).strip().lower()
    normalized_site_name = _require_text(site_name, "site_name").strip().lower()
    if "." not in normalized:
        normalized = f"{normalized}.{normalized_site_name}"
    if normalized == normalized_site_name and allow_apex:
        return normalized
    if normalized == normalized_site_name or not normalized.endswith(
        f".{normalized_site_name}"
    ):
        raise ValueError(f"{label} must be a subdomain under the target ESA site")
    return normalized


def _resolve_origin_pool_id(
    client: AliyunEsaClient,
    *,
    site_id: int,
    pool_id: int | None = None,
    pool_name: str = "",
) -> int:
    if isinstance(pool_id, int) and pool_id > 0:
        return int(pool_id)

    normalized_name = _require_text(pool_name, "origin pool name").strip().lower()
    matches = [
        item
        for item in client.list_origin_pools(
            site_id=site_id,
            name=normalized_name,
            match_type="exact",
        )
        if isinstance(item, dict)
        and str(item.get("Name") or "").strip().lower() == normalized_name
        and isinstance(item.get("Id"), int)
        and int(item.get("Id")) > 0
    ]
    if not matches:
        raise ValueError(f"ESA origin pool '{normalized_name}' was not found")
    return int(matches[0]["Id"])


def _resolve_origin_pool_ids(
    client: AliyunEsaClient,
    *,
    site_id: int,
    pool_ids: list[int] | None = None,
    pool_names: list[str] | None = None,
) -> list[int]:
    resolved: list[int] = []
    for item in pool_ids or []:
        if isinstance(item, int) and item > 0 and item not in resolved:
            resolved.append(int(item))
    for item in pool_names or []:
        normalized_name = str(item or "").strip()
        if not normalized_name:
            continue
        resolved_id = _resolve_origin_pool_id(
            client,
            site_id=site_id,
            pool_name=normalized_name,
        )
        if resolved_id not in resolved:
            resolved.append(resolved_id)
    if not resolved:
        raise ValueError("at least one default origin pool is required")
    return resolved


def _resolve_load_balancer_id(
    client: AliyunEsaClient,
    *,
    site_id: int,
    load_balancer_id: int | None = None,
    name: str = "",
) -> int:
    if isinstance(load_balancer_id, int) and load_balancer_id > 0:
        return int(load_balancer_id)

    normalized_name = _require_text(name, "name").strip().lower()
    matches = [
        item
        for item in client.list_load_balancers(
            site_id=site_id,
            name=normalized_name,
            match_type="exact",
        )
        if isinstance(item, dict)
        and str(item.get("Name") or "").strip().lower() == normalized_name
        and isinstance(item.get("Id"), int)
        and int(item.get("Id")) > 0
    ]
    if not matches:
        raise ValueError(f"ESA load balancer '{normalized_name}' was not found")
    return int(matches[0]["Id"])


def _raise_load_balancer_create_error(
    exc: AliyunEsaApiError,
    *,
    site_name: str,
    load_balancer_name: str,
) -> None:
    detail = str(exc)
    if "LoadBalancerQuotaCheckFailed" in detail:
        raise ValueError(
            f"ESA load balancer '{load_balancer_name}' cannot be created on site '{site_name}' because the current plan does not expose usable load balancer quota: {detail}"
        ) from exc
    raise exc


def site_load_balancer_create(
    *,
    site_name: str,
    name: str,
    default_pool_ids: list[int] | None = None,
    default_pool_names: list[str] | None = None,
    fallback_pool_id: int | None = None,
    fallback_pool_name: str = "",
    description: str = "",
    monitor_type: str = "off",
    monitor_port: int = 0,
    monitor_path: str = "",
    monitor_method: str = "GET",
    steering_policy: str = "order",
    session_affinity: str = "off",
    ttl: int = 30,
    enabled: bool = True,
) -> dict[str, Any]:
    context = _resolve_site_context(site_name, require_site_id=True)
    site_id = int(context["site_id"])
    client = context["client"]

    load_balancer_name = _normalize_load_balancer_name(
        name, site_name=context["site_name"]
    )
    normalized_steering_policy = (
        str(steering_policy or "order").strip().lower() or "order"
    )
    if normalized_steering_policy not in {"order", "random"}:
        raise ValueError("steering_policy must be one of: order, random")

    normalized_session_affinity = (
        str(session_affinity or "off").strip().lower() or "off"
    )
    if normalized_session_affinity not in {"off", "ip", "cookie"}:
        raise ValueError("session_affinity must be one of: off, ip, cookie")

    normalized_monitor_type = str(monitor_type or "off").strip() or "off"
    resolved_default_pool_ids = _resolve_origin_pool_ids(
        client,
        site_id=site_id,
        pool_ids=default_pool_ids,
        pool_names=default_pool_names,
    )
    resolved_fallback_pool_id = (
        _resolve_origin_pool_id(
            client,
            site_id=site_id,
            pool_id=fallback_pool_id,
            pool_name=fallback_pool_name,
        )
        if (isinstance(fallback_pool_id, int) and fallback_pool_id > 0)
        or str(fallback_pool_name or "").strip()
        else resolved_default_pool_ids[0]
    )

    monitor_payload: dict[str, Any] = {"Type": normalized_monitor_type}
    if normalized_monitor_type.lower() != "off":
        if int(monitor_port or 0) > 0:
            monitor_payload["Port"] = int(monitor_port)
        if str(monitor_path or "").strip():
            monitor_payload["Path"] = str(monitor_path).strip()
        if str(monitor_method or "").strip():
            monitor_payload["Method"] = str(monitor_method).strip().upper()

    try:
        create_result = client.create_load_balancer(
            site_id=site_id,
            name=load_balancer_name,
            default_pools=resolved_default_pool_ids,
            fallback_pool=resolved_fallback_pool_id,
            monitor=monitor_payload,
            steering_policy=normalized_steering_policy,
            description=str(description or "").strip() or None,
            enabled=bool(enabled),
            session_affinity=normalized_session_affinity,
            ttl=max(10, min(600, int(ttl))),
            random_steering=(
                {"DefaultWeight": 100}
                if normalized_steering_policy == "random"
                else None
            ),
        )
    except AliyunEsaApiError as exc:
        _raise_load_balancer_create_error(
            exc,
            site_name=context["site_name"],
            load_balancer_name=load_balancer_name,
        )
    created_id = create_result.get("Id") if isinstance(create_result, dict) else None
    if not isinstance(created_id, int) or created_id <= 0:
        raise RuntimeError(
            f"ESA create load balancer returned an invalid Id for '{load_balancer_name}'"
        )
    load_balancer = client.get_load_balancer(
        site_id=site_id,
        load_balancer_id=created_id,
    )
    return {
        "site_name": context["site_name"],
        "remote_site": context["remote_site"],
        "current_ns": context["current_ns"],
        "config_site": context["config_site"],
        "resolved_default_pool_ids": resolved_default_pool_ids,
        "resolved_fallback_pool_id": resolved_fallback_pool_id,
        "create_result": create_result,
        "load_balancer": load_balancer,
    }


def site_load_balancer_delete(
    *,
    site_name: str,
    load_balancer_id: int | None = None,
    name: str = "",
) -> dict[str, Any]:
    context = _resolve_site_context(site_name, require_site_id=True)
    site_id = int(context["site_id"])
    client = context["client"]
    resolved_load_balancer_id = _resolve_load_balancer_id(
        client,
        site_id=site_id,
        load_balancer_id=load_balancer_id,
        name=name,
    )
    load_balancer = client.get_load_balancer(
        site_id=site_id,
        load_balancer_id=resolved_load_balancer_id,
    )
    delete_result = client.delete_load_balancer(
        site_id=site_id,
        load_balancer_id=resolved_load_balancer_id,
    )
    remaining = [
        item
        for item in client.list_load_balancers(
            site_id=site_id,
            name=str(load_balancer.get("Name") or "").strip() or None,
            match_type="exact",
        )
        if isinstance(item, dict)
        and int(item.get("Id") or 0) == resolved_load_balancer_id
    ]
    return {
        "site_name": context["site_name"],
        "remote_site": context["remote_site"],
        "current_ns": context["current_ns"],
        "config_site": context["config_site"],
        "load_balancer": load_balancer,
        "delete_result": delete_result,
        "deleted": len(remaining) == 0,
    }


def site_origin_pool_cname_apply(
    *,
    site_name: str,
    record_name: str,
    pool_name: str = "",
    pool_id: int | None = None,
    biz_name: str = "web",
    host_policy: str = "",
    ttl: int = 30,
    comment: str = "",
    purge_conflicts: bool = False,
    retry_attempts: int = DEFAULT_EXPOSURE_RETRY_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_EXPOSURE_RETRY_DELAY_SECONDS,
    restore_on_failure: bool = True,
) -> dict[str, Any]:
    context = _resolve_site_context(site_name, require_site_id=True)
    site_id = int(context["site_id"])
    client = context["client"]
    normalized_record_name = _normalize_subdomain_under_site(
        record_name,
        site_name=context["site_name"],
        label="record_name",
        allow_apex=True,
    )
    normalized_biz_name = str(biz_name or "web").strip() or "web"
    if normalized_biz_name not in {"web", "api", "image_video"}:
        raise ValueError("biz_name must be one of: web, api, image_video")

    normalized_host_policy = str(host_policy or "").strip()
    if normalized_host_policy not in {"", "follow_hostname", "follow_origin_domain"}:
        raise ValueError(
            "host_policy must be empty or one of: follow_hostname, follow_origin_domain"
        )

    resolved_pool_id = _resolve_origin_pool_id(
        client,
        site_id=site_id,
        pool_id=pool_id,
        pool_name=pool_name,
    )
    before_pool = client.get_origin_pool(
        site_id=site_id, origin_pool_id=resolved_pool_id
    )
    pool_record_name = str(before_pool.get("RecordName") or "").strip()
    if not pool_record_name:
        raise ValueError(
            f"ESA origin pool '{before_pool.get('Name')}' does not expose a usable RecordName"
        )

    record_result = _ensure_record(
        client,
        site_id=site_id,
        record_name=normalized_record_name,
        record_type="CNAME",
        data_value=pool_record_name,
        ttl=max(1, int(ttl)),
        proxied=True,
        biz_name=normalized_biz_name,
        source_type="OP",
        comment=str(comment or "").strip() or None,
        host_policy=normalized_host_policy or None,
        purge_conflicts=purge_conflicts,
        retry_attempts=retry_attempts,
        retry_delay_seconds=retry_delay_seconds,
        restore_on_failure=restore_on_failure,
    )
    after_pool = client.get_origin_pool(
        site_id=site_id, origin_pool_id=resolved_pool_id
    )
    return {
        "site_name": context["site_name"],
        "remote_site": context["remote_site"],
        "current_ns": context["current_ns"],
        "config_site": context["config_site"],
        "origin_pool": before_pool,
        "record": record_result,
        "before_references": before_pool.get("References"),
        "after_references": after_pool.get("References"),
        "after_reference_lb_count": after_pool.get("ReferenceLBCount"),
    }


def site_origin_pool_cname_delete(
    *,
    site_name: str,
    record_name: str,
) -> dict[str, Any]:
    context = _resolve_site_context(site_name, require_site_id=True)
    site_id = int(context["site_id"])
    client = context["client"]
    normalized_record_name = _normalize_subdomain_under_site(
        record_name,
        site_name=context["site_name"],
        label="record_name",
        allow_apex=True,
    )

    matches = [
        item
        for item in client.list_records(
            site_id=site_id, record_name=normalized_record_name
        )
        if isinstance(item, dict)
        and str(item.get("RecordName") or "").strip().lower() == normalized_record_name
        and _normalize_esa_record_type(str(item.get("RecordType") or "")) == "CNAME"
        and str(item.get("RecordSourceType") or "").strip() == "OP"
    ]
    if not matches:
        raise ValueError(
            f"ESA OP-backed CNAME record '{normalized_record_name}' was not found"
        )

    deleted: list[dict[str, Any]] = []
    for item in matches:
        record_id = item.get("RecordId")
        if not isinstance(record_id, int) or record_id <= 0:
            continue
        deleted.append(
            {
                "record": item,
                "delete_result": client.delete_record(record_id=record_id),
            }
        )

    remaining = [
        item
        for item in client.list_records(
            site_id=site_id, record_name=normalized_record_name
        )
        if isinstance(item, dict)
        and str(item.get("RecordName") or "").strip().lower() == normalized_record_name
        and _normalize_esa_record_type(str(item.get("RecordType") or "")) == "CNAME"
        and str(item.get("RecordSourceType") or "").strip() == "OP"
    ]
    return {
        "site_name": context["site_name"],
        "remote_site": context["remote_site"],
        "current_ns": context["current_ns"],
        "config_site": context["config_site"],
        "record_name": normalized_record_name,
        "deleted": deleted,
        "deleted_count": len(deleted),
        "remaining_count": len(remaining),
    }


def _cf_record_data(record: dict[str, Any]) -> tuple[str, str, dict[str, Any] | None]:
    record_type = str(record.get("type") or "").strip().upper()
    content = _normalize_record_value(record.get("content"))
    data = record.get("data") if isinstance(record.get("data"), dict) else {}

    if record_type in {"A", "AAAA", "CNAME", "TXT", "NS"}:
        return record_type, content, None
    if record_type == "MX":
        priority = data.get("priority", record.get("priority"))
        extra = {"Priority": int(priority)} if isinstance(priority, int) else None
        return record_type, content, extra
    if record_type == "CAA":
        extra = {
            "Flag": int(data.get("flags") or 0),
            "Tag": str(data.get("tag") or "").strip(),
        }
        return record_type, _normalize_record_value(data.get("value") or content), extra
    if record_type == "SRV":
        extra = {
            "Priority": int(data.get("priority") or 0),
            "Weight": int(data.get("weight") or 0),
            "Port": int(data.get("port") or 0),
        }
        return (
            record_type,
            _normalize_record_value(data.get("target") or content),
            extra,
        )
    raise ValueError(f"unsupported Cloudflare record type: {record_type}")


def _normalize_cf_ttl(value: object) -> int:
    if isinstance(value, bool):
        return 1
    if isinstance(value, int) and value > 0:
        return value
    return 1


def sync_site_dns_from_cloudflare(
    *,
    site_name: str,
    skip_record_names: list[str] | None = None,
    save_config: bool = False,
    strict: bool = True,
) -> dict[str, Any]:
    normalized_site_name = _require_text(site_name, "site_name")
    config_payload = load_ali_esa_config(validate=False)
    ensured_site = ensure_site(site_name=normalized_site_name, save_config=False)
    site_payload = ensured_site.get("site") or {}
    site_id = site_payload.get("site_id")
    if not isinstance(site_id, int) or site_id <= 0:
        raise ValueError(
            f"ESA site '{normalized_site_name}' does not have a valid SiteId"
        )

    client = _build_esa_client(config_payload)
    cf_client = _build_cloudflare_client(config_payload)
    zone_id = resolve_cloudflare_zone_id(config_payload, normalized_site_name)
    if not zone_id:
        raise ValueError(
            f"Could not resolve Cloudflare zone_id for site '{normalized_site_name}'"
        )

    skip_names = {
        str(item).strip().lower()
        for item in skip_record_names or []
        if str(item).strip()
    }
    cf_records = cf_client.list_dns_records(zone_id)
    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for record in cf_records:
        record_name = str(record.get("name") or "").strip()
        record_type = str(record.get("type") or "").strip().upper()
        if not record_name or not record_type:
            continue
        if record_name.lower() in skip_names:
            skipped.append(
                {
                    "record_name": record_name,
                    "record_type": record_type,
                    "reason": "explicitly skipped",
                }
            )
            continue
        if record_type == "SOA":
            skipped.append(
                {
                    "record_name": record_name,
                    "record_type": record_type,
                    "reason": "SOA is provider-managed",
                }
            )
            continue
        if record_type == "NS" and record_name.lower() == normalized_site_name.lower():
            skipped.append(
                {
                    "record_name": record_name,
                    "record_type": record_type,
                    "reason": "apex NS is provider-managed",
                }
            )
            continue
        if record_type not in SUPPORTED_CLOUDFLARE_IMPORT_RECORD_TYPES:
            error_payload = {
                "record_name": record_name,
                "record_type": record_type,
                "reason": "unsupported record type",
            }
            if strict:
                errors.append(error_payload)
                continue
            skipped.append(error_payload)
            continue
        if str(record.get("content") or "").strip().endswith("cfargotunnel.com"):
            skipped.append(
                {
                    "record_name": record_name,
                    "record_type": record_type,
                    "reason": "legacy Cloudflare Tunnel target",
                }
            )
            continue

        try:
            normalized_record_type, data_value, data_extra = _cf_record_data(record)
            result = _ensure_record(
                client,
                site_id=site_id,
                record_name=record_name,
                record_type=normalized_record_type,
                data_value=data_value,
                ttl=_normalize_cf_ttl(record.get("ttl")),
                proxied=False,
                biz_name=None,
                data_extra=data_extra,
            )
        except (AliyunEsaApiError, ValueError) as exc:
            errors.append(
                {
                    "record_name": record_name,
                    "record_type": record_type,
                    "reason": str(exc),
                }
            )
            continue

        imported.append(
            {
                "record_name": record_name,
                "record_type": normalized_record_type,
                "created": result.get("created"),
                "updated": result.get("updated"),
            }
        )

    if errors and strict:
        raise RuntimeError(
            "Failed to sync Cloudflare DNS records to ESA: "
            + "; ".join(
                f"{item['record_name']}[{item['record_type']}]: {item['reason']}"
                for item in errors
            )
        )

    persisted_site = _upsert_site_payload(
        config_payload,
        site_name=normalized_site_name,
        coverage=str(
            site_payload.get("coverage")
            or config_payload.get("default_coverage")
            or "overseas"
        ),
        access_type=str(
            site_payload.get("access_type")
            or config_payload.get("default_access_type")
            or "NS"
        ),
        instance_id=str(
            site_payload.get("instance_id")
            or config_payload.get("default_instance_id")
            or ""
        ),
        site_data={
            "SiteId": site_id,
            "Status": site_payload.get("status"),
            "NameServerList": site_payload.get("name_server_list"),
            "VerifyCode": site_payload.get("verify_code"),
            "cloudflare_zone_id": zone_id,
        },
        current_ns=site_payload.get("current_ns") or [],
        last_cloudflare_sync_at=_utc_now_iso(),
    )
    saved_config_path = _persist_config_if_requested(
        config_payload,
        save_config=save_config,
    )
    return {
        "site_name": normalized_site_name,
        "site": _serialize_site(persisted_site),
        "cloudflare_zone_id": zone_id,
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "config_saved": saved_config_path,
    }


def _task_state(details: list[dict[str, Any]]) -> str:
    if not details:
        return "unknown"
    states = {
        str(
            item.get("TaskStatus")
            or item.get("Status")
            or item.get("DetailStatus")
            or ""
        )
        .strip()
        .lower()
        for item in details
        if isinstance(item, dict)
    }
    if not states:
        return "unknown"
    if states <= {"success", "succeed", "succeeded", "completed", "done"}:
        return "succeeded"
    if states & {"fail", "failed", "error", "rejected"}:
        return "failed"
    return "pending"


def activate_site_ns(
    *,
    site_name: str,
    save_config: bool = False,
    wait: bool = False,
    verify_site_after_switch: bool = False,
    verify_attempts: int = DEFAULT_SITE_VERIFY_ATTEMPTS,
    verify_interval_seconds: int = DEFAULT_SITE_VERIFY_INTERVAL_SECONDS,
) -> dict[str, Any]:
    normalized_site_name = _require_text(site_name, "site_name")
    config_payload = load_ali_esa_config(validate=False)
    ensured_site = ensure_site(site_name=normalized_site_name, save_config=False)
    site_payload = ensured_site.get("site") or {}
    site_id = site_payload.get("site_id")
    if not isinstance(site_id, int) or site_id <= 0:
        raise ValueError(
            f"ESA site '{normalized_site_name}' does not have a valid SiteId"
        )

    nameservers = _normalize_nameservers(site_payload.get("name_server_list"))
    if not nameservers:
        raise ValueError(
            f"ESA site '{normalized_site_name}' does not have assigned nameservers yet"
        )

    registrar = _build_registrar_client(config_payload)
    task_no = registrar.modify_domain_dns(
        domain_name=normalized_site_name,
        nameservers=nameservers,
    )
    details = registrar.query_task_details(task_no=task_no)
    state = _task_state(details)
    if wait and state == "pending":
        for _ in range(20):
            time.sleep(15)
            details = registrar.query_task_details(task_no=task_no)
            state = _task_state(details)
            if state != "pending":
                break

    verify_result: dict[str, Any] | None = None
    current_ns: list[str] = []
    if verify_site_after_switch:
        client = _build_esa_client(config_payload)
        for _ in range(max(1, int(verify_attempts))):
            try:
                current_ns = client.get_site_current_ns(site_id=site_id)
            except AliyunEsaApiError:
                current_ns = []
            verify_result = client.verify_site(site_id=site_id)
            if bool((verify_result or {}).get("Passed")):
                break
            time.sleep(max(1, int(verify_interval_seconds)))

    persisted_site = _upsert_site_payload(
        config_payload,
        site_name=normalized_site_name,
        coverage=str(
            site_payload.get("coverage")
            or config_payload.get("default_coverage")
            or "overseas"
        ),
        access_type=str(
            site_payload.get("access_type")
            or config_payload.get("default_access_type")
            or "NS"
        ),
        instance_id=str(
            site_payload.get("instance_id")
            or config_payload.get("default_instance_id")
            or ""
        ),
        site_data={
            "SiteId": site_id,
            "Status": site_payload.get("status"),
            "NameServerList": nameservers,
            "VerifyCode": site_payload.get("verify_code"),
        },
        current_ns=current_ns or _normalize_nameservers(site_payload.get("current_ns")),
        registrar_task_no=task_no,
        last_verified_at=(
            _utc_now_iso() if bool((verify_result or {}).get("Passed")) else None
        ),
    )
    saved_config_path = _persist_config_if_requested(
        config_payload,
        save_config=save_config,
    )
    return {
        "site_name": normalized_site_name,
        "task_no": task_no,
        "task_state": state,
        "task_details": details,
        "verify_result": verify_result,
        "site": _serialize_site(persisted_site),
        "config_saved": saved_config_path,
    }


def apply_exposure(
    *,
    domain_name: str,
    local_url: str,
    zone_name: str = "",
    coverage: str = "",
    access_type: str = "",
    instance_id: str = "",
    origin_address: str = "auto",
    record_mode: str = DEFAULT_EXPOSURE_RECORD_MODE,
    origin_pool_name: str = "",
    origin_pool_id: int | None = None,
    biz_name: str = "web",
    host_policy: str = "",
    ttl: int = 30,
    comment: str = "",
    purge_conflicts: bool = False,
    save_config: bool = False,
    verify_site_after_apply: bool = False,
    retry_attempts: int = DEFAULT_EXPOSURE_RETRY_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_EXPOSURE_RETRY_DELAY_SECONDS,
    restore_on_failure: bool = True,
) -> dict[str, Any]:
    hostname = _require_text(domain_name, "domain_name")
    normalized_site_name = str(zone_name or infer_site_name(hostname)).strip()
    origin = _parse_origin(local_url)
    normalized_record_mode = _normalize_exposure_record_mode(record_mode)
    config_payload = load_ali_esa_config(validate=False)
    ensured_site = ensure_site(
        site_name=normalized_site_name,
        coverage=coverage,
        access_type=access_type,
        instance_id=instance_id,
        save_config=False,
    )
    site_payload = ensured_site.get("site") or {}
    site_id = site_payload.get("site_id")
    if not isinstance(site_id, int) or site_id <= 0:
        raise ValueError(
            f"ESA site '{normalized_site_name}' does not have a valid SiteId"
        )

    client = _build_esa_client(config_payload)

    exposure_record: dict[str, Any]
    record_result: dict[str, Any]
    if normalized_record_mode == "origin-pool":
        origin_pool_result = site_origin_pool_cname_apply(
            site_name=normalized_site_name,
            record_name=hostname,
            pool_name=origin_pool_name,
            pool_id=origin_pool_id,
            biz_name=biz_name,
            host_policy=host_policy,
            ttl=ttl,
            comment=comment,
            purge_conflicts=purge_conflicts,
            retry_attempts=retry_attempts,
            retry_delay_seconds=retry_delay_seconds,
            restore_on_failure=restore_on_failure,
        )
        origin_pool_payload = origin_pool_result.get("origin_pool") or {}
        origins = origin_pool_payload.get("Origins") or []
        primary_origin = origins[0] if origins else {}
        resolved_origin_address = str(primary_origin.get("Address") or "").strip()
        if not resolved_origin_address:
            raise ValueError(
                f"ESA origin pool '{origin_pool_payload.get('Name')}' does not expose a usable origin address"
            )
        parsed_origin_address = ip_address(resolved_origin_address)
        pool_record_name = str(origin_pool_payload.get("RecordName") or "").strip()
        exposure_record = {
            "address": resolved_origin_address,
            "family": f"ipv{parsed_origin_address.version}",
            "source": "origin-pool",
            "record_type": "CNAME",
            "record_value": pool_record_name,
            "record_addresses": [resolved_origin_address],
            "record_family": f"ipv{parsed_origin_address.version}",
            "record_mode": normalized_record_mode,
            "record_source_type": "OP",
            "origin_pool": {
                "id": origin_pool_payload.get("Id"),
                "name": origin_pool_payload.get("Name"),
                "record_name": pool_record_name,
            },
        }
        record_result = _serialize_record_result(origin_pool_result.get("record") or {})
    else:
        exposure_record = _resolve_exposure_record(
            config_payload,
            site_payload,
            hostname=hostname,
            origin_address=origin_address,
        )
        resolved_origin_address = str(exposure_record["address"])
        record_result = _ensure_record(
            client,
            site_id=site_id,
            record_name=hostname,
            record_type=str(exposure_record["record_type"]),
            data_value=str(exposure_record["record_value"]),
            ttl=1,
            proxied=True,
            biz_name="web",
            purge_conflicts=purge_conflicts,
            retry_attempts=retry_attempts,
            retry_delay_seconds=retry_delay_seconds,
            restore_on_failure=restore_on_failure,
        )

    resolved_origin_address = str(exposure_record["address"])
    origin_address_source = str(exposure_record["source"])
    origin_address_family = str(exposure_record["family"])
    record_type = str(exposure_record["record_type"])
    record_value = str(exposure_record["record_value"])

    origin_verify = None if origin["scheme"] == "http" else "off"
    origin_rule_result = _ensure_origin_rule(
        client,
        site_id=site_id,
        hostname=hostname,
        origin_scheme=origin["scheme"],
        origin_port=int(origin["port"]),
        origin_host=hostname,
        origin_sni=(hostname if origin["scheme"] == "https" else None),
        origin_verify=origin_verify,
        origin_read_timeout=10,
    )

    persisted_public_origin_address = (
        None
        if origin_address_source == "cloudflare-authoritative"
        else resolved_origin_address
    )

    verify_result = None
    current_ns: list[str] | None = None
    if verify_site_after_apply:
        verify_result = client.verify_site(site_id=site_id)
        try:
            current_ns = client.get_site_current_ns(site_id=site_id)
        except AliyunEsaApiError:
            current_ns = []

    persisted_site = _upsert_site_payload(
        config_payload,
        site_name=normalized_site_name,
        coverage=str(
            site_payload.get("coverage")
            or coverage
            or config_payload.get("default_coverage")
            or "overseas"
        ),
        access_type=str(
            site_payload.get("access_type")
            or access_type
            or config_payload.get("default_access_type")
            or "NS"
        ),
        instance_id=str(
            site_payload.get("instance_id")
            or instance_id
            or config_payload.get("default_instance_id")
            or ""
        ),
        site_data={
            "SiteId": site_id,
            "Status": site_payload.get("status"),
            "NameServerList": site_payload.get("name_server_list"),
            "VerifyCode": site_payload.get("verify_code"),
        },
        current_ns=(
            current_ns
            if current_ns is not None
            else site_payload.get("current_ns") or []
        ),
        cloudflare_name_server_list=(
            site_payload.get("cloudflare_name_server_list")
            or site_payload.get("current_ns")
        ),
        public_origin_address=persisted_public_origin_address,
        last_verified_at=(
            _utc_now_iso() if bool((verify_result or {}).get("Passed")) else None
        ),
        last_exposure_applied_at=_utc_now_iso(),
    )
    saved_config_path = _persist_config_if_requested(
        config_payload,
        save_config=save_config,
    )
    return {
        "site": _serialize_site(persisted_site),
        "hostname": hostname,
        "local_url": local_url,
        "origin": {
            **origin,
            "public_address": resolved_origin_address,
            "public_address_family": origin_address_family,
            "public_address_source": origin_address_source,
            "record_mode": normalized_record_mode,
            "record_type": record_type,
            "record_value": record_value,
            "record_addresses": list(exposure_record["record_addresses"]),
            "record_family": str(exposure_record["record_family"]),
            "record_source_type": str(exposure_record.get("record_source_type") or ""),
            "origin_pool": exposure_record.get("origin_pool"),
        },
        "record": record_result,
        "origin_rule": origin_rule_result,
        "verify_result": verify_result,
        "config_saved": saved_config_path,
    }


def _resolved_addresses(hostname: str) -> list[dict[str, str]]:
    try:
        addrinfo = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    results: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for family, _, _, _, sockaddr in addrinfo:
        ip = str(sockaddr[0]).strip()
        if not ip:
            continue
        family_name = "ipv6" if family == socket.AF_INET6 else "ipv4"
        key = (ip, family_name)
        if key in seen:
            continue
        seen.add(key)
        results.append({"ip": ip, "family": family_name})
    return results


def _snapshot_entry(hostname: str, client: AliyunEsaClient) -> dict[str, Any]:
    resolved = _resolved_addresses(hostname)
    esa_ip_info = (
        client.list_esa_ip_info(ips=[item["ip"] for item in resolved])
        if resolved
        else []
    )
    esa_lookup = {
        str(item.get("Ip") or "").strip(): str(item.get("CdnIp") or "").strip().lower()
        == "true"
        for item in esa_ip_info
        if isinstance(item, dict)
    }

    matched = [item for item in resolved if esa_lookup.get(item["ip"], False)]
    unmatched = [
        item
        for item in resolved
        if item["ip"] not in {value["ip"] for value in matched}
    ]

    if not resolved:
        recommended_prefer_family = None
        reason_codes = ["dns_lookup_failed"]
        family_summary = (
            "Local resolver could not return any public IP for this hostname."
        )
    elif not matched:
        recommended_prefer_family = None
        reason_codes = ["dns_mismatch"]
        family_summary = "The current DNS answer does not point at ESA edge IPs yet."
    elif unmatched:
        families = {item["family"] for item in matched}
        recommended_prefer_family = (
            next(iter(families)) if len(families) == 1 else "any"
        )
        reason_codes = ["recursive_dns_mismatch"]
        family_summary = "Some resolved IPs belong to ESA, but at least one answer still points elsewhere."
    else:
        families = {item["family"] for item in matched}
        recommended_prefer_family = (
            next(iter(families)) if len(families) == 1 else "any"
        )
        reason_codes = []
        family_summary = "The current DNS answer is served by ESA edge IPs."

    top_candidates = matched or resolved
    public_probe: dict[str, Any] | None = None
    try:
        started_at = time.perf_counter()
        response = requests.get(f"https://{hostname}/", timeout=10)
        public_probe = {
            "ok": response.ok,
            "status_code": response.status_code,
            "latency_ms": int(round((time.perf_counter() - started_at) * 1000)),
        }
    except requests.RequestException as exc:
        public_probe = {
            "ok": False,
            "error": str(exc),
        }

    files = {}
    operator_shortcuts = {
        "first_round_strategy": "esa-edge-check",
        "manual_checks": [
            {
                "label": "Google DNS Resolve",
                "url": f"https://dns.google/resolve?name={hostname}&type=A",
                "mode": "manual",
            },
            {
                "label": "Public HTTPS",
                "url": f"https://{hostname}/",
                "mode": "manual",
            },
        ],
        "automation_ready": [],
    }
    if top_candidates:
        primary = top_candidates[0]
        rollout_template = {
            "primary_candidate_ip": primary["ip"],
            "primary_candidate_family": primary["family"],
        }
    else:
        rollout_template = {}

    return {
        "hostname": hostname,
        "generated_at": _utc_now_iso(),
        "provider": "ali-esa",
        "recommended_prefer_family": recommended_prefer_family,
        "family_summary": family_summary,
        "reason_codes": reason_codes,
        "observed_colos": [],
        "top_candidates": top_candidates,
        "operator_shortcuts": operator_shortcuts,
        "rollout_template": rollout_template,
        "files": files,
        "resolved_addresses": resolved,
        "esa_ip_matches": [
            {
                "ip": item["ip"],
                "family": item["family"],
                "is_esa": esa_lookup.get(item["ip"], False),
            }
            for item in resolved
        ],
        "public_probe": public_probe,
    }


def snapshot(
    *,
    names: list[str],
    output_dir: Path | str = DEFAULT_SNAPSHOT_OUTPUT_DIR,
    stamp: str | None = None,
) -> dict[str, Any]:
    normalized_names = [_require_text(item, "name") for item in names]
    snapshot_label = str(stamp or "").strip() or _utc_now().strftime("%Y%m%dT%H%M%SZ")
    destination_dir = _project_relative_output_dir(output_dir) / snapshot_label
    destination_dir.mkdir(parents=True, exist_ok=True)

    config_payload = load_ali_esa_config(validate=False)
    client = _build_esa_client(config_payload)
    entries = [_snapshot_entry(name, client) for name in normalized_names]
    summary = {
        "provider": "ali-esa",
        "generated_at": _utc_now_iso(),
        "snapshot_label": snapshot_label,
        "snapshots": entries,
    }
    summary_path = destination_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "provider": "ali-esa",
        "snapshot_label": snapshot_label,
        "output_dir": str(destination_dir),
        "summary_path": str(summary_path),
        "snapshots": entries,
    }
