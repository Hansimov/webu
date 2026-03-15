from __future__ import annotations

import argparse
import json

from webu.clis import print_json

from .helptext import COMMAND_HELP, command_epilog, root_description, root_help_epilog
from .operations import (
    access_diagnose,
    apply_tunnel,
    client_canary_bundle,
    client_override_plan,
    client_report_summary,
    client_report_template,
    config_check,
    config_init,
    config_schema_json,
    docs_sync,
    edge_trace,
    ensure_token,
    migrate_dns_to_cloudflare,
    page_audit,
    tunnel_status,
)


def _add_common_token_mode(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--cf-token-mode",
        choices=["auto", "manual", "prompt"],
        default="auto",
        help="How to resolve the Cloudflare API token: auto-create, manual prompt, or prompt for a choice.",
    )
    parser.add_argument(
        "--save-config",
        action="store_true",
        help="Persist newly created token, zone_id, nameservers, tunnel_id, or tunnel_token back to configs/cf_tunnel.json.",
    )


def cmd_dns_migrate(args):
    result = migrate_dns_to_cloudflare(
        domain_name=args.domain_name,
        zone_name=args.zone_name,
        cf_token_mode=args.cf_token_mode,
        aliyun_credential_mode=args.aliyun_credential_mode,
        save_config=args.save_config,
    )
    print_json(result)


def cmd_tunnel_apply(args):
    result = apply_tunnel(
        tunnel_name=args.name,
        apply_all=args.all,
        install_service=args.install_service,
        cf_token_mode=args.cf_token_mode,
        save_config=args.save_config,
    )
    print_json(result)


def cmd_tunnel_status(args):
    print_json(tunnel_status(tunnel_name=args.name, cf_token_mode=args.cf_token_mode))


def cmd_token_ensure(args):
    print_json(
        ensure_token(
            zone_name=args.zone_name,
            cf_token_mode=args.cf_token_mode,
            save_config=args.save_config,
        )
    )


def cmd_access_diagnose(args):
    print_json(access_diagnose(tunnel_name=args.name, hostname=args.hostname))


def cmd_page_audit(args):
    print_json(
        page_audit(tunnel_name=args.name, hostname=args.hostname, path=args.path)
    )


def cmd_edge_trace(args):
    print_json(
        edge_trace(tunnel_name=args.name, hostname=args.hostname, path=args.path)
    )


def cmd_client_override_plan(args):
    print_json(
        client_override_plan(
            tunnel_name=args.name,
            hostname=args.hostname,
            prefer_family=args.prefer_family,
            max_candidates=args.max_candidates,
        )
    )


def cmd_client_canary_bundle(args):
    print_json(
        client_canary_bundle(
            tunnel_name=args.name,
            hostname=args.hostname,
            prefer_family=args.prefer_family,
            max_candidates=args.max_candidates,
        )
    )


def cmd_client_report_template(args):
    print_json(
        client_report_template(
            tunnel_name=args.name,
            hostname=args.hostname,
            prefer_family=args.prefer_family,
            max_candidates=args.max_candidates,
        )
    )


def cmd_client_report_summary(args):
    print_json(client_report_summary(report_file=args.report_file))


def cmd_config_schema(args):
    print(json.dumps(config_schema_json(), indent=2, ensure_ascii=False))


def cmd_config_check(args):
    errors = config_check()
    if errors:
        raise SystemExit("; ".join(errors))
    print("config ok")


def cmd_config_init(args):
    print(config_init(force=args.force))


def cmd_docs_sync(args):
    print_json(docs_sync())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cftn",
        description=root_description(),
        epilog=root_help_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    dns_migrate = subparsers.add_parser(
        "dns-migrate",
        help=COMMAND_HELP["dns-migrate"]["summary"],
        epilog=command_epilog("dns-migrate"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    dns_migrate.add_argument("domain_name")
    dns_migrate.add_argument("--zone-name", default="")
    dns_migrate.add_argument(
        "--aliyun-credential-mode",
        choices=["existing", "manual"],
        default="existing",
        help="Use existing Aliyun credentials from config or prompt manually.",
    )
    _add_common_token_mode(dns_migrate)
    dns_migrate.set_defaults(func=cmd_dns_migrate)

    tunnel_apply = subparsers.add_parser(
        "tunnel-apply",
        help=COMMAND_HELP["tunnel-apply"]["summary"],
        epilog=command_epilog("tunnel-apply"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    tunnel_apply.add_argument("--name", default="")
    tunnel_apply.add_argument("--all", action="store_true")
    tunnel_apply.add_argument("--install-service", action="store_true")
    _add_common_token_mode(tunnel_apply)
    tunnel_apply.set_defaults(func=cmd_tunnel_apply)

    tunnel_status_parser = subparsers.add_parser(
        "tunnel-status",
        help=COMMAND_HELP["tunnel-status"]["summary"],
        epilog=command_epilog("tunnel-status"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    tunnel_status_parser.add_argument("--name", default="")
    tunnel_status_parser.add_argument(
        "--cf-token-mode",
        choices=["auto", "manual", "prompt"],
        default="auto",
    )
    tunnel_status_parser.set_defaults(func=cmd_tunnel_status)

    access_diagnose_parser = subparsers.add_parser(
        "access-diagnose",
        help=COMMAND_HELP["access-diagnose"]["summary"],
        epilog=command_epilog("access-diagnose"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    access_diagnose_parser.add_argument("--name", default="")
    access_diagnose_parser.add_argument("--hostname", default="")
    access_diagnose_parser.set_defaults(func=cmd_access_diagnose)

    page_audit_parser = subparsers.add_parser(
        "page-audit",
        help=COMMAND_HELP["page-audit"]["summary"],
        epilog=command_epilog("page-audit"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    page_audit_parser.add_argument("--name", default="")
    page_audit_parser.add_argument("--hostname", default="")
    page_audit_parser.add_argument("--path", default="/")
    page_audit_parser.set_defaults(func=cmd_page_audit)

    edge_trace_parser = subparsers.add_parser(
        "edge-trace",
        help=COMMAND_HELP["edge-trace"]["summary"],
        epilog=command_epilog("edge-trace"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    edge_trace_parser.add_argument("--name", default="")
    edge_trace_parser.add_argument("--hostname", default="")
    edge_trace_parser.add_argument("--path", default="/cdn-cgi/trace")
    edge_trace_parser.set_defaults(func=cmd_edge_trace)

    client_override_parser = subparsers.add_parser(
        "client-override-plan",
        help=COMMAND_HELP["client-override-plan"]["summary"],
        epilog=command_epilog("client-override-plan"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    client_override_parser.add_argument("--name", default="")
    client_override_parser.add_argument("--hostname", default="")
    client_override_parser.add_argument(
        "--prefer-family",
        choices=["any", "ipv4", "ipv6"],
        default="ipv4",
    )
    client_override_parser.add_argument("--max-candidates", type=int, default=2)
    client_override_parser.set_defaults(func=cmd_client_override_plan)

    client_bundle_parser = subparsers.add_parser(
        "client-canary-bundle",
        help=COMMAND_HELP["client-canary-bundle"]["summary"],
        epilog=command_epilog("client-canary-bundle"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    client_bundle_parser.add_argument("--name", default="")
    client_bundle_parser.add_argument("--hostname", default="")
    client_bundle_parser.add_argument(
        "--prefer-family",
        choices=["any", "ipv4", "ipv6"],
        default="ipv4",
    )
    client_bundle_parser.add_argument("--max-candidates", type=int, default=2)
    client_bundle_parser.set_defaults(func=cmd_client_canary_bundle)

    client_template_parser = subparsers.add_parser(
        "client-report-template",
        help=COMMAND_HELP["client-report-template"]["summary"],
        epilog=command_epilog("client-report-template"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    client_template_parser.add_argument("--name", default="")
    client_template_parser.add_argument("--hostname", default="")
    client_template_parser.add_argument(
        "--prefer-family",
        choices=["any", "ipv4", "ipv6"],
        default="ipv4",
    )
    client_template_parser.add_argument("--max-candidates", type=int, default=2)
    client_template_parser.set_defaults(func=cmd_client_report_template)

    client_summary_parser = subparsers.add_parser(
        "client-report-summary",
        help=COMMAND_HELP["client-report-summary"]["summary"],
        epilog=command_epilog("client-report-summary"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    client_summary_parser.add_argument("report_file")
    client_summary_parser.set_defaults(func=cmd_client_report_summary)

    token_ensure_parser = subparsers.add_parser(
        "token-ensure",
        help=COMMAND_HELP["token-ensure"]["summary"],
        epilog=command_epilog("token-ensure"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    token_ensure_parser.add_argument("--zone-name", required=True)
    _add_common_token_mode(token_ensure_parser)
    token_ensure_parser.set_defaults(func=cmd_token_ensure)

    config_schema_parser = subparsers.add_parser(
        "config-schema",
        help=COMMAND_HELP["config-schema"]["summary"],
        epilog=command_epilog("config-schema"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_schema_parser.set_defaults(func=cmd_config_schema)

    config_check_parser = subparsers.add_parser(
        "config-check",
        help=COMMAND_HELP["config-check"]["summary"],
        epilog=command_epilog("config-check"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_check_parser.set_defaults(func=cmd_config_check)

    config_init_parser = subparsers.add_parser(
        "config-init",
        help=COMMAND_HELP["config-init"]["summary"],
        epilog=command_epilog("config-init"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_init_parser.add_argument("--force", action="store_true")
    config_init_parser.set_defaults(func=cmd_config_init)

    docs_sync_parser = subparsers.add_parser(
        "docs-sync",
        help=COMMAND_HELP["docs-sync"]["summary"],
        epilog=command_epilog("docs-sync"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    docs_sync_parser.set_defaults(func=cmd_docs_sync)
    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
