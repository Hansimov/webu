from __future__ import annotations

import argparse
import json
import os

from pathlib import Path

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
    guard_tunnel_quality,
    migrate_dns_to_cloudflare,
    page_audit,
    stabilize_tunnel,
    tunnel_status,
)
from .snapshot import capture_canary_snapshot


def _parse_optional_json_object(raw_value: str, *, label: str) -> dict | None:
    raw_value = str(raw_value or "").strip()
    if not raw_value:
        return None
    parsed = json.loads(raw_value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed


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


def _add_runtime_path_options(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--project-root",
        default="",
        help="Explicit webu project root used to resolve relative paths and project-local outputs.",
    )
    parser.add_argument(
        "--config-dir",
        default="",
        help="Explicit directory containing webu JSON configs such as configs/cf_tunnel.json.",
    )


def _apply_runtime_path_overrides(args) -> None:
    project_root = str(getattr(args, "project_root", "") or "").strip()
    config_dir = str(getattr(args, "config_dir", "") or "").strip()

    if project_root:
        os.environ["WEBU_PROJECT_ROOT"] = str(Path(project_root).expanduser().resolve())
    if config_dir:
        os.environ["WEBU_CONFIG_DIR"] = str(Path(config_dir).expanduser().resolve())


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
        install_guard_service=bool(args.install_service)
        and not bool(args.no_guard_service),
        cf_token_mode=args.cf_token_mode,
        save_config=args.save_config,
        domain_name=args.domain_name or None,
        local_url=args.local_url or None,
        zone_name=args.zone_name or None,
        origin_request=_parse_optional_json_object(
            args.origin_request_json,
            label="--origin-request-json",
        ),
        cloudflared_run=_parse_optional_json_object(
            args.cloudflared_run_json,
            label="--cloudflared-run-json",
        ),
    )
    print_json(result)


def cmd_tunnel_status(args):
    print_json(tunnel_status(tunnel_name=args.name, cf_token_mode=args.cf_token_mode))


def cmd_tunnel_stabilize(args):
    print_json(
        stabilize_tunnel(
            tunnel_name=args.name or None,
            hostname=args.hostname or None,
            cf_token_mode=args.cf_token_mode,
            prefer_family=args.prefer_family,
            max_candidates=args.max_candidates,
            install_service=bool(args.install_service),
            save_config=bool(args.save_config),
            capture_snapshot=bool(args.capture_snapshot),
            snapshot_output_dir=Path(args.snapshot_output_dir),
            snapshot_stamp=str(args.stamp or "").strip() or None,
        )
    )


def cmd_tunnel_guard(args):
    def emit_event(record):
        print(json.dumps(record, ensure_ascii=False), flush=True)

    print_json(
        guard_tunnel_quality(
            tunnel_name=args.name or None,
            hostname=args.hostname or None,
            cf_token_mode=args.cf_token_mode,
            interval_seconds=args.interval_seconds,
            failure_threshold=args.failure_threshold,
            cooldown_seconds=args.cooldown_seconds,
            snapshot_interval_seconds=args.snapshot_interval_seconds,
            prefer_family=args.prefer_family,
            max_candidates=args.max_candidates,
            install_service=bool(args.install_service),
            save_config=bool(args.save_config),
            snapshot_output_dir=Path(args.snapshot_output_dir),
            iterations=(args.iterations if args.iterations > 0 else None),
            history_limit=args.history_limit,
            emit_event=emit_event,
        )
    )


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


def cmd_snapshot(args):
    print_json(
        capture_canary_snapshot(
            names=list(args.names or []),
            prefer_family=args.prefer_family,
            max_candidates=args.max_candidates,
            output_dir=Path(args.output_dir),
            stamp=str(args.stamp or "").strip() or None,
        )
    )


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
    _add_runtime_path_options(dns_migrate)
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
    tunnel_apply.add_argument(
        "--domain-name", "--domain", dest="domain_name", default=""
    )
    tunnel_apply.add_argument("--local-url", default="")
    tunnel_apply.add_argument("--zone-name", default="")
    tunnel_apply.add_argument(
        "--origin-request-json",
        "--origin-request",
        dest="origin_request_json",
        default="",
    )
    tunnel_apply.add_argument(
        "--cloudflared-run-json",
        "--cloudflared-run",
        dest="cloudflared_run_json",
        default="",
    )
    tunnel_apply.add_argument("--install-service", action="store_true")
    tunnel_apply.add_argument(
        "--no-guard-service",
        action="store_true",
        help="When --install-service is used, skip installing the companion tunnel-guard sidecar service.",
    )
    _add_runtime_path_options(tunnel_apply)
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
    _add_runtime_path_options(tunnel_status_parser)
    tunnel_status_parser.set_defaults(func=cmd_tunnel_status)

    tunnel_stabilize_parser = subparsers.add_parser(
        "tunnel-stabilize",
        help=COMMAND_HELP["tunnel-stabilize"]["summary"],
        epilog=command_epilog("tunnel-stabilize"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    tunnel_stabilize_parser.add_argument("--name", default="")
    tunnel_stabilize_parser.add_argument("--hostname", default="")
    tunnel_stabilize_parser.add_argument(
        "--prefer-family",
        choices=["any", "ipv4", "ipv6"],
        default="any",
    )
    tunnel_stabilize_parser.add_argument("--max-candidates", type=int, default=3)
    tunnel_stabilize_parser.add_argument(
        "--snapshot-output-dir",
        default="debugs/cf-tunnel-snapshots",
    )
    tunnel_stabilize_parser.add_argument("--stamp", default="")
    tunnel_stabilize_parser.add_argument(
        "--cf-token-mode",
        choices=["auto", "manual", "prompt"],
        default="auto",
    )
    tunnel_stabilize_parser.add_argument("--save-config", action="store_true")
    tunnel_stabilize_parser.set_defaults(install_service=True, capture_snapshot=True)
    tunnel_stabilize_parser.add_argument(
        "--no-install-service",
        dest="install_service",
        action="store_false",
        help="Inspect and snapshot only; do not restart or reinstall the tunnel service even when a repairable issue is detected.",
    )
    tunnel_stabilize_parser.add_argument(
        "--no-snapshot",
        dest="capture_snapshot",
        action="store_false",
        help="Skip writing a fresh snapshot when the stabilize pass detects a non-healthy condition.",
    )
    _add_runtime_path_options(tunnel_stabilize_parser)
    tunnel_stabilize_parser.set_defaults(func=cmd_tunnel_stabilize)

    tunnel_guard_parser = subparsers.add_parser(
        "tunnel-guard",
        help=COMMAND_HELP["tunnel-guard"]["summary"],
        epilog=command_epilog("tunnel-guard"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    tunnel_guard_parser.add_argument("--name", default="")
    tunnel_guard_parser.add_argument("--hostname", default="")
    tunnel_guard_parser.add_argument(
        "--cf-token-mode",
        choices=["auto", "manual", "prompt"],
        default="auto",
    )
    tunnel_guard_parser.add_argument(
        "--interval-seconds",
        type=int,
        default=60,
    )
    tunnel_guard_parser.add_argument(
        "--failure-threshold",
        type=int,
        default=2,
    )
    tunnel_guard_parser.add_argument(
        "--cooldown-seconds",
        type=int,
        default=300,
    )
    tunnel_guard_parser.add_argument(
        "--snapshot-interval-seconds",
        type=int,
        default=1800,
        help="Capture a fresh snapshot every N seconds while the guard is healthy. Use 0 to disable periodic snapshots.",
    )
    tunnel_guard_parser.add_argument(
        "--prefer-family",
        choices=["any", "ipv4", "ipv6"],
        default="any",
    )
    tunnel_guard_parser.add_argument("--max-candidates", type=int, default=3)
    tunnel_guard_parser.add_argument(
        "--snapshot-output-dir",
        default="debugs/cf-tunnel-snapshots",
    )
    tunnel_guard_parser.add_argument(
        "--iterations",
        type=int,
        default=0,
        help="Run a fixed number of guard cycles for testing. Use 0 to run continuously.",
    )
    tunnel_guard_parser.add_argument(
        "--history-limit",
        type=int,
        default=20,
    )
    tunnel_guard_parser.add_argument("--save-config", action="store_true")
    tunnel_guard_parser.set_defaults(install_service=True)
    tunnel_guard_parser.add_argument(
        "--no-install-service",
        dest="install_service",
        action="store_false",
        help="Observe and snapshot only; do not trigger tunnel service reapply when the guard decides a baseline repair is needed.",
    )
    _add_runtime_path_options(tunnel_guard_parser)
    tunnel_guard_parser.set_defaults(func=cmd_tunnel_guard)

    access_diagnose_parser = subparsers.add_parser(
        "access-diagnose",
        help=COMMAND_HELP["access-diagnose"]["summary"],
        epilog=command_epilog("access-diagnose"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    access_diagnose_parser.add_argument("--name", default="")
    access_diagnose_parser.add_argument("--hostname", default="")
    _add_runtime_path_options(access_diagnose_parser)
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
    _add_runtime_path_options(page_audit_parser)
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
    _add_runtime_path_options(edge_trace_parser)
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
    _add_runtime_path_options(client_override_parser)
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
    _add_runtime_path_options(client_bundle_parser)
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
    _add_runtime_path_options(client_template_parser)
    client_template_parser.set_defaults(func=cmd_client_report_template)

    client_summary_parser = subparsers.add_parser(
        "client-report-summary",
        help=COMMAND_HELP["client-report-summary"]["summary"],
        epilog=command_epilog("client-report-summary"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    client_summary_parser.add_argument("report_file")
    _add_runtime_path_options(client_summary_parser)
    client_summary_parser.set_defaults(func=cmd_client_report_summary)

    snapshot_parser = subparsers.add_parser(
        "snapshot",
        help=COMMAND_HELP["snapshot"]["summary"],
        epilog=command_epilog("snapshot"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    snapshot_parser.add_argument(
        "--name",
        "--names",
        dest="names",
        action="append",
        required=True,
    )
    snapshot_parser.add_argument(
        "--prefer-family",
        choices=["any", "ipv4", "ipv6"],
        default="any",
    )
    snapshot_parser.add_argument("--max-candidates", type=int, default=3)
    snapshot_parser.add_argument("--output-dir", default="debugs/cf-tunnel-snapshots")
    snapshot_parser.add_argument("--stamp", default="")
    _add_runtime_path_options(snapshot_parser)
    snapshot_parser.set_defaults(func=cmd_snapshot)

    token_ensure_parser = subparsers.add_parser(
        "token-ensure",
        help=COMMAND_HELP["token-ensure"]["summary"],
        epilog=command_epilog("token-ensure"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    token_ensure_parser.add_argument("--zone-name", required=True)
    _add_runtime_path_options(token_ensure_parser)
    _add_common_token_mode(token_ensure_parser)
    token_ensure_parser.set_defaults(func=cmd_token_ensure)

    config_schema_parser = subparsers.add_parser(
        "config-schema",
        help=COMMAND_HELP["config-schema"]["summary"],
        epilog=command_epilog("config-schema"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_runtime_path_options(config_schema_parser)
    config_schema_parser.set_defaults(func=cmd_config_schema)

    config_check_parser = subparsers.add_parser(
        "config-check",
        help=COMMAND_HELP["config-check"]["summary"],
        epilog=command_epilog("config-check"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_runtime_path_options(config_check_parser)
    config_check_parser.set_defaults(func=cmd_config_check)

    config_init_parser = subparsers.add_parser(
        "config-init",
        help=COMMAND_HELP["config-init"]["summary"],
        epilog=command_epilog("config-init"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_init_parser.add_argument("--force", action="store_true")
    _add_runtime_path_options(config_init_parser)
    config_init_parser.set_defaults(func=cmd_config_init)

    docs_sync_parser = subparsers.add_parser(
        "docs-sync",
        help=COMMAND_HELP["docs-sync"]["summary"],
        epilog=command_epilog("docs-sync"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_runtime_path_options(docs_sync_parser)
    docs_sync_parser.set_defaults(func=cmd_docs_sync)
    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    _apply_runtime_path_overrides(args)
    args.func(args)


if __name__ == "__main__":
    main()
