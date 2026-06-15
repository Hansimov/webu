from __future__ import annotations

from copy import deepcopy
from typing import Any

from webu.schema import render_template_json, validate_payload_against_schema

from .clients import AliDirectMailClient
from .schema import (
    ALI_EMAIL_CONFIG,
    load_ali_email_config,
    resolve_runtime_config,
    save_ali_email_config,
)


def config_schema_json() -> dict[str, Any]:
    return deepcopy(ALI_EMAIL_CONFIG.schema)


def config_check(payload: dict[str, Any] | None = None) -> list[str]:
    payload = payload if isinstance(payload, dict) else load_ali_email_config(validate=False)
    errors = validate_payload_against_schema(payload, ALI_EMAIL_CONFIG.schema, "ali_email")
    runtime = resolve_runtime_config(payload)
    if not runtime.sender_account_name:
        errors.append("ali_email.sender_account_name: missing required sender address")
    if not runtime.aliyun_access_id:
        errors.append("ali_email.aliyun_access_id: missing credential")
    if not runtime.aliyun_access_secret:
        errors.append("ali_email.aliyun_access_secret: missing credential")
    return errors


def config_init(*, force: bool = False) -> str:
    current = load_ali_email_config(validate=False)
    if current and not force:
        return "configs/ali_email.json already exists"
    save_ali_email_config(deepcopy(ALI_EMAIL_CONFIG.sample))
    return render_template_json(ALI_EMAIL_CONFIG)


def build_verification_email(
    *,
    code: str,
    purpose: str = "register",
    ttl_minutes: int = 10,
    product_name: str = "Account",
) -> dict[str, str]:
    normalized_code = str(code).strip()
    if not normalized_code:
        raise ValueError("code is required")
    purpose_label = "registration" if purpose == "register" else "password reset"
    subject = f"{product_name} {purpose_label} code"
    text = (
        f"Your {product_name} {purpose_label} verification code is {normalized_code}.\n"
        f"It expires in {int(ttl_minutes)} minutes.\n"
        "If you did not request this code, ignore this email."
    )
    html = (
        f"<p>Your {product_name} {purpose_label} verification code is "
        f"<strong>{normalized_code}</strong>.</p>"
        f"<p>It expires in {int(ttl_minutes)} minutes.</p>"
        "<p>If you did not request this code, ignore this email.</p>"
    )
    return {"subject": subject, "text_body": text, "html_body": html}


def send_verification_code(
    *,
    to_address: str,
    code: str,
    purpose: str = "register",
    ttl_minutes: int = 10,
    product_name: str = "Account",
    dry_run: bool = False,
) -> dict[str, Any]:
    runtime = resolve_runtime_config()
    message = build_verification_email(
        code=code,
        purpose=purpose,
        ttl_minutes=ttl_minutes,
        product_name=product_name,
    )
    payload = {
        "account_name": runtime.sender_account_name,
        "address_type": runtime.address_type,
        "reply_to_address": runtime.reply_to_address,
        "to_address": str(to_address).strip(),
        "subject": message["subject"],
        "text_body": message["text_body"],
        "html_body": message["html_body"],
        "from_alias": runtime.sender_alias,
        "tag_name": runtime.tag_name or None,
    }
    if dry_run:
        return {"dry_run": True, "payload": {**payload, "to_address": "***"}}

    client = AliDirectMailClient(
        access_key_id=runtime.aliyun_access_id,
        access_key_secret=runtime.aliyun_access_secret,
        endpoint=runtime.endpoint,
        region_id=runtime.region_id,
    )
    return client.single_send_mail(**payload)


def create_sender_address(
    *,
    account_name: str,
    sendtype: str = "trigger",
    reply_address: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    runtime = resolve_runtime_config()
    payload = {
        "account_name": str(account_name or runtime.sender_account_name).strip(),
        "sendtype": str(sendtype or "trigger").strip(),
        "reply_address": str(reply_address or "").strip() or None,
    }
    if dry_run:
        return {"dry_run": True, "payload": payload}

    client = AliDirectMailClient(
        access_key_id=runtime.aliyun_access_id,
        access_key_secret=runtime.aliyun_access_secret,
        endpoint=runtime.endpoint,
        region_id=runtime.region_id,
    )
    return client.create_mail_address(**payload)


def _client_from_runtime() -> AliDirectMailClient:
    runtime = resolve_runtime_config()
    return AliDirectMailClient(
        access_key_id=runtime.aliyun_access_id,
        access_key_secret=runtime.aliyun_access_secret,
        endpoint=runtime.endpoint,
        region_id=runtime.region_id,
    )


def create_sender_domain(
    *,
    domain_name: str,
    dkim_selector: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    payload = {
        "domain_name": str(domain_name).strip(),
        "dkim_selector": str(dkim_selector or "").strip() or None,
    }
    if dry_run:
        return {"dry_run": True, "payload": payload}
    return _client_from_runtime().create_domain(**payload)


def query_sender_domains(
    *,
    key_word: str = "",
    page_no: int = 1,
    page_size: int = 10,
    status: int | None = None,
) -> dict[str, Any]:
    return _client_from_runtime().query_domains(
        key_word=key_word,
        page_no=page_no,
        page_size=page_size,
        status=status,
    )


def query_sender_addresses(
    *,
    key_word: str = "",
    page_no: int = 1,
    page_size: int = 10,
    sendtype: str | None = None,
) -> dict[str, Any]:
    return _client_from_runtime().query_mail_addresses(
        key_word=key_word,
        page_no=page_no,
        page_size=page_size,
        sendtype=sendtype,
    )


def describe_sender_domain(*, domain_id: str | int) -> dict[str, Any]:
    return _client_from_runtime().desc_domain(domain_id=domain_id)


def check_sender_domain(*, domain_id: str | int) -> dict[str, Any]:
    return _client_from_runtime().check_domain(domain_id=domain_id)
