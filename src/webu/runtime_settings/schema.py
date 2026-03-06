from __future__ import annotations

import json
import os

from copy import deepcopy
from pathlib import Path
from typing import Any

from .defaults import DEFAULT_GOOGLE_API_PORT, DEFAULT_GOOGLE_HUB_PORT
from .sensitive import assert_public_text_safe


CONFIGS_DOC_PATH = Path(__file__).resolve().parents[3] / "docs" / "google-docker" / "CONFIGS.md"


def _find_project_root() -> Path:
    explicit_root = os.getenv("WEBU_PROJECT_ROOT")
    if explicit_root:
        return Path(explicit_root).expanduser().resolve()

    for candidate in [Path.cwd(), *Path.cwd().parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate

    return Path(__file__).resolve().parents[3]


CONFIG_SCHEMAS: dict[str, dict[str, Any]] = {
    "google_api": {
        "file": "configs/google_api.json",
        "purpose": [
            "约定 google_api 服务的监听参数。",
            "维护不同环境的服务地址和 /search 访问 token。",
        ],
        "notes": [
            "type 只允许 local、remote-server、hf-space。",
            "api_token 为空表示该环境不强制校验 /search。",
            "hf-space 项可以不写 url，此时会从 configs/hf_spaces.json 或 WEBU_HF_SPACE_NAME 自动推导域名。",
            "只有当你真的在用独立远程服务器时，才需要额外添加 remote-server 项。",
        ],
        "sample": {
            "host": "0.0.0.0",
            "port": DEFAULT_GOOGLE_API_PORT,
            "proxy_mode": "auto",
            "services": [
                {"url": f"http://127.0.0.1:{DEFAULT_GOOGLE_API_PORT}", "type": "local", "api_token": ""},
                {"type": "hf-space", "api_token": "your-hf-search-token"},
            ],
        },
        "schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer"},
                "proxy_mode": {"type": "string", "enum": ["auto", "enabled", "disabled"]},
                "services": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "type": {"type": "string", "enum": ["local", "remote-server", "hf-space"]},
                            "api_token": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
    "google_docker": {
        "file": "configs/google_docker.json",
        "purpose": [
            "管理 google_docker 的管理接口 token。",
            "作为 /admin/* 的长期鉴权源。",
            "ggdk hf-runtime、ggdk hf-logs、ggdk hf-check、ggdk hf-doctor 默认会从这里读 token。",
        ],
        "notes": [],
        "sample": {"admin_token": "your-admin-token"},
        "schema": {
            "type": "object",
            "properties": {
                "admin_token": {"type": "string"},
            },
        },
    },
    "google_hub": {
        "file": "configs/google_hub.json",
        "purpose": [
            "定义本地中心化调度服务的监听参数和调度策略。",
            "集中管理多个 Google API / HF Space 后端。",
            "供 google_hub 服务执行健康检查、路由和负载均衡。",
        ],
        "notes": [
            "kind 只允许 local-google-api、google-api、hf-space。",
            "hf-space 后端可以只写 space，不写 base_url。",
            "search_api_token 和 admin_token 为空时，会回退到现有 google_api/google_docker 配置中的默认 token。",
        ],
        "sample": {
            "host": "0.0.0.0",
            "port": DEFAULT_GOOGLE_HUB_PORT,
            "strategy": "least-inflight",
            "health_interval_sec": 30,
            "health_timeout_sec": 10,
            "request_timeout_sec": 90,
            "backends": [
                {
                    "name": "local-google-api",
                    "kind": "local-google-api",
                    "base_url": f"http://127.0.0.1:{DEFAULT_GOOGLE_API_PORT}",
                    "enabled": True,
                    "weight": 2,
                    "tags": ["local", "primary"],
                },
                {
                    "name": "space1",
                    "kind": "hf-space",
                    "space": "owner/space1",
                    "enabled": True,
                    "weight": 1,
                    "tags": ["hf", "primary"],
                },
                {
                    "name": "space2",
                    "kind": "hf-space",
                    "space": "owner/space2",
                    "enabled": True,
                    "weight": 1,
                    "tags": ["hf", "secondary"],
                },
            ],
        },
        "schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer"},
                "admin_token": {"type": "string"},
                "strategy": {"type": "string", "enum": ["least-inflight"]},
                "health_interval_sec": {"type": "integer"},
                "health_timeout_sec": {"type": "integer"},
                "request_timeout_sec": {"type": "integer"},
                "backends": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "kind": {"type": "string", "enum": ["local-google-api", "google-api", "hf-space"]},
                            "base_url": {"type": "string"},
                            "space": {"type": "string"},
                            "enabled": {"type": "boolean"},
                            "weight": {"type": "integer"},
                            "search_api_token": {"type": "string"},
                            "admin_token": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
        },
    },
    "proxies": {
        "file": "configs/proxies.json",
        "purpose": [
            "收敛所有本地代理地址。",
            "供 google_api、gemini、proxy_api、searches 共用。",
        ],
        "notes": [
            "该文件只在本地使用，不用于远端环境。",
        ],
        "sample": {
            "google_api": {
                "proxies": [
                    {"url": "http://127.0.0.1:11111", "name": "proxy-11111"},
                    {"url": "http://127.0.0.1:11119", "name": "proxy-11119"},
                ]
            },
            "gemini": {"default_proxy": "http://127.0.0.1:11119"},
            "proxy_api": {"fetch_proxy": "http://127.0.0.1:11119"},
            "searches": {"chrome_proxy": "http://127.0.0.1:11111"},
        },
        "schema": {
            "type": "object",
            "properties": {
                "google_api": {
                    "type": "object",
                    "properties": {
                        "proxies": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["url", "name"],
                                "properties": {
                                    "url": {"type": "string"},
                                    "name": {"type": "string"},
                                },
                            },
                        }
                    },
                },
                "gemini": {"type": "object"},
                "proxy_api": {"type": "object"},
                "searches": {"type": "object"},
            },
        },
    },
    "captcha": {
        "file": "configs/captcha.json",
        "purpose": [
            "指定验证码识别用的 VLM 配置。",
            "可以直接写 endpoint，也可以通过 profile 关联 llms.json。",
        ],
        "notes": [],
        "sample": {"vlm": {"profile": "sf_qwen3_vl_8b"}},
        "schema": {
            "type": "object",
            "properties": {
                "vlm": {
                    "type": "object",
                    "properties": {
                        "profile": {"type": "string"},
                        "endpoint": {"type": "string"},
                        "api_key": {"type": "string"},
                        "model": {"type": "string"},
                        "api_format": {"type": "string"},
                    },
                }
            },
        },
    },
    "llms": {
        "file": "configs/llms.json",
        "purpose": [
            "管理可复用的 LLM/VLM profile。",
            "提供 captcha 等模块统一复用。",
        ],
        "notes": [],
        "sample": {
            "sf_qwen3_vl_8b": {
                "endpoint": "https://api.siliconflow.cn/v1/chat/completions",
                "api_key": "your-api-key",
                "model": "Qwen/Qwen3-VL-8B-Instruct",
                "api_format": "openai",
            }
        },
        "schema": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["endpoint"],
                "properties": {
                    "endpoint": {"type": "string"},
                    "api_key": {"type": "string"},
                    "model": {"type": "string"},
                    "api_format": {"type": "string"},
                },
            },
        },
    },
    "hf_spaces": {
        "file": "configs/hf_spaces.json",
        "purpose": [
            "维护 HF Space 名称和 HF token。",
            "仅用于 CLI 访问 Hugging Face Hub。",
            "第一项会被 ggdk hf-sync、ggdk hf-status、ggdk hf-files 等命令当作默认 Space。",
        ],
        "notes": [
            "这里不要放 /search 的业务 token。",
            "这里也不要放 admin_token。",
            "可以通过 enabled、weight、tags 参与本地 google_hub 的调度配置。",
        ],
        "sample": [
            {"space": "owner/space1", "hf_token": "your-hf-token", "enabled": True, "weight": 1, "tags": ["primary"]},
            {"space": "owner/space2", "hf_token": "your-hf-token", "enabled": True, "weight": 1, "tags": ["secondary"]},
        ],
        "schema": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["space", "hf_token"],
                "properties": {
                    "space": {"type": "string"},
                    "hf_token": {"type": "string"},
                    "enabled": {"type": "boolean"},
                    "weight": {"type": "integer"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


def available_config_names() -> list[str]:
    return sorted(CONFIG_SCHEMAS.keys())


def has_config_schema(name: str) -> bool:
    return name in CONFIG_SCHEMAS


def config_schema_json(name: str) -> dict[str, Any]:
    return CONFIG_SCHEMAS[name]["schema"]


def default_config_payload(name: str) -> Any:
    return deepcopy(CONFIG_SCHEMAS[name]["sample"])


def render_config_template_json(name: str) -> str:
    return json.dumps(default_config_payload(name), indent=2, ensure_ascii=False) + "\n"


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return type(value).__name__


def _validate_schema(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type and _type_name(value) != expected_type:
        return [f"{path}: expected {expected_type}, got {_type_name(value)}"]

    if expected_type == "object":
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required key '{key}'")

        properties = schema.get("properties", {})
        for key, item_value in value.items():
            next_path = f"{path}.{key}" if path else key
            if key in properties:
                errors.extend(_validate_schema(item_value, properties[key], next_path))
                continue
            additional = schema.get("additionalProperties")
            if isinstance(additional, dict):
                errors.extend(_validate_schema(item_value, additional, next_path))

    if expected_type == "array":
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                errors.extend(_validate_schema(item, item_schema, f"{path}[{index}]"))

    enum_values = schema.get("enum")
    if enum_values and value not in enum_values:
        errors.append(f"{path}: expected one of {enum_values}, got {value!r}")

    return errors


def validate_config_payload(name: str, payload: Any) -> list[str]:
    return _validate_schema(payload, config_schema_json(name), name)
def render_configs_markdown() -> str:
    lines = [
        "# 配置模板",
        "",
        "> 本文档由 `ggdk docs-sync` 从共享 schema 定义自动生成。",
        "",
        "## 最常用的最小配置集合",
        "",
        "多数情况下，只需要维护以下三个文件：",
        "",
        "1. `configs/hf_spaces.json`",
        "2. `configs/google_api.json`",
        "3. `configs/google_docker.json`",
        "",
        "只有在需要验证码远程识别或本地代理时，再补 `captcha.json`、`llms.json`、`proxies.json`。",
        "",
    ]

    for index, name in enumerate(available_config_names(), start=1):
        entry = CONFIG_SCHEMAS[name]
        lines.append(f"## {index}. `{entry['file']}`")
        lines.append("")
        lines.append("用途：")
        lines.append("")
        for item_index, item in enumerate(entry["purpose"], start=1):
            lines.append(f"{item_index}. {item}")
        lines.append("")
        lines.append("模板：")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(entry["sample"], indent=2, ensure_ascii=False))
        lines.append("```")
        if entry["notes"]:
            lines.append("")
            lines.append("说明：")
            lines.append("")
            for item_index, item in enumerate(entry["notes"], start=1):
                lines.append(f"{item_index}. {item}")
        lines.append("")

    lines.append("## Schema 用法")
    lines.append("")
    lines.append("初始化最小配置骨架：")
    lines.append("")
    lines.append("```bash")
    lines.append("ggdk config-init")
    lines.append("```")
    lines.append("")
    lines.append("查看某个配置的 schema：")
    lines.append("")
    lines.append("```bash")
    lines.append("ggdk config-schema google_api")
    lines.append("```")
    lines.append("")
    lines.append("校验当前本地配置：")
    lines.append("")
    lines.append("```bash")
    lines.append("ggdk config-check")
    lines.append("```")
    lines.append("")
    return assert_public_text_safe("\n".join(lines))