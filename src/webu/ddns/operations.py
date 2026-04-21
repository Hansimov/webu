from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import tempfile

from pathlib import Path
from typing import Any

import yaml

from webu.ali_esa.clients import AliyunEsaClient
from webu.ali_esa.schema import find_site, load_ali_esa_config, resolve_credentials
from webu.schema import (
    find_project_root,
    render_template_json,
    validate_payload_against_schema,
)
from webu.sudo import run as sudo_run

from .schema import (
    DDNS_CONFIG,
    DEFAULT_CACHE_TIMES,
    DEFAULT_DDNS_GO_BINARY,
    DEFAULT_DDNS_GO_CONFIG_DIR,
    DEFAULT_PROVIDER,
    DEFAULT_RUN_INTERVAL_SECONDS,
    DEFAULT_TARGET_SEED_IPV6,
    DEFAULT_TARGET_TTL,
    DdnsTargetConfig,
    delete_target,
    find_target,
    list_targets,
    load_ddns_config,
    normalize_ipv6_source_mode,
    normalize_provider,
    save_ddns_config,
    upsert_target,
)


DEFAULT_DDNS_RUN_TIMEOUT_SECONDS = 15
ORIGIN_POOL_PROVIDER = "aliesa-origin-pool"
DIRECT_RECORD_PROVIDER = "aliesa-record"
DIRECT_RECORD_TYPE = "A/AAAA"


def _printable_process_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


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


def _resolve_project_path(raw_value: str, *, default: Path | None = None) -> Path:
    candidate = (
        Path(raw_value).expanduser() if str(raw_value or "").strip() else default
    )
    if candidate is None:
        raise ValueError("path is required")
    if candidate.is_absolute():
        return candidate.resolve()
    return (_project_root() / candidate).resolve()


def _ensure_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    normalized.setdefault("ddns_go_binary", DEFAULT_DDNS_GO_BINARY)
    normalized.setdefault("default_run_interval_seconds", DEFAULT_RUN_INTERVAL_SECONDS)
    normalized.setdefault("default_cache_times", DEFAULT_CACHE_TIMES)
    normalized.setdefault("targets", [])
    return normalized


def _serialize_target(target: DdnsTargetConfig) -> dict[str, Any]:
    return {
        "name": target.name,
        "provider": target.provider,
        "site_name": target.site_name,
        "pool_name": target.pool_name,
        "origin_name": target.origin_name,
        "record_name": target.record_name,
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


def config_schema_json() -> dict[str, Any]:
    return DDNS_CONFIG.schema


def config_check() -> list[str]:
    payload = load_ddns_config(validate=False)
    return validate_payload_against_schema(
        payload, DDNS_CONFIG.schema, DDNS_CONFIG.name
    )


def config_init(*, force: bool) -> str:
    config_path = _project_root() / "configs" / DDNS_CONFIG.file_name
    if config_path.exists() and not force:
        raise FileExistsError(
            f"{config_path} already exists; rerun with --force to overwrite"
        )
    payload = json.loads(render_template_json(DDNS_CONFIG))
    return str(save_ddns_config(payload))


def target_list() -> dict[str, Any]:
    payload = _ensure_payload(load_ddns_config(validate=False))
    targets = list_targets(payload)
    return {
        "count": len(targets),
        "targets": [_serialize_target(item) for item in targets],
    }


def target_upsert(
    *,
    name: str,
    site_name: str,
    pool_name: str = "",
    origin_name: str = "",
    record_name: str = "",
    provider: str = DEFAULT_PROVIDER,
    enabled: bool | None = None,
    target_ipv6: str = "",
    seed_ipv6: str = DEFAULT_TARGET_SEED_IPV6,
    ipv6_source_mode: str = "cmd",
    ipv6_url: str = "https://api6.ipify.org",
    ttl: int = DEFAULT_TARGET_TTL,
    binary_path: str = "",
    config_path: str = "",
    run_interval_seconds: int = DEFAULT_RUN_INTERVAL_SECONDS,
    cache_times: int = DEFAULT_CACHE_TIMES,
    service_name: str = "",
    save_config: bool = False,
) -> dict[str, Any]:
    payload = _ensure_payload(load_ddns_config(validate=False))
    existing = find_target(payload, name)
    raw = dict(existing.raw) if existing is not None else {}
    normalized_provider = normalize_provider(provider)
    resolved_site_name = _require_text(
        site_name or (existing.site_name if existing else ""), "site_name"
    )
    resolved_pool_name = str(
        pool_name or (existing.pool_name if existing else "")
    ).strip()
    resolved_origin_name = str(
        origin_name or (existing.origin_name if existing else "")
    ).strip()
    resolved_record_name = str(
        record_name or (existing.record_name if existing else "")
    ).strip()
    if normalized_provider == ORIGIN_POOL_PROVIDER:
        resolved_pool_name = _require_text(resolved_pool_name, "pool_name")
        resolved_origin_name = _require_text(resolved_origin_name, "origin_name")
    elif normalized_provider == DIRECT_RECORD_PROVIDER:
        resolved_record_name = _require_text(resolved_record_name, "record_name")
    updated = DdnsTargetConfig(
        name=_require_text(name, "name"),
        provider=normalized_provider,
        site_name=resolved_site_name,
        pool_name=resolved_pool_name,
        origin_name=resolved_origin_name,
        record_name=resolved_record_name,
        enabled=(
            bool(enabled)
            if enabled is not None
            else (existing.enabled if existing else True)
        ),
        target_ipv6=str(
            target_ipv6 or (existing.target_ipv6 if existing else "")
        ).strip(),
        seed_ipv6=str(
            seed_ipv6 or (existing.seed_ipv6 if existing else DEFAULT_TARGET_SEED_IPV6)
        ).strip()
        or DEFAULT_TARGET_SEED_IPV6,
        ipv6_source_mode=normalize_ipv6_source_mode(
            ipv6_source_mode or (existing.ipv6_source_mode if existing else "cmd")
        ),
        ipv6_url=str(
            ipv6_url or (existing.ipv6_url if existing else "https://api6.ipify.org")
        ).strip()
        or "https://api6.ipify.org",
        ttl=max(1, int(ttl or (existing.ttl if existing else DEFAULT_TARGET_TTL))),
        binary_path=str(
            binary_path or (existing.binary_path if existing else "")
        ).strip(),
        config_path=str(
            config_path or (existing.config_path if existing else "")
        ).strip(),
        run_interval_seconds=max(
            1,
            int(
                run_interval_seconds
                or (
                    existing.run_interval_seconds
                    if existing
                    else DEFAULT_RUN_INTERVAL_SECONDS
                )
            ),
        ),
        cache_times=max(
            1,
            int(
                cache_times
                or (existing.cache_times if existing else DEFAULT_CACHE_TIMES)
            ),
        ),
        service_name=str(
            service_name or (existing.service_name if existing else "")
        ).strip(),
        raw=raw,
    )
    payload = upsert_target(payload, updated)
    saved_config_path = str(save_ddns_config(payload)) if save_config else None
    return {
        "target": _serialize_target(updated),
        "config_saved": saved_config_path,
    }


def target_delete(*, name: str, save_config: bool = True) -> dict[str, Any]:
    payload = _ensure_payload(load_ddns_config(validate=False))
    updated_payload, removed = delete_target(payload, name)
    if removed is None:
        raise ValueError(f"ddns target '{name}' not found in configs/ddns.json")
    saved_config_path = str(save_ddns_config(updated_payload)) if save_config else None
    return {
        "target": _serialize_target(removed),
        "config_saved": saved_config_path,
        "remaining_count": len(list_targets(updated_payload)),
    }


def _resolve_binary_path(payload: dict[str, Any], target: DdnsTargetConfig) -> Path:
    candidates: list[str] = []
    for raw_value in [
        target.binary_path,
        str(payload.get("ddns_go_binary") or "").strip(),
        DEFAULT_DDNS_GO_BINARY,
        "ddns-go",
    ]:
        normalized = str(raw_value or "").strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    for candidate in candidates:
        if "/" not in candidate and not candidate.startswith("."):
            resolved = shutil.which(candidate)
            if resolved:
                return Path(resolved).expanduser().resolve()
        try:
            resolved_path = _resolve_project_path(candidate)
        except Exception:
            continue
        if resolved_path.exists() and resolved_path.is_file():
            return resolved_path

    raise FileNotFoundError(
        "Could not find ddns-go binary; set ddns_go_binary or target.binary_path in configs/ddns.json"
    )


def _maybe_resolve_binary_path(
    payload: dict[str, Any], target: DdnsTargetConfig
) -> str:
    try:
        return str(_resolve_binary_path(payload, target))
    except FileNotFoundError:
        return ""


def _resolve_config_path(target: DdnsTargetConfig) -> Path:
    configured = str(target.config_path or "").strip()
    if configured:
        return _resolve_project_path(configured)
    return _resolve_project_path(
        "",
        default=Path(DEFAULT_DDNS_GO_CONFIG_DIR) / f"{target.name}.yaml",
    )


def _ddns_service_name(target: DdnsTargetConfig) -> str:
    configured = str(target.service_name or "").strip()
    if configured:
        return (
            configured if configured.endswith(".service") else f"{configured}.service"
        )
    return f"wdns-{_safe_systemd_token(target.name)}.service"


def _ddns_service_path(service_name: str) -> Path:
    return Path("/etc/systemd/system") / service_name


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
        detail = summary["stderr"] or summary["stdout"] or "unknown error"
        raise RuntimeError(f"{label} failed: {detail}")
    return summary


def _build_esa_client(config_payload: dict[str, Any]) -> AliyunEsaClient:
    credentials = resolve_credentials(config_payload)
    return AliyunEsaClient(
        access_key_id=_require_text(
            credentials.get("aliyun_access_id"), "aliyun_access_id"
        ),
        access_key_secret=_require_text(
            credentials.get("aliyun_access_secret"),
            "aliyun_access_secret",
        ),
        region_id=str(credentials.get("region_id") or "cn-hangzhou").strip()
        or "cn-hangzhou",
    )


def _resolve_target_ipv6(
    ali_esa_payload: dict[str, Any], *, target: DdnsTargetConfig
) -> str:
    explicit = str(target.target_ipv6 or "").strip()
    if explicit:
        return explicit

    site = find_site(ali_esa_payload, target.site_name)
    for candidate in [
        site.public_origin_address if site is not None else "",
        ali_esa_payload.get("default_public_origin_ipv6"),
    ]:
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized

    raise ValueError(
        "target_ipv6 is required because configs/ali_esa.json does not contain a usable default_public_origin_ipv6"
    )


def _find_site_id(client: AliyunEsaClient, site_name: str) -> int:
    site = client.get_site(site_name=site_name)
    if not isinstance(site, dict):
        raise ValueError(f"ESA site '{site_name}' was not found")
    site_id = site.get("SiteId")
    if not isinstance(site_id, int) or site_id <= 0:
        raise ValueError(f"ESA site '{site_name}' does not have a valid SiteId")
    return site_id


def _find_origin_pool(
    client: AliyunEsaClient,
    *,
    site_id: int,
    pool_name: str,
) -> dict[str, Any] | None:
    normalized_name = pool_name.strip().lower()
    for item in client.list_origin_pools(
        site_id=site_id, name=pool_name, match_type="exact"
    ):
        if str(item.get("Name") or "").strip().lower() != normalized_name:
            continue
        pool_id = item.get("Id")
        if isinstance(pool_id, int) and pool_id > 0:
            return client.get_origin_pool(site_id=site_id, origin_pool_id=pool_id)
    return None


def _build_origin_entry(
    *,
    origin_name: str,
    address: str,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(existing or {})
    payload["Name"] = origin_name
    payload["Address"] = address
    payload["Type"] = str(payload.get("Type") or "ip_domain").strip() or "ip_domain"
    payload["Enabled"] = bool(payload.get("Enabled", True))
    payload["Weight"] = int(payload.get("Weight") or 100)
    return payload


def _upsert_origin_pool(
    client: AliyunEsaClient,
    *,
    site_id: int,
    target: DdnsTargetConfig,
    target_ipv6: str,
    seed_existing: bool,
) -> tuple[dict[str, Any], str]:
    pool = _find_origin_pool(client, site_id=site_id, pool_name=target.pool_name)
    if pool is None:
        initial_address = target.seed_ipv6 if seed_existing else target_ipv6
        created = client.create_origin_pool(
            site_id=site_id,
            name=target.pool_name,
            enabled=True,
            origins=[
                _build_origin_entry(
                    origin_name=target.origin_name,
                    address=initial_address,
                )
            ],
        )
        created_id = created.get("Id") if isinstance(created, dict) else None
        if isinstance(created_id, int) and created_id > 0:
            refreshed = client.get_origin_pool(
                site_id=site_id, origin_pool_id=created_id
            )
        else:
            refreshed = _find_origin_pool(
                client, site_id=site_id, pool_name=target.pool_name
            )
        if refreshed is None:
            raise RuntimeError(f"Failed to create origin pool '{target.pool_name}'")
        return refreshed, "created"

    pool_id = pool.get("Id")
    if not isinstance(pool_id, int) or pool_id <= 0:
        raise RuntimeError(f"Origin pool '{target.pool_name}' does not have a valid Id")

    origins: list[dict[str, Any]] = []
    found_origin = False
    changed = False
    for item in pool.get("Origins") if isinstance(pool.get("Origins"), list) else []:
        origin = dict(item) if isinstance(item, dict) else {}
        if str(origin.get("Name") or "").strip() == target.origin_name:
            found_origin = True
            if seed_existing:
                current_address = str(origin.get("Address") or "").strip()
                if current_address != target.seed_ipv6:
                    changed = True
                    origins.append(
                        _build_origin_entry(
                            origin_name=target.origin_name,
                            address=target.seed_ipv6,
                            existing=origin,
                        )
                    )
                else:
                    origins.append(origin)
            else:
                origins.append(origin)
        else:
            origins.append(origin)

    if not found_origin:
        changed = True
        origins.append(
            _build_origin_entry(
                origin_name=target.origin_name,
                address=(target.seed_ipv6 if seed_existing else target_ipv6),
            )
        )

    if changed:
        client.update_origin_pool(
            site_id=site_id,
            origin_pool_id=pool_id,
            enabled=bool(pool.get("Enabled", True)),
            origins=origins,
        )
        refreshed = client.get_origin_pool(site_id=site_id, origin_pool_id=pool_id)
        return refreshed, "seeded" if seed_existing else "updated"

    return pool, "unchanged"


def _build_ddns_go_config_payload(
    *,
    config_name: str = "aliesa-origin-pool-ipv6",
    access_key_id: str,
    access_key_secret: str,
    domain: str,
    ttl: int,
    ipv6_source_mode: str,
    target_ipv6: str,
    ipv6_url: str,
) -> dict[str, Any]:
    ipv6_block = {
        "enable": True,
        "gettype": ipv6_source_mode,
        "url": ipv6_url if ipv6_source_mode == "url" else "",
        "netinterface": "",
        "cmd": "",
        "ipv6reg": "",
        "domains": [domain],
    }
    if ipv6_source_mode == "cmd":
        ipv6_block["cmd"] = f"printf '%s\\n' '{target_ipv6}'"

    return {
        "name": config_name,
        "ttl": str(ttl),
        "dns": {
            "name": "aliesa",
            "id": access_key_id,
            "secret": access_key_secret,
            "extparam": "",
        },
        "ipv4": {
            "enable": False,
            "gettype": "url",
            "url": "",
            "netinterface": "",
            "cmd": "",
            "domains": [],
        },
        "ipv6": ipv6_block,
        "httpinterface": "",
    }


def _write_ddns_go_config(
    *,
    config_path: Path,
    config_name: str = "aliesa-origin-pool-ipv6",
    access_key_id: str,
    access_key_secret: str,
    domain: str,
    ttl: int,
    ipv6_source_mode: str,
    target_ipv6: str,
    ipv6_url: str,
) -> Path:
    payload = _build_ddns_go_config_payload(
        config_name=config_name,
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        domain=domain,
        ttl=ttl,
        ipv6_source_mode=ipv6_source_mode,
        target_ipv6=target_ipv6,
        ipv6_url=ipv6_url,
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    return config_path


def _extract_origin_address(pool: dict[str, Any], *, origin_name: str) -> str:
    for item in pool.get("Origins") if isinstance(pool.get("Origins"), list) else []:
        if str(item.get("Name") or "").strip() == origin_name:
            return str(item.get("Address") or "").strip()
    return ""


def _find_site_record(
    client: AliyunEsaClient,
    *,
    site_id: int,
    record_name: str,
    record_type: str = DIRECT_RECORD_TYPE,
) -> dict[str, Any] | None:
    normalized_record_name = record_name.strip().lower()
    normalized_record_type = record_type.strip().upper()
    for item in client.list_records(
        site_id=site_id,
        record_name=record_name,
        record_type=record_type,
    ):
        if str(item.get("RecordName") or "").strip().lower() != normalized_record_name:
            continue
        item_record_type = (
            str(item.get("RecordType") or item.get("Type") or "").strip().upper()
        )
        if item_record_type != normalized_record_type:
            continue
        record_id = item.get("RecordId")
        if isinstance(record_id, int) and record_id > 0:
            return item
    return None


def _extract_record_value(record: dict[str, Any] | None) -> str:
    if not isinstance(record, dict):
        return ""
    data = record.get("Data")
    if isinstance(data, dict):
        return str(data.get("Value") or "").strip()
    return ""


def _upsert_site_record(
    client: AliyunEsaClient,
    *,
    site_id: int,
    target: DdnsTargetConfig,
    seed_existing: bool,
) -> tuple[dict[str, Any] | None, str]:
    record = _find_site_record(
        client,
        site_id=site_id,
        record_name=target.record_name,
        record_type=DIRECT_RECORD_TYPE,
    )
    if record is None:
        if not seed_existing:
            return None, "absent"
        client.create_record(
            site_id=site_id,
            record_name=target.record_name,
            record_type=DIRECT_RECORD_TYPE,
            ttl=max(60, int(target.ttl)),
            data_value=target.seed_ipv6,
            proxied=False,
        )
        refreshed = _find_site_record(
            client,
            site_id=site_id,
            record_name=target.record_name,
            record_type=DIRECT_RECORD_TYPE,
        )
        if refreshed is None:
            raise RuntimeError(f"Failed to create record '{target.record_name}'")
        return refreshed, "seed-created"

    if not seed_existing:
        return record, "existing"

    current_value = _extract_record_value(record)
    if current_value == target.seed_ipv6:
        return record, "unchanged"

    record_id = record.get("RecordId")
    if not isinstance(record_id, int) or record_id <= 0:
        raise RuntimeError(
            f"Record '{target.record_name}' does not have a valid RecordId"
        )
    client.update_record(
        record_id=record_id,
        record_type=DIRECT_RECORD_TYPE,
        ttl=max(60, int(target.ttl)),
        data_value=target.seed_ipv6,
        proxied=False,
    )
    refreshed = _find_site_record(
        client,
        site_id=site_id,
        record_name=target.record_name,
        record_type=DIRECT_RECORD_TYPE,
    )
    if refreshed is None:
        raise RuntimeError(f"Record '{target.record_name}' disappeared after seeding")
    return refreshed, "seeded"


def _prepare_origin_pool_target(
    payload: dict[str, Any],
    target: DdnsTargetConfig,
    *,
    seed_existing: bool,
) -> dict[str, Any]:
    ali_esa_payload = load_ali_esa_config(validate=False)
    credentials = resolve_credentials(ali_esa_payload)
    client = _build_esa_client(ali_esa_payload)
    site_id = _find_site_id(client, target.site_name)
    target_ipv6 = _resolve_target_ipv6(ali_esa_payload, target=target)
    pool, pool_action = _upsert_origin_pool(
        client,
        site_id=site_id,
        target=target,
        target_ipv6=target_ipv6,
        seed_existing=seed_existing,
    )
    config_path = _write_ddns_go_config(
        config_path=_resolve_config_path(target),
        config_name=f"{ORIGIN_POOL_PROVIDER}-ipv6",
        access_key_id=_require_text(
            credentials.get("aliyun_access_id"),
            "aliyun_access_id",
        ),
        access_key_secret=_require_text(
            credentials.get("aliyun_access_secret"),
            "aliyun_access_secret",
        ),
        domain=f"{target.pool_name}.origin-pool.{target.site_name}?Name={target.origin_name}",
        ttl=max(60, int(target.ttl)),
        ipv6_source_mode=target.ipv6_source_mode,
        target_ipv6=target_ipv6,
        ipv6_url=target.ipv6_url,
    )
    return {
        "target": _serialize_target(target),
        "site_id": site_id,
        "target_ipv6": target_ipv6,
        "pool_action": pool_action,
        "origin_pool": pool,
        "current_origin_address": _extract_origin_address(
            pool, origin_name=target.origin_name
        ),
        "pool_ddns_go_domain": f"{target.pool_name}.origin-pool.{target.site_name}?Name={target.origin_name}",
        "ddns_go_config_path": str(config_path),
        "binary_path": _maybe_resolve_binary_path(payload, target),
        "service_name": _ddns_service_name(target),
    }


def _prepare_record_target(
    payload: dict[str, Any],
    target: DdnsTargetConfig,
    *,
    seed_existing: bool,
) -> dict[str, Any]:
    ali_esa_payload = load_ali_esa_config(validate=False)
    credentials = resolve_credentials(ali_esa_payload)
    client = _build_esa_client(ali_esa_payload)
    site_id = _find_site_id(client, target.site_name)
    target_ipv6 = _resolve_target_ipv6(ali_esa_payload, target=target)
    record, record_action = _upsert_site_record(
        client,
        site_id=site_id,
        target=target,
        seed_existing=seed_existing,
    )
    config_path = _write_ddns_go_config(
        config_path=_resolve_config_path(target),
        config_name=f"{DIRECT_RECORD_PROVIDER}-ipv6",
        access_key_id=_require_text(
            credentials.get("aliyun_access_id"),
            "aliyun_access_id",
        ),
        access_key_secret=_require_text(
            credentials.get("aliyun_access_secret"),
            "aliyun_access_secret",
        ),
        domain=target.record_name,
        ttl=max(60, int(target.ttl)),
        ipv6_source_mode=target.ipv6_source_mode,
        target_ipv6=target_ipv6,
        ipv6_url=target.ipv6_url,
    )
    return {
        "target": _serialize_target(target),
        "site_id": site_id,
        "target_ipv6": target_ipv6,
        "record_action": record_action,
        "site_record": record,
        "current_record_value": _extract_record_value(record),
        "record_ddns_go_domain": target.record_name,
        "ddns_go_config_path": str(config_path),
        "binary_path": _maybe_resolve_binary_path(payload, target),
        "service_name": _ddns_service_name(target),
    }


def _load_target_or_raise(name: str) -> tuple[dict[str, Any], DdnsTargetConfig]:
    payload = _ensure_payload(load_ddns_config(validate=False))
    target = find_target(payload, name)
    if target is None:
        raise ValueError(f"ddns target '{name}' not found in configs/ddns.json")
    if not target.enabled:
        raise ValueError(f"ddns target '{name}' is disabled")
    return payload, target


def target_prepare(*, name: str, seed_existing: bool = False) -> dict[str, Any]:
    payload, target = _load_target_or_raise(name)
    if target.provider == ORIGIN_POOL_PROVIDER:
        return _prepare_origin_pool_target(
            payload,
            target,
            seed_existing=seed_existing,
        )
    if target.provider == DIRECT_RECORD_PROVIDER:
        return _prepare_record_target(
            payload,
            target,
            seed_existing=seed_existing,
        )
    raise NotImplementedError(f"unsupported ddns provider: {target.provider}")


def target_run_once(
    *,
    name: str,
    seed_existing: bool = False,
    timeout_seconds: int = DEFAULT_DDNS_RUN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    prepared = target_prepare(name=name, seed_existing=seed_existing)
    payload, target = _load_target_or_raise(name)
    binary_path = _resolve_binary_path(payload, target)
    command = [
        str(binary_path),
        "-noweb",
        "-c",
        str(prepared["ddns_go_config_path"]),
        "-f",
        str(max(60, int(target.run_interval_seconds))),
        "-cacheTimes",
        str(max(1, int(target.cache_times))),
    ]

    timed_out = False
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=_project_root(),
            timeout=max(1, int(timeout_seconds)),
        )
        process_summary = {
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        process_summary = {
            "returncode": 124,
            "stdout": _printable_process_output(exc.stdout).strip(),
            "stderr": _printable_process_output(exc.stderr).strip(),
            "timed_out": True,
        }

    ali_esa_payload = load_ali_esa_config(validate=False)
    client = _build_esa_client(ali_esa_payload)
    site_id = int(prepared["site_id"])
    target_ipv6 = str(prepared["target_ipv6"])
    if target.provider == ORIGIN_POOL_PROVIDER:
        pool = _find_origin_pool(client, site_id=site_id, pool_name=target.pool_name)
        if pool is None:
            raise RuntimeError(
                f"origin pool '{target.pool_name}' disappeared after ddns-go run"
            )
        current_value = _extract_origin_address(pool, origin_name=target.origin_name)
        verification_state = {
            "current_origin_address": current_value,
            "origin_pool": pool,
        }
    elif target.provider == DIRECT_RECORD_PROVIDER:
        record = _find_site_record(
            client,
            site_id=site_id,
            record_name=target.record_name,
            record_type=DIRECT_RECORD_TYPE,
        )
        current_value = _extract_record_value(record)
        verification_state = {
            "current_record_value": current_value,
            "site_record": record,
        }
    else:
        raise NotImplementedError(f"unsupported ddns provider: {target.provider}")
    output_text = "\n".join(
        [
            part
            for part in [process_summary["stdout"], process_summary["stderr"]]
            if part
        ]
    )
    normalized_output_text = output_text.lower()
    return {
        **prepared,
        "command": command,
        "process": process_summary,
        "timed_out": timed_out,
        **verification_state,
        "verified": current_value == target_ipv6,
        "log_contains_update": (
            "updated domain" in normalized_output_text
            or "added domain" in normalized_output_text
        ),
    }


def _render_ddns_service_unit(
    *,
    target: DdnsTargetConfig,
    binary_path: Path,
    config_path: Path,
) -> str:
    project_root = _project_root()
    exec_start = shlex.join(
        [
            str(binary_path),
            "-noweb",
            "-c",
            str(config_path),
            "-f",
            str(max(60, int(target.run_interval_seconds))),
            "-cacheTimes",
            str(max(1, int(target.cache_times))),
        ]
    )
    return "\n".join(
        [
            "[Unit]",
            f"Description=wdns target {target.name}",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"WorkingDirectory={project_root}",
            f"Environment=WEBU_PROJECT_ROOT={project_root}",
            f"Environment=WEBU_CONFIG_DIR={project_root / 'configs'}",
            f"ExecStart={exec_start}",
            "Restart=always",
            "RestartSec=5s",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )


def service_install(*, name: str, seed_existing: bool = False) -> dict[str, Any]:
    prepared = target_prepare(name=name, seed_existing=seed_existing)
    payload, target = _load_target_or_raise(name)
    service_name = _ddns_service_name(target)
    service_path = _ddns_service_path(service_name)
    unit_text = _render_ddns_service_unit(
        target=target,
        binary_path=_resolve_binary_path(payload, target),
        config_path=Path(str(prepared["ddns_go_config_path"])),
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(unit_text)
        temp_path = Path(handle.name)

    try:
        write_result = _ensure_success(
            sudo_run(
                ["install", "-D", "-m", "644", str(temp_path), str(service_path)],
                check=False,
                timeout=60,
            ),
            label=f"install systemd unit {service_name}",
        )
        daemon_reload_result = _ensure_success(
            sudo_run(["systemctl", "daemon-reload"], check=False, timeout=60),
            label="systemctl daemon-reload",
        )
        enable_result = _ensure_success(
            sudo_run(["systemctl", "enable", service_name], check=False, timeout=60),
            label=f"systemctl enable {service_name}",
        )
        restart_result = _summarize_completed_process(
            sudo_run(["systemctl", "restart", service_name], check=False, timeout=60)
        )
        status_result = _ensure_success(
            sudo_run(
                [
                    "systemctl",
                    "show",
                    "--property",
                    "LoadState,ActiveState,SubState,UnitFileState,FragmentPath",
                    service_name,
                ],
                check=False,
                timeout=60,
            ),
            label=f"systemctl show {service_name}",
        )
    finally:
        temp_path.unlink(missing_ok=True)

    return {
        **prepared,
        "service_name": service_name,
        "service_path": str(service_path),
        "write_unit": write_result,
        "daemon_reload": daemon_reload_result,
        "enable_service": enable_result,
        "restart_service": restart_result,
        "service_status": status_result,
    }


def service_status(*, name: str) -> dict[str, Any]:
    payload, target = _load_target_or_raise(name)
    service_name = _ddns_service_name(target)
    return {
        "target": _serialize_target(target),
        "service_name": service_name,
        "service_path": str(_ddns_service_path(service_name)),
        "binary_path": str(_resolve_binary_path(payload, target)),
        "config_path": str(_resolve_config_path(target)),
        "show": _summarize_completed_process(
            sudo_run(
                [
                    "systemctl",
                    "show",
                    "--property",
                    "LoadState,ActiveState,SubState,UnitFileState,FragmentPath",
                    service_name,
                ],
                check=False,
                timeout=60,
            )
        ),
        "is_active": _summarize_completed_process(
            sudo_run(["systemctl", "is-active", service_name], check=False, timeout=60)
        ),
        "is_enabled": _summarize_completed_process(
            sudo_run(["systemctl", "is-enabled", service_name], check=False, timeout=60)
        ),
    }


def service_logs(*, name: str, lines: int = 100) -> dict[str, Any]:
    _, target = _load_target_or_raise(name)
    service_name = _ddns_service_name(target)
    return {
        "service_name": service_name,
        "lines": max(1, int(lines)),
        "journal": _summarize_completed_process(
            sudo_run(
                [
                    "journalctl",
                    "-u",
                    service_name,
                    "-n",
                    str(max(1, int(lines))),
                    "--no-pager",
                ],
                check=False,
                timeout=60,
            )
        ),
    }


def service_restart(*, name: str, seed_existing: bool = False) -> dict[str, Any]:
    prepared = target_prepare(name=name, seed_existing=seed_existing)
    _, target = _load_target_or_raise(name)
    service_name = _ddns_service_name(target)
    restart_result = _summarize_completed_process(
        sudo_run(["systemctl", "restart", service_name], check=False, timeout=60)
    )
    show_result = _summarize_completed_process(
        sudo_run(
            [
                "systemctl",
                "show",
                "--property",
                "LoadState,ActiveState,SubState,UnitFileState,FragmentPath",
                service_name,
            ],
            check=False,
            timeout=60,
        )
    )
    return {
        **prepared,
        "service_name": service_name,
        "restart_service": restart_result,
        "service_status": show_result,
    }


def service_disable(*, name: str, purge_unit_file: bool = False) -> dict[str, Any]:
    _, target = _load_target_or_raise(name)
    service_name = _ddns_service_name(target)
    service_path = _ddns_service_path(service_name)
    stop_result = _summarize_completed_process(
        sudo_run(["systemctl", "stop", service_name], check=False, timeout=60)
    )
    disable_result = _summarize_completed_process(
        sudo_run(["systemctl", "disable", service_name], check=False, timeout=60)
    )
    purge_result: dict[str, Any] | None = None
    daemon_reload_result: dict[str, Any] | None = None
    if purge_unit_file:
        purge_result = _summarize_completed_process(
            sudo_run(["rm", "-f", str(service_path)], check=False, timeout=60)
        )
        daemon_reload_result = _summarize_completed_process(
            sudo_run(["systemctl", "daemon-reload"], check=False, timeout=60)
        )
    return {
        "service_name": service_name,
        "service_path": str(service_path),
        "stop_service": stop_result,
        "disable_service": disable_result,
        "purge_unit_file": purge_result,
        "daemon_reload": daemon_reload_result,
    }
