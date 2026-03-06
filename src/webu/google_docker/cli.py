from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib

from pathlib import Path
from urllib.parse import urlsplit

import requests

from huggingface_hub import HfApi
from tclogger import dict_to_str, logger

from webu.runtime_settings.schema import (
    CONFIGS_DOC_PATH,
    available_config_names,
    config_schema_json,
    render_config_template_json,
    render_configs_markdown,
    validate_config_payload,
)
from webu.google_docker.helptext import (
    HINTS_DOC_PATH,
    SETUP_DOC_PATH,
    USAGE_DOC_PATH,
    command_description,
    command_epilog,
    render_hints_markdown,
    render_setup_markdown,
    render_usage_markdown,
    root_description,
    root_epilog,
)
from webu.google_api.profile_bootstrap import (
    DEFAULT_BOOTSTRAP_ARCHIVE_NAME,
    create_encrypted_profile_archive,
)
from webu.runtime_settings import (
    get_workspace_paths,
    load_json_config,
    resolve_captcha_vlm_settings,
    resolve_google_api_settings,
    resolve_google_api_service_profile,
    resolve_google_docker_settings,
    resolve_hf_space_settings,
)


ASSET_DIR = Path(__file__).resolve().parent / "assets"
DOCKERFILE_PATH = ASSET_DIR / "Dockerfile"
ROOT_IGNORE_NAMES = {
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    ".chats",
    "__pycache__",
    "data",
    "debugs",
    "tests",
    "configs",
}
SPACE_PACKAGE_DIRS = [
    "captcha",
    "fastapis",
    "google_api",
    "google_docker",
    "runtime_settings",
]
SPACE_BOOTSTRAP_ARCHIVE = f"bootstrap/{DEFAULT_BOOTSTRAP_ARCHIVE_NAME}"


def _space_package_ignore(package_name: str):
    ignore_names = [
        "__pycache__",
        "*.pyc",
        "*.pyo",
        "ipv6_global_addrs.json",
        "ipv6_mirrors",
    ]
    if package_name == "captcha":
        ignore_names.append("imgs")
    return shutil.ignore_patterns(*ignore_names)


def _write_minimal_webu_init(package_root: Path):
    (package_root / "__init__.py").write_text(
        "__all__ = []\n",
        encoding="utf-8",
    )


def _run_command(command: list[str], check: bool = True):
    logger.note("> " + " ".join(command))
    return subprocess.run(command, check=check)


def _add_command_parser(subparsers, command_name: str, help_text: str):
    return subparsers.add_parser(
        command_name,
        help=help_text,
        description=command_description(command_name),
        epilog=command_epilog(command_name),
        formatter_class=argparse.RawTextHelpFormatter,
    )


def _space_readme(repo_id: str, app_port: int) -> str:
    title = repo_id.split("/")[-1]
    return (
        "---\n"
        f"title: {title}\n"
        "emoji: 🐳\n"
        "colorFrom: blue\n"
        "colorTo: gray\n"
        "sdk: docker\n"
        f"app_port: {app_port}\n"
        "pinned: false\n"
        "---\n\n"
        "# WebU Google Docker\n\n"
        "Dockerized WebU google_api service with runtime config delivered via env/secrets.\n"
    )


def _format_toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _render_toml_string_list(key: str, values: list[str]) -> list[str]:
    if not values:
        return []
    lines = [f"{key} = ["]
    for value in values:
        lines.append(f"    {_format_toml_string(value)},")
    lines.append("]")
    return lines


def _write_sanitized_pyproject(source_root: Path, bundle_root: Path):
    source_path = source_root / "pyproject.toml"
    if not source_path.exists():
        return

    project_data = tomllib.loads(source_path.read_text(encoding="utf-8")).get("project", {})
    lines = ["[project]"]

    for key in ["name", "version", "description", "readme", "license", "requires-python"]:
        value = project_data.get(key)
        if value:
            lines.append(f"{key} = {_format_toml_string(value)}")

    lines.extend(_render_toml_string_list("classifiers", list(project_data.get("classifiers", []))))
    lines.extend(_render_toml_string_list("dependencies", list(project_data.get("dependencies", []))))

    scripts = project_data.get("scripts", {})
    if scripts:
        lines.append("")
        lines.append("[project.scripts]")
        for key, value in scripts.items():
            lines.append(f"{key} = {_format_toml_string(value)}")

    (bundle_root / "pyproject.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _create_google_profile_bootstrap_archive(bundle_root: Path):
    bootstrap_root = bundle_root / "bootstrap"
    bootstrap_root.mkdir(parents=True, exist_ok=True)

    source_profile_dir = resolve_google_api_settings(runtime_env="local", service_type="local").profile_dir
    if not source_profile_dir.exists() or not any(source_profile_dir.iterdir()):
        return

    google_service = resolve_google_api_service_profile(runtime_env="hf-space", service_type="hf-space")
    api_token = str(google_service.get("api_token", "")).strip()
    if not api_token:
        raise ValueError("google_api hf-space api_token is required to encrypt the bootstrap profile")

    create_encrypted_profile_archive(
        source_profile_dir,
        bundle_root / SPACE_BOOTSTRAP_ARCHIVE,
        api_token,
    )


def prepare_space_bundle(source_root: Path, output_root: Path, app_port: int, repo_id: str) -> Path:
    bundle_root = output_root / "bundle"
    bundle_root.mkdir(parents=True, exist_ok=True)

    _write_sanitized_pyproject(source_root, bundle_root)

    license_path = source_root / "LICENSE"
    if license_path.exists():
        shutil.copy2(license_path, bundle_root / "LICENSE")

    shutil.copy2(DOCKERFILE_PATH, bundle_root / "Dockerfile")
    (bundle_root / "README.md").write_text(_space_readme(repo_id, app_port), encoding="utf-8")
    _create_google_profile_bootstrap_archive(bundle_root)

    src_root = source_root / "src"
    bundle_src_root = bundle_root / "src"
    bundle_src_root.mkdir(parents=True, exist_ok=True)
    bundle_webu_root = bundle_src_root / "webu"
    bundle_webu_root.mkdir(parents=True, exist_ok=True)
    _write_minimal_webu_init(bundle_webu_root)

    for package_name in SPACE_PACKAGE_DIRS:
        src_package = src_root / "webu" / package_name
        dst_package = bundle_webu_root / package_name
        shutil.copytree(
            src_package,
            dst_package,
            dirs_exist_ok=True,
            ignore=_space_package_ignore(package_name),
        )
    return bundle_root


def _docker_env_args(env_map: dict[str, str]) -> list[str]:
    args = []
    for key, value in env_map.items():
        args.extend(["-e", f"{key}={value}"])
    return args


def _resolve_default_space_name(explicit_space: str | None = None) -> str:
    space_name = str(explicit_space or os.getenv("WEBU_HF_SPACE_NAME") or "").strip()
    if space_name:
        return space_name

    raw_entries = load_json_config("hf_spaces") or []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        candidate = str(entry.get("space", "")).strip()
        if candidate:
            return candidate

    raise ValueError("HF space not configured; pass --space or add configs/hf_spaces.json")


def _resolve_hf_service_profile() -> dict[str, str]:
    return resolve_google_api_service_profile(runtime_env="hf-space", service_type="hf-space")


def _resolve_hf_service_url() -> str:
    service_url = str(_resolve_hf_service_profile().get("url", "")).strip().rstrip("/")
    if not service_url:
        raise ValueError("hf-space service URL is not configured")
    return service_url


def _resolve_hf_search_token(explicit_token: str | None = None) -> str:
    token = str(explicit_token or _resolve_hf_service_profile().get("api_token", "")).strip()
    return token


def _resolve_admin_token(explicit_token: str | None = None) -> str:
    token = str(explicit_token or resolve_google_docker_settings().admin_token).strip()
    return token


def _print_http_response(response: requests.Response):
    try:
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except ValueError:
        print(response.text)


def _read_config_payload(name: str):
    config_path = get_workspace_paths().config_dir / f"{name}.json"
    if not config_path.exists():
        return None, str(config_path), "missing"
    return json.loads(config_path.read_text(encoding="utf-8")), str(config_path), "present"


def _container_running(container_name: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def _resolve_local_service_url(port: int | None = None) -> str:
    resolved_port = int(port or resolve_google_docker_settings().port)
    return f"http://127.0.0.1:{resolved_port}"


def _detect_port_listener(port: int) -> str:
    commands = [
        ["ss", "-ltnp", f"( sport = :{port} )"],
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
    ]
    for command in commands:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        output = (result.stdout or "").strip()
        if result.returncode == 0 and output:
            return output
    return ""


def _request_hf_service(
    path: str,
    *,
    params: dict[str, str | int] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
):
    response = requests.get(
        f"{_resolve_hf_service_url()}{path}",
        params=params,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    return response


def _resolve_hf_api(space_name: str) -> tuple[HfApi, object]:
    space_name = _resolve_default_space_name(space_name)
    settings = resolve_hf_space_settings(space_name)
    if not settings.hf_token:
        raise ValueError(f"HF token not found for space: {space_name}")
    return HfApi(token=settings.hf_token), settings


def _super_squash_space_history(api: HfApi, repo_id: str, branch: str = "main"):
    api.super_squash_history(repo_id=repo_id, repo_type="space", branch=branch)


def _restart_space_request(space_name: str, hf_token: str, factory_reboot: bool = False):
    control_endpoints = []
    preferred = os.getenv("WEBU_HF_CONTROL_ENDPOINT", "https://huggingface.co").rstrip("/")
    control_endpoints.append(preferred)
    mirror_endpoint = os.getenv("HF_ENDPOINT", "").strip().rstrip("/")
    if mirror_endpoint and mirror_endpoint not in control_endpoints:
        control_endpoints.append(mirror_endpoint)

    headers = {"Authorization": f"Bearer {hf_token}"}
    params = {"factory": "true"} if factory_reboot else None
    last_error = None

    for endpoint in control_endpoints:
        try:
            response = requests.post(
                f"{endpoint}/api/spaces/{space_name}/restart",
                headers=headers,
                params=params,
                timeout=60,
            )
            response.raise_for_status()
            return endpoint
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Failed to restart Space via all control endpoints: {last_error}")


def _is_public_http_endpoint(endpoint: str) -> bool:
    if not endpoint:
        return False
    try:
        parsed = urlsplit(endpoint)
    except Exception:
        return False
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname or hostname in {"localhost", "host.docker.internal"}:
        return False
    try:
        ip_addr = ipaddress.ip_address(hostname)
    except ValueError:
        return "." in hostname and not hostname.endswith(".local")
    return not (ip_addr.is_loopback or ip_addr.is_private or ip_addr.is_link_local)


def _sync_space_runtime_config(api: HfApi, space_name: str, admin_token: str | None):
    captcha = resolve_captcha_vlm_settings()
    google_service = resolve_google_api_service_profile(runtime_env="hf-space", service_type="hf-space")
    llm_catalog = load_json_config("llms") or {}
    hf_profile_name = os.getenv("WEBU_HF_CAPTCHA_VLM_PROFILE", "sf_qwen3_vl_8b").strip()
    hf_profile = llm_catalog.get(hf_profile_name, {}) if hf_profile_name else {}
    hf_captcha_endpoint = os.getenv("WEBU_HF_CAPTCHA_VLM_ENDPOINT", "").strip()
    hf_captcha_api_key = os.getenv("WEBU_HF_CAPTCHA_VLM_API_KEY", "").strip()
    hf_captcha_model = os.getenv("WEBU_HF_CAPTCHA_VLM_MODEL", "").strip()
    hf_captcha_api_format = os.getenv("WEBU_HF_CAPTCHA_VLM_API_FORMAT", "").strip()

    variable_map = {
        "WEBU_RUNTIME_ENV": "hf-space",
        "WEBU_GOOGLE_PROXY_MODE": os.getenv("WEBU_GOOGLE_PROXY_MODE", "disabled"),
        "WEBU_GOOGLE_HEADLESS": "true",
        "WEBU_SERVICE_LOG": "/tmp/webu-google-docker.log",
        "WEBU_GOOGLE_SERVICE_TYPE": google_service["type"],
    }
    if google_service["url"]:
        variable_map["WEBU_GOOGLE_SERVICE_URL"] = google_service["url"]

    selected_endpoint = hf_captcha_endpoint
    if not selected_endpoint:
        selected_endpoint = str(hf_profile.get("endpoint", "")).strip()
    if not selected_endpoint and _is_public_http_endpoint(captcha.endpoint):
        selected_endpoint = captcha.endpoint
    if selected_endpoint:
        variable_map["WEBU_CAPTCHA_VLM_ENDPOINT"] = selected_endpoint
    elif captcha.endpoint:
        logger.warn(
            "> Skip propagating local/private captcha endpoint to HF Space; set WEBU_HF_CAPTCHA_VLM_ENDPOINT if remote captcha solving is required"
        )

    selected_model = hf_captcha_model or str(hf_profile.get("model", "")).strip() or captcha.model
    if selected_model:
        variable_map["WEBU_CAPTCHA_VLM_MODEL"] = selected_model
    selected_api_format = hf_captcha_api_format or str(hf_profile.get("api_format", "")).strip() or captcha.api_format
    if selected_api_format:
        variable_map["WEBU_CAPTCHA_VLM_API_FORMAT"] = selected_api_format

    for key, value in variable_map.items():
        api.add_space_variable(repo_id=space_name, key=key, value=value)

    selected_api_key = hf_captcha_api_key or str(hf_profile.get("api_key", "")).strip() or captcha.api_key
    if selected_api_key:
        api.add_space_secret(
            repo_id=space_name,
            key="WEBU_CAPTCHA_VLM_API_KEY",
            value=selected_api_key,
        )
    if google_service["api_token"]:
        api.add_space_secret(
            repo_id=space_name,
            key="WEBU_GOOGLE_API_TOKEN",
            value=google_service["api_token"],
        )
    if admin_token:
        api.add_space_secret(
            repo_id=space_name,
            key="WEBU_ADMIN_TOKEN",
            value=admin_token,
        )


def cmd_print_config(args):
    google = resolve_google_api_settings()
    docker = resolve_google_docker_settings()
    captcha = resolve_captcha_vlm_settings()
    rendered = {
        "google_api": {
            "host": google.host,
            "port": google.port,
            "headless": google.headless,
            "proxy_mode": google.proxy_mode,
            "proxies": google.proxies,
            "service_url": google.service_url,
            "service_type": google.service_type,
            "api_token_configured": bool(google.api_token),
            "profile_dir": str(google.profile_dir),
            "screenshot_dir": str(google.screenshot_dir),
        },
        "google_docker": {
            "host": docker.host,
            "port": docker.port,
            "image_name": docker.image_name,
            "container_name": docker.container_name,
            "service_log_path": str(docker.service_log_path),
            "admin_token_configured": bool(docker.admin_token),
        },
        "captcha": {
            "endpoint": captcha.endpoint,
            "model": captcha.model,
            "api_format": captcha.api_format,
            "profile": captcha.profile,
            "api_key_configured": bool(captcha.api_key),
        },
    }
    print(json.dumps(rendered, indent=2, ensure_ascii=False))


def cmd_serve(args):
    from .server import main as server_main

    sys.argv = [sys.argv[0], "--host", args.host, "--port", str(args.port)]
    server_main()


def cmd_docker_build(args):
    docker_settings = resolve_google_docker_settings()
    image_name = args.image or docker_settings.image_name
    paths = get_workspace_paths()
    apt_mirror = os.getenv("WEBU_APT_MIRROR", "https://mirrors.ustc.edu.cn/debian")
    apt_security_mirror = os.getenv("WEBU_APT_SECURITY_MIRROR", "https://mirrors.ustc.edu.cn/debian-security")
    pip_index_url = os.getenv("PIP_INDEX_URL", "https://mirrors.ustc.edu.cn/pypi/simple")
    pip_trusted_host = os.getenv("PIP_TRUSTED_HOST", "mirrors.ustc.edu.cn")
    command = [
        "docker",
        "build",
        "--build-arg",
        f"APT_MIRROR={apt_mirror}",
        "--build-arg",
        f"APT_SECURITY_MIRROR={apt_security_mirror}",
        "--build-arg",
        f"PIP_INDEX_URL={pip_index_url}",
        "--build-arg",
        f"PIP_TRUSTED_HOST={pip_trusted_host}",
        "-f",
        str(DOCKERFILE_PATH),
        "-t",
        image_name,
        str(paths.root),
    ]
    if args.no_cache:
        command.insert(2, "--no-cache")
    for proxy_var in ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"]:
        if os.getenv(proxy_var):
            command[2:2] = ["--build-arg", f"{proxy_var}={os.getenv(proxy_var)}"]
    _run_command(command)


def cmd_docker_run(args):
    paths = get_workspace_paths()
    docker_settings = resolve_google_docker_settings()
    image_name = args.image or docker_settings.image_name
    container_name = args.name or docker_settings.container_name
    admin_token = args.admin_token or docker_settings.admin_token
    use_host_network = sys.platform.startswith("linux") and args.proxy_mode != "disabled"

    env_map = {
        "WEBU_RUNTIME_ENV": "docker",
        "WEBU_DOCKER_HOST": "0.0.0.0",
        "WEBU_DOCKER_PORT": str(args.port),
        "WEBU_GOOGLE_PORT": str(args.port),
        "WEBU_GOOGLE_HEADLESS": "true",
    }
    if admin_token:
        env_map["WEBU_ADMIN_TOKEN"] = admin_token
    if args.proxy_mode:
        env_map["WEBU_GOOGLE_PROXY_MODE"] = args.proxy_mode
    if use_host_network:
        env_map["WEBU_DOCKER_HOST_PROXY_HOST"] = "127.0.0.1"

    command = [
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
        "--restart",
        "unless-stopped",
    ]

    if use_host_network:
        logger.note(
            "> Linux local proxy mode detected, using --network host so container can reach host loopback proxies"
        )
        command.extend(["--network", "host"])
    else:
        command.extend([
            "--add-host",
            "host.docker.internal:host-gateway",
            "-p",
            f"{args.port}:{args.port}",
        ])

    if args.replace:
        subprocess.run(["docker", "rm", "-f", container_name], check=False)

    if args.mount_configs and paths.config_dir.exists():
        command.extend(["-v", f"{paths.config_dir}:/run/webu-configs:ro"])
        env_map["WEBU_CONFIG_DIR"] = "/run/webu-configs"

    if args.bind_source:
        command.extend(["-v", f"{paths.root}:/workspace"])
        env_map["PYTHONPATH"] = "/workspace/src"
        env_map["WEBU_PROJECT_ROOT"] = "/workspace"

    command.extend(_docker_env_args(env_map))
    command.append(image_name)
    _run_command(command)


def cmd_docker_stop(args):
    docker_settings = resolve_google_docker_settings()
    container_name = args.name or docker_settings.container_name
    _run_command(["docker", "rm", "-f", container_name], check=False)


def cmd_docker_logs(args):
    docker_settings = resolve_google_docker_settings()
    container_name = args.name or docker_settings.container_name
    command = ["docker", "logs", "--tail", str(args.lines)]
    if args.follow:
        command.append("-f")
    command.append(container_name)
    _run_command(command, check=False)


def cmd_docker_up(args):
    docker_settings = resolve_google_docker_settings()
    build_args = argparse.Namespace(
        image=args.image,
        no_cache=args.no_cache,
    )
    run_args = argparse.Namespace(
        image=args.image,
        name=args.name,
        port=args.port,
        proxy_mode=args.proxy_mode,
        bind_source=not args.no_bind_source,
        mount_configs=not args.no_mount_configs,
        replace=True,
        admin_token=args.admin_token,
    )
    if not args.skip_build:
        cmd_docker_build(build_args)
    cmd_docker_run(run_args)
    logger.okay(f"  ✓ Docker service is up: {args.name or docker_settings.container_name}")


def cmd_docker_down(args):
    cmd_docker_stop(argparse.Namespace(name=args.name))


def cmd_docker_check(args):
    docker_settings = resolve_google_docker_settings()
    container_name = args.name or docker_settings.container_name
    local_url = _resolve_local_service_url(args.port)
    is_running = _container_running(container_name)
    health = None
    runtime = None
    health_error = ""
    runtime_error = ""
    service_hint = ""
    port_listener = ""
    admin_token = _resolve_admin_token(args.admin_token)

    try:
        response = requests.get(f"{local_url}/health", timeout=args.timeout)
        response.raise_for_status()
        health = response.json()
    except Exception as exc:
        health_error = str(exc)

    if admin_token and is_running:
        try:
            response = requests.get(
                f"{local_url}/admin/runtime",
                headers={"X-Admin-Token": admin_token},
                timeout=args.timeout,
            )
            response.raise_for_status()
            runtime = response.json()
        except Exception as exc:
            runtime_error = str(exc)
    elif not is_running:
        runtime_error = "docker container is not running"
        if health is not None:
            port_listener = _detect_port_listener(args.port)
            service_hint = (
                "service port is reachable even though the docker container is stopped; "
                "this usually means a direct local process is already bound to the same port"
            )

    print(
        json.dumps(
            {
                "container_name": container_name,
                "running": is_running,
                "service_url": local_url,
                "health": health,
                "health_error": health_error,
                "runtime": runtime,
                "runtime_error": runtime_error,
                "service_hint": service_hint,
                "port_listener": port_listener,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def cmd_hf_sync(args):
    space_name = _resolve_default_space_name(args.space)
    api, hf_settings = _resolve_hf_api(space_name)
    docker_settings = resolve_google_docker_settings()
    repo_id = args.repo_id or space_name

    api.create_repo(repo_id=repo_id, repo_type="space", space_sdk="docker", exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="webu-hf-space-") as tmpdir:
        bundle_root = prepare_space_bundle(
            source_root=get_workspace_paths().root,
            output_root=Path(tmpdir),
            app_port=args.port,
            repo_id=repo_id,
        )
        api.upload_folder(
            repo_id=repo_id,
            repo_type="space",
            folder_path=str(bundle_root),
            commit_message=args.message or "Sync WebU google_docker bundle",
            delete_patterns="*",
        )

    _sync_space_runtime_config(api, repo_id, args.admin_token or docker_settings.admin_token)
    if args.restart:
        try:
            used_endpoint = _restart_space_request(repo_id, hf_settings.hf_token, factory_reboot=args.factory)
            logger.okay(f"  ✓ Restart requested via: {used_endpoint}")
        except Exception as exc:
            logger.warn(f"> HF restart request failed after sync: {exc}")
    logger.okay(f"  ✓ Synced to HF Space: {repo_id}")
    logger.mesg(f"  URL: {hf_settings.space_host}")


def cmd_hf_status(args):
    space_name = _resolve_default_space_name(args.space)
    api, hf_settings = _resolve_hf_api(space_name)
    runtime = api.get_space_runtime(repo_id=space_name)
    info = {
        "repo_id": space_name,
        "stage": str(runtime.stage),
        "hardware": runtime.hardware,
        "requested_hardware": runtime.requested_hardware,
        "sleep_time": runtime.sleep_time,
        "storage": runtime.storage,
        "space_host": hf_settings.space_host,
    }
    print(json.dumps(info, indent=2, ensure_ascii=False))


def cmd_hf_restart(args):
    space_name = _resolve_default_space_name(args.space)
    _, hf_settings = _resolve_hf_api(space_name)
    used_endpoint = _restart_space_request(space_name, hf_settings.hf_token, factory_reboot=args.factory)
    logger.okay(f"  ✓ Restart requested for: {space_name} via {used_endpoint}")


def cmd_hf_super_squash(args):
    space_name = _resolve_default_space_name(args.space)
    api, _ = _resolve_hf_api(space_name)
    _super_squash_space_history(api, space_name, branch=args.branch)
    logger.okay(f"  ✓ Super-squashed Space history for: {space_name} ({args.branch})")


def cmd_hf_logs(args):
    space_name = _resolve_default_space_name(args.space)
    _, hf_settings = _resolve_hf_api(space_name)
    headers = {}
    if hf_settings.hf_token:
        headers["Authorization"] = f"Bearer {hf_settings.hf_token}"
    admin_token = _resolve_admin_token(args.admin_token)
    if admin_token:
        headers["X-Admin-Token"] = admin_token
    response = requests.get(
        f"{hf_settings.space_host}/admin/logs",
        params={"lines": args.lines},
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    print(response.json().get("content", ""))


def cmd_hf_url(args):
    print(_resolve_hf_service_url())


def cmd_hf_health(args):
    response = _request_hf_service("/health", timeout=args.timeout)
    _print_http_response(response)


def cmd_hf_home(args):
    response = _request_hf_service("/", timeout=args.timeout)
    _print_http_response(response)


def cmd_hf_runtime(args):
    admin_token = _resolve_admin_token(args.admin_token)
    if not admin_token:
        raise ValueError("Admin token not configured; set configs/google_docker.json or pass --admin-token")
    response = _request_hf_service(
        "/admin/runtime",
        headers={"X-Admin-Token": admin_token},
        timeout=args.timeout,
    )
    _print_http_response(response)


def cmd_hf_search(args):
    headers = {}
    if not args.no_auth:
        api_token = _resolve_hf_search_token(args.api_token)
        if api_token:
            headers["X-Api-Token"] = api_token
    response = _request_hf_service(
        "/search",
        params={"q": args.query, "num": args.num, "lang": args.lang},
        headers=headers or None,
        timeout=args.timeout,
    )
    _print_http_response(response)


def cmd_hf_files(args):
    space_name = _resolve_default_space_name(args.space)
    api, _ = _resolve_hf_api(space_name)
    files = sorted(api.list_repo_files(space_name, repo_type="space"))
    for path in files:
        if args.prefix and not path.startswith(args.prefix):
            continue
        print(path)


def cmd_hf_commit_count(args):
    space_name = _resolve_default_space_name(args.space)
    api, _ = _resolve_hf_api(space_name)
    print(len(api.list_repo_commits(space_name, repo_type="space")))


def _collect_hf_check_report(args, *, include_diagnostics: bool = False) -> dict[str, object]:
    space_name = _resolve_default_space_name(args.space)
    api, hf_settings = _resolve_hf_api(space_name)
    runtime = api.get_space_runtime(repo_id=space_name)
    service_url = _resolve_hf_service_url()
    health = None
    runtime_info = None
    health_error = ""
    runtime_error = ""
    search_auth_error = ""
    search_auth_status = None
    admin_token = _resolve_admin_token(args.admin_token)
    report: dict[str, object] = {
        "repo_id": space_name,
        "service_url": service_url,
        "space_host": hf_settings.space_host,
        "stage": str(runtime.stage),
        "hardware": runtime.hardware,
        "requested_hardware": runtime.requested_hardware,
    }

    try:
        response = requests.get(f"{service_url}/health", timeout=args.timeout)
        response.raise_for_status()
        health = response.json()
    except Exception as exc:
        health_error = str(exc)

    if admin_token:
        try:
            response = requests.get(
                f"{service_url}/admin/runtime",
                headers={"X-Admin-Token": admin_token},
                timeout=args.timeout,
            )
            response.raise_for_status()
            runtime_info = response.json()
        except Exception as exc:
            runtime_error = str(exc)

    if args.check_auth:
        try:
            response = requests.get(
                f"{service_url}/search",
                params={"q": args.query, "num": 1},
                timeout=args.timeout,
            )
            search_auth_status = response.status_code
            if response.status_code != 401:
                search_auth_error = f"expected 401 for anonymous search, got {response.status_code}"
        except Exception as exc:
            search_auth_error = str(exc)

    report.update(
        {
            "health": health,
            "health_error": health_error,
            "runtime": runtime_info,
            "runtime_error": runtime_error,
            "anonymous_search_status": search_auth_status,
            "anonymous_search_error": search_auth_error,
        }
    )

    if include_diagnostics:
        bootstrap_files: list[str] = []
        bootstrap_error = ""
        commit_count = None
        commit_error = ""
        logs_excerpt = ""
        logs_error = ""

        try:
            bootstrap_files = sorted(
                path for path in api.list_repo_files(space_name, repo_type="space") if path.startswith("bootstrap/")
            )
        except Exception as exc:
            bootstrap_error = str(exc)

        try:
            commit_count = len(api.list_repo_commits(space_name, repo_type="space"))
        except Exception as exc:
            commit_error = str(exc)

        if admin_token:
            try:
                response = requests.get(
                    f"{service_url}/admin/logs",
                    params={"lines": args.lines},
                    headers={"X-Admin-Token": admin_token},
                    timeout=args.timeout,
                )
                response.raise_for_status()
                logs_excerpt = response.json().get("content", "")
            except Exception as exc:
                logs_error = str(exc)
        else:
            logs_error = "admin token not configured"

        report.update(
            {
                "bootstrap_files": bootstrap_files,
                "bootstrap_error": bootstrap_error,
                "commit_count": commit_count,
                "commit_error": commit_error,
                "logs_excerpt": logs_excerpt,
                "logs_error": logs_error,
            }
        )

    return report


def cmd_hf_check(args):
    print(json.dumps(_collect_hf_check_report(args), indent=2, ensure_ascii=False))


def cmd_hf_doctor(args):
    print(json.dumps(_collect_hf_check_report(args, include_diagnostics=True), indent=2, ensure_ascii=False))


def cmd_config_check(args):
    names = [args.name] if args.name else available_config_names()
    results = []
    for name in names:
        payload, path, state = _read_config_payload(name)
        entry = {
            "name": name,
            "path": path,
            "state": state,
            "valid": False,
            "errors": [],
        }
        if state == "missing":
            entry["errors"] = ["file does not exist"]
        else:
            entry["errors"] = validate_config_payload(name, payload)
            entry["valid"] = not entry["errors"]
        results.append(entry)
    print(json.dumps({"configs": results}, indent=2, ensure_ascii=False))


def cmd_config_init(args):
    config_dir = get_workspace_paths().config_dir
    config_dir.mkdir(parents=True, exist_ok=True)
    names = [args.name] if args.name else available_config_names()
    results = []
    for name in names:
        config_path = config_dir / f"{name}.json"
        existed_before = config_path.exists()
        action = "skipped"
        if args.force or not existed_before:
            config_path.write_text(render_config_template_json(name), encoding="utf-8")
            action = "updated" if existed_before else "written"
        results.append(
            {
                "name": name,
                "path": str(config_path),
                "action": action,
            }
        )
    print(json.dumps({"configs": results}, indent=2, ensure_ascii=False))


def cmd_config_schema(args):
    print(json.dumps(config_schema_json(args.name), indent=2, ensure_ascii=False))


def cmd_docs_sync(args):
    rendered_docs = {
        USAGE_DOC_PATH: render_usage_markdown(),
        SETUP_DOC_PATH: render_setup_markdown(),
        HINTS_DOC_PATH: render_hints_markdown(),
        CONFIGS_DOC_PATH: render_configs_markdown(),
    }
    for path, content in rendered_docs.items():
        path.write_text(content, encoding="utf-8")
    for path in rendered_docs:
        print(str(path))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=root_description(),
        epilog=root_epilog(),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    print_config = _add_command_parser(subparsers, "print-config", "Render resolved runtime config")
    print_config.set_defaults(func=cmd_print_config)

    serve = _add_command_parser(subparsers, "serve", "Run google_docker service in foreground")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=18000)
    serve.set_defaults(func=cmd_serve)

    docker_build = _add_command_parser(subparsers, "docker-build", "Build local docker image")
    docker_build.add_argument("--image", default="")
    docker_build.add_argument("--no-cache", action="store_true")
    docker_build.set_defaults(func=cmd_docker_build)

    docker_run = _add_command_parser(subparsers, "docker-run", "Run local docker container")
    docker_run.add_argument("--image", default="")
    docker_run.add_argument("--name", default="")
    docker_run.add_argument("--port", type=int, default=18000)
    docker_run.add_argument("--proxy-mode", choices=["auto", "enabled", "disabled"], default="auto")
    docker_run.add_argument("--bind-source", action="store_true")
    docker_run.add_argument("--mount-configs", action="store_true")
    docker_run.add_argument("--replace", action="store_true")
    docker_run.add_argument("--admin-token", default="")
    docker_run.set_defaults(func=cmd_docker_run)

    docker_stop = _add_command_parser(subparsers, "docker-stop", "Stop local docker container")
    docker_stop.add_argument("--name", default="")
    docker_stop.set_defaults(func=cmd_docker_stop)

    docker_logs = _add_command_parser(subparsers, "docker-logs", "Tail local docker logs")
    docker_logs.add_argument("--name", default="")
    docker_logs.add_argument("--lines", type=int, default=200)
    docker_logs.add_argument("--follow", action="store_true")
    docker_logs.set_defaults(func=cmd_docker_logs)

    docker_up = _add_command_parser(subparsers, "docker-up", "Build and run the local docker service with practical defaults")
    docker_up.add_argument("--image", default="")
    docker_up.add_argument("--name", default="")
    docker_up.add_argument("--port", type=int, default=18000)
    docker_up.add_argument("--proxy-mode", choices=["auto", "enabled", "disabled"], default="auto")
    docker_up.add_argument("--skip-build", action="store_true")
    docker_up.add_argument("--no-cache", action="store_true")
    docker_up.add_argument("--no-bind-source", action="store_true")
    docker_up.add_argument("--no-mount-configs", action="store_true")
    docker_up.add_argument("--admin-token", default="")
    docker_up.set_defaults(func=cmd_docker_up)

    docker_down = _add_command_parser(subparsers, "docker-down", "Stop and remove the local docker service")
    docker_down.add_argument("--name", default="")
    docker_down.set_defaults(func=cmd_docker_down)

    docker_check = _add_command_parser(subparsers, "docker-check", "Check local docker container and service health")
    docker_check.add_argument("--name", default="")
    docker_check.add_argument("--port", type=int, default=18000)
    docker_check.add_argument("--admin-token", default="")
    docker_check.add_argument("--timeout", type=int, default=15)
    docker_check.set_defaults(func=cmd_docker_check)

    hf_sync = _add_command_parser(subparsers, "hf-sync", "Upload current workspace to a Docker Space")
    hf_sync.add_argument("--space", default="")
    hf_sync.add_argument("--repo-id", default="")
    hf_sync.add_argument("--port", type=int, default=18000)
    hf_sync.add_argument("--message", default="")
    hf_sync.add_argument("--restart", action="store_true")
    hf_sync.add_argument("--factory", action="store_true")
    hf_sync.add_argument("--admin-token", default="")
    hf_sync.set_defaults(func=cmd_hf_sync)

    hf_status = _add_command_parser(subparsers, "hf-status", "Get HF Space runtime status")
    hf_status.add_argument("--space", default="")
    hf_status.set_defaults(func=cmd_hf_status)

    hf_restart = _add_command_parser(subparsers, "hf-restart", "Restart HF Space")
    hf_restart.add_argument("--space", default="")
    hf_restart.add_argument("--factory", action="store_true")
    hf_restart.set_defaults(func=cmd_hf_restart)

    hf_super_squash = _add_command_parser(subparsers, "hf-super-squash", "Super-squash HF Space commit history")
    hf_super_squash.add_argument("--space", default="")
    hf_super_squash.add_argument("--branch", default="main")
    hf_super_squash.set_defaults(func=cmd_hf_super_squash)

    hf_logs = _add_command_parser(subparsers, "hf-logs", "Read remote service logs from HF Space")
    hf_logs.add_argument("--space", default="")
    hf_logs.add_argument("--lines", type=int, default=200)
    hf_logs.add_argument("--admin-token", default="")
    hf_logs.set_defaults(func=cmd_hf_logs)

    hf_url = _add_command_parser(subparsers, "hf-url", "Print the resolved HF service URL")
    hf_url.set_defaults(func=cmd_hf_url)

    hf_health = _add_command_parser(subparsers, "hf-health", "Call remote /health")
    hf_health.add_argument("--timeout", type=int, default=30)
    hf_health.set_defaults(func=cmd_hf_health)

    hf_home = _add_command_parser(subparsers, "hf-home", "Call remote /")
    hf_home.add_argument("--timeout", type=int, default=30)
    hf_home.set_defaults(func=cmd_hf_home)

    hf_runtime = _add_command_parser(subparsers, "hf-runtime", "Call remote /admin/runtime")
    hf_runtime.add_argument("--admin-token", default="")
    hf_runtime.add_argument("--timeout", type=int, default=30)
    hf_runtime.set_defaults(func=cmd_hf_runtime)

    hf_search = _add_command_parser(subparsers, "hf-search", "Call remote /search")
    hf_search.add_argument("query")
    hf_search.add_argument("--num", type=int, default=3)
    hf_search.add_argument("--lang", default="en")
    hf_search.add_argument("--api-token", default="")
    hf_search.add_argument("--no-auth", action="store_true")
    hf_search.add_argument("--timeout", type=int, default=60)
    hf_search.set_defaults(func=cmd_hf_search)

    hf_files = _add_command_parser(subparsers, "hf-files", "List remote Space repository files")
    hf_files.add_argument("--space", default="")
    hf_files.add_argument("--prefix", default="")
    hf_files.set_defaults(func=cmd_hf_files)

    hf_commit_count = _add_command_parser(subparsers, "hf-commit-count", "Print remote Space commit count")
    hf_commit_count.add_argument("--space", default="")
    hf_commit_count.set_defaults(func=cmd_hf_commit_count)

    hf_check = _add_command_parser(subparsers, "hf-check", "Run a compact remote health and auth check")
    hf_check.add_argument("--space", default="")
    hf_check.add_argument("--admin-token", default="")
    hf_check.add_argument("--timeout", type=int, default=30)
    hf_check.add_argument("--query", default="OpenAI news")
    hf_check.add_argument("--check-auth", action="store_true")
    hf_check.set_defaults(func=cmd_hf_check)

    hf_doctor = _add_command_parser(subparsers, "hf-doctor", "Run a broader remote diagnosis with repo and log details")
    hf_doctor.add_argument("--space", default="")
    hf_doctor.add_argument("--admin-token", default="")
    hf_doctor.add_argument("--timeout", type=int, default=30)
    hf_doctor.add_argument("--query", default="OpenAI news")
    hf_doctor.add_argument("--check-auth", action="store_true")
    hf_doctor.add_argument("--lines", type=int, default=80)
    hf_doctor.set_defaults(func=cmd_hf_doctor)

    config_check = _add_command_parser(subparsers, "config-check", "Validate local configs against shared schema")
    config_check.add_argument("--name", choices=available_config_names(), default="")
    config_check.set_defaults(func=cmd_config_check)

    config_init = _add_command_parser(subparsers, "config-init", "Write minimal local config templates from shared schema")
    config_init.add_argument("--name", choices=available_config_names(), default="")
    config_init.add_argument("--force", action="store_true")
    config_init.set_defaults(func=cmd_config_init)

    config_schema = _add_command_parser(subparsers, "config-schema", "Print shared schema for one config file")
    config_schema.add_argument("name", choices=available_config_names())
    config_schema.set_defaults(func=cmd_config_schema)

    docs_sync = _add_command_parser(subparsers, "docs-sync", "Regenerate shared docs/google-docker markdown files")
    docs_sync.set_defaults(func=cmd_docs_sync)

    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())