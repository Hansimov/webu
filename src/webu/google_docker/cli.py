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

from webu.runtime_settings import (
    get_workspace_paths,
    load_json_config,
    resolve_captcha_vlm_settings,
    resolve_google_api_settings,
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


def _write_minimal_webu_init(package_root: Path):
    (package_root / "__init__.py").write_text(
        "__all__ = []\n",
        encoding="utf-8",
    )


def _run_command(command: list[str], check: bool = True):
    logger.note("> " + " ".join(command))
    return subprocess.run(command, check=check)


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


def prepare_space_bundle(source_root: Path, output_root: Path, app_port: int, repo_id: str) -> Path:
    bundle_root = output_root / "bundle"
    bundle_root.mkdir(parents=True, exist_ok=True)

    _write_sanitized_pyproject(source_root, bundle_root)

    license_path = source_root / "LICENSE"
    if license_path.exists():
        shutil.copy2(license_path, bundle_root / "LICENSE")

    shutil.copy2(DOCKERFILE_PATH, bundle_root / "Dockerfile")
    (bundle_root / "README.md").write_text(_space_readme(repo_id, app_port), encoding="utf-8")

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
            ignore=shutil.ignore_patterns(
                "__pycache__",
                "*.pyc",
                "*.pyo",
                "ipv6_global_addrs.json",
                "ipv6_mirrors",
            ),
        )
    return bundle_root


def _docker_env_args(env_map: dict[str, str]) -> list[str]:
    args = []
    for key, value in env_map.items():
        args.extend(["-e", f"{key}={value}"])
    return args


def _resolve_hf_api(space_name: str) -> tuple[HfApi, object]:
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
    }

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


def cmd_hf_sync(args):
    api, hf_settings = _resolve_hf_api(args.space)
    docker_settings = resolve_google_docker_settings()
    repo_id = args.repo_id or args.space

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
    api, hf_settings = _resolve_hf_api(args.space)
    runtime = api.get_space_runtime(repo_id=args.space)
    info = {
        "repo_id": args.space,
        "stage": str(runtime.stage),
        "hardware": runtime.hardware,
        "requested_hardware": runtime.requested_hardware,
        "sleep_time": runtime.sleep_time,
        "storage": runtime.storage,
        "space_host": hf_settings.space_host,
    }
    print(json.dumps(info, indent=2, ensure_ascii=False))


def cmd_hf_restart(args):
    _, hf_settings = _resolve_hf_api(args.space)
    used_endpoint = _restart_space_request(args.space, hf_settings.hf_token, factory_reboot=args.factory)
    logger.okay(f"  ✓ Restart requested for: {args.space} via {used_endpoint}")


def cmd_hf_super_squash(args):
    api, _ = _resolve_hf_api(args.space)
    _super_squash_space_history(api, args.space, branch=args.branch)
    logger.okay(f"  ✓ Super-squashed Space history for: {args.space} ({args.branch})")


def cmd_hf_logs(args):
    _, hf_settings = _resolve_hf_api(args.space)
    headers = {}
    if hf_settings.hf_token:
        headers["Authorization"] = f"Bearer {hf_settings.hf_token}"
    if args.admin_token:
        headers["X-Admin-Token"] = args.admin_token
    response = requests.get(
        f"{hf_settings.space_host}/admin/logs",
        params={"lines": args.lines},
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    print(response.json().get("content", ""))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage dockerized WebU google_api deployments")
    subparsers = parser.add_subparsers(dest="command")

    print_config = subparsers.add_parser("print-config", help="Render resolved runtime config")
    print_config.set_defaults(func=cmd_print_config)

    serve = subparsers.add_parser("serve", help="Run google_docker service in foreground")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=18000)
    serve.set_defaults(func=cmd_serve)

    docker_build = subparsers.add_parser("docker-build", help="Build local docker image")
    docker_build.add_argument("--image", default="")
    docker_build.add_argument("--no-cache", action="store_true")
    docker_build.set_defaults(func=cmd_docker_build)

    docker_run = subparsers.add_parser("docker-run", help="Run local docker container")
    docker_run.add_argument("--image", default="")
    docker_run.add_argument("--name", default="")
    docker_run.add_argument("--port", type=int, default=18000)
    docker_run.add_argument("--proxy-mode", choices=["auto", "enabled", "disabled"], default="auto")
    docker_run.add_argument("--bind-source", action="store_true")
    docker_run.add_argument("--mount-configs", action="store_true")
    docker_run.add_argument("--replace", action="store_true")
    docker_run.add_argument("--admin-token", default="")
    docker_run.set_defaults(func=cmd_docker_run)

    docker_stop = subparsers.add_parser("docker-stop", help="Stop local docker container")
    docker_stop.add_argument("--name", default="")
    docker_stop.set_defaults(func=cmd_docker_stop)

    docker_logs = subparsers.add_parser("docker-logs", help="Tail local docker logs")
    docker_logs.add_argument("--name", default="")
    docker_logs.add_argument("--lines", type=int, default=200)
    docker_logs.add_argument("--follow", action="store_true")
    docker_logs.set_defaults(func=cmd_docker_logs)

    hf_sync = subparsers.add_parser("hf-sync", help="Upload current workspace to a Docker Space")
    hf_sync.add_argument("--space", required=True)
    hf_sync.add_argument("--repo-id", default="")
    hf_sync.add_argument("--port", type=int, default=18000)
    hf_sync.add_argument("--message", default="")
    hf_sync.add_argument("--restart", action="store_true")
    hf_sync.add_argument("--factory", action="store_true")
    hf_sync.add_argument("--admin-token", default="")
    hf_sync.set_defaults(func=cmd_hf_sync)

    hf_status = subparsers.add_parser("hf-status", help="Get HF Space runtime status")
    hf_status.add_argument("--space", required=True)
    hf_status.set_defaults(func=cmd_hf_status)

    hf_restart = subparsers.add_parser("hf-restart", help="Restart HF Space")
    hf_restart.add_argument("--space", required=True)
    hf_restart.add_argument("--factory", action="store_true")
    hf_restart.set_defaults(func=cmd_hf_restart)

    hf_super_squash = subparsers.add_parser("hf-super-squash", help="Super-squash HF Space commit history")
    hf_super_squash.add_argument("--space", required=True)
    hf_super_squash.add_argument("--branch", default="main")
    hf_super_squash.set_defaults(func=cmd_hf_super_squash)

    hf_logs = subparsers.add_parser("hf-logs", help="Read remote service logs from HF Space")
    hf_logs.add_argument("--space", required=True)
    hf_logs.add_argument("--lines", type=int, default=200)
    hf_logs.add_argument("--admin-token", default="")
    hf_logs.set_defaults(func=cmd_hf_logs)

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