from __future__ import annotations

import argparse
import json
import os

from pathlib import Path

from webu.clis import print_json

from .operations import (
    activate_site_ns,
    apply_exposure,
    config_check,
    config_init,
    config_schema_json,
    ensure_site,
    list_plan_instances,
    site_check,
    site_origin_pools,
    site_records,
    site_status,
    snapshot,
    sync_site_dns_from_cloudflare,
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
        help="Explicit directory containing webu JSON configs such as configs/ali_esa.json.",
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
    print(config_init(force=args.force, from_cf_tunnel=args.from_cf_tunnel))


def cmd_plan_list(_args):
    print_json(list_plan_instances())


def cmd_site_check(args):
    print_json(site_check(site_name=args.site_name))


def cmd_site_ensure(args):
    print_json(
        ensure_site(
            site_name=args.site_name,
            coverage=args.coverage,
            access_type=args.access_type,
            instance_id=args.instance_id,
            save_config=args.save_config,
        )
    )


def cmd_site_status(args):
    print_json(site_status(site_name=args.site_name))


def cmd_site_records(args):
    print_json(
        site_records(
            site_name=args.site_name,
            record_name=args.record_name,
            record_type=args.record_type,
        )
    )


def cmd_site_origin_pools(args):
    print_json(
        site_origin_pools(
            site_name=args.site_name,
            name=args.name,
            match_type=args.match_type,
        )
    )


def cmd_site_sync_cloudflare_dns(args):
    print_json(
        sync_site_dns_from_cloudflare(
            site_name=args.site_name,
            skip_record_names=list(args.skip_record_name or []),
            save_config=args.save_config,
            strict=not bool(args.allow_skip_unsupported),
        )
    )


def cmd_site_activate_ns(args):
    print_json(
        activate_site_ns(
            site_name=args.site_name,
            save_config=args.save_config,
            wait=args.wait,
            verify_site_after_switch=args.verify_site,
            verify_attempts=args.verify_attempts,
            verify_interval_seconds=args.verify_interval_seconds,
        )
    )


def cmd_exposure_apply(args):
    print_json(
        apply_exposure(
            domain_name=args.domain_name,
            local_url=args.local_url,
            zone_name=args.zone_name,
            coverage=args.coverage,
            access_type=args.access_type,
            instance_id=args.instance_id,
            origin_address=args.origin_address,
            save_config=args.save_config,
            verify_site_after_apply=args.verify_site,
        )
    )


def cmd_snapshot(args):
    print_json(
        snapshot(
            names=list(args.names or []),
            output_dir=Path(args.output_dir),
            stamp=str(args.stamp or "").strip() or None,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aesa",
        description="Manage Alibaba Cloud ESA sites, DNS cutover, and public exposure from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_schema_parser = subparsers.add_parser(
        "config-schema",
        help="Print the ali_esa shared schema.",
    )
    _add_runtime_path_options(config_schema_parser)
    config_schema_parser.set_defaults(func=cmd_config_schema)

    config_check_parser = subparsers.add_parser(
        "config-check",
        help="Validate configs/ali_esa.json.",
    )
    _add_runtime_path_options(config_check_parser)
    config_check_parser.set_defaults(func=cmd_config_check)

    config_init_parser = subparsers.add_parser(
        "config-init",
        help="Write a minimal ali_esa config skeleton.",
    )
    config_init_parser.add_argument("--force", action="store_true")
    config_init_parser.add_argument(
        "--from-cf-tunnel",
        action="store_true",
        help="Bootstrap ali_esa.json from the existing cf_tunnel.json credentials and zone metadata.",
    )
    _add_runtime_path_options(config_init_parser)
    config_init_parser.set_defaults(func=cmd_config_init)

    plan_list_parser = subparsers.add_parser(
        "plan-list",
        help="List online ESA plan instances with remaining site quota.",
    )
    _add_runtime_path_options(plan_list_parser)
    plan_list_parser.set_defaults(func=cmd_plan_list)

    site_check_parser = subparsers.add_parser(
        "site-check",
        help="Check whether a site name is valid and whether it already exists in ESA.",
    )
    site_check_parser.add_argument("--site-name", required=True)
    _add_runtime_path_options(site_check_parser)
    site_check_parser.set_defaults(func=cmd_site_check)

    site_ensure_parser = subparsers.add_parser(
        "site-ensure",
        help="Create the ESA site if it does not already exist.",
    )
    site_ensure_parser.add_argument("--site-name", required=True)
    site_ensure_parser.add_argument("--coverage", default="")
    site_ensure_parser.add_argument("--access-type", default="")
    site_ensure_parser.add_argument("--instance-id", default="")
    site_ensure_parser.add_argument("--save-config", action="store_true")
    _add_runtime_path_options(site_ensure_parser)
    site_ensure_parser.set_defaults(func=cmd_site_ensure)

    site_status_parser = subparsers.add_parser(
        "site-status",
        help="Show the current ESA site state and assigned nameservers.",
    )
    site_status_parser.add_argument("--site-name", required=True)
    _add_runtime_path_options(site_status_parser)
    site_status_parser.set_defaults(func=cmd_site_status)

    site_records_parser = subparsers.add_parser(
        "site-records",
        help="List ESA DNS records currently configured for a site.",
    )
    site_records_parser.add_argument("--site-name", required=True)
    site_records_parser.add_argument(
        "--record-name",
        default="",
        help="Optional fully qualified record name filter.",
    )
    site_records_parser.add_argument(
        "--record-type",
        default="",
        help="Optional record type filter such as A, AAAA, A/AAAA, CNAME, TXT, or MX.",
    )
    _add_runtime_path_options(site_records_parser)
    site_records_parser.set_defaults(func=cmd_site_records)

    site_origin_pools_parser = subparsers.add_parser(
        "site-origin-pools",
        help="List ESA origin pools currently configured for a site.",
    )
    site_origin_pools_parser.add_argument("--site-name", required=True)
    site_origin_pools_parser.add_argument(
        "--name",
        default="",
        help="Optional origin pool name filter.",
    )
    site_origin_pools_parser.add_argument(
        "--match-type",
        default="exact",
        choices=["exact", "fuzzy"],
        help="How --name should be matched when filtering origin pools.",
    )
    _add_runtime_path_options(site_origin_pools_parser)
    site_origin_pools_parser.set_defaults(func=cmd_site_origin_pools)

    site_sync_parser = subparsers.add_parser(
        "site-sync-cloudflare-dns",
        help="Import the current Cloudflare zone records into the ESA site.",
    )
    site_sync_parser.add_argument("--site-name", required=True)
    site_sync_parser.add_argument(
        "--skip-record-name",
        action="append",
        default=[],
        help="Fully qualified record name to skip during import. Repeat for multiple names.",
    )
    site_sync_parser.add_argument(
        "--allow-skip-unsupported",
        action="store_true",
        help="Best-effort import. Unsupported Cloudflare record types are skipped instead of failing the whole run.",
    )
    site_sync_parser.add_argument("--save-config", action="store_true")
    _add_runtime_path_options(site_sync_parser)
    site_sync_parser.set_defaults(func=cmd_site_sync_cloudflare_dns)

    site_activate_parser = subparsers.add_parser(
        "site-activate-ns",
        help="Switch the registrar nameservers to the ESA-assigned NS set.",
    )
    site_activate_parser.add_argument("--site-name", required=True)
    site_activate_parser.add_argument("--wait", action="store_true")
    site_activate_parser.add_argument("--verify-site", action="store_true")
    site_activate_parser.add_argument("--verify-attempts", type=int, default=10)
    site_activate_parser.add_argument(
        "--verify-interval-seconds",
        type=int,
        default=15,
    )
    site_activate_parser.add_argument("--save-config", action="store_true")
    _add_runtime_path_options(site_activate_parser)
    site_activate_parser.set_defaults(func=cmd_site_activate_ns)

    exposure_apply_parser = subparsers.add_parser(
        "exposure-apply",
        help="Ensure a proxied ESA record and matching origin rule for a public hostname.",
    )
    exposure_apply_parser.add_argument(
        "--domain-name",
        "--domain",
        dest="domain_name",
        required=True,
    )
    exposure_apply_parser.add_argument("--local-url", required=True)
    exposure_apply_parser.add_argument("--zone-name", default="")
    exposure_apply_parser.add_argument("--coverage", default="")
    exposure_apply_parser.add_argument("--access-type", default="")
    exposure_apply_parser.add_argument("--instance-id", default="")
    exposure_apply_parser.add_argument(
        "--origin-address",
        default="auto",
        help=(
            "Public origin IP address. Use 'auto' to prefer ali_esa.json overrides or IPv4 auto-detection, "
            "or use 'auto4' / 'auto6' to prefer a specific family. ESA proxied records use Alibaba Cloud's "
            "A/AAAA model and still require at least one IPv4 origin address."
        ),
    )
    exposure_apply_parser.add_argument("--verify-site", action="store_true")
    exposure_apply_parser.add_argument("--save-config", action="store_true")
    _add_runtime_path_options(exposure_apply_parser)
    exposure_apply_parser.set_defaults(func=cmd_exposure_apply)

    snapshot_parser = subparsers.add_parser(
        "snapshot",
        help="Capture a local-resolver ESA edge snapshot for one or more public hostnames.",
    )
    snapshot_parser.add_argument(
        "--name",
        "--names",
        dest="names",
        action="append",
        required=True,
    )
    snapshot_parser.add_argument(
        "--output-dir",
        default="debugs/ali-esa-snapshots",
    )
    snapshot_parser.add_argument("--stamp", default="")
    _add_runtime_path_options(snapshot_parser)
    snapshot_parser.set_defaults(func=cmd_snapshot)

    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    _apply_runtime_path_overrides(args)
    args.func(args)


if __name__ == "__main__":
    main()
