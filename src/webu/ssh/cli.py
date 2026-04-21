from __future__ import annotations

import argparse
import json
import os

from pathlib import Path

from webu.clis import print_json

from .operations import (
    config_check,
    config_init,
    config_schema_json,
    copy_from,
    copy_to,
    exec_host,
    host_list,
    host_upsert,
    probe_host,
    tunnel_command,
    tunnel_list,
    tunnel_service_disable,
    tunnel_service_install,
    tunnel_service_logs,
    tunnel_service_restart,
    tunnel_service_status,
    tunnel_upsert,
)
from .schema import (
    DEFAULT_SERVER_ALIVE_COUNT_MAX,
    DEFAULT_SERVER_ALIVE_INTERVAL_SECONDS,
    DEFAULT_SSH_PORT,
    DEFAULT_TUNNEL_LOCAL_HOST,
    DEFAULT_TUNNEL_MODE,
    DEFAULT_TUNNEL_REMOTE_HOST,
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
        help="Explicit directory containing webu JSON configs such as configs/ssh.json.",
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


def cmd_host_list(_args):
    print_json(host_list())


def cmd_host_upsert(args):
    print_json(
        host_upsert(
            name=args.name,
            ip=args.ip,
            hostname=args.hostname,
            port=args.port,
            username=args.username,
            password=args.password,
            identity_file=args.identity_file,
            notes=args.notes,
            save_config=args.save_config,
        )
    )


def cmd_probe(args):
    print_json(probe_host(name=args.name, timeout_seconds=args.timeout_seconds))


def cmd_exec(args):
    print_json(
        exec_host(
            name=args.name,
            command=args.command_text,
            timeout_seconds=args.timeout_seconds,
            allocate_tty=args.allocate_tty,
        )
    )


def cmd_copy_to(args):
    print_json(
        copy_to(
            name=args.name, local_path=args.local_path, remote_path=args.remote_path
        )
    )


def cmd_copy_from(args):
    print_json(
        copy_from(
            name=args.name, remote_path=args.remote_path, local_path=args.local_path
        )
    )


def cmd_tunnel_list(_args):
    print_json(tunnel_list())


def cmd_tunnel_upsert(args):
    enabled = None
    if args.enable:
        enabled = True
    elif args.disable:
        enabled = False
    print_json(
        tunnel_upsert(
            name=args.name,
            host_name=args.host_name,
            mode=args.mode,
            local_host=args.local_host,
            local_port=args.local_port,
            remote_host=args.remote_host,
            remote_port=args.remote_port,
            enabled=enabled,
            server_alive_interval_seconds=args.server_alive_interval_seconds,
            server_alive_count_max=args.server_alive_count_max,
            service_name=args.service_name,
            notes=args.notes,
            save_config=args.save_config,
        )
    )


def cmd_tunnel_command(args):
    print_json(tunnel_command(name=args.name))


def cmd_tunnel_service_install(args):
    print_json(
        tunnel_service_install(name=args.name, use_user_systemd=args.use_user_systemd)
    )


def cmd_tunnel_service_status(args):
    print_json(
        tunnel_service_status(name=args.name, use_user_systemd=args.use_user_systemd)
    )


def cmd_tunnel_service_logs(args):
    print_json(
        tunnel_service_logs(
            name=args.name, lines=args.lines, use_user_systemd=args.use_user_systemd
        )
    )


def cmd_tunnel_service_restart(args):
    print_json(
        tunnel_service_restart(name=args.name, use_user_systemd=args.use_user_systemd)
    )


def cmd_tunnel_service_disable(args):
    print_json(
        tunnel_service_disable(
            name=args.name,
            purge_unit_file=args.purge_unit_file,
            use_user_systemd=args.use_user_systemd,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wssh",
        description="Manage remote SSH hosts, commands, files, and SSH tunnel services for webu.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_schema_parser = subparsers.add_parser(
        "config-schema", help="Print the ssh shared schema."
    )
    _add_runtime_path_options(config_schema_parser)
    config_schema_parser.set_defaults(func=cmd_config_schema)

    config_check_parser = subparsers.add_parser(
        "config-check", help="Validate configs/ssh.json."
    )
    _add_runtime_path_options(config_check_parser)
    config_check_parser.set_defaults(func=cmd_config_check)

    config_init_parser = subparsers.add_parser(
        "config-init", help="Write a minimal ssh config skeleton."
    )
    config_init_parser.add_argument("--force", action="store_true")
    _add_runtime_path_options(config_init_parser)
    config_init_parser.set_defaults(func=cmd_config_init)

    host_list_parser = subparsers.add_parser(
        "host-list", help="List configured ssh hosts."
    )
    _add_runtime_path_options(host_list_parser)
    host_list_parser.set_defaults(func=cmd_host_list)

    host_upsert_parser = subparsers.add_parser(
        "host-upsert", help="Create or update an ssh host entry in configs/ssh.json."
    )
    host_upsert_parser.add_argument("--name", required=True)
    host_upsert_parser.add_argument("--ip", default="")
    host_upsert_parser.add_argument("--hostname", default="")
    host_upsert_parser.add_argument("--port", type=int, default=DEFAULT_SSH_PORT)
    host_upsert_parser.add_argument("--username", required=True)
    host_upsert_parser.add_argument("--password", default="")
    host_upsert_parser.add_argument("--identity-file", default="")
    host_upsert_parser.add_argument("--notes", default="")
    host_upsert_parser.add_argument("--save-config", action="store_true")
    _add_runtime_path_options(host_upsert_parser)
    host_upsert_parser.set_defaults(func=cmd_host_upsert)

    probe_parser = subparsers.add_parser(
        "probe", help="Run a minimal SSH probe against a configured host."
    )
    probe_parser.add_argument("--name", required=True)
    probe_parser.add_argument("--timeout-seconds", type=int, default=15)
    _add_runtime_path_options(probe_parser)
    probe_parser.set_defaults(func=cmd_probe)

    exec_parser = subparsers.add_parser(
        "exec", help="Execute a shell command on a configured host over SSH."
    )
    exec_parser.add_argument("--name", required=True)
    exec_parser.add_argument("--command-text", required=True)
    exec_parser.add_argument("--timeout-seconds", type=int, default=60)
    exec_parser.add_argument("--allocate-tty", action="store_true")
    _add_runtime_path_options(exec_parser)
    exec_parser.set_defaults(func=cmd_exec)

    copy_to_parser = subparsers.add_parser(
        "copy-to", help="Copy a local file or directory to a configured host with scp."
    )
    copy_to_parser.add_argument("--name", required=True)
    copy_to_parser.add_argument("--local-path", required=True)
    copy_to_parser.add_argument("--remote-path", required=True)
    _add_runtime_path_options(copy_to_parser)
    copy_to_parser.set_defaults(func=cmd_copy_to)

    copy_from_parser = subparsers.add_parser(
        "copy-from",
        help="Copy a remote file or directory from a configured host with scp.",
    )
    copy_from_parser.add_argument("--name", required=True)
    copy_from_parser.add_argument("--remote-path", required=True)
    copy_from_parser.add_argument("--local-path", required=True)
    _add_runtime_path_options(copy_from_parser)
    copy_from_parser.set_defaults(func=cmd_copy_from)

    tunnel_list_parser = subparsers.add_parser(
        "tunnel-list", help="List configured SSH tunnels."
    )
    _add_runtime_path_options(tunnel_list_parser)
    tunnel_list_parser.set_defaults(func=cmd_tunnel_list)

    tunnel_upsert_parser = subparsers.add_parser(
        "tunnel-upsert",
        help="Create or update an SSH tunnel definition in configs/ssh.json.",
    )
    tunnel_upsert_parser.add_argument("--name", required=True)
    tunnel_upsert_parser.add_argument("--host-name", required=True)
    tunnel_upsert_parser.add_argument(
        "--mode", choices=["remote", "local"], default=DEFAULT_TUNNEL_MODE
    )
    tunnel_upsert_parser.add_argument("--local-host", default=DEFAULT_TUNNEL_LOCAL_HOST)
    tunnel_upsert_parser.add_argument("--local-port", type=int, required=True)
    tunnel_upsert_parser.add_argument(
        "--remote-host", default=DEFAULT_TUNNEL_REMOTE_HOST
    )
    tunnel_upsert_parser.add_argument("--remote-port", type=int, required=True)
    tunnel_upsert_parser.add_argument(
        "--server-alive-interval-seconds",
        type=int,
        default=DEFAULT_SERVER_ALIVE_INTERVAL_SECONDS,
    )
    tunnel_upsert_parser.add_argument(
        "--server-alive-count-max", type=int, default=DEFAULT_SERVER_ALIVE_COUNT_MAX
    )
    tunnel_upsert_parser.add_argument("--service-name", default="")
    tunnel_upsert_parser.add_argument("--notes", default="")
    tunnel_upsert_parser.add_argument("--enable", action="store_true")
    tunnel_upsert_parser.add_argument("--disable", action="store_true")
    tunnel_upsert_parser.add_argument("--save-config", action="store_true")
    _add_runtime_path_options(tunnel_upsert_parser)
    tunnel_upsert_parser.set_defaults(func=cmd_tunnel_upsert)

    tunnel_command_parser = subparsers.add_parser(
        "tunnel-command", help="Render the ssh command for a configured tunnel."
    )
    tunnel_command_parser.add_argument("--name", required=True)
    _add_runtime_path_options(tunnel_command_parser)
    tunnel_command_parser.set_defaults(func=cmd_tunnel_command)

    tunnel_service_install_parser = subparsers.add_parser(
        "tunnel-service-install",
        help="Install and start a systemd service for a configured SSH tunnel.",
    )
    tunnel_service_install_parser.add_argument("--name", required=True)
    tunnel_service_install_parser.add_argument(
        "--user", dest="use_user_systemd", action="store_true"
    )
    _add_runtime_path_options(tunnel_service_install_parser)
    tunnel_service_install_parser.set_defaults(func=cmd_tunnel_service_install)

    tunnel_service_status_parser = subparsers.add_parser(
        "tunnel-service-status",
        help="Show systemd status for a configured SSH tunnel service.",
    )
    tunnel_service_status_parser.add_argument("--name", required=True)
    tunnel_service_status_parser.add_argument(
        "--user", dest="use_user_systemd", action="store_true"
    )
    _add_runtime_path_options(tunnel_service_status_parser)
    tunnel_service_status_parser.set_defaults(func=cmd_tunnel_service_status)

    tunnel_service_logs_parser = subparsers.add_parser(
        "tunnel-service-logs",
        help="Show recent journalctl logs for a configured SSH tunnel service.",
    )
    tunnel_service_logs_parser.add_argument("--name", required=True)
    tunnel_service_logs_parser.add_argument("--lines", type=int, default=100)
    tunnel_service_logs_parser.add_argument(
        "--user", dest="use_user_systemd", action="store_true"
    )
    _add_runtime_path_options(tunnel_service_logs_parser)
    tunnel_service_logs_parser.set_defaults(func=cmd_tunnel_service_logs)

    tunnel_service_restart_parser = subparsers.add_parser(
        "tunnel-service-restart", help="Restart a configured SSH tunnel service."
    )
    tunnel_service_restart_parser.add_argument("--name", required=True)
    tunnel_service_restart_parser.add_argument(
        "--user", dest="use_user_systemd", action="store_true"
    )
    _add_runtime_path_options(tunnel_service_restart_parser)
    tunnel_service_restart_parser.set_defaults(func=cmd_tunnel_service_restart)

    tunnel_service_disable_parser = subparsers.add_parser(
        "tunnel-service-disable",
        help="Stop and disable a configured SSH tunnel service.",
    )
    tunnel_service_disable_parser.add_argument("--name", required=True)
    tunnel_service_disable_parser.add_argument("--purge-unit-file", action="store_true")
    tunnel_service_disable_parser.add_argument(
        "--user", dest="use_user_systemd", action="store_true"
    )
    _add_runtime_path_options(tunnel_service_disable_parser)
    tunnel_service_disable_parser.set_defaults(func=cmd_tunnel_service_disable)

    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    _apply_runtime_path_overrides(args)
    args.func(args)


if __name__ == "__main__":
    main()
