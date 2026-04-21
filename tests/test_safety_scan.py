from __future__ import annotations

import json
import subprocess

from pathlib import Path

from webu.safety_scan import find_forbidden_tracked_paths, scan_text, scan_tracked_files


def test_find_forbidden_tracked_paths_flags_runtime_configs():
    violations = find_forbidden_tracked_paths(
        {
            "configs/cf_tunnel.json",
            "configs/ali_esa.json",
            "configs/ddns.json",
            "configs/ssh.json",
            "configs/frp.json",
            "README.md",
        }
    )

    assert any("configs/cf_tunnel.json" in violation for violation in violations)
    assert any("configs/ali_esa.json" in violation for violation in violations)
    assert any("configs/ddns.json" in violation for violation in violations)
    assert any("configs/ssh.json" in violation for violation in violations)
    assert any("configs/frp.json" in violation for violation in violations)


def test_scan_text_detects_local_sensitive_value_leaks(tmp_path):
    path = tmp_path / "docs" / "usage.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    violations = scan_text(
        path,
        "Expose corp.invalid through the edge gateway.",
        root=tmp_path,
        sensitive_values=["corp.invalid"],
    )

    assert any("leaked local sensitive values" in violation for violation in violations)


def test_scan_text_skips_runtime_config_content_for_local_value_leaks(tmp_path):
    path = tmp_path / "configs" / "ali_esa.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    violations = scan_text(
        path,
        '{"site_name": "corp.invalid"}',
        root=tmp_path,
        sensitive_values=["corp.invalid"],
    )

    assert violations == []


def test_scan_text_ignores_templated_secret_assignments_in_renderer_code(tmp_path):
    path = tmp_path / "src" / "webu" / "frp" / "operations.py"
    path.parent.mkdir(parents=True, exist_ok=True)

    violations = scan_text(
        path,
        "return [f'auth.token = \"{auth_token}\"', f'auth.token = \"{server.auth_token}\"']",
        root=tmp_path,
        sensitive_values=[],
    )

    assert violations == []


def test_scan_tracked_files_detects_typescript_leaks_from_runtime_configs(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "ssh.json").write_text(
        json.dumps(
            {
                "hosts": [
                    {
                        "name": "relay-vps",
                        "ip": "198.51.100.24",
                        "username": "root",
                        "password": "secret",
                    }
                ],
                "tunnels": [],
            }
        ),
        encoding="utf-8",
    )

    source_path = tmp_path / "frontend" / "src" / "relay.ts"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        'export const relayHost = "relay-vps";\nexport const relayIp = "198.51.100.24";\n',
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "configs/ssh.json", "frontend/src/relay.ts"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    violations = scan_tracked_files(tmp_path)

    assert any(
        "frontend/src/relay.ts: leaked local sensitive values" in violation
        for violation in violations
    )
    assert any(
        "relay-vps" in violation or "198.51.100.24" in violation
        for violation in violations
    )


def test_scan_tracked_files_detects_systemd_unit_leaks_from_runtime_configs(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "ddns.json").write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "name": "home-ddns",
                        "site_name": "corp.invalid",
                        "record_name": "home.corp.invalid",
                        "pool_name": "home-pool",
                        "origin_name": "origin-alpha",
                        "target_ipv6": "2001:db8:1::10",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    unit_path = tmp_path / "configs" / "systemd" / "home-ddns.service"
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    unit_path.write_text(
        "[Service]\nEnvironment=TARGET_RECORD=home.corp.invalid\n",
        encoding="utf-8",
    )

    subprocess.run(
        ["git", "add", "configs/ddns.json", "configs/systemd/home-ddns.service"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    violations = scan_tracked_files(tmp_path)

    assert any(
        "configs/systemd/home-ddns.service: leaked local sensitive values" in violation
        for violation in violations
    )
    assert any("home.corp.invalid" in violation for violation in violations)
