from __future__ import annotations

import json
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
    origin_address: str,
) -> dict[str, Any]:
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
    data_payload = record.get("Data") if isinstance(record.get("Data"), dict) else {}
    if data_extra:
        for key, value in data_extra.items():
            if key == "Value":
                continue
            if data_payload.get(key) != value:
                return False
    return True


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
) -> dict[str, Any]:
    existing_records = client.list_records(
        site_id=site_id,
        record_name=record_name,
    )
    deleted_conflicts: list[dict[str, Any]] = []
    normalized_record_type = _normalize_esa_record_type(record_type)
    normalized_data_value = _normalize_esa_record_data_value(record_type, data_value)
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
            if not isinstance(record_id, int):
                continue
            client.delete_record(record_id=record_id)
            deleted_conflicts.append(
                {
                    "record_id": record_id,
                    "record_name": item.get("RecordName"),
                    "record_type": existing_type,
                }
            )
        if deleted_conflicts:
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
            data_extra=data_extra,
        ):
            return {
                "record": item,
                "created": False,
                "updated": False,
                "deleted_conflicts": deleted_conflicts,
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
            "deleted_conflicts": deleted_conflicts,
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
        "deleted_conflicts": deleted_conflicts,
    }


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
        "selected_instance": selected_instance,
        "site": _serialize_site(persisted_site),
        "config_saved": saved_config_path,
    }


def site_status(*, site_name: str) -> dict[str, Any]:
    normalized_site_name = _require_text(site_name, "site_name")
    config_payload = load_ali_esa_config(validate=False)
    client = _build_esa_client(config_payload)
    remote_site = client.get_site(site_name=normalized_site_name)
    current_ns: list[str] = []
    site_id = remote_site.get("SiteId") if isinstance(remote_site, dict) else None
    if isinstance(site_id, int) and site_id > 0:
        try:
            current_ns = client.get_site_current_ns(site_id=site_id)
        except AliyunEsaApiError:
            current_ns = []
    return {
        "site_name": normalized_site_name,
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
    normalized_site_name = _require_text(site_name, "site_name")
    config_payload = load_ali_esa_config(validate=False)
    client = _build_esa_client(config_payload)
    remote_site = client.get_site(site_name=normalized_site_name)
    site_id = remote_site.get("SiteId") if isinstance(remote_site, dict) else None
    if not isinstance(site_id, int) or site_id <= 0:
        raise ValueError(
            f"ESA site '{normalized_site_name}' does not exist or does not have a valid SiteId"
        )

    current_ns: list[str] = []
    try:
        current_ns = client.get_site_current_ns(site_id=site_id)
    except AliyunEsaApiError:
        current_ns = []

    records = client.list_records(
        site_id=site_id,
        record_name=str(record_name or "").strip() or None,
        record_type=str(record_type or "").strip() or None,
    )
    return {
        "site_name": normalized_site_name,
        "remote_site": remote_site,
        "current_ns": current_ns,
        "config_site": _serialize_site(find_site(config_payload, normalized_site_name)),
        "count": len(records),
        "records": records,
    }


def site_origin_pools(
    *,
    site_name: str,
    name: str = "",
    match_type: str = "exact",
) -> dict[str, Any]:
    normalized_site_name = _require_text(site_name, "site_name")
    config_payload = load_ali_esa_config(validate=False)
    client = _build_esa_client(config_payload)
    remote_site = client.get_site(site_name=normalized_site_name)
    site_id = remote_site.get("SiteId") if isinstance(remote_site, dict) else None
    if not isinstance(site_id, int) or site_id <= 0:
        raise ValueError(
            f"ESA site '{normalized_site_name}' does not exist or does not have a valid SiteId"
        )

    current_ns: list[str] = []
    try:
        current_ns = client.get_site_current_ns(site_id=site_id)
    except AliyunEsaApiError:
        current_ns = []

    normalized_match_type = str(match_type or "exact").strip().lower() or "exact"
    if normalized_match_type not in {"exact", "fuzzy"}:
        raise ValueError("match_type must be one of: exact, fuzzy")

    origin_pools = client.list_origin_pools(
        site_id=site_id,
        name=str(name or "").strip() or None,
        match_type=normalized_match_type,
    )
    return {
        "site_name": normalized_site_name,
        "remote_site": remote_site,
        "current_ns": current_ns,
        "config_site": _serialize_site(find_site(config_payload, normalized_site_name)),
        "count": len(origin_pools),
        "origin_pools": origin_pools,
    }


def site_load_balancers(
    *,
    site_name: str,
    name: str = "",
    match_type: str = "exact",
) -> dict[str, Any]:
    normalized_site_name = _require_text(site_name, "site_name")
    config_payload = load_ali_esa_config(validate=False)
    client = _build_esa_client(config_payload)
    remote_site = client.get_site(site_name=normalized_site_name)
    site_id = remote_site.get("SiteId") if isinstance(remote_site, dict) else None
    if not isinstance(site_id, int) or site_id <= 0:
        raise ValueError(
            f"ESA site '{normalized_site_name}' does not exist or does not have a valid SiteId"
        )

    current_ns: list[str] = []
    try:
        current_ns = client.get_site_current_ns(site_id=site_id)
    except AliyunEsaApiError:
        current_ns = []

    normalized_match_type = str(match_type or "exact").strip().lower() or "exact"
    if normalized_match_type not in {"exact", "fuzzy"}:
        raise ValueError("match_type must be one of: exact, fuzzy")

    load_balancers = client.list_load_balancers(
        site_id=site_id,
        name=str(name or "").strip() or None,
        match_type=normalized_match_type,
    )
    return {
        "site_name": normalized_site_name,
        "remote_site": remote_site,
        "current_ns": current_ns,
        "config_site": _serialize_site(find_site(config_payload, normalized_site_name)),
        "count": len(load_balancers),
        "load_balancers": load_balancers,
    }


def site_load_balancer_origin_status(
    *,
    site_name: str,
    load_balancer_ids: list[int] | None = None,
    pool_type: str = "",
) -> dict[str, Any]:
    normalized_site_name = _require_text(site_name, "site_name")
    config_payload = load_ali_esa_config(validate=False)
    client = _build_esa_client(config_payload)
    remote_site = client.get_site(site_name=normalized_site_name)
    site_id = remote_site.get("SiteId") if isinstance(remote_site, dict) else None
    if not isinstance(site_id, int) or site_id <= 0:
        raise ValueError(
            f"ESA site '{normalized_site_name}' does not exist or does not have a valid SiteId"
        )

    current_ns: list[str] = []
    try:
        current_ns = client.get_site_current_ns(site_id=site_id)
    except AliyunEsaApiError:
        current_ns = []

    normalized_ids = [
        int(item)
        for item in (load_balancer_ids or [])
        if isinstance(item, int) and int(item) > 0
    ]
    if not normalized_ids:
        normalized_ids = [
            int(item.get("Id"))
            for item in client.list_load_balancers(site_id=site_id)
            if isinstance(item, dict) and isinstance(item.get("Id"), int)
        ]

    origin_status = client.list_load_balancer_origin_status(
        site_id=site_id,
        load_balancer_ids=normalized_ids,
        pool_type=str(pool_type or "").strip() or None,
    )
    return {
        "site_name": normalized_site_name,
        "remote_site": remote_site,
        "current_ns": current_ns,
        "config_site": _serialize_site(find_site(config_payload, normalized_site_name)),
        "load_balancer_ids": normalized_ids,
        "pool_type": str(pool_type or "").strip(),
        "count": len(origin_status),
        "origin_status": origin_status,
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
    save_config: bool = False,
    verify_site_after_apply: bool = False,
) -> dict[str, Any]:
    hostname = _require_text(domain_name, "domain_name")
    normalized_site_name = str(zone_name or infer_site_name(hostname)).strip()
    origin = _parse_origin(local_url)
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

    exposure_record = _resolve_exposure_record(
        config_payload,
        site_payload,
        origin_address=origin_address,
    )
    resolved_origin_address = str(exposure_record["address"])
    origin_address_source = str(exposure_record["source"])
    origin_address_family = str(exposure_record["family"])
    record_type = str(exposure_record["record_type"])
    record_value = str(exposure_record["record_value"])

    client = _build_esa_client(config_payload)
    record_result = _ensure_record(
        client,
        site_id=site_id,
        record_name=hostname,
        record_type=record_type,
        data_value=record_value,
        ttl=1,
        proxied=True,
        biz_name="web",
        purge_conflicts=True,
    )
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
        public_origin_address=resolved_origin_address,
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
            "record_type": record_type,
            "record_value": record_value,
            "record_addresses": list(exposure_record["record_addresses"]),
            "record_family": str(exposure_record["record_family"]),
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
