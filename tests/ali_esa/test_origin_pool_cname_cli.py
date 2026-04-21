from webu.ali_esa.cli import build_parser


def test_parser_supports_origin_pool_cname_apply_and_delete_commands():
    parser = build_parser()

    apply_args = parser.parse_args(
        [
            "site-origin-pool-cname-apply",
            "--site-name",
            "example.com",
            "--record-name",
            "op-probe",
            "--pool-name",
            "search-prod",
            "--biz-name",
            "web",
        ]
    )
    delete_args = parser.parse_args(
        [
            "site-origin-pool-cname-delete",
            "--site-name",
            "example.com",
            "--record-name",
            "op-probe.example.com",
        ]
    )

    assert apply_args.command == "site-origin-pool-cname-apply"
    assert apply_args.record_name == "op-probe"
    assert apply_args.pool_name == "search-prod"
    assert apply_args.biz_name == "web"
    assert delete_args.command == "site-origin-pool-cname-delete"
    assert delete_args.record_name == "op-probe.example.com"
