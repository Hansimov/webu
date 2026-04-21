import os

from pathlib import Path

from webu.ddns.cli import _apply_runtime_path_overrides, build_parser


def test_parser_supports_config_target_and_service_commands():
    parser = build_parser()
    project_root = "/tmp/webu-project"
    config_dir = "/tmp/webu-project/configs"

    config_args = parser.parse_args(["config-check"])
    upsert_args = parser.parse_args(
        [
            "target-upsert",
            "--name",
            "example-origin-pool",
            "--site-name",
            "example.com",
            "--pool-name",
            "example-origin-pool",
            "--origin-name",
            "home6",
            "--save-config",
            "--project-root",
            project_root,
            "--config-dir",
            config_dir,
        ]
    )
    prepare_args = parser.parse_args(
        ["target-prepare", "--name", "example-origin-pool"]
    )
    delete_args = parser.parse_args(["target-delete", "--name", "example-origin-pool"])
    run_once_args = parser.parse_args(
        ["target-run-once", "--name", "example-origin-pool", "--timeout-seconds", "9"]
    )
    install_args = parser.parse_args(
        ["service-install", "--name", "example-origin-pool"]
    )
    status_args = parser.parse_args(["service-status", "--name", "example-origin-pool"])
    logs_args = parser.parse_args(
        ["service-logs", "--name", "example-origin-pool", "--lines", "20"]
    )
    restart_args = parser.parse_args(
        ["service-restart", "--name", "example-origin-pool"]
    )
    disable_args = parser.parse_args(
        ["service-disable", "--name", "example-origin-pool", "--purge-unit-file"]
    )

    assert config_args.command == "config-check"
    assert upsert_args.name == "example-origin-pool"
    assert upsert_args.site_name == "example.com"
    assert upsert_args.project_root == project_root
    assert upsert_args.config_dir == config_dir
    assert prepare_args.seed_existing is False
    assert delete_args.name == "example-origin-pool"
    assert run_once_args.timeout_seconds == 9
    assert install_args.name == "example-origin-pool"
    assert status_args.name == "example-origin-pool"
    assert logs_args.lines == 20
    assert restart_args.name == "example-origin-pool"
    assert disable_args.purge_unit_file is True


def test_runtime_path_overrides_set_environment(monkeypatch, tmp_path):
    parser = build_parser()
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    monkeypatch.delenv("WEBU_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("WEBU_CONFIG_DIR", raising=False)

    args = parser.parse_args(
        [
            "target-list",
            "--project-root",
            str(tmp_path),
            "--config-dir",
            str(config_dir),
        ]
    )

    _apply_runtime_path_overrides(args)

    assert Path(os.environ["WEBU_PROJECT_ROOT"]).resolve() == tmp_path.resolve()
    assert Path(os.environ["WEBU_CONFIG_DIR"]).resolve() == config_dir.resolve()
