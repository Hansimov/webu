from __future__ import annotations

import json
import os

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

from .schema import has_config_schema, validate_config_payload


def _find_project_root() -> Path:
    explicit_root = os.getenv("WEBU_PROJECT_ROOT")
    if explicit_root:
        return Path(explicit_root).expanduser().resolve()

    for candidate in [Path.cwd(), *Path.cwd().parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate

    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    config_dir: Path
    data_dir: Path
    debug_dir: Path
    docs_dir: Path


@dataclass(frozen=True)
class CaptchaVlmSettings:
    endpoint: str = ""
    api_key: str = ""
    model: str = ""
    api_format: str = "openai"
    profile: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GoogleApiSettings:
    host: str
    port: int
    headless: bool
    proxies: list[dict[str, str]]
    profile_dir: Path
    screenshot_dir: Path
    data_dir: Path
    proxy_mode: str
    runtime_env: str
    service_url: str
    service_type: str
    api_token: str


@dataclass(frozen=True)
class GoogleDockerSettings:
    host: str
    port: int
    image_name: str
    container_name: str
    admin_token: str
    service_log_path: Path
    app_port: int
    runtime_env: str
    project_root: Path
    config_dir: Path


@dataclass(frozen=True)
class HfSpaceSettings:
    repo_id: str
    hf_token: str
    space_host: str
    raw: dict[str, Any] = field(default_factory=dict)


def _runtime_uses_local_proxy_config(runtime_env: str | None = None) -> bool:
    env = runtime_env or detect_runtime_environment()
    return env in {"local", "docker"}


def resolve_proxy_catalog(runtime_env: str | None = None) -> dict[str, Any]:
    env = runtime_env or detect_runtime_environment()
    if not _runtime_uses_local_proxy_config(env):
        return {}
    raw = load_json_config("proxies") or {}
    return raw if isinstance(raw, dict) else {}


def resolve_local_google_proxies(runtime_env: str | None = None) -> list[dict[str, str]]:
    catalog = resolve_proxy_catalog(runtime_env=runtime_env)
    section = catalog.get("google_api", {})
    if isinstance(section, dict):
        proxies = section.get("proxies", [])
    elif isinstance(section, list):
        proxies = section
    else:
        proxies = []

    normalized = []
    for item in proxies:
        if not isinstance(item, dict):
            continue
        proxy_url = str(item.get("url", "")).strip()
        if not proxy_url:
            continue
        normalized.append(
            {
                "url": proxy_url,
                "name": str(item.get("name", proxy_url)),
            }
        )
    return normalized


def resolve_named_local_proxy(section_name: str, key: str) -> str:
    catalog = resolve_proxy_catalog()
    section = catalog.get(section_name, {})
    if not isinstance(section, dict):
        return ""
    value = section.get(key, "")
    return str(value).strip()


def resolve_gemini_default_proxy() -> str:
    return resolve_named_local_proxy("gemini", "default_proxy")


def resolve_proxy_api_fetch_proxy() -> str:
    return resolve_named_local_proxy("proxy_api", "fetch_proxy")


def resolve_searches_chrome_proxy() -> str:
    return resolve_named_local_proxy("searches", "chrome_proxy")


def _default_google_api_service_type(runtime_env: str) -> str:
    if runtime_env == "hf-space":
        return "hf-space"
    if runtime_env == "docker":
        return "local"
    return "local"


def _normalize_service_type(value: str | None, runtime_env: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"local", "remote-server", "hf-space"}:
        return text
    return _default_google_api_service_type(runtime_env)


def _resolve_default_hf_space_name(selected: dict[str, Any] | None = None) -> str:
    explicit = (
        os.getenv("WEBU_HF_SPACE_NAME")
        or os.getenv("SPACE_ID")
        or os.getenv("HF_SPACE_NAME")
    )
    if explicit:
        return str(explicit).strip()

    if selected:
        selected_space = str(selected.get("space", "")).strip()
        if selected_space:
            return selected_space

    raw_entries = load_json_config("hf_spaces") or []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        space_name = str(entry.get("space", "")).strip()
        if space_name:
            return space_name
    return ""


def resolve_google_api_service_profile(
    *,
    runtime_env: str | None = None,
    service_type: str | None = None,
    host: str | None = None,
    port: int | None = None,
) -> dict[str, str]:
    env = runtime_env or detect_runtime_environment()
    config = load_json_config("google_api") or {}

    resolved_type = _normalize_service_type(
        os.getenv("WEBU_GOOGLE_SERVICE_TYPE") or service_type or config.get("service_type", ""),
        env,
    )
    env_url = str(os.getenv("WEBU_GOOGLE_SERVICE_URL", "")).strip()
    env_token = os.getenv("WEBU_GOOGLE_API_TOKEN")

    selected = {}
    for item in config.get("services", []):
        if not isinstance(item, dict):
            continue
        item_type = _normalize_service_type(item.get("type"), env)
        if item_type == resolved_type:
            selected = item
            break

    resolved_host = str(host or os.getenv("WEBU_GOOGLE_HOST", config.get("host", "0.0.0.0")))
    resolved_port = int(port or _env_int("WEBU_GOOGLE_PORT", int(config.get("port", 18200))))
    default_url = f"http://127.0.0.1:{resolved_port}"
    selected_url = str(selected.get("url", "")).strip()
    derived_url = ""
    if resolved_type == "hf-space" and not env_url and not selected_url:
        derived_space_name = _resolve_default_hf_space_name(selected)
        if derived_space_name:
            derived_url = resolve_hf_space_settings(derived_space_name).space_host

    return {
        "url": env_url or selected_url or derived_url or default_url,
        "type": resolved_type,
        "api_token": env_token if env_token is not None else str(selected.get("api_token", "")).strip(),
    }


def get_workspace_paths() -> WorkspacePaths:
    root = _find_project_root()
    config_dir = Path(os.getenv("WEBU_CONFIG_DIR", root / "configs")).expanduser()
    data_dir = Path(os.getenv("WEBU_DATA_DIR", root / "data")).expanduser()
    debug_dir = Path(os.getenv("WEBU_DEBUG_DIR", root / "debugs")).expanduser()
    docs_dir = root / "docs"
    return WorkspacePaths(
        root=root,
        config_dir=config_dir,
        data_dir=data_dir,
        debug_dir=debug_dir,
        docs_dir=docs_dir,
    )


def detect_runtime_environment() -> str:
    explicit = os.getenv("WEBU_RUNTIME_ENV", "").strip().lower()
    if explicit:
        return explicit
    if os.getenv("SPACE_ID") or os.getenv("SPACE_HOST"):
        return "hf-space"
    if Path("/.dockerenv").exists():
        return "docker"
    return "local"


def _load_json_file(path: Path) -> Any:
    if not path.exists():
        return {} if path.suffix == ".json" else None
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)


def load_json_config(name: str) -> Any:
    paths = get_workspace_paths()
    env_key = f"WEBU_{name.upper()}_CONFIG_PATH"
    config_path = Path(os.getenv(env_key, paths.config_dir / f"{name}.json")).expanduser()
    payload = _load_json_file(config_path)

    validation_env = os.getenv("WEBU_VALIDATE_CONFIGS", "true").strip().lower()
    validation_enabled = validation_env not in {"0", "false", "no", "off"}
    if validation_enabled and config_path.exists() and has_config_schema(name):
        errors = validate_config_payload(name, payload)
        if errors:
            joined = "; ".join(errors)
            raise ValueError(f"Invalid config '{name}' at {config_path}: {joined}")

    return payload


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _env_json(name: str) -> Any:
    value = os.getenv(name)
    if not value:
        return None
    return json.loads(value)


def _merge_mapping(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(base)
    if not override:
        return merged
    for key, value in override.items():
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        merged[key] = value
    return merged


def _normalize_proxy_url(proxy_url: str, runtime_env: str) -> str:
    if runtime_env != "docker":
        return proxy_url
    parts = urlsplit(proxy_url)
    if parts.hostname not in {"127.0.0.1", "localhost", "0.0.0.0"}:
        return proxy_url
    docker_host = os.getenv("WEBU_DOCKER_HOST_PROXY_HOST", "host.docker.internal")
    netloc = docker_host
    if parts.port:
        netloc = f"{docker_host}:{parts.port}"
    if parts.username:
        auth = parts.username
        if parts.password:
            auth = f"{auth}:{parts.password}"
        netloc = f"{auth}@{netloc}"
    normalized = SplitResult(
        scheme=parts.scheme,
        netloc=netloc,
        path=parts.path,
        query=parts.query,
        fragment=parts.fragment,
    )
    return urlunsplit(normalized)


def resolve_captcha_vlm_settings() -> CaptchaVlmSettings:
    captcha_config = load_json_config("captcha") or {}
    llm_catalog = load_json_config("llms") or {}

    root_vlm = captcha_config.get("vlm", {}) if isinstance(captcha_config, dict) else {}
    profile = (
        os.getenv("WEBU_CAPTCHA_VLM_PROFILE")
        or root_vlm.get("profile")
        or root_vlm.get("llm")
        or captcha_config.get("profile", "")
    )
    profile_config = llm_catalog.get(profile, {}) if profile else {}
    merged = _merge_mapping(profile_config, root_vlm)
    merged = _merge_mapping(merged, captcha_config)

    endpoint = os.getenv("WEBU_CAPTCHA_VLM_ENDPOINT", merged.get("endpoint", ""))
    api_key = os.getenv("WEBU_CAPTCHA_VLM_API_KEY", merged.get("api_key", ""))
    model = os.getenv("WEBU_CAPTCHA_VLM_MODEL", merged.get("model", ""))
    api_format = os.getenv("WEBU_CAPTCHA_VLM_API_FORMAT", merged.get("api_format", "openai"))

    return CaptchaVlmSettings(
        endpoint=str(endpoint).rstrip("/"),
        api_key=str(api_key),
        model=str(model),
        api_format=str(api_format),
        profile=str(profile or ""),
        raw=merged,
    )


def resolve_google_api_settings(
    *,
    headless: bool | None = None,
    host: str | None = None,
    port: int | None = None,
    runtime_env: str | None = None,
    service_type: str | None = None,
) -> GoogleApiSettings:
    paths = get_workspace_paths()
    runtime_env = runtime_env or detect_runtime_environment()
    config = load_json_config("google_api") or {}

    proxy_mode = os.getenv("WEBU_GOOGLE_PROXY_MODE", config.get("proxy_mode", "auto")).strip().lower()
    proxies = _env_json("WEBU_GOOGLE_PROXIES")
    if proxies is None:
        proxies = resolve_local_google_proxies(runtime_env=runtime_env)
    if proxies is None:
        proxies = config.get("proxies")
    if proxy_mode == "disabled":
        proxies = []
    if proxy_mode == "auto" and runtime_env == "hf-space":
        proxies = []

    normalized_proxies = []
    for proxy in proxies or []:
        proxy_url = proxy.get("url", "")
        if not proxy_url:
            continue
        normalized_proxies.append(
            {
                "url": _normalize_proxy_url(proxy_url, runtime_env),
                "name": proxy.get("name", proxy_url),
            }
        )

    resolved_headless = headless
    if resolved_headless is None:
        resolved_headless = _env_bool(
            "WEBU_GOOGLE_HEADLESS",
            config.get("headless", runtime_env != "local"),
        )

    resolved_host = host or os.getenv("WEBU_GOOGLE_HOST", config.get("host", "0.0.0.0"))
    resolved_port = port or _env_int("WEBU_GOOGLE_PORT", int(config.get("port", 18200)))

    profile_dir = Path(
        os.getenv(
            "WEBU_GOOGLE_PROFILE_DIR",
            config.get("profile_dir", paths.data_dir / "google_api" / "chrome_profile"),
        )
    ).expanduser()
    screenshot_dir = Path(
        os.getenv(
            "WEBU_GOOGLE_SCREENSHOT_DIR",
            config.get("screenshot_dir", paths.data_dir / "google_api_screenshots"),
        )
    ).expanduser()
    data_dir = Path(
        os.getenv(
            "WEBU_GOOGLE_DATA_DIR",
            config.get("data_dir", paths.data_dir / "google_api"),
        )
    ).expanduser()
    service_profile = resolve_google_api_service_profile(
        runtime_env=runtime_env,
        service_type=service_type,
        host=resolved_host,
        port=resolved_port,
    )

    return GoogleApiSettings(
        host=str(resolved_host),
        port=int(resolved_port),
        headless=bool(resolved_headless),
        proxies=normalized_proxies,
        profile_dir=profile_dir,
        screenshot_dir=screenshot_dir,
        data_dir=data_dir,
        proxy_mode=proxy_mode,
        runtime_env=runtime_env,
        service_url=service_profile["url"],
        service_type=service_profile["type"],
        api_token=service_profile["api_token"],
    )


def resolve_google_docker_settings() -> GoogleDockerSettings:
    paths = get_workspace_paths()
    runtime_env = detect_runtime_environment()
    config = load_json_config("google_docker") or {}
    host = os.getenv("WEBU_DOCKER_HOST", config.get("host", "0.0.0.0"))
    port = _env_int("WEBU_DOCKER_PORT", int(config.get("port", 18200)))
    app_port = _env_int("WEBU_DOCKER_APP_PORT", int(config.get("app_port", port)))
    image_name = os.getenv("WEBU_DOCKER_IMAGE", config.get("image_name", "webu/google-api:dev"))
    container_name = os.getenv("WEBU_DOCKER_CONTAINER", config.get("container_name", "webu-google-api"))
    admin_token = os.getenv("WEBU_ADMIN_TOKEN", config.get("admin_token", ""))
    service_log_path = Path(
        os.getenv(
            "WEBU_SERVICE_LOG",
            config.get("service_log_path", paths.data_dir / "google_docker" / "service.log"),
        )
    ).expanduser()
    config_dir = Path(os.getenv("WEBU_CONTAINER_CONFIG_DIR", paths.config_dir)).expanduser()

    return GoogleDockerSettings(
        host=str(host),
        port=int(port),
        image_name=str(image_name),
        container_name=str(container_name),
        admin_token=str(admin_token),
        service_log_path=service_log_path,
        app_port=int(app_port),
        runtime_env=runtime_env,
        project_root=paths.root,
        config_dir=config_dir,
    )


def resolve_hf_space_settings(space_name: str) -> HfSpaceSettings:
    raw_entries = load_json_config("hf_spaces") or []
    matched = None
    for entry in raw_entries:
        if entry.get("space") == space_name:
            matched = entry
            break
    matched = matched or {}
    hf_token = os.getenv("WEBU_HF_TOKEN") or os.getenv("HF_TOKEN") or matched.get("hf_token", "")
    return HfSpaceSettings(
        repo_id=space_name,
        hf_token=str(hf_token),
        space_host=f"https://{space_name.replace('/', '-')}.hf.space",
        raw=matched,
    )