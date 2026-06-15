from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from webu.cf_tunnel.schema import (
    infer_zone_name,
    list_domains,
    load_cf_tunnel_config,
)
from webu.schema import ConfigSpec, load_json_config, save_json_config


CF_EMAIL_CONFIG = ConfigSpec(
    name="cf_email",
    file_name="cf_email.json",
    purpose=[
        "Manage Cloudflare Email Routing for development mailboxes.",
        "Route inbound verification email to a Worker that can post parsed content to an internal webhook.",
    ],
    notes=[
        "cf_api_token and cf_account_id may be left empty to fall back to cf_tunnel.json.",
        "zone_id may be resolved from cf_tunnel.json domains when zone_name matches.",
        "webhook_secret must stay in local config or environment variables.",
    ],
    sample={
        "cf_account_id": "",
        "cf_api_token": "",
        "zone_name": "example.com",
        "zone_id": "",
        "worker_name": "account-email-inbox",
        "route_local_part": "account-dev",
        "webhook_url": "http://127.0.0.1:14567/api/dev/email/inbound",
        "webhook_secret": "",
        "code_regex": "\\b([0-9]{6})\\b",
    },
    schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "cf_account_id": {"type": "string"},
            "cf_api_token": {"type": "string"},
            "zone_name": {"type": "string"},
            "zone_id": {"type": "string"},
            "worker_name": {"type": "string"},
            "route_local_part": {"type": "string"},
            "webhook_url": {"type": "string"},
            "webhook_secret": {"type": "string"},
            "code_regex": {"type": "string"},
        },
    },
)


@dataclass(frozen=True)
class CfEmailRuntimeConfig:
    cf_account_id: str
    cf_api_token: str
    zone_name: str
    zone_id: str
    worker_name: str
    route_local_part: str
    webhook_url: str
    webhook_secret: str
    code_regex: str

    @property
    def route_address(self) -> str:
        return f"{self.route_local_part}@{self.zone_name}"


def load_cf_email_config(*, validate: bool = True) -> dict[str, Any]:
    payload = load_json_config(CF_EMAIL_CONFIG, validate=validate)
    return payload if isinstance(payload, dict) else {}


def save_cf_email_config(payload: dict[str, Any]) -> Path:
    return save_json_config(CF_EMAIL_CONFIG, payload)


def _fallback_cf_tunnel_payload() -> dict[str, Any]:
    try:
        return load_cf_tunnel_config()
    except Exception:
        return {}


def _resolve_zone_id(payload: dict[str, Any], zone_name: str) -> str:
    configured = str(payload.get("zone_id") or "").strip()
    if configured:
        return configured
    cf_payload = _fallback_cf_tunnel_payload()
    normalized = zone_name.lower()
    for domain in list_domains(cf_payload):
        if domain.zone_name.lower() == normalized and domain.zone_id:
            return domain.zone_id
    return ""


def resolve_runtime_config(payload: dict[str, Any] | None = None) -> CfEmailRuntimeConfig:
    payload = payload if isinstance(payload, dict) else load_cf_email_config()
    cf_payload = _fallback_cf_tunnel_payload()
    zone_name = str(payload.get("zone_name") or "").strip()
    if not zone_name:
        domains = list_domains(cf_payload)
        zone_name = domains[0].zone_name if domains else "example.com"
    zone_name = infer_zone_name(zone_name)
    return CfEmailRuntimeConfig(
        cf_account_id=str(
            payload.get("cf_account_id") or cf_payload.get("cf_account_id") or ""
        ).strip(),
        cf_api_token=str(
            payload.get("cf_api_token") or cf_payload.get("cf_api_token") or ""
        ).strip(),
        zone_name=zone_name,
        zone_id=_resolve_zone_id(payload, zone_name),
        worker_name=str(payload.get("worker_name") or "account-email-inbox").strip(),
        route_local_part=str(payload.get("route_local_part") or "account-dev").strip(),
        webhook_url=str(payload.get("webhook_url") or "").strip(),
        webhook_secret=str(payload.get("webhook_secret") or "").strip(),
        code_regex=str(payload.get("code_regex") or r"\b([0-9]{6})\b"),
    )
