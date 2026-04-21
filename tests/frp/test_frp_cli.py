import os

from pathlib import Path

from webu.frp.cli import _apply_runtime_path_overrides, build_parser


def test_parser_supports_server_and_client_commands():
    parser = build_parser()
    project_root = "/tmp/webu-project"
    config_dir = "/tmp/webu-project/configs"

    config_args = parser.parse_args(["config-check"])
    server_upsert_args = parser.parse_args(
        [
            "server-upsert",
            "--name",
            "relay-frps",
            "--ssh-host-name",
            "relay-vps",
            "--auth-token",
            "secret",
            "--remote-binary-path",
            "/root/frps",
            "--remote-config-path",
            "/root/frps.toml",
            "--save-config",
            "--project-root",
            project_root,
            "--config-dir",
            config_dir,
        ]
    )
    server_deploy_args = parser.parse_args(
        ["server-deploy", "--name", "relay-frps", "--install-service"]
    )
    client_upsert_args = parser.parse_args(
        [
            "client-upsert",
            "--name",
            "relay-public-web",
            "--server-name",
            "relay-frps",
            "--local-port",
            "20002",
            "--remote-port",
            "32002",
            "--save-config",
        ]
    )
    client_prepare_args = parser.parse_args(
        ["client-prepare", "--name", "relay-public-web"]
    )
    client_run_once_args = parser.parse_args(
        ["client-run-once", "--name", "relay-public-web", "--timeout-seconds", "9"]
    )
    client_install_args = parser.parse_args(
        ["client-service-install", "--name", "relay-public-web"]
    )
    client_logs_args = parser.parse_args(
        ["client-service-logs", "--name", "relay-public-web", "--lines", "20"]
    )
    client_disable_args = parser.parse_args(
        [
            "client-service-disable",
            "--name",
            "relay-public-web",
            "--purge-unit-file",
        ]
    )

    assert config_args.command == "config-check"
    assert server_upsert_args.name == "relay-frps"
    assert server_upsert_args.project_root == project_root
    assert server_upsert_args.config_dir == config_dir
    assert server_deploy_args.install_service is True
    assert client_upsert_args.remote_port == 32002
    assert client_prepare_args.name == "relay-public-web"
    assert client_run_once_args.timeout_seconds == 9
    assert client_install_args.name == "relay-public-web"
    assert client_logs_args.lines == 20
    assert client_disable_args.purge_unit_file is True


def test_runtime_path_overrides_set_environment(monkeypatch, tmp_path):
    parser = build_parser()
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    monkeypatch.delenv("WEBU_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("WEBU_CONFIG_DIR", raising=False)

    args = parser.parse_args(
        [
            "server-list",
            "--project-root",
            str(tmp_path),
            "--config-dir",
            str(config_dir),
        ]
    )

    _apply_runtime_path_overrides(args)

    assert Path(os.environ["WEBU_PROJECT_ROOT"]).resolve() == tmp_path.resolve()
    assert Path(os.environ["WEBU_CONFIG_DIR"]).resolve() == config_dir.resolve()
