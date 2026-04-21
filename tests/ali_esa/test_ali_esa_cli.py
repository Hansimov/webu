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
