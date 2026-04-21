from webu.ali_esa.cli import build_parser


def test_parser_supports_load_balancer_create_and_delete_commands():
    parser = build_parser()

    create_args = parser.parse_args(
        [
            "site-load-balancer-create",
            "--site-name",
            "example.com",
            "--name",
            "lb-probe",
            "--default-pool-name",
            "search-prod",
            "--monitor-type",
            "off",
        ]
    )
    delete_args = parser.parse_args(
        [
            "site-load-balancer-delete",
            "--site-name",
            "example.com",
            "--name",
            "lb-probe.example.com",
        ]
    )

    assert create_args.command == "site-load-balancer-create"
    assert create_args.site_name == "example.com"
    assert create_args.name == "lb-probe"
    assert create_args.default_pool_name == ["search-prod"]
    assert create_args.monitor_type == "off"
    assert delete_args.command == "site-load-balancer-delete"
    assert delete_args.site_name == "example.com"
    assert delete_args.name == "lb-probe.example.com"


def test_parser_supports_exposure_apply_origin_pool_mode():
    parser = build_parser()

    args = parser.parse_args(
        [
            "exposure-apply",
            "--domain",
            "prod.example.com",
            "--local-url",
            "http://127.0.0.1:20002",
            "--zone-name",
            "example.com",
            "--record-mode",
            "origin-pool",
            "--origin-pool-name",
            "home6-prod",
            "--biz-name",
            "web",
            "--purge-conflicts",
        ]
    )

    assert args.command == "exposure-apply"
    assert args.domain_name == "prod.example.com"
    assert args.local_url == "http://127.0.0.1:20002"
    assert args.zone_name == "example.com"
    assert args.record_mode == "origin-pool"
    assert args.origin_pool_name == "home6-prod"
    assert args.biz_name == "web"
    assert args.purge_conflicts is True


def test_parser_supports_exposure_apply_cloudflare_bridge_mode():
    parser = build_parser()

    args = parser.parse_args(
        [
            "exposure-apply",
            "--domain",
            "dev.example.com",
            "--local-url",
            "https://127.0.0.1:443",
            "--zone-name",
            "example.com",
            "--record-mode",
            "direct",
            "--origin-address",
            "cloudflare",
            "--purge-conflicts",
        ]
    )

    assert args.command == "exposure-apply"
    assert args.domain_name == "dev.example.com"
    assert args.local_url == "https://127.0.0.1:443"
    assert args.zone_name == "example.com"
    assert args.record_mode == "direct"
    assert args.origin_address == "cloudflare"
    assert args.purge_conflicts is True


def test_parser_supports_dns01_auth_and_cleanup_commands():
    parser = build_parser()

    auth_args = parser.parse_args(
        [
            "dns-01-auth",
            "--site-name",
            "example.com",
            "--domain",
            "*.example.com",
            "--validation",
            "token-value",
            "--ttl",
            "120",
            "--wait-seconds",
            "5",
        ]
    )
    cleanup_args = parser.parse_args(
        [
            "dns-01-cleanup",
            "--site-name",
            "example.com",
            "--domain",
            "example.com",
            "--validation",
            "token-value",
        ]
    )

    assert auth_args.command == "dns-01-auth"
    assert auth_args.site_name == "example.com"
    assert auth_args.domain == "*.example.com"
    assert auth_args.validation == "token-value"
    assert auth_args.ttl == 120
    assert auth_args.wait_seconds == 5
    assert cleanup_args.command == "dns-01-cleanup"
    assert cleanup_args.site_name == "example.com"
    assert cleanup_args.domain == "example.com"
    assert cleanup_args.validation == "token-value"
