import os

from pathlib import Path

from webu.ssh.cli import _apply_runtime_path_overrides, build_parser


def test_parser_supports_host_exec_copy_and_tunnel_commands():
    parser = build_parser()
    project_root = "/tmp/webu-project"
    config_dir = "/tmp/webu-project/configs"

    list_args = parser.parse_args(["host-list"])
    upsert_args = parser.parse_args(
        [
            "host-upsert",
            "--name",
            "relay-vps",
            "--ip",
            "198.51.100.24",
            "--username",
            "root",
            "--password",
            "secret",
            "--save-config",
            "--project-root",
            project_root,
            "--config-dir",
            config_dir,
        ]
    )
    probe_args = parser.parse_args(["probe", "--name", "relay-vps"])
    exec_args = parser.parse_args(
        ["exec", "--name", "relay-vps", "--command-text", "uname -a"]
    )
    copy_to_args = parser.parse_args(
        [
            "copy-to",
            "--name",
            "relay-vps",
            "--local-path",
            "README.md",
            "--remote-path",
            "/tmp/README.md",
        ]
    )
    copy_from_args = parser.parse_args(
        [
            "copy-from",
            "--name",
            "relay-vps",
            "--remote-path",
            "/tmp/README.md",
            "--local-path",
            "debugs/README.md",
        ]
    )
    tunnel_upsert_args = parser.parse_args(
        [
            "tunnel-upsert",
            "--name",
            "relay-prod",
            "--host-name",
            "relay-vps",
            "--mode",
            "remote",
            "--local-port",
            "20002",
            "--remote-port",
            "32002",
            "--save-config",
        ]
    )
    tunnel_command_args = parser.parse_args(["tunnel-command", "--name", "relay-prod"])
    tunnel_install_args = parser.parse_args(
        ["tunnel-service-install", "--name", "relay-prod", "--user"]
    )
    tunnel_status_args = parser.parse_args(
        ["tunnel-service-status", "--name", "relay-prod", "--user"]
    )
    tunnel_logs_args = parser.parse_args(
        ["tunnel-service-logs", "--name", "relay-prod", "--lines", "25", "--user"]
    )
    tunnel_restart_args = parser.parse_args(
        ["tunnel-service-restart", "--name", "relay-prod", "--user"]
    )
    tunnel_disable_args = parser.parse_args(
        [
            "tunnel-service-disable",
            "--name",
            "relay-prod",
            "--purge-unit-file",
            "--user",
        ]
    )

    assert list_args.command == "host-list"
    assert upsert_args.name == "relay-vps"
    assert upsert_args.project_root == project_root
    assert upsert_args.config_dir == config_dir
    assert probe_args.timeout_seconds == 15
    assert exec_args.command_text == "uname -a"
    assert copy_to_args.remote_path == "/tmp/README.md"
    assert copy_from_args.local_path == "debugs/README.md"
    assert tunnel_upsert_args.remote_port == 32002
    assert tunnel_command_args.command == "tunnel-command"
    assert tunnel_install_args.name == "relay-prod"
    assert tunnel_install_args.use_user_systemd is True
    assert tunnel_status_args.name == "relay-prod"
    assert tunnel_status_args.use_user_systemd is True
    assert tunnel_logs_args.lines == 25
    assert tunnel_logs_args.use_user_systemd is True
    assert tunnel_restart_args.name == "relay-prod"
    assert tunnel_restart_args.use_user_systemd is True
    assert tunnel_disable_args.purge_unit_file is True
    assert tunnel_disable_args.use_user_systemd is True


def test_runtime_path_overrides_set_environment(monkeypatch, tmp_path):
    parser = build_parser()
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    monkeypatch.delenv("WEBU_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("WEBU_CONFIG_DIR", raising=False)

    args = parser.parse_args(
        [
            "host-list",
            "--project-root",
            str(tmp_path),
            "--config-dir",
            str(config_dir),
        ]
    )

    _apply_runtime_path_overrides(args)

    assert Path(os.environ["WEBU_PROJECT_ROOT"]).resolve() == tmp_path.resolve()
    assert Path(os.environ["WEBU_CONFIG_DIR"]).resolve() == config_dir.resolve()
