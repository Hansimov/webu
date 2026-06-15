from __future__ import annotations

import argparse
import json
import os

from pathlib import Path

from webu.clis import print_json

from .operations import (
    check_sender_domain,
    config_check,
    config_init,
    config_schema_json,
    create_sender_address,
    create_sender_domain,
    describe_sender_domain,
    query_sender_addresses,
    query_sender_domains,
    send_verification_code,
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


def cmd_send_code(args):
    print_json(
        send_verification_code(
            to_address=args.to,
            code=args.code,
            purpose=args.purpose,
            ttl_minutes=args.ttl_minutes,
            product_name=args.product_name,
            dry_run=args.dry_run,
        )
    )


def cmd_create_sender(args):
    print_json(
        create_sender_address(
            account_name=args.account_name,
            sendtype=args.sendtype,
            reply_address=args.reply_address,
            dry_run=args.dry_run,
        )
    )


def cmd_sender_list(args):
    print_json(
        query_sender_addresses(
            key_word=args.keyword,
            page_no=args.page_no,
            page_size=args.page_size,
            sendtype=args.sendtype,
        )
    )


def cmd_domain_create(args):
    print_json(
        create_sender_domain(
            domain_name=args.domain_name,
            dkim_selector=args.dkim_selector,
            dry_run=args.dry_run,
        )
    )


def cmd_domain_list(args):
    print_json(
        query_sender_domains(
            key_word=args.keyword,
            page_no=args.page_no,
            page_size=args.page_size,
            status=args.status,
        )
    )


def cmd_domain_desc(args):
    print_json(describe_sender_domain(domain_id=args.domain_id))


def cmd_domain_check(args):
    print_json(check_sender_domain(domain_id=args.domain_id))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alem", description="Aliyun email helper")
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

    send_parser = subparsers.add_parser("send-code")
    _add_runtime_path_options(send_parser)
    send_parser.add_argument("--to", required=True)
    send_parser.add_argument("--code", required=True)
    send_parser.add_argument("--purpose", default="register")
    send_parser.add_argument("--ttl-minutes", type=int, default=10)
    send_parser.add_argument("--product-name", default="Account")
    send_parser.add_argument("--dry-run", action="store_true")
    send_parser.set_defaults(func=cmd_send_code)

    create_sender_parser = subparsers.add_parser("create-sender")
    _add_runtime_path_options(create_sender_parser)
    create_sender_parser.add_argument("--account-name", default="")
    create_sender_parser.add_argument("--sendtype", default="trigger", choices=["batch", "trigger"])
    create_sender_parser.add_argument("--reply-address", default="")
    create_sender_parser.add_argument("--dry-run", action="store_true")
    create_sender_parser.set_defaults(func=cmd_create_sender)

    sender_list_parser = subparsers.add_parser("sender-list")
    _add_runtime_path_options(sender_list_parser)
    sender_list_parser.add_argument("--keyword", default="")
    sender_list_parser.add_argument("--page-no", type=int, default=1)
    sender_list_parser.add_argument("--page-size", type=int, default=10)
    sender_list_parser.add_argument("--sendtype", default=None, choices=["batch", "trigger"])
    sender_list_parser.set_defaults(func=cmd_sender_list)

    domain_create_parser = subparsers.add_parser("domain-create")
    _add_runtime_path_options(domain_create_parser)
    domain_create_parser.add_argument("--domain-name", required=True)
    domain_create_parser.add_argument("--dkim-selector", default="")
    domain_create_parser.add_argument("--dry-run", action="store_true")
    domain_create_parser.set_defaults(func=cmd_domain_create)

    domain_list_parser = subparsers.add_parser("domain-list")
    _add_runtime_path_options(domain_list_parser)
    domain_list_parser.add_argument("--keyword", default="")
    domain_list_parser.add_argument("--page-no", type=int, default=1)
    domain_list_parser.add_argument("--page-size", type=int, default=10)
    domain_list_parser.add_argument("--status", type=int, default=None)
    domain_list_parser.set_defaults(func=cmd_domain_list)

    domain_desc_parser = subparsers.add_parser("domain-desc")
    _add_runtime_path_options(domain_desc_parser)
    domain_desc_parser.add_argument("--domain-id", required=True)
    domain_desc_parser.set_defaults(func=cmd_domain_desc)

    domain_check_parser = subparsers.add_parser("domain-check")
    _add_runtime_path_options(domain_check_parser)
    domain_check_parser.add_argument("--domain-id", required=True)
    domain_check_parser.set_defaults(func=cmd_domain_check)
    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    _apply_runtime_path_overrides(args)
    return args.func(args)


if __name__ == "__main__":
    main()
