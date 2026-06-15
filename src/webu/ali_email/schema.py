from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from webu.ali_esa.schema import load_ali_esa_config
from webu.cf_tunnel.schema import load_cf_tunnel_config
from webu.schema import ConfigSpec, load_json_config, save_json_config


ALI_EMAIL_CONFIG = ConfigSpec(
    name="ali_email",
    file_name="ali_email.json",
    purpose=[
        "Manage Alibaba Cloud DirectMail settings for account verification emails.",
        "Keep sender address, region and credentials outside public source files.",
    ],
    notes=[
        "aliyun_access_id and aliyun_access_secret may be left empty to fall back to ali_esa.json or cf_tunnel.json.",
        "sender_account_name must be an approved DirectMail sender address.",
        "This file is a local runtime config and must not be committed.",
    ],
    sample={
        "region_id": "cn-hangzhou",
        "endpoint": "dm.aliyuncs.com",
        "sender_account_name": "noreply@example.com",
        "sender_alias": "Account",
        "reply_to_address": False,
        "address_type": 1,
        "tag_name": "account-verification",
        "aliyun_access_id": "",
        "aliyun_access_secret": "",
    },
    schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "region_id": {"type": "string"},
            "endpoint": {"type": "string"},
            "sender_account_name": {"type": "string"},
            "sender_alias": {"type": "string"},
            "reply_to_address": {"type": "boolean"},
            "address_type": {"type": "integer"},
            "tag_name": {"type": "string"},
            "aliyun_access_id": {"type": "string"},
            "aliyun_access_secret": {"type": "string"},
        },
    },
)


@dataclass(frozen=True)
class AliEmailRuntimeConfig:
    region_id: str
    endpoint: str
    sender_account_name: str
    sender_alias: str
    reply_to_address: bool
    address_type: int
    tag_name: str
    aliyun_access_id: str
    aliyun_access_secret: str


def load_ali_email_config(*, validate: bool = True) -> dict[str, Any]:
    payload = load_json_config(ALI_EMAIL_CONFIG, validate=validate)
    return payload if isinstance(payload, dict) else {}


def save_ali_email_config(payload: dict[str, Any]) -> Path:
    return save_json_config(ALI_EMAIL_CONFIG, payload)


def resolve_credentials(payload: dict[str, Any]) -> dict[str, str]:
    ali_esa_payload: dict[str, Any] = {}
    cf_tunnel_payload: dict[str, Any] = {}
    try:
        ali_esa_payload = load_ali_esa_config(validate=False)
    except Exception:
        ali_esa_payload = {}
    try:
        cf_tunnel_payload = load_cf_tunnel_config()
    except Exception:
        cf_tunnel_payload = {}

    return {
        "aliyun_access_id": str(
            payload.get("aliyun_access_id")
            or ali_esa_payload.get("aliyun_access_id")
            or cf_tunnel_payload.get("aliyun_access_id")
            or ""
        ).strip(),
        "aliyun_access_secret": str(
            payload.get("aliyun_access_secret")
            or ali_esa_payload.get("aliyun_access_secret")
            or cf_tunnel_payload.get("aliyun_access_secret")
            or ""
        ).strip(),
    }


def resolve_runtime_config(payload: dict[str, Any] | None = None) -> AliEmailRuntimeConfig:
    payload = payload if isinstance(payload, dict) else load_ali_email_config()
    credentials = resolve_credentials(payload)
    return AliEmailRuntimeConfig(
        region_id=str(payload.get("region_id") or "cn-hangzhou").strip()
        or "cn-hangzhou",
        endpoint=str(payload.get("endpoint") or "dm.aliyuncs.com").strip()
        or "dm.aliyuncs.com",
        sender_account_name=str(payload.get("sender_account_name") or "").strip(),
        sender_alias=str(payload.get("sender_alias") or "Account").strip(),
        reply_to_address=bool(payload.get("reply_to_address", False)),
        address_type=int(payload.get("address_type") or 1),
        tag_name=str(payload.get("tag_name") or "").strip(),
        aliyun_access_id=credentials["aliyun_access_id"],
        aliyun_access_secret=credentials["aliyun_access_secret"],
    )
