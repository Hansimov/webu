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
    dns01_auth,
    dns01_cleanup,
    ensure_site,
    list_plan_instances,
    site_check,
    site_load_balancer_create,
    site_load_balancer_delete,
    site_load_balancer_origin_status,
    site_load_balancers,
    site_origin_pool_cname_apply,
    site_origin_pool_cname_delete,
    site_origin_pool_upsert,
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


def cmd_dns01_auth(args):
    print_json(
        dns01_auth(
            site_name=args.site_name,
            domain=args.domain,
            validation=args.validation,
            ttl=args.ttl,
            wait_seconds=args.wait_seconds,
            comment=args.comment,
        )
    )


def cmd_dns01_cleanup(args):
    print_json(
        dns01_cleanup(
            site_name=args.site_name,
            domain=args.domain,
            validation=args.validation,
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


def cmd_site_origin_pool_upsert(args):
    print_json(
        site_origin_pool_upsert(
            site_name=args.site_name,
            pool_name=args.pool_name,
            origin_name=args.origin_name,
            origin_address=args.origin_address,
            weight=args.weight,
            enabled=(not args.disable),
        )
    )


def cmd_site_load_balancers(args):
    print_json(
        site_load_balancers(
            site_name=args.site_name,
            name=args.name,
            match_type=args.match_type,
        )
    )


def cmd_site_load_balancer_origin_status(args):
    print_json(
        site_load_balancer_origin_status(
            site_name=args.site_name,
            load_balancer_ids=list(args.load_balancer_id or []),
            pool_type=args.pool_type,
        )
    )


def cmd_site_load_balancer_create(args):
    print_json(
        site_load_balancer_create(
            site_name=args.site_name,
            name=args.name,
            default_pool_ids=list(args.default_pool_id or []),
            default_pool_names=list(args.default_pool_name or []),
            fallback_pool_id=(
                args.fallback_pool_id if args.fallback_pool_id > 0 else None
            ),
            fallback_pool_name=args.fallback_pool_name,
            description=args.description,
            monitor_type=args.monitor_type,
            monitor_port=args.monitor_port,
            monitor_path=args.monitor_path,
            monitor_method=args.monitor_method,
            steering_policy=args.steering_policy,
            session_affinity=args.session_affinity,
            ttl=args.ttl,
            enabled=(not args.disable),
        )
    )


def cmd_site_load_balancer_delete(args):
    print_json(
        site_load_balancer_delete(
            site_name=args.site_name,
            load_balancer_id=(
                args.load_balancer_id if args.load_balancer_id > 0 else None
            ),
            name=args.name,
        )
    )


def cmd_site_origin_pool_cname_apply(args):
    print_json(
        site_origin_pool_cname_apply(
            site_name=args.site_name,
            record_name=args.record_name,
            pool_name=args.pool_name,
            pool_id=(args.pool_id if args.pool_id > 0 else None),
            biz_name=args.biz_name,
            host_policy=args.host_policy,
            ttl=args.ttl,
            comment=args.comment,
            purge_conflicts=args.purge_conflicts,
            retry_attempts=args.retry_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
            restore_on_failure=args.restore_on_failure,
        )
    )


def cmd_site_origin_pool_cname_delete(args):
    print_json(
        site_origin_pool_cname_delete(
            site_name=args.site_name,
            record_name=args.record_name,
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
            record_mode=args.record_mode,
            origin_pool_name=args.origin_pool_name,
            origin_pool_id=(args.origin_pool_id if args.origin_pool_id > 0 else None),
            biz_name=args.biz_name,
            host_policy=args.host_policy,
            ttl=args.ttl,
            comment=args.comment,
            purge_conflicts=args.purge_conflicts,
            save_config=args.save_config,
            verify_site_after_apply=args.verify_site,
            retry_attempts=args.retry_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
            restore_on_failure=args.restore_on_failure,
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

    dns01_auth_parser = subparsers.add_parser(
        "dns-01-auth",
        help="Create or reuse an ESA TXT record for ACME DNS-01 validation.",
    )
    dns01_auth_parser.add_argument(
        "--site-name",
        default="",
        help="ESA site name. If omitted, infer it from --domain or CERTBOT_DOMAIN.",
    )
    dns01_auth_parser.add_argument(
        "--domain",
        default="",
        help="Certificate domain. Defaults to CERTBOT_DOMAIN or CERTBOT_IDENTIFIER.",
    )
    dns01_auth_parser.add_argument(
        "--validation",
        default="",
        help="ACME TXT validation value. Defaults to CERTBOT_VALIDATION.",
    )
    dns01_auth_parser.add_argument(
        "--ttl",
        type=int,
        default=60,
        help="TXT record TTL in seconds.",
    )
    dns01_auth_parser.add_argument(
        "--wait-seconds",
        type=int,
        default=30,
        help="Sleep after applying the TXT record to give public DNS time to converge.",
    )
    dns01_auth_parser.add_argument(
        "--comment",
        default="",
        help="Optional TXT record comment.",
    )
    _add_runtime_path_options(dns01_auth_parser)
    dns01_auth_parser.set_defaults(func=cmd_dns01_auth)

    dns01_cleanup_parser = subparsers.add_parser(
        "dns-01-cleanup",
        help="Delete ESA TXT records created for ACME DNS-01 validation.",
    )
    dns01_cleanup_parser.add_argument(
        "--site-name",
        default="",
        help="ESA site name. If omitted, infer it from --domain or CERTBOT_DOMAIN.",
    )
    dns01_cleanup_parser.add_argument(
        "--domain",
        default="",
        help="Certificate domain. Defaults to CERTBOT_DOMAIN or CERTBOT_IDENTIFIER.",
    )
    dns01_cleanup_parser.add_argument(
        "--validation",
        default="",
        help="ACME TXT validation value. Defaults to CERTBOT_VALIDATION.",
    )
    _add_runtime_path_options(dns01_cleanup_parser)
    dns01_cleanup_parser.set_defaults(func=cmd_dns01_cleanup)

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

    site_origin_pool_upsert_parser = subparsers.add_parser(
        "site-origin-pool-upsert",
        help="Create or update an ESA origin pool and ensure a named origin entry points at the requested address.",
    )
    site_origin_pool_upsert_parser.add_argument("--site-name", required=True)
    site_origin_pool_upsert_parser.add_argument("--pool-name", required=True)
    site_origin_pool_upsert_parser.add_argument("--origin-name", required=True)
    site_origin_pool_upsert_parser.add_argument("--origin-address", required=True)
    site_origin_pool_upsert_parser.add_argument(
        "--weight",
        type=int,
        default=100,
        help="Origin weight used when the pool contains multiple origins.",
    )
    site_origin_pool_upsert_parser.add_argument(
        "--disable",
        action="store_true",
        help="Persist the pool in disabled state.",
    )
    _add_runtime_path_options(site_origin_pool_upsert_parser)
    site_origin_pool_upsert_parser.set_defaults(func=cmd_site_origin_pool_upsert)

    site_load_balancers_parser = subparsers.add_parser(
        "site-load-balancers",
        help="List ESA load balancers currently configured for a site.",
    )
    site_load_balancers_parser.add_argument("--site-name", required=True)
    site_load_balancers_parser.add_argument(
        "--name",
        default="",
        help="Optional load balancer name filter.",
    )
    site_load_balancers_parser.add_argument(
        "--match-type",
        default="exact",
        choices=["exact", "fuzzy"],
        help="How --name should be matched when filtering load balancers.",
    )
    _add_runtime_path_options(site_load_balancers_parser)
    site_load_balancers_parser.set_defaults(func=cmd_site_load_balancers)

    site_load_balancer_origin_status_parser = subparsers.add_parser(
        "site-load-balancer-origin-status",
        help="List ESA load balancer origin health status for one or more load balancers.",
    )
    site_load_balancer_origin_status_parser.add_argument("--site-name", required=True)
    site_load_balancer_origin_status_parser.add_argument(
        "--load-balancer-id",
        action="append",
        type=int,
        default=[],
        help="Specific load balancer ID to query. Repeat for multiple IDs. If omitted, all site load balancers are queried.",
    )
    site_load_balancer_origin_status_parser.add_argument(
        "--pool-type",
        default="",
        help="Optional pool type filter such as default_pool.",
    )
    _add_runtime_path_options(site_load_balancer_origin_status_parser)
    site_load_balancer_origin_status_parser.set_defaults(
        func=cmd_site_load_balancer_origin_status
    )

    site_load_balancer_create_parser = subparsers.add_parser(
        "site-load-balancer-create",
        help="Create an ESA load balancer that references one or more origin pools.",
    )
    site_load_balancer_create_parser.add_argument("--site-name", required=True)
    site_load_balancer_create_parser.add_argument(
        "--name",
        required=True,
        help="Load balancer hostname. A bare label is expanded under the site domain.",
    )
    site_load_balancer_create_parser.add_argument(
        "--default-pool-id",
        action="append",
        type=int,
        default=[],
        help="Default origin pool ID. Repeat for multiple pools.",
    )
    site_load_balancer_create_parser.add_argument(
        "--default-pool-name",
        action="append",
        default=[],
        help="Default origin pool name. Repeat for multiple pools.",
    )
    site_load_balancer_create_parser.add_argument(
        "--fallback-pool-id",
        type=int,
        default=0,
        help="Optional fallback origin pool ID. Defaults to the first default pool.",
    )
    site_load_balancer_create_parser.add_argument(
        "--fallback-pool-name",
        default="",
        help="Optional fallback origin pool name. Defaults to the first default pool.",
    )
    site_load_balancer_create_parser.add_argument("--description", default="")
    site_load_balancer_create_parser.add_argument(
        "--monitor-type",
        default="off",
        help="Monitor type such as off, HTTP, HTTPS, or TCP.",
    )
    site_load_balancer_create_parser.add_argument(
        "--monitor-port",
        type=int,
        default=0,
        help="Optional monitor port.",
    )
    site_load_balancer_create_parser.add_argument(
        "--monitor-path",
        default="",
        help="Optional monitor path for HTTP/HTTPS checks.",
    )
    site_load_balancer_create_parser.add_argument(
        "--monitor-method",
        default="GET",
        help="Optional monitor method for HTTP/HTTPS checks.",
    )
    site_load_balancer_create_parser.add_argument(
        "--steering-policy",
        default="order",
        choices=["order", "random"],
        help="Load balancing strategy for the minimal supported wrapper.",
    )
    site_load_balancer_create_parser.add_argument(
        "--session-affinity",
        default="off",
        choices=["off", "ip", "cookie"],
        help="Optional session affinity mode.",
    )
    site_load_balancer_create_parser.add_argument(
        "--ttl",
        type=int,
        default=30,
        help="TTL for the load balancer hostname, clamped to 10-600.",
    )
    site_load_balancer_create_parser.add_argument(
        "--disable",
        action="store_true",
        help="Create the load balancer in disabled state.",
    )
    _add_runtime_path_options(site_load_balancer_create_parser)
    site_load_balancer_create_parser.set_defaults(func=cmd_site_load_balancer_create)

    site_load_balancer_delete_parser = subparsers.add_parser(
        "site-load-balancer-delete",
        help="Delete an ESA load balancer by ID or exact name.",
    )
    site_load_balancer_delete_parser.add_argument("--site-name", required=True)
    site_load_balancer_delete_parser.add_argument(
        "--load-balancer-id",
        type=int,
        default=0,
        help="Load balancer ID to delete.",
    )
    site_load_balancer_delete_parser.add_argument(
        "--name",
        default="",
        help="Exact load balancer hostname to delete when ID is not provided.",
    )
    _add_runtime_path_options(site_load_balancer_delete_parser)
    site_load_balancer_delete_parser.set_defaults(func=cmd_site_load_balancer_delete)

    site_origin_pool_cname_apply_parser = subparsers.add_parser(
        "site-origin-pool-cname-apply",
        help="Create or update a proxied CNAME record that references an ESA origin pool through SourceType=OP.",
    )
    site_origin_pool_cname_apply_parser.add_argument("--site-name", required=True)
    site_origin_pool_cname_apply_parser.add_argument("--record-name", required=True)
    site_origin_pool_cname_apply_parser.add_argument(
        "--pool-name",
        default="",
        help="Origin pool name to reference.",
    )
    site_origin_pool_cname_apply_parser.add_argument(
        "--pool-id",
        type=int,
        default=0,
        help="Origin pool ID to reference. Overrides --pool-name when provided.",
    )
    site_origin_pool_cname_apply_parser.add_argument(
        "--biz-name",
        default="web",
        choices=["web", "api", "image_video"],
        help="Acceleration business type required by proxied CNAME records.",
    )
    site_origin_pool_cname_apply_parser.add_argument(
        "--host-policy",
        default="",
        choices=["", "follow_hostname", "follow_origin_domain"],
        help="Optional host policy for the proxied CNAME.",
    )
    site_origin_pool_cname_apply_parser.add_argument(
        "--ttl",
        type=int,
        default=30,
    )
    site_origin_pool_cname_apply_parser.add_argument("--comment", default="")
    site_origin_pool_cname_apply_parser.add_argument(
        "--purge-conflicts",
        action="store_true",
        help="Delete conflicting CNAME or A/AAAA records with the same name before applying the OP-backed CNAME.",
    )
    site_origin_pool_cname_apply_parser.add_argument(
        "--retry-attempts",
        type=int,
        default=3,
        help="Retry attempts for transient ESA control-plane errors such as Site.ServiceBusy.",
    )
    site_origin_pool_cname_apply_parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=1.0,
        help="Delay between retry attempts for transient ESA control-plane errors.",
    )
    site_origin_pool_cname_apply_parser.add_argument(
        "--no-restore-on-failure",
        dest="restore_on_failure",
        action="store_false",
        help="Do not attempt to restore the previous public record set if the apply fails after mutating records.",
    )
    site_origin_pool_cname_apply_parser.set_defaults(restore_on_failure=True)
    _add_runtime_path_options(site_origin_pool_cname_apply_parser)
    site_origin_pool_cname_apply_parser.set_defaults(
        func=cmd_site_origin_pool_cname_apply
    )

    site_origin_pool_cname_delete_parser = subparsers.add_parser(
        "site-origin-pool-cname-delete",
        help="Delete a proxied CNAME record that references an origin pool through SourceType=OP.",
    )
    site_origin_pool_cname_delete_parser.add_argument("--site-name", required=True)
    site_origin_pool_cname_delete_parser.add_argument("--record-name", required=True)
    _add_runtime_path_options(site_origin_pool_cname_delete_parser)
    site_origin_pool_cname_delete_parser.set_defaults(
        func=cmd_site_origin_pool_cname_delete
    )

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
    exposure_apply_parser.add_argument(
        "--record-mode",
        default="direct",
        choices=["direct", "origin-pool"],
        help="Whether exposure-apply should write a direct A/AAAA record or a proxied CNAME backed by an ESA origin pool.",
    )
    exposure_apply_parser.add_argument(
        "--origin-pool-name",
        default="",
        help="Origin pool name used when --record-mode origin-pool is selected.",
    )
    exposure_apply_parser.add_argument(
        "--origin-pool-id",
        type=int,
        default=0,
        help="Origin pool ID used when --record-mode origin-pool is selected.",
    )
    exposure_apply_parser.add_argument(
        "--biz-name",
        default="web",
        choices=["web", "api", "image_video"],
        help="ESA business type used for proxied records; relevant for --record-mode origin-pool.",
    )
    exposure_apply_parser.add_argument(
        "--host-policy",
        default="",
        choices=["", "follow_hostname", "follow_origin_domain"],
        help="Optional ESA host policy used for --record-mode origin-pool.",
    )
    exposure_apply_parser.add_argument(
        "--ttl",
        type=int,
        default=30,
        help="Record TTL used for --record-mode origin-pool.",
    )
    exposure_apply_parser.add_argument(
        "--comment",
        default="",
        help="Optional record comment used for --record-mode origin-pool.",
    )
    exposure_apply_parser.add_argument(
        "--purge-conflicts",
        action="store_true",
        help="Delete conflicting A/AAAA or CNAME records with the same name before applying the desired public record.",
    )
    exposure_apply_parser.add_argument(
        "--retry-attempts",
        type=int,
        default=3,
        help="Retry attempts for transient ESA control-plane errors such as Site.ServiceBusy.",
    )
    exposure_apply_parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=1.0,
        help="Delay between retry attempts for transient ESA control-plane errors.",
    )
    exposure_apply_parser.add_argument(
        "--no-restore-on-failure",
        dest="restore_on_failure",
        action="store_false",
        help="Do not attempt to restore the previous public record set if the apply fails after mutating records.",
    )
    exposure_apply_parser.set_defaults(restore_on_failure=True)
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
