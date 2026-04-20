from __future__ import annotations

import json

from pathlib import Path

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


def test_public_ali_esa_and_cf_tunnel_sources_do_not_leak_local_sensitive_values():
    project_root = Path(__file__).resolve().parents[2]
    sensitive_values = collect_sensitive_local_values(project_root / "configs")

    target_paths = [
        project_root / "src" / "webu" / "ali_esa" / "schema.py",
        project_root / "src" / "webu" / "ali_esa" / "operations.py",
        project_root / "src" / "webu" / "ali_esa" / "cli.py",
        project_root / "tests" / "cf_tunnel" / "test_cli.py",
        project_root / "tests" / "cf_tunnel" / "test_guard.py",
        project_root / "tests" / "cf_tunnel" / "test_snapshot.py",
    ]

    leaked = {}
    for path in target_paths:
        text = path.read_text(encoding="utf-8")
        leaks = find_sensitive_text_leaks(text, sensitive_values=sensitive_values)
        if leaks:
            leaked[str(path)] = leaks

    assert leaked == {}
