from __future__ import annotations

import html
import json
import re

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage
from typing import Any

from webu.cf_tunnel.clients import CloudflareApiError
from webu.cf_tunnel.schema import load_cf_tunnel_config
from webu.schema import render_template_json, validate_payload_against_schema

from .clients import CloudflareEmailClient
from .schema import (
    CF_EMAIL_CONFIG,
    CfEmailRuntimeConfig,
    load_cf_email_config,
    resolve_runtime_config,
    save_cf_email_config,
)


def config_schema_json() -> dict[str, Any]:
    return deepcopy(CF_EMAIL_CONFIG.schema)


def config_check(payload: dict[str, Any] | None = None) -> list[str]:
    payload = payload if isinstance(payload, dict) else load_cf_email_config(validate=False)
    errors = validate_payload_against_schema(payload, CF_EMAIL_CONFIG.schema, "cf_email")
    runtime = resolve_runtime_config(payload)
    if not runtime.cf_account_id:
        errors.append("cf_email.cf_account_id: missing credential")
    if not runtime.cf_api_token:
        errors.append("cf_email.cf_api_token: missing credential")
    if not runtime.zone_id:
        errors.append("cf_email.zone_id: missing zone id")
    if not runtime.worker_name:
        errors.append("cf_email.worker_name: missing worker name")
    if not runtime.webhook_url:
        errors.append("cf_email.webhook_url: missing webhook URL")
    return errors


def config_init(*, force: bool = False) -> str:
    current = load_cf_email_config(validate=False)
    if current and not force:
        return "configs/cf_email.json already exists"
    save_cf_email_config(deepcopy(CF_EMAIL_CONFIG.sample))
    return render_template_json(CF_EMAIL_CONFIG)


def _message_body(message: EmailMessage) -> str:
    parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type not in {"text/plain", "text/html"}:
                continue
            try:
                text = part.get_content()
            except Exception:
                payload = part.get_payload(decode=True) or b""
                text = payload.decode(part.get_content_charset() or "utf-8", "replace")
            parts.append(str(text))
    else:
        try:
            parts.append(str(message.get_content()))
        except Exception:
            payload = message.get_payload(decode=True) or b""
            parts.append(payload.decode(message.get_content_charset() or "utf-8", "replace"))
    raw = "\n".join(parts)
    without_tags = re.sub(r"<[^>]+>", " ", raw)
    return html.unescape(re.sub(r"\s+", " ", without_tags)).strip()


def parse_email_message(raw_message: bytes | str) -> dict[str, Any]:
    raw_bytes = raw_message.encode("utf-8") if isinstance(raw_message, str) else raw_message
    message = message_from_bytes(raw_bytes, policy=policy.default)
    return {
        "from": str(message.get("from", "")).strip(),
        "to": str(message.get("to", "")).strip(),
        "subject": str(message.get("subject", "")).strip(),
        "date": str(message.get("date", "")).strip(),
        "message_id": str(message.get("message-id", "")).strip(),
        "body": _message_body(message),
    }


def extract_verification_codes(
    raw_message: bytes | str,
    *,
    code_regex: str | None = None,
) -> list[str]:
    parsed = parse_email_message(raw_message)
    pattern = re.compile(code_regex or resolve_runtime_config().code_regex)
    matches: list[str] = []
    for source in [parsed.get("subject", ""), parsed.get("body", "")]:
        for match in pattern.finditer(str(source)):
            value = match.group(1) if match.groups() else match.group(0)
            if value not in matches:
                matches.append(value)
    return matches


def routing_plan(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime = resolve_runtime_config(payload)
    return {
        "zone_name": runtime.zone_name,
        "zone_id": runtime.zone_id,
        "account_id": "***" if runtime.cf_account_id else "",
        "route_address": runtime.route_address,
        "worker_name": runtime.worker_name,
        "required_api_endpoints": [
            "GET /zones/{zone_id}/email/routing",
            "POST /zones/{zone_id}/email/routing/dns",
            "GET /zones/{zone_id}/email/routing/rules",
            "POST /zones/{zone_id}/email/routing/rules",
        ],
    }


def _permission_group(
    groups: list[dict[str, Any]],
    name: str,
    *,
    scope: str,
) -> dict[str, str]:
    for group in groups:
        group_name = str(group.get("name", "")).strip()
        scopes = [str(item).strip() for item in group.get("scopes", [])]
        if group_name == name and scope in scopes:
            return {"id": str(group.get("id", "")).strip(), "name": group_name}
    raise CloudflareApiError(f"Cloudflare permission group not found: {name}")


def build_email_routing_token_payload(
    *,
    groups: list[dict[str, Any]],
    name: str,
    account_id: str,
    zone_id: str,
    expires_in_days: int | None = 30,
) -> dict[str, Any]:
    account_scope = "com.cloudflare.api.account"
    zone_scope = "com.cloudflare.api.account.zone"
    payload: dict[str, Any] = {
        "name": str(name).strip(),
        "policies": [
            {
                "effect": "allow",
                "resources": {f"com.cloudflare.api.account.{account_id}": "*"},
                "permission_groups": [
                    _permission_group(
                        groups, "Email Routing Addresses Read", scope=account_scope
                    ),
                    _permission_group(
                        groups, "Email Routing Addresses Write", scope=account_scope
                    ),
                    _permission_group(groups, "Workers Scripts Read", scope=account_scope),
                    _permission_group(groups, "Workers Scripts Write", scope=account_scope),
                ],
            },
            {
                "effect": "allow",
                "resources": {f"com.cloudflare.api.account.zone.{zone_id}": "*"},
                "permission_groups": [
                    _permission_group(groups, "Zone Read", scope=zone_scope),
                    _permission_group(groups, "DNS Read", scope=zone_scope),
                    _permission_group(groups, "DNS Write", scope=zone_scope),
                    _permission_group(
                        groups, "Email Routing Rules Read", scope=zone_scope
                    ),
                    _permission_group(
                        groups, "Email Routing Rules Write", scope=zone_scope
                    ),
                ],
            },
        ],
    }
    if expires_in_days:
        payload["expires_on"] = (
            datetime.now(timezone.utc) + timedelta(days=max(1, int(expires_in_days)))
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    return payload


def _discover_zone_id(runtime: CfEmailRuntimeConfig) -> str:
    if runtime.zone_id:
        return runtime.zone_id
    for token in [runtime.cf_api_token, str(load_cf_tunnel_config().get("cf_api_token") or "")]:
        token = str(token or "").strip()
        if not token:
            continue
        try:
            zones = CloudflareEmailClient(token).list_zones(
                name=runtime.zone_name,
                account_id=runtime.cf_account_id,
            )
        except CloudflareApiError:
            continue
        if zones:
            return str(zones[0].get("id", "")).strip()
    return ""


def create_email_routing_token(
    *,
    name: str = "",
    expires_in_days: int | None = 30,
    save_config: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    payload = load_cf_email_config(validate=False)
    runtime = resolve_runtime_config(payload)
    account_id = runtime.cf_account_id
    if not account_id:
        raise ValueError("cf_account_id is required")
    zone_id = _discover_zone_id(runtime)
    if not zone_id:
        raise ValueError(f"Could not resolve Cloudflare zone_id for {runtime.zone_name}")

    tunnel_payload = load_cf_tunnel_config()
    bootstrap_token = str(tunnel_payload.get("cf_account_api_tokens_edit_token") or "").strip()
    if not bootstrap_token:
        raise ValueError("cf_account_api_tokens_edit_token is required")

    token_name = str(name or f"cfem-{runtime.zone_name}-email-routing").strip()
    bootstrap_client = CloudflareEmailClient(bootstrap_token)
    groups = bootstrap_client.list_permission_groups(account_id=account_id)
    create_payload = build_email_routing_token_payload(
        groups=groups,
        name=token_name,
        account_id=account_id,
        zone_id=zone_id,
        expires_in_days=expires_in_days,
    )
    if dry_run:
        return {
            "dry_run": True,
            "name": token_name,
            "zone_name": runtime.zone_name,
            "zone_id_resolved": True,
            "policy_count": len(create_payload["policies"]),
        }

    result = bootstrap_client._request(
        "POST",
        f"/accounts/{account_id}/tokens",
        json_body=create_payload,
    )
    token_value = str(result.get("value") or result.get("token") or "").strip()
    if not token_value:
        raise CloudflareApiError("Cloudflare did not return the new token secret")

    verification_client = CloudflareEmailClient(token_value)
    verification_client.list_routing_rules(zone_id=zone_id)

    if save_config:
        payload["cf_account_id"] = account_id
        payload["cf_api_token"] = token_value
        payload["zone_name"] = runtime.zone_name
        payload["zone_id"] = zone_id
        payload["worker_name"] = runtime.worker_name
        payload["route_local_part"] = runtime.route_local_part
        payload["webhook_url"] = runtime.webhook_url
        payload["webhook_secret"] = runtime.webhook_secret
        payload["code_regex"] = runtime.code_regex
        save_cf_email_config(payload)

    return {
        "created": True,
        "id": str(result.get("id", "")).strip(),
        "name": str(result.get("name") or token_name).strip(),
        "zone_name": runtime.zone_name,
        "zone_id_resolved": True,
        "token_saved": bool(save_config),
    }


def _existing_rule_for_address(
    rules: list[dict[str, Any]], route_address: str
) -> dict[str, Any] | None:
    normalized = route_address.lower()
    for rule in rules:
        for matcher in rule.get("matchers", []) or []:
            if str(matcher.get("value") or "").strip().lower() == normalized:
                return rule
    return None


def ensure_worker_rule(
    *,
    dry_run: bool = False,
    runtime: CfEmailRuntimeConfig | None = None,
) -> dict[str, Any]:
    runtime = runtime or resolve_runtime_config()
    desired = {
        "address": runtime.route_address,
        "action_type": "worker",
        "action_values": [runtime.worker_name],
        "name": f"Route {runtime.route_address} to {runtime.worker_name}",
        "enabled": True,
    }
    if dry_run:
        return {"dry_run": True, "desired": desired}
    client = CloudflareEmailClient(runtime.cf_api_token)
    rules = client.list_routing_rules(zone_id=runtime.zone_id)
    existing = _existing_rule_for_address(rules, runtime.route_address)
    if existing:
        return {"changed": False, "rule": existing}
    rule = client.create_routing_rule(zone_id=runtime.zone_id, **desired)
    return {"changed": True, "rule": rule}


def deploy_worker(
    *,
    dry_run: bool = False,
    runtime: CfEmailRuntimeConfig | None = None,
) -> dict[str, Any]:
    runtime = runtime or resolve_runtime_config()
    script = build_worker_script(runtime)
    if dry_run:
        return {
            "dry_run": True,
            "account_id": "***" if runtime.cf_account_id else "",
            "worker_name": runtime.worker_name,
            "webhook_url": runtime.webhook_url,
            "has_webhook_secret": bool(runtime.webhook_secret),
        }
    client = CloudflareEmailClient(runtime.cf_api_token)
    upload = client.upload_worker_script(
        account_id=runtime.cf_account_id,
        script_name=runtime.worker_name,
        script=script,
    )
    secret = {}
    if runtime.webhook_secret:
        secret = client.put_worker_secret(
            account_id=runtime.cf_account_id,
            script_name=runtime.worker_name,
            name="WEBHOOK_SECRET",
            text=runtime.webhook_secret,
        )
    return {
        "deployed": True,
        "worker_name": runtime.worker_name,
        "script_id": str(upload.get("id") or upload.get("etag") or "").strip(),
        "secret_set": bool(secret) if runtime.webhook_secret else False,
    }


def build_worker_script(runtime: CfEmailRuntimeConfig | None = None) -> str:
    runtime = runtime or resolve_runtime_config()
    payload = {
        "webhookUrl": runtime.webhook_url,
        "secretName": "WEBHOOK_SECRET",
    }
    return f"""export default {{
  async email(message, env, ctx) {{
    const raw = await new Response(message.raw).text();
    const body = {{
      from: message.from,
      to: message.to,
      raw,
      rawSize: message.rawSize,
      subject: message.headers.get("subject") || ""
    }};
    ctx.waitUntil(fetch({json.dumps(payload["webhookUrl"])}, {{
      method: "POST",
      headers: {{
        "content-type": "application/json",
        "x-webhook-secret": env.{payload["secretName"]}
      }},
      body: JSON.stringify(body)
    }}));
  }}
}};
"""
