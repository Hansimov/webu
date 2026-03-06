from __future__ import annotations

import json
import os

from pathlib import Path
from typing import Any


SENSITIVE_TOKEN_KEYS = {
    "admin_token",
    "api_key",
    "api_token",
    "hf_token",
    "search_api_token",
}
SENSITIVE_SPACE_KEYS = {"space"}
SENSITIVE_URL_KEYS = {"base_url", "url"}


def _find_project_root() -> Path:
    explicit_root = os.getenv("WEBU_PROJECT_ROOT")
    if explicit_root:
        return Path(explicit_root).expanduser().resolve()

    for candidate in [Path.cwd(), *Path.cwd().parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate

    return Path(__file__).resolve().parents[3]


def _default_config_dir() -> Path:
    return Path(os.getenv("WEBU_CONFIG_DIR", _find_project_root() / "configs")).expanduser()


def _add_space_value(values: set[str], raw_value: Any):
    space_name = str(raw_value or "").strip()
    if not space_name:
        return
    values.add(space_name)
    if "/" in space_name:
        owner, _, _name = space_name.partition("/")
        if owner:
            values.add(owner)
        values.add(f"https://{space_name.replace('/', '-')}.hf.space")


def _add_url_value(values: set[str], raw_value: Any):
    url = str(raw_value or "").strip().rstrip("/")
    if not url:
        return
    if ".hf.space" in url:
        values.add(url)
        hostname = url.split("://", 1)[-1].split("/", 1)[0]
        if hostname:
            values.add(hostname)


def _collect_from_payload(payload: Any, values: set[str], parent_key: str = ""):
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).strip().lower()
            if lowered in SENSITIVE_TOKEN_KEYS:
                token = str(value or "").strip()
                if token:
                    values.add(token)
            if lowered in SENSITIVE_SPACE_KEYS:
                _add_space_value(values, value)
            if lowered in SENSITIVE_URL_KEYS:
                _add_url_value(values, value)
            _collect_from_payload(value, values, lowered)
        return

    if isinstance(payload, list):
        for item in payload:
            _collect_from_payload(item, values, parent_key)


def collect_sensitive_local_values(config_dir: Path | None = None) -> list[str]:
    values: set[str] = set()
    resolved_config_dir = (config_dir or _default_config_dir()).expanduser()
    for config_path in sorted(resolved_config_dir.glob("*.json")):
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        _collect_from_payload(payload, values)

    return sorted(value for value in values if value)


def find_sensitive_text_leaks(text: str, sensitive_values: list[str] | None = None) -> list[str]:
    values = sensitive_values or collect_sensitive_local_values()
    return [value for value in values if value and value in text]


def assert_public_text_safe(text: str, sensitive_values: list[str] | None = None) -> str:
    leaks = find_sensitive_text_leaks(text, sensitive_values=sensitive_values)
    if leaks:
        raise ValueError(f"public docs/help leaked sensitive local config values: {', '.join(leaks[:5])}")
    return text