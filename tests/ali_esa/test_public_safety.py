from __future__ import annotations

import json

from pathlib import Path

from webu.safety_scan import should_scan
from webu.runtime_settings import (
    collect_sensitive_local_values,
    find_sensitive_text_leaks,
)


def test_collect_sensitive_local_values_extracts_ali_esa_runtime_fields(tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "ali_esa.json").write_text(
        json.dumps(
            {
                "default_public_origin_ipv6": "2001:db8:1::10",
                "sites": [
                    {
                        "site_name": "corp.invalid",
                        "instance_id": "esa-site-private-001",
                        "cloudflare_zone_id": "zone-private-001",
                        "name_server_list": [
                            "ns1.private.invalid",
                            "ns2.private.invalid",
                        ],
                        "public_origin_address": "2001:db8:1::20",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    values = collect_sensitive_local_values(config_dir)

    assert "corp.invalid" in values
    assert "esa-site-private-001" in values
    assert "zone-private-001" in values
    assert "ns1.private.invalid" in values
    assert "2001:db8:1::10" in values


def test_collect_sensitive_local_values_extracts_ssh_and_frp_runtime_fields(tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
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
                "tunnels": [
                    {
                        "name": "relay-prod",
                        "host_name": "relay-vps",
                        "local_port": 20002,
                        "remote_port": 32002,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "frp.json").write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "relay-frps",
                        "ssh_host_name": "relay-vps",
                        "auth_token": "secret",
                        "remote_binary_path": "/root/frps",
                        "remote_config_path": "/root/frps.toml",
                    }
                ],
                "clients": [
                    {
                        "name": "relay-public-web",
                        "server_name": "relay-frps",
                        "server_addr": "198.51.100.24",
                        "local_port": 20002,
                        "remote_port": 32002,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    values = collect_sensitive_local_values(config_dir)

    assert "relay-vps" in values
    assert "relay-prod" in values
    assert "relay-frps" in values
    assert "198.51.100.24" in values


def test_collect_sensitive_local_values_extracts_ddns_runtime_fields(tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
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
                        "client_secret": "secret",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    values = collect_sensitive_local_values(config_dir)

    assert "home-ddns" in values
    assert "home.corp.invalid" in values
    assert "home-pool" in values
    assert "origin-alpha" in values
    assert "2001:db8:1::10" in values


def test_public_ali_esa_and_cf_tunnel_sources_do_not_leak_local_sensitive_values():
    project_root = Path(__file__).resolve().parents[2]
    sensitive_values = collect_sensitive_local_values(project_root / "configs")

    target_paths = sorted(
        path
        for base_name in ["docs", "src", "tests"]
        for path in (project_root / base_name).rglob("*")
        if path.is_file() and should_scan(path)
    )

    leaked = {}
    for path in target_paths:
        text = path.read_text(encoding="utf-8")
        leaks = find_sensitive_text_leaks(text, sensitive_values=sensitive_values)
        if leaks:
            leaked[str(path)] = leaks

    assert leaked == {}
