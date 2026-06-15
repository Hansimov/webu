from __future__ import annotations

import argparse
import json
import os
import sys

from pathlib import Path

from webu.clis import print_json

from .operations import (
    build_worker_script,
    config_check,
    config_init,
    config_schema_json,
    create_email_routing_token,
    deploy_worker,
    ensure_worker_rule,
    extract_verification_codes,
    parse_email_message,
    routing_plan,
)


def _add_runtime_path_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", default="")
    parser.add_argument("--config-dir", default="")


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


def cmd_plan(_args):
    print_json(routing_plan())


def cmd_ensure_worker_rule(args):
    print_json(ensure_worker_rule(dry_run=args.dry_run))


def cmd_token_create(args):
    print_json(
        create_email_routing_token(
            name=args.name,
            expires_in_days=None if args.no_expiry else args.expires_in_days,
            save_config=not args.no_save_config,
            dry_run=args.dry_run,
        )
    )


def cmd_worker_script(_args):
    print(build_worker_script())


def cmd_worker_deploy(args):
    print_json(deploy_worker(dry_run=args.dry_run))


def _read_message_arg(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def cmd_parse(args):
    print_json(parse_email_message(_read_message_arg(args.file)))


def cmd_extract_code(args):
    print_json(extract_verification_codes(_read_message_arg(args.file), code_regex=args.regex))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cfem", description="Cloudflare email helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_schema = subparsers.add_parser("config-schema")
    config_schema.set_defaults(func=cmd_config_schema)

    config_check_parser = subparsers.add_parser("config-check")
    _add_runtime_path_options(config_check_parser)
    config_check_parser.set_defaults(func=cmd_config_check)

    config_init_parser = subparsers.add_parser("config-init")
    _add_runtime_path_options(config_init_parser)
    config_init_parser.add_argument("--force", action="store_true")
    config_init_parser.set_defaults(func=cmd_config_init)

    plan_parser = subparsers.add_parser("plan")
    _add_runtime_path_options(plan_parser)
    plan_parser.set_defaults(func=cmd_plan)

    ensure_parser = subparsers.add_parser("ensure-worker-rule")
    _add_runtime_path_options(ensure_parser)
    ensure_parser.add_argument("--dry-run", action="store_true")
    ensure_parser.set_defaults(func=cmd_ensure_worker_rule)

    token_parser = subparsers.add_parser("token-create")
    _add_runtime_path_options(token_parser)
    token_parser.add_argument("--name", default="")
    token_parser.add_argument("--expires-in-days", type=int, default=30)
    token_parser.add_argument("--no-expiry", action="store_true")
    token_parser.add_argument("--no-save-config", action="store_true")
    token_parser.add_argument("--dry-run", action="store_true")
    token_parser.set_defaults(func=cmd_token_create)

    worker_parser = subparsers.add_parser("worker-script")
    _add_runtime_path_options(worker_parser)
    worker_parser.set_defaults(func=cmd_worker_script)

    worker_deploy_parser = subparsers.add_parser("worker-deploy")
    _add_runtime_path_options(worker_deploy_parser)
    worker_deploy_parser.add_argument("--dry-run", action="store_true")
    worker_deploy_parser.set_defaults(func=cmd_worker_deploy)

    parse_parser = subparsers.add_parser("parse")
    parse_parser.add_argument("file")
    parse_parser.set_defaults(func=cmd_parse)

    code_parser = subparsers.add_parser("extract-code")
    code_parser.add_argument("file")
    code_parser.add_argument("--regex", default="")
    code_parser.set_defaults(func=cmd_extract_code)
    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    _apply_runtime_path_overrides(args)
    return args.func(args)


if __name__ == "__main__":
    main()
