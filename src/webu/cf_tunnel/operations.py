from __future__ import annotations

import json
import shutil

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from webu.clis import prompt_choice, prompt_secret, prompt_text
from webu.schema import (
    find_project_root,
    render_config_markdown,
    render_template_json,
    validate_payload_against_schema,
)
from webu.sudo import run as sudo_run

from .clients import (
    AliyunApiError,
    AliyunDomainClient,
    CloudflareApiError,
    CloudflareClient,
)
from .helptext import CONFIGS_DOC_PATH, USAGE_DOC_PATH, render_usage_markdown
from .schema import (
    CF_TUNNEL_CONFIG,
    DomainConfig,
    TunnelConfig,
    infer_zone_name,
    list_domains,
    list_tunnels,
    load_cf_tunnel_config,
    save_cf_tunnel_config,
    upsert_domain,
    upsert_tunnel,
)


@dataclass(frozen=True)
class CloudflareCredentialResolution:
    api_token: str
    source: str
    created: bool


def _require_text(value: str, label: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


def _domain_lookup(
    payload: dict[str, Any], domain_name: str, *, zone_name: str | None = None
) -> DomainConfig:
    for item in list_domains(payload):
        if item.domain_name == domain_name or item.zone_name == (zone_name or ""):
            return item
    resolved_zone_name = zone_name or infer_zone_name(domain_name)
    return DomainConfig(
        domain_name=domain_name,
        zone_name=resolved_zone_name,
        zone_id="",
        cloudflare_nameservers=[],
        aliyun_task_no="",
        raw={},
    )


def _tunnel_lookup(
    payload: dict[str, Any], *, tunnel_name: str | None = None
) -> TunnelConfig:
    tunnels = list_tunnels(payload)
    if not tunnels:
        raise ValueError("no cf_tunnels entries found in configs/cf_tunnel.json")
    if tunnel_name:
        for item in tunnels:
            if item.tunnel_name == tunnel_name or item.domain_name == tunnel_name:
                return item
        raise ValueError(f"tunnel '{tunnel_name}' not found in configs/cf_tunnel.json")
    if len(tunnels) != 1:
        raise ValueError("multiple tunnels configured; choose one with --name")
    return tunnels[0]


def _write_payload(payload: dict[str, Any], *, save_config: bool) -> Path | None:
    if not save_config:
        return None
    return save_cf_tunnel_config(payload)


def ensure_cf_api_token(
    payload: dict[str, Any],
    *,
    account_id: str,
    zone_name: str,
    zone_id: str | None,
    token_mode: str,
    save_config: bool,
) -> CloudflareCredentialResolution:
    configured_api_token = str(payload.get("cf_api_token", "")).strip()
    if configured_api_token:
        return CloudflareCredentialResolution(configured_api_token, "config", False)

    if token_mode == "manual":
        manual_token = prompt_secret("Cloudflare API token")
        payload["cf_api_token"] = manual_token
        _write_payload(payload, save_config=save_config)
        return CloudflareCredentialResolution(manual_token, "manual", False)

    bootstrap_token = str(payload.get("cf_account_api_tokens_edit_token", "")).strip()
    if not bootstrap_token:
        if token_mode == "prompt":
            chosen = prompt_choice(
                "Cloudflare token source", ["manual", "existing"], default="manual"
            )
            if chosen == "manual":
                manual_token = prompt_secret("Cloudflare API token")
                payload["cf_api_token"] = manual_token
                _write_payload(payload, save_config=save_config)
                return CloudflareCredentialResolution(manual_token, "manual", False)
        raise ValueError(
            "cf_api_token is missing and cf_account_api_tokens_edit_token is unavailable for auto creation"
        )

    bootstrap_client = CloudflareClient(bootstrap_token)
    token_name = f"cftn-{zone_name}"
    created = bootstrap_client.create_api_token(
        name=token_name,
        account_id=account_id,
        zone_id=zone_id,
        include_zone_write=not bool(zone_id),
        expires_in_days=30,
    )
    payload["cf_api_token"] = created["value"]
    _write_payload(payload, save_config=save_config)
    return CloudflareCredentialResolution(created["value"], "auto", True)


def ensure_aliyun_client(
    payload: dict[str, Any], *, credential_mode: str
) -> AliyunDomainClient:
    access_id = str(payload.get("aliyun_access_id", "")).strip()
    access_secret = str(payload.get("aliyun_access_secret", "")).strip()
    if not access_id or not access_secret:
        if credential_mode != "manual":
            raise ValueError(
                "Aliyun credentials are missing; rerun with --aliyun-credential-mode manual or fill configs/cf_tunnel.json"
            )
        access_id = prompt_text("Aliyun AccessKey ID")
        access_secret = prompt_secret("Aliyun AccessKey Secret")
    return AliyunDomainClient(access_id, access_secret)


def ensure_domain_zone(
    payload: dict[str, Any],
    *,
    domain_name: str,
    zone_name: str | None,
    cf_token_mode: str,
    save_config: bool,
) -> tuple[dict[str, Any], DomainConfig, CloudflareCredentialResolution]:
    account_id = _require_text(str(payload.get("cf_account_id", "")), "cf_account_id")
    domain = _domain_lookup(payload, domain_name, zone_name=zone_name)
    bootstrap_or_existing = ensure_cf_api_token(
        payload,
        account_id=account_id,
        zone_name=domain.zone_name,
        zone_id=domain.zone_id or None,
        token_mode=cf_token_mode,
        save_config=save_config,
    )
    cf_client = CloudflareClient(bootstrap_or_existing.api_token)
    zone = cf_client.ensure_zone(account_id=account_id, zone_name=domain.zone_name)
    nameservers = [
        str(item).strip() for item in zone.get("name_servers", []) if str(item).strip()
    ]
    updated_domain = DomainConfig(
        domain_name=domain.domain_name,
        zone_name=domain.zone_name,
        zone_id=str(zone.get("id", "")).strip(),
        cloudflare_nameservers=nameservers,
        aliyun_task_no=domain.aliyun_task_no,
        raw=domain.raw,
    )
    payload = upsert_domain(payload, updated_domain)
    _write_payload(payload, save_config=save_config)

    if bootstrap_or_existing.created and not updated_domain.zone_id:
        return zone, updated_domain, bootstrap_or_existing

    if bootstrap_or_existing.source == "auto" and updated_domain.zone_id:
        return zone, updated_domain, bootstrap_or_existing

    if bootstrap_or_existing.source == "config" and updated_domain.zone_id:
        return zone, updated_domain, bootstrap_or_existing

    if str(payload.get("cf_api_token", "")).strip() and updated_domain.zone_id:
        return zone, updated_domain, bootstrap_or_existing

    return zone, updated_domain, bootstrap_or_existing


def migrate_dns_to_cloudflare(
    *,
    domain_name: str,
    zone_name: str | None,
    cf_token_mode: str,
    aliyun_credential_mode: str,
    save_config: bool,
) -> dict[str, Any]:
    payload = load_cf_tunnel_config()
    zone, domain, credential = ensure_domain_zone(
        payload,
        domain_name=domain_name,
        zone_name=zone_name,
        cf_token_mode=cf_token_mode,
        save_config=save_config,
    )
    nameservers = domain.cloudflare_nameservers
    if len(nameservers) < 2:
        raise CloudflareApiError(
            "Cloudflare did not return at least two assigned nameservers for the zone"
        )
    aliyun_client = ensure_aliyun_client(
        payload, credential_mode=aliyun_credential_mode
    )
    task_no = aliyun_client.modify_domain_dns(
        domain_name=domain.domain_name, nameservers=nameservers
    )
    task_details = aliyun_client.query_task_details(task_no=task_no)
    updated_domain = DomainConfig(
        domain_name=domain.domain_name,
        zone_name=domain.zone_name,
        zone_id=domain.zone_id,
        cloudflare_nameservers=nameservers,
        aliyun_task_no=task_no,
        raw=domain.raw,
    )
    payload = upsert_domain(payload, updated_domain)
    config_path = _write_payload(payload, save_config=save_config)
    return {
        "domain_name": domain.domain_name,
        "zone_name": domain.zone_name,
        "zone_id": domain.zone_id,
        "nameservers": nameservers,
        "aliyun_task_no": task_no,
        "aliyun_task_details": task_details,
        "cf_token_source": credential.source,
        "config_path": str(config_path) if config_path else "",
        "verification": {
            "precheck": [
                f"dig @{nameservers[0]} {domain.domain_name} A",
                f"dig @{nameservers[1]} {domain.domain_name} MX",
            ],
            "propagation": [
                f"dig {domain.domain_name} NS",
                f"dig +trace {domain.domain_name} A",
            ],
        },
    }


def apply_tunnel(
    *,
    tunnel_name: str | None,
    apply_all: bool,
    install_service: bool,
    cf_token_mode: str,
    save_config: bool,
) -> list[dict[str, Any]]:
    payload = load_cf_tunnel_config()
    account_id = _require_text(str(payload.get("cf_account_id", "")), "cf_account_id")
    targets = (
        list_tunnels(payload)
        if apply_all
        else [_tunnel_lookup(payload, tunnel_name=tunnel_name)]
    )
    results: list[dict[str, Any]] = []

    for item in targets:
        _, domain, credential = ensure_domain_zone(
            payload,
            domain_name=item.zone_name,
            zone_name=item.zone_name,
            cf_token_mode=cf_token_mode,
            save_config=save_config,
        )
        cf_client = CloudflareClient(credential.api_token)
        tunnel = cf_client.ensure_tunnel(
            account_id=account_id, tunnel_name=item.tunnel_name
        )
        tunnel_id = str(tunnel.get("id", item.tunnel_id)).strip()
        tunnel_token = str(
            tunnel.get("token", "")
        ).strip() or cf_client.get_tunnel_token(
            account_id=account_id, tunnel_id=tunnel_id
        )
        cf_client.put_tunnel_configuration(
            account_id=account_id,
            tunnel_id=tunnel_id,
            hostname=item.domain_name,
            service=item.local_url,
        )
        cf_client.upsert_cname_record(
            zone_id=domain.zone_id,
            hostname=item.domain_name,
            content=f"{tunnel_id}.cfargotunnel.com",
            proxied=True,
        )
        updated_tunnel = TunnelConfig(
            tunnel_name=item.tunnel_name,
            domain_name=item.domain_name,
            local_url=item.local_url,
            zone_name=item.zone_name,
            tunnel_id=tunnel_id,
            tunnel_token=tunnel_token,
            raw=item.raw,
        )
        payload = upsert_tunnel(payload, updated_tunnel)
        config_path = _write_payload(payload, save_config=save_config)
        install_result: dict[str, Any] | None = None
        if install_service:
            if not shutil.which("cloudflared"):
                raise FileNotFoundError("cloudflared is not installed or not in PATH")
            completed = sudo_run(
                ["cloudflared", "service", "install", tunnel_token],
                check=False,
                timeout=60,
            )
            install_result = {
                "returncode": completed.returncode,
                "stdout": completed.stdout.decode(errors="replace").strip(),
                "stderr": completed.stderr.decode(errors="replace").strip(),
            }
        results.append(
            {
                "tunnel_name": item.tunnel_name,
                "domain_name": item.domain_name,
                "local_url": item.local_url,
                "zone_name": item.zone_name,
                "tunnel_id": tunnel_id,
                "tunnel_token_saved": bool(tunnel_token),
                "install_command": "sudo cloudflared service install <TUNNEL_TOKEN>",
                "install_result": install_result or {},
                "cf_token_source": credential.source,
                "config_path": str(config_path) if config_path else "",
            }
        )
    return results


def tunnel_status(*, tunnel_name: str | None, cf_token_mode: str) -> dict[str, Any]:
    payload = load_cf_tunnel_config()
    account_id = _require_text(str(payload.get("cf_account_id", "")), "cf_account_id")
    target = _tunnel_lookup(payload, tunnel_name=tunnel_name)
    credential = ensure_cf_api_token(
        payload,
        account_id=account_id,
        zone_name=target.zone_name,
        zone_id=None,
        token_mode=cf_token_mode,
        save_config=False,
    )
    cf_client = CloudflareClient(credential.api_token)
    tunnel_id = target.tunnel_id
    if not tunnel_id:
        tunnel = cf_client.ensure_tunnel(
            account_id=account_id, tunnel_name=target.tunnel_name
        )
        tunnel_id = str(tunnel.get("id", "")).strip()
    result = cf_client.get_tunnel(account_id=account_id, tunnel_id=tunnel_id)
    return {
        "tunnel_name": target.tunnel_name,
        "tunnel_id": tunnel_id,
        "status": result.get("status", "unknown"),
        "connections": result.get("connections", []),
        "conns_active_at": result.get("conns_active_at"),
        "conns_inactive_at": result.get("conns_inactive_at"),
    }


def ensure_token(
    *, zone_name: str, cf_token_mode: str, save_config: bool
) -> dict[str, Any]:
    payload = load_cf_tunnel_config()
    account_id = _require_text(str(payload.get("cf_account_id", "")), "cf_account_id")
    zone_matches = [
        item for item in list_domains(payload) if item.zone_name == zone_name
    ]
    zone_id = zone_matches[0].zone_id if zone_matches else ""
    credential = ensure_cf_api_token(
        payload,
        account_id=account_id,
        zone_name=zone_name,
        zone_id=zone_id or None,
        token_mode=cf_token_mode,
        save_config=save_config,
    )
    return {
        "zone_name": zone_name,
        "source": credential.source,
        "created": credential.created,
    }


def config_schema_json() -> dict[str, Any]:
    return CF_TUNNEL_CONFIG.schema


def config_check() -> list[str]:
    payload = load_cf_tunnel_config()
    return validate_payload_against_schema(
        payload, CF_TUNNEL_CONFIG.schema, CF_TUNNEL_CONFIG.name
    )


def config_init(*, force: bool) -> str:
    path = find_project_root()
    config_path = Path(path / "configs" / CF_TUNNEL_CONFIG.file_name)
    if config_path.exists() and not force:
        raise FileExistsError(
            f"{config_path} already exists; rerun with --force to overwrite"
        )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(render_template_json(CF_TUNNEL_CONFIG), encoding="utf-8")
    return str(config_path)


def docs_sync() -> dict[str, str]:
    USAGE_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIGS_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    USAGE_DOC_PATH.write_text(render_usage_markdown(), encoding="utf-8")
    CONFIGS_DOC_PATH.write_text(
        render_config_markdown([CF_TUNNEL_CONFIG]), encoding="utf-8"
    )
    return {"usage": str(USAGE_DOC_PATH), "configs": str(CONFIGS_DOC_PATH)}
