from __future__ import annotations

import argparse
import json
import os

from pathlib import Path

from webu.clis import print_json

from .operations import (
    client_list,
    client_prepare,
    client_render,
    client_run_once,
    client_service_disable,
    client_service_install,
    client_service_logs,
    client_service_restart,
    client_service_status,
    client_upsert,
    config_check,
    config_init,
    config_schema_json,
    server_deploy,
    server_disable,
    server_list,
    server_logs,
    server_render,
    server_restart,
    server_status,
    server_upsert,
)
from .schema import (
    DEFAULT_FRPC_BINARY,
    DEFAULT_FRPC_LOCAL_HOST,
    DEFAULT_FRP_PROTOCOL,
    DEFAULT_FRPS_BIND_PORT,
    DEFAULT_PROXY_BIND_ADDR,
)


def _add_runtime_path_options(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--project-root",
        default="",
        help="Explicit webu project root used to resolve relative paths and project-local outputs.",
    )
    parser.add_argument(
        "--config-dir",
        default="",
        help="Explicit directory containing webu JSON configs such as configs/frp.json.",
    )


def _apply_runtime_path_overrides(args) -> None:
    project_root = str(getattr(args, "project_root", "") or "").strip()
    config_dir = str(getattr(args, "config_dir", "") or "").strip()

    if project_root:
        os.environ["WEBU_PROJECT_ROOT"] = str(Path(project_root).expanduser().resolve())
    if config_dir:
        os.environ["WEBU_CONFIG_DIR"] = str(Path(config_dir).expanduser().resolve())


def cmd_config_schema(_args):
    print(json.dumps(config_schema_json(), indent=2, ensure_ascii=False))


def cmd_config_check(_args):
    errors = config_check()
    if errors:
        raise SystemExit("; ".join(errors))
    print("config ok")


def cmd_config_init(args):
    print(config_init(force=args.force))


def cmd_server_list(_args):
    print_json(server_list())


def cmd_server_upsert(args):
    print_json(
        server_upsert(
            name=args.name,
            ssh_host_name=args.ssh_host_name,
            bind_port=args.bind_port,
            proxy_bind_addr=args.proxy_bind_addr,
            auth_token=args.auth_token,
            remote_binary_path=args.remote_binary_path,
            remote_config_path=args.remote_config_path,
            remote_service_name=args.remote_service_name,
            notes=args.notes,
            save_config=args.save_config,
        )
    )


def cmd_server_render(args):
    print_json(server_render(name=args.name))


def cmd_server_deploy(args):
    print_json(server_deploy(name=args.name, install_service=args.install_service))


def cmd_server_status(args):
    print_json(server_status(name=args.name))


def cmd_server_logs(args):
    print_json(server_logs(name=args.name, lines=args.lines))


def cmd_server_restart(args):
    print_json(server_restart(name=args.name))


def cmd_server_disable(args):
    print_json(server_disable(name=args.name, purge_unit_file=args.purge_unit_file))


def cmd_client_list(_args):
    print_json(client_list())


def cmd_client_upsert(args):
    enabled = None
    if args.enable:
        enabled = True
    elif args.disable:
        enabled = False
    print_json(
        client_upsert(
            name=args.name,
            server_name=args.server_name,
            server_addr=args.server_addr,
            server_port=args.server_port,
            auth_token=args.auth_token,
            protocol=args.protocol,
            local_host=args.local_host,
            local_port=args.local_port,
            remote_port=args.remote_port,
            binary_path=args.binary_path,
            config_path=args.config_path,
            service_name=args.service_name,
            enabled=enabled,
            notes=args.notes,
            save_config=args.save_config,
        )
    )


def cmd_client_render(args):
    print_json(client_render(name=args.name))


def cmd_client_prepare(args):
    print_json(client_prepare(name=args.name))


def cmd_client_run_once(args):
    print_json(client_run_once(name=args.name, timeout_seconds=args.timeout_seconds))


def cmd_client_service_install(args):
    print_json(client_service_install(name=args.name))


def cmd_client_service_status(args):
    print_json(client_service_status(name=args.name))


def cmd_client_service_logs(args):
    print_json(client_service_logs(name=args.name, lines=args.lines))


def cmd_client_service_restart(args):
    print_json(client_service_restart(name=args.name))


def cmd_client_service_disable(args):
    print_json(
        client_service_disable(name=args.name, purge_unit_file=args.purge_unit_file)
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wfrp",
        description="Manage frps/frpc configs, remote deployment, and local frpc services for webu.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_schema_parser = subparsers.add_parser(
        "config-schema", help="Print the frp shared schema."
    )
    _add_runtime_path_options(config_schema_parser)
    config_schema_parser.set_defaults(func=cmd_config_schema)

    config_check_parser = subparsers.add_parser(
        "config-check", help="Validate configs/frp.json."
    )
    _add_runtime_path_options(config_check_parser)
    config_check_parser.set_defaults(func=cmd_config_check)

    config_init_parser = subparsers.add_parser(
        "config-init", help="Write a minimal frp config skeleton."
    )
    config_init_parser.add_argument("--force", action="store_true")
    _add_runtime_path_options(config_init_parser)
    config_init_parser.set_defaults(func=cmd_config_init)

    server_list_parser = subparsers.add_parser(
        "server-list", help="List configured frps servers."
    )
    _add_runtime_path_options(server_list_parser)
    server_list_parser.set_defaults(func=cmd_server_list)

    server_upsert_parser = subparsers.add_parser(
        "server-upsert",
        help="Create or update an frps server definition in configs/frp.json.",
    )
    server_upsert_parser.add_argument("--name", required=True)
    server_upsert_parser.add_argument("--ssh-host-name", required=True)
    server_upsert_parser.add_argument(
        "--bind-port", type=int, default=DEFAULT_FRPS_BIND_PORT
    )
    server_upsert_parser.add_argument(
        "--proxy-bind-addr", default=DEFAULT_PROXY_BIND_ADDR
    )
    server_upsert_parser.add_argument("--auth-token", required=True)
    server_upsert_parser.add_argument("--remote-binary-path", required=True)
    server_upsert_parser.add_argument("--remote-config-path", required=True)
    server_upsert_parser.add_argument("--remote-service-name", default="")
    server_upsert_parser.add_argument("--notes", default="")
    server_upsert_parser.add_argument("--save-config", action="store_true")
    _add_runtime_path_options(server_upsert_parser)
    server_upsert_parser.set_defaults(func=cmd_server_upsert)

    server_render_parser = subparsers.add_parser(
        "server-render", help="Render the frps TOML for a configured server."
    )
    server_render_parser.add_argument("--name", required=True)
    _add_runtime_path_options(server_render_parser)
    server_render_parser.set_defaults(func=cmd_server_render)

    server_deploy_parser = subparsers.add_parser(
        "server-deploy",
        help="Upload a rendered frps config to the remote ssh host and optionally install a remote service.",
    )
    server_deploy_parser.add_argument("--name", required=True)
    server_deploy_parser.add_argument("--install-service", action="store_true")
    _add_runtime_path_options(server_deploy_parser)
    server_deploy_parser.set_defaults(func=cmd_server_deploy)

    server_status_parser = subparsers.add_parser(
        "server-status",
        help="Show remote systemd status for a configured frps service.",
    )
    server_status_parser.add_argument("--name", required=True)
    _add_runtime_path_options(server_status_parser)
    server_status_parser.set_defaults(func=cmd_server_status)

    server_logs_parser = subparsers.add_parser(
        "server-logs",
        help="Show recent remote journalctl logs for a configured frps service.",
    )
    server_logs_parser.add_argument("--name", required=True)
    server_logs_parser.add_argument("--lines", type=int, default=100)
    _add_runtime_path_options(server_logs_parser)
    server_logs_parser.set_defaults(func=cmd_server_logs)

    server_restart_parser = subparsers.add_parser(
        "server-restart", help="Restart a configured remote frps service."
    )
    server_restart_parser.add_argument("--name", required=True)
    _add_runtime_path_options(server_restart_parser)
    server_restart_parser.set_defaults(func=cmd_server_restart)

    server_disable_parser = subparsers.add_parser(
        "server-disable", help="Stop and disable a configured remote frps service."
    )
    server_disable_parser.add_argument("--name", required=True)
    server_disable_parser.add_argument("--purge-unit-file", action="store_true")
    _add_runtime_path_options(server_disable_parser)
    server_disable_parser.set_defaults(func=cmd_server_disable)

    client_list_parser = subparsers.add_parser(
        "client-list", help="List configured frpc clients."
    )
    _add_runtime_path_options(client_list_parser)
    client_list_parser.set_defaults(func=cmd_client_list)

    client_upsert_parser = subparsers.add_parser(
        "client-upsert",
        help="Create or update an frpc client definition in configs/frp.json.",
    )
    client_upsert_parser.add_argument("--name", required=True)
    client_upsert_parser.add_argument("--server-name", required=True)
    client_upsert_parser.add_argument("--server-addr", default="")
    client_upsert_parser.add_argument(
        "--server-port", type=int, default=DEFAULT_FRPS_BIND_PORT
    )
    client_upsert_parser.add_argument("--auth-token", default="")
    client_upsert_parser.add_argument(
        "--protocol", choices=["tcp"], default=DEFAULT_FRP_PROTOCOL
    )
    client_upsert_parser.add_argument("--local-host", default=DEFAULT_FRPC_LOCAL_HOST)
    client_upsert_parser.add_argument("--local-port", type=int, required=True)
    client_upsert_parser.add_argument("--remote-port", type=int, required=True)
    client_upsert_parser.add_argument("--binary-path", default=DEFAULT_FRPC_BINARY)
    client_upsert_parser.add_argument("--config-path", default="")
    client_upsert_parser.add_argument("--service-name", default="")
    client_upsert_parser.add_argument("--notes", default="")
    client_upsert_parser.add_argument("--enable", action="store_true")
    client_upsert_parser.add_argument("--disable", action="store_true")
    client_upsert_parser.add_argument("--save-config", action="store_true")
    _add_runtime_path_options(client_upsert_parser)
    client_upsert_parser.set_defaults(func=cmd_client_upsert)

    client_render_parser = subparsers.add_parser(
        "client-render", help="Render the frpc TOML for a configured client."
    )
    client_render_parser.add_argument("--name", required=True)
    _add_runtime_path_options(client_render_parser)
    client_render_parser.set_defaults(func=cmd_client_render)

    client_prepare_parser = subparsers.add_parser(
        "client-prepare", help="Write the frpc TOML for a configured client to disk."
    )
    client_prepare_parser.add_argument("--name", required=True)
    _add_runtime_path_options(client_prepare_parser)
    client_prepare_parser.set_defaults(func=cmd_client_prepare)

    client_run_once_parser = subparsers.add_parser(
        "client-run-once", help="Run frpc once for a configured client."
    )
    client_run_once_parser.add_argument("--name", required=True)
    client_run_once_parser.add_argument("--timeout-seconds", type=int, default=15)
    _add_runtime_path_options(client_run_once_parser)
    client_run_once_parser.set_defaults(func=cmd_client_run_once)

    client_service_install_parser = subparsers.add_parser(
        "client-service-install",
        help="Install and start a local systemd service for a configured frpc client.",
    )
    client_service_install_parser.add_argument("--name", required=True)
    _add_runtime_path_options(client_service_install_parser)
    client_service_install_parser.set_defaults(func=cmd_client_service_install)

    client_service_status_parser = subparsers.add_parser(
        "client-service-status",
        help="Show local systemd status for a configured frpc client service.",
    )
    client_service_status_parser.add_argument("--name", required=True)
    _add_runtime_path_options(client_service_status_parser)
    client_service_status_parser.set_defaults(func=cmd_client_service_status)

    client_service_logs_parser = subparsers.add_parser(
        "client-service-logs",
        help="Show recent local journalctl logs for a configured frpc client service.",
    )
    client_service_logs_parser.add_argument("--name", required=True)
    client_service_logs_parser.add_argument("--lines", type=int, default=100)
    _add_runtime_path_options(client_service_logs_parser)
    client_service_logs_parser.set_defaults(func=cmd_client_service_logs)

    client_service_restart_parser = subparsers.add_parser(
        "client-service-restart", help="Restart a configured frpc client service."
    )
    client_service_restart_parser.add_argument("--name", required=True)
    _add_runtime_path_options(client_service_restart_parser)
    client_service_restart_parser.set_defaults(func=cmd_client_service_restart)

    client_service_disable_parser = subparsers.add_parser(
        "client-service-disable",
        help="Stop and disable a configured frpc client service.",
    )
    client_service_disable_parser.add_argument("--name", required=True)
    client_service_disable_parser.add_argument("--purge-unit-file", action="store_true")
    _add_runtime_path_options(client_service_disable_parser)
    client_service_disable_parser.set_defaults(func=cmd_client_service_disable)

    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    _apply_runtime_path_overrides(args)
    args.func(args)


if __name__ == "__main__":
    main()
