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
    service_disable,
    service_install,
    service_logs,
    service_restart,
    service_status,
    target_delete,
    target_list,
    target_prepare,
    target_run_once,
    target_upsert,
)
from .schema import (
    DEFAULT_CACHE_TIMES,
    DEFAULT_RUN_INTERVAL_SECONDS,
    DEFAULT_TARGET_SEED_IPV6,
    DEFAULT_TARGET_TTL,
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
        help="Explicit directory containing webu JSON configs such as configs/ddns.json.",
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


def cmd_target_list(_args):
    print_json(target_list())


def cmd_target_upsert(args):
    enabled = None
    if args.enable:
        enabled = True
    elif args.disable:
        enabled = False
    print_json(
        target_upsert(
            name=args.name,
            site_name=args.site_name,
            pool_name=args.pool_name,
            origin_name=args.origin_name,
            record_name=args.record_name,
            provider=args.provider,
            enabled=enabled,
            target_ipv6=args.target_ipv6,
            seed_ipv6=args.seed_ipv6,
            ipv6_source_mode=args.ipv6_source_mode,
            ipv6_url=args.ipv6_url,
            ttl=args.ttl,
            binary_path=args.binary_path,
            config_path=args.config_path,
            run_interval_seconds=args.run_interval_seconds,
            cache_times=args.cache_times,
            service_name=args.service_name,
            save_config=args.save_config,
        )
    )


def cmd_target_prepare(args):
    print_json(target_prepare(name=args.name, seed_existing=args.seed_existing))


def cmd_target_delete(args):
    print_json(target_delete(name=args.name, save_config=(not args.no_save_config)))


def cmd_target_run_once(args):
    print_json(
        target_run_once(
            name=args.name,
            seed_existing=args.seed_existing,
            timeout_seconds=args.timeout_seconds,
        )
    )


def cmd_service_install(args):
    print_json(service_install(name=args.name, seed_existing=args.seed_existing))


def cmd_service_status(args):
    print_json(service_status(name=args.name))


def cmd_service_logs(args):
    print_json(service_logs(name=args.name, lines=args.lines))


def cmd_service_restart(args):
    print_json(service_restart(name=args.name, seed_existing=args.seed_existing))


def cmd_service_disable(args):
    print_json(service_disable(name=args.name, purge_unit_file=args.purge_unit_file))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wdns",
        description="Manage ddns-go targets and services for webu.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_schema_parser = subparsers.add_parser(
        "config-schema",
        help="Print the ddns shared schema.",
    )
    _add_runtime_path_options(config_schema_parser)
    config_schema_parser.set_defaults(func=cmd_config_schema)

    config_check_parser = subparsers.add_parser(
        "config-check",
        help="Validate configs/ddns.json.",
    )
    _add_runtime_path_options(config_check_parser)
    config_check_parser.set_defaults(func=cmd_config_check)

    config_init_parser = subparsers.add_parser(
        "config-init",
        help="Write a minimal ddns config skeleton.",
    )
    config_init_parser.add_argument("--force", action="store_true")
    _add_runtime_path_options(config_init_parser)
    config_init_parser.set_defaults(func=cmd_config_init)

    target_list_parser = subparsers.add_parser(
        "target-list",
        help="List configured ddns targets.",
    )
    _add_runtime_path_options(target_list_parser)
    target_list_parser.set_defaults(func=cmd_target_list)

    target_upsert_parser = subparsers.add_parser(
        "target-upsert",
        help="Create or update a ddns target in configs/ddns.json.",
    )
    target_upsert_parser.add_argument("--name", required=True)
    target_upsert_parser.add_argument(
        "--provider",
        choices=["aliesa-origin-pool", "aliesa-record"],
        default="aliesa-origin-pool",
    )
    target_upsert_parser.add_argument("--site-name", required=True)
    target_upsert_parser.add_argument("--pool-name", default="")
    target_upsert_parser.add_argument("--origin-name", default="")
    target_upsert_parser.add_argument("--record-name", default="")
    target_upsert_parser.add_argument("--target-ipv6", default="")
    target_upsert_parser.add_argument("--seed-ipv6", default=DEFAULT_TARGET_SEED_IPV6)
    target_upsert_parser.add_argument(
        "--ipv6-source-mode",
        choices=["cmd", "url"],
        default="cmd",
    )
    target_upsert_parser.add_argument("--ipv6-url", default="https://api6.ipify.org")
    target_upsert_parser.add_argument("--ttl", type=int, default=DEFAULT_TARGET_TTL)
    target_upsert_parser.add_argument("--binary-path", default="")
    target_upsert_parser.add_argument("--config-path", default="")
    target_upsert_parser.add_argument(
        "--run-interval-seconds",
        type=int,
        default=DEFAULT_RUN_INTERVAL_SECONDS,
    )
    target_upsert_parser.add_argument(
        "--cache-times", type=int, default=DEFAULT_CACHE_TIMES
    )
    target_upsert_parser.add_argument("--service-name", default="")
    target_upsert_parser.add_argument("--enable", action="store_true")
    target_upsert_parser.add_argument("--disable", action="store_true")
    target_upsert_parser.add_argument("--save-config", action="store_true")
    _add_runtime_path_options(target_upsert_parser)
    target_upsert_parser.set_defaults(func=cmd_target_upsert)

    target_prepare_parser = subparsers.add_parser(
        "target-prepare",
        help="Prepare a DDNS target in ESA when needed and write the ddns-go config for it.",
    )
    target_prepare_parser.add_argument("--name", required=True)
    target_prepare_parser.add_argument("--seed-existing", action="store_true")
    _add_runtime_path_options(target_prepare_parser)
    target_prepare_parser.set_defaults(func=cmd_target_prepare)

    target_delete_parser = subparsers.add_parser(
        "target-delete",
        help="Remove a ddns target from configs/ddns.json.",
    )
    target_delete_parser.add_argument("--name", required=True)
    target_delete_parser.add_argument("--no-save-config", action="store_true")
    _add_runtime_path_options(target_delete_parser)
    target_delete_parser.set_defaults(func=cmd_target_delete)

    target_run_once_parser = subparsers.add_parser(
        "target-run-once",
        help="Run ddns-go once for a target and verify the corresponding ESA state afterwards.",
    )
    target_run_once_parser.add_argument("--name", required=True)
    target_run_once_parser.add_argument("--seed-existing", action="store_true")
    target_run_once_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=15,
    )
    _add_runtime_path_options(target_run_once_parser)
    target_run_once_parser.set_defaults(func=cmd_target_run_once)

    service_install_parser = subparsers.add_parser(
        "service-install",
        help="Install and start a systemd service for a ddns target.",
    )
    service_install_parser.add_argument("--name", required=True)
    service_install_parser.add_argument("--seed-existing", action="store_true")
    _add_runtime_path_options(service_install_parser)
    service_install_parser.set_defaults(func=cmd_service_install)

    service_status_parser = subparsers.add_parser(
        "service-status",
        help="Show systemd status for a ddns target service.",
    )
    service_status_parser.add_argument("--name", required=True)
    _add_runtime_path_options(service_status_parser)
    service_status_parser.set_defaults(func=cmd_service_status)

    service_logs_parser = subparsers.add_parser(
        "service-logs",
        help="Show recent journalctl logs for a ddns target service.",
    )
    service_logs_parser.add_argument("--name", required=True)
    service_logs_parser.add_argument("--lines", type=int, default=100)
    _add_runtime_path_options(service_logs_parser)
    service_logs_parser.set_defaults(func=cmd_service_logs)

    service_restart_parser = subparsers.add_parser(
        "service-restart",
        help="Restart a ddns target service.",
    )
    service_restart_parser.add_argument("--name", required=True)
    service_restart_parser.add_argument("--seed-existing", action="store_true")
    _add_runtime_path_options(service_restart_parser)
    service_restart_parser.set_defaults(func=cmd_service_restart)

    service_disable_parser = subparsers.add_parser(
        "service-disable",
        help="Stop and disable a ddns target service.",
    )
    service_disable_parser.add_argument("--name", required=True)
    service_disable_parser.add_argument("--purge-unit-file", action="store_true")
    _add_runtime_path_options(service_disable_parser)
    service_disable_parser.set_defaults(func=cmd_service_disable)

    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    _apply_runtime_path_overrides(args)
    args.func(args)


if __name__ == "__main__":
    main()
