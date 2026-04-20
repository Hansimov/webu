from __future__ import annotations

from pathlib import Path

from webu.safety_scan import find_forbidden_tracked_paths, scan_text


def test_find_forbidden_tracked_paths_flags_runtime_configs():
    violations = find_forbidden_tracked_paths(
        {"configs/cf_tunnel.json", "configs/ali_esa.json", "README.md"}
    )

    assert any("configs/cf_tunnel.json" in violation for violation in violations)
    assert any("configs/ali_esa.json" in violation for violation in violations)


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
