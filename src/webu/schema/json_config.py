from __future__ import annotations

import json
import os

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ConfigSpec:
    name: str
    file_name: str
    purpose: list[str]
    notes: list[str]
    sample: Any
    schema: dict[str, Any]


def find_project_root() -> Path:
    explicit_root = os.getenv("WEBU_PROJECT_ROOT")
    if explicit_root:
        return Path(explicit_root).expanduser().resolve()

    for candidate in [Path.cwd(), *Path.cwd().parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate

    return Path(__file__).resolve().parents[3]


def get_config_dir(config_dir: Path | None = None) -> Path:
    return Path(
        config_dir or os.getenv("WEBU_CONFIG_DIR") or find_project_root() / "configs"
    ).expanduser()


def get_config_path(
    spec_or_name: ConfigSpec | str, config_dir: Path | None = None
) -> Path:
    resolved_dir = get_config_dir(config_dir)
    if isinstance(spec_or_name, ConfigSpec):
        file_name = spec_or_name.file_name
    else:
        file_name = f"{spec_or_name}.json"
    return resolved_dir / file_name


def _load_json_file(path: Path) -> Any:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)


def _validate_schema(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")

    if expected_type == "object":
        if not isinstance(value, dict):
            return [f"{path}: expected object"]
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key}: missing required field")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties")
        for item_key, item_value in value.items():
            next_path = f"{path}.{item_key}"
            if item_key in properties:
                errors.extend(
                    _validate_schema(item_value, properties[item_key], next_path)
                )
            elif additional is False:
                errors.append(f"{next_path}: unexpected field")
            elif isinstance(additional, dict):
                errors.extend(_validate_schema(item_value, additional, next_path))
        return errors

    if expected_type == "array":
        if not isinstance(value, list):
            return [f"{path}: expected array"]
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                errors.extend(_validate_schema(item, item_schema, f"{path}[{index}]"))
        return errors

    if expected_type == "string" and not isinstance(value, str):
        errors.append(f"{path}: expected string")
    elif expected_type == "integer" and not isinstance(value, int):
        errors.append(f"{path}: expected integer")
    elif expected_type == "boolean" and not isinstance(value, bool):
        errors.append(f"{path}: expected boolean")
    elif expected_type == "number" and not isinstance(value, (int, float)):
        errors.append(f"{path}: expected number")

    enum_values = schema.get("enum")
    if enum_values and value not in enum_values:
        errors.append(f"{path}: expected one of {', '.join(map(str, enum_values))}")

    min_length = schema.get("minLength")
    if (
        isinstance(value, str)
        and isinstance(min_length, int)
        and len(value) < min_length
    ):
        errors.append(f"{path}: expected minimum length {min_length}")

    return errors


def validate_payload_against_schema(
    payload: Any, schema: dict[str, Any], path: str = "root"
) -> list[str]:
    return _validate_schema(payload, schema, path)


def load_json_config(
    spec: ConfigSpec, *, config_dir: Path | None = None, validate: bool = True
) -> Any:
    config_path = get_config_path(spec, config_dir)
    payload = _load_json_file(config_path)
    if validate and config_path.exists():
        errors = validate_payload_against_schema(payload, spec.schema, spec.name)
        if errors:
            raise ValueError(
                f"Invalid config '{spec.name}' at {config_path}: {'; '.join(errors)}"
            )
    return payload


def save_json_config(
    spec: ConfigSpec,
    payload: Any,
    *,
    config_dir: Path | None = None,
    validate: bool = True,
) -> Path:
    config_path = get_config_path(spec, config_dir)
    if validate:
        errors = validate_payload_against_schema(payload, spec.schema, spec.name)
        if errors:
            raise ValueError(f"Invalid config '{spec.name}': {'; '.join(errors)}")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return config_path


def render_template_json(spec: ConfigSpec) -> str:
    return json.dumps(deepcopy(spec.sample), indent=2, ensure_ascii=False) + "\n"


def render_config_markdown(specs: list[ConfigSpec]) -> str:
    lines = ["# Configs", ""]
    for spec in specs:
        lines.append(f"## {spec.name}")
        lines.append("")
        lines.append(f"- File: `configs/{spec.file_name}`")
        for item in spec.purpose:
            lines.append(f"- Purpose: {item}")
        for item in spec.notes:
            lines.append(f"- Note: {item}")
        lines.append("")
        lines.append("Example:")
        lines.append("```json")
        lines.append(render_template_json(spec).rstrip())
        lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
