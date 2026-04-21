from pathlib import Path

import subprocess

from webu.ssh.operations import host_list, tunnel_command
from webu.ssh.schema import load_ssh_config


def test_load_ssh_config_normalizes_legacy_host_list(monkeypatch):
    monkeypatch.setattr(
        "webu.ssh.schema.load_json_config",
        lambda spec, validate=False: [
            {
                "name": "relay-vps",
                "ip": "198.51.100.24",
                "username": "root",
                "password": "secret",
            }
        ],
    )

    payload = load_ssh_config()

    assert list(payload) == ["hosts", "tunnels"]
    assert len(payload["hosts"]) == 1
    assert payload["tunnels"] == []


def test_tunnel_command_uses_sshpass_for_password_hosts(monkeypatch):
    payload = {
        "hosts": [
            {
                "name": "relay-vps",
                "ip": "198.51.100.24",
                "username": "root",
                "password": "secret",
            }
        ],
        "tunnels": [
            {
                "name": "relay-prod",
                "host_name": "relay-vps",
                "mode": "remote",
                "local_host": "127.0.0.1",
                "local_port": 20002,
                "remote_host": "127.0.0.1",
                "remote_port": 32002,
            }
        ],
    }
    monkeypatch.setattr(
        "webu.ssh.operations.load_ssh_config", lambda validate=False: payload
    )

    result = tunnel_command(name="relay-prod")

    assert result["forward_spec"] == "127.0.0.1:32002:127.0.0.1:20002"
    assert "sshpass" in result["command"]
    assert "SSHPASS=secret" in result["command"]


def test_host_list_redacts_password_field(monkeypatch):
    payload = {
        "hosts": [
            {
                "name": "relay-vps",
                "ip": "198.51.100.24",
                "username": "root",
                "password": "secret",
                "notes": "edge relay",
            }
        ],
        "tunnels": [],
    }
    monkeypatch.setattr(
        "webu.ssh.operations.load_ssh_config", lambda validate=False: payload
    )

    result = host_list()

    assert result["count"] == 1
    assert "password" not in result["hosts"][0]


def test_tunnel_service_install_supports_user_systemd(monkeypatch, tmp_path):
    from webu.ssh.operations import tunnel_service_install

    payload = {
        "hosts": [
            {
                "name": "relay-vps",
                "ip": "198.51.100.24",
                "username": "root",
                "password": "secret",
            }
        ],
        "tunnels": [
            {
                "name": "relay-prod",
                "host_name": "relay-vps",
                "mode": "remote",
                "local_host": "127.0.0.1",
                "local_port": 20002,
                "remote_host": "127.0.0.1",
                "remote_port": 32002,
            }
        ],
    }
    commands: list[tuple[list[str], bool]] = []
    installed_unit = {"text": ""}

    def fake_sudo_run(
        command, *, use_sudo=True, check=False, capture_output=True, **kwargs
    ):
        commands.append((list(command), use_sudo))
        if command[:3] == ["install", "-m", "0644"]:
            installed_unit["text"] = Path(command[3]).read_text(encoding="utf-8")
        return subprocess.CompletedProcess(list(command), 0, b"", b"")

    monkeypatch.setattr(
        "webu.ssh.operations.load_ssh_config", lambda validate=False: payload
    )
    monkeypatch.setattr("webu.ssh.operations.sudo_run", fake_sudo_run)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = tunnel_service_install(name="relay-prod", use_user_systemd=True)

    assert result["systemd_scope"] == "user"
    assert result["service_path"] == str(
        tmp_path / ".config/systemd/user/webu-ssh-tunnel-relay-prod.service"
    )
    assert any(
        command == ["mkdir", "-p", str(tmp_path / ".config/systemd/user")]
        and not use_sudo
        for command, use_sudo in commands
    )
    assert any(
        command == ["systemctl", "--user", "daemon-reload"] and not use_sudo
        for command, use_sudo in commands
    )
    assert any(
        command
        == ["systemctl", "--user", "enable", "webu-ssh-tunnel-relay-prod.service"]
        and not use_sudo
        for command, use_sudo in commands
    )
    assert any(
        command
        == ["systemctl", "--user", "restart", "webu-ssh-tunnel-relay-prod.service"]
        and not use_sudo
        for command, use_sudo in commands
    )
    assert "WantedBy=default.target" in installed_unit["text"]
    assert "network-online.target" not in installed_unit["text"]


def test_tunnel_service_status_uses_user_systemd(monkeypatch):
    from webu.ssh.operations import tunnel_service_status

    payload = {
        "hosts": [
            {
                "name": "relay-vps",
                "ip": "198.51.100.24",
                "username": "root",
                "password": "secret",
            }
        ],
        "tunnels": [
            {
                "name": "relay-prod",
                "host_name": "relay-vps",
                "mode": "remote",
                "local_host": "127.0.0.1",
                "local_port": 20002,
                "remote_host": "127.0.0.1",
                "remote_port": 32002,
            }
        ],
    }
    commands: list[tuple[list[str], bool]] = []

    def fake_sudo_run(
        command, *, use_sudo=True, check=False, capture_output=True, **kwargs
    ):
        commands.append((list(command), use_sudo))
        if command[-2:] == ["is-active", "webu-ssh-tunnel-relay-prod.service"]:
            return subprocess.CompletedProcess(list(command), 0, b"active\n", b"")
        if command[-2:] == ["is-enabled", "webu-ssh-tunnel-relay-prod.service"]:
            return subprocess.CompletedProcess(list(command), 0, b"enabled\n", b"")
        return subprocess.CompletedProcess(list(command), 0, b"", b"")

    monkeypatch.setattr(
        "webu.ssh.operations.load_ssh_config", lambda validate=False: payload
    )
    monkeypatch.setattr("webu.ssh.operations.sudo_run", fake_sudo_run)

    result = tunnel_service_status(name="relay-prod", use_user_systemd=True)

    assert result["systemd_scope"] == "user"
    assert result["is_active"] is True
    assert result["is_enabled"] is True
    assert any(
        command
        == [
            "systemctl",
            "--user",
            "show",
            "webu-ssh-tunnel-relay-prod.service",
            "--no-pager",
            "--property=ActiveState,SubState,UnitFileState,FragmentPath,ExecMainStatus",
        ]
        and not use_sudo
        for command, use_sudo in commands
    )
    assert any(
        command
        == ["systemctl", "--user", "is-active", "webu-ssh-tunnel-relay-prod.service"]
        and not use_sudo
        for command, use_sudo in commands
    )
    assert any(
        command
        == ["systemctl", "--user", "is-enabled", "webu-ssh-tunnel-relay-prod.service"]
        and not use_sudo
        for command, use_sudo in commands
    )
