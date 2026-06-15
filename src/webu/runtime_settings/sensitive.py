from __future__ import annotations

import json
import os

from pathlib import Path
from typing import Any


SENSITIVE_TOKEN_KEYS = {
    "access_key_secret",
    "access_secret",
    "admin_token",
    "api_key",
    "api_token",
    "auth_token",
    "authorization",
    "bearer_token",
    "cf_account_api_tokens_edit_token",
    "cf_api_token",
    "client_secret",
    "cookie",
    "cookie_value",
    "hf_token",
    "search_api_token",
    "tunnel_token",
    "aliyun_access_secret",
    "password",
    "webhook_secret",
}
SENSITIVE_SPACE_KEYS = {"space", "account"}
SENSITIVE_URL_KEYS = {"base_url", "url"}
SENSITIVE_DOMAIN_KEYS = {"domain_name", "zone_name", "site_name", "tunnel_name"}
SENSITIVE_IDENTIFIER_KEYS = {
    "aliyun_access_id",
    "cf_account_id",
    "cloudflare_zone_id",
    "default_public_origin_ipv4",
    "default_public_origin_ipv6",
    "instance_id",
    "origin_name",
    "pool_name",
    "registrar_task_no",
    "record_name",
    "site_id",
    "tunnel_id",
    "verify_code",
    "zone_id",
    "sender_account_name",
    "webhook_url",
}
SENSITIVE_STRING_LIST_KEYS = {
    "cloudflare_nameservers",
    "current_ns",
    "name_server_list",
}
SENSITIVE_PUBLIC_ADDRESS_KEYS = {"public_origin_address", "target_ipv6"}
GENERIC_SECRET_KEY_TOKENS = ("token", "secret", "password", "credential")
SENSITIVE_FILE_EXTRACTION_KEYS = {
    "ssh.json": {"name", "host_name", "hostname", "ip"},
    "ddns.json": {"name", "record_name", "pool_name", "origin_name"},
    "frp.json": {"name", "server_addr", "server_name", "ssh_host_name"},
}


def _find_project_root() -> Path:
    explicit_root = os.getenv("WEBU_PROJECT_ROOT")
    if explicit_root:
        return Path(explicit_root).expanduser().resolve()

    for candidate in [Path.cwd(), *Path.cwd().parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate

    return Path(__file__).resolve().parents[3]


def _default_config_dir() -> Path:
    return Path(
        os.getenv("WEBU_CONFIG_DIR", _find_project_root() / "configs")
    ).expanduser()


def _is_placeholder_value(raw_value: Any) -> bool:
    value = str(raw_value or "").strip()
    lowered = value.lower()
    if not value:
        return True
    if lowered in {"0", "example.com", "dev.example.com", "aliyun", "cloudflare"}:
        return True
    if lowered.startswith(("your-", "your_", "dummy-", "fake-", "mock-")):
        return True
    if "example" in lowered or "placeholder" in lowered or "replace-me" in lowered:
        return True
    if value.startswith("http://127.0.0.1") or value.startswith("https://127.0.0.1"):
        return True
    return False


def _add_string_value(values: set[str], raw_value: Any):
    value = str(raw_value or "").strip()
    if _is_placeholder_value(value):
        return
    values.add(value)


def _add_space_value(values: set[str], raw_value: Any):
    space_name = str(raw_value or "").strip()
    if _is_placeholder_value(space_name):
        return
    values.add(space_name)
    if "/" in space_name:
        owner, _, _name = space_name.partition("/")
        if owner:
            values.add(owner)
        values.add(f"https://{space_name.replace('/', '-')}.hf.space")


def _add_url_value(values: set[str], raw_value: Any):
    url = str(raw_value or "").strip().rstrip("/")
    if _is_placeholder_value(url):
        return
    if ".hf.space" in url:
        values.add(url)
        hostname = url.split("://", 1)[-1].split("/", 1)[0]
        if hostname:
            values.add(hostname)


def _add_string_list_values(values: set[str], raw_value: Any):
    if not isinstance(raw_value, list):
        return
    for item in raw_value:
        _add_string_value(values, item)


def _collect_from_payload(
    payload: Any,
    values: set[str],
    parent_key: str = "",
    *,
    extra_keys: set[str] | frozenset[str] = frozenset(),
):
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).strip().lower()
            if lowered in SENSITIVE_TOKEN_KEYS or any(
                token in lowered for token in GENERIC_SECRET_KEY_TOKENS
            ):
                _add_string_value(values, value)
            if lowered in SENSITIVE_SPACE_KEYS:
                _add_space_value(values, value)
            if lowered in SENSITIVE_URL_KEYS:
                _add_url_value(values, value)
            if lowered in SENSITIVE_DOMAIN_KEYS or lowered in SENSITIVE_IDENTIFIER_KEYS:
                _add_string_value(values, value)
            if lowered in SENSITIVE_PUBLIC_ADDRESS_KEYS:
                _add_string_value(values, value)
            if lowered in SENSITIVE_STRING_LIST_KEYS:
                _add_string_list_values(values, value)
            if lowered in extra_keys:
                _add_string_value(values, value)
            _collect_from_payload(value, values, lowered, extra_keys=extra_keys)
        return

    if isinstance(payload, list):
        for item in payload:
            _collect_from_payload(item, values, parent_key, extra_keys=extra_keys)


def collect_sensitive_local_values(config_dir: Path | None = None) -> list[str]:
    values: set[str] = set()
    resolved_config_dir = (config_dir or _default_config_dir()).expanduser()
    for config_path in sorted(resolved_config_dir.glob("*.json")):
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        _collect_from_payload(
            payload,
            values,
            extra_keys=SENSITIVE_FILE_EXTRACTION_KEYS.get(
                config_path.name.lower(), frozenset()
            ),
        )

    return sorted(value for value in values if value)


def find_sensitive_text_leaks(
    text: str, sensitive_values: list[str] | None = None
) -> list[str]:
    values = sensitive_values or collect_sensitive_local_values()
    return [value for value in values if value and value in text]


def assert_public_text_safe(
    text: str, sensitive_values: list[str] | None = None
) -> str:
    leaks = find_sensitive_text_leaks(text, sensitive_values=sensitive_values)
    if leaks:
        raise ValueError(
            f"public docs/help leaked sensitive local config values: {', '.join(leaks[:5])}"
        )
    return text
