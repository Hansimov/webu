from pathlib import Path

from webu.runtime_settings import (
    collect_sensitive_local_values,
    find_sensitive_text_leaks,
)


def test_public_docs_and_test_sources_do_not_leak_local_sensitive_values():
    project_root = Path(__file__).resolve().parents[2]
    sensitive_values = collect_sensitive_local_values(project_root / "configs")

    target_paths = [
        project_root / "docs" / "google-docker" / "USAGE.md",
        project_root / "docs" / "google-docker" / "SETUP.md",
        project_root / "docs" / "google-docker" / "HINTS.md",
        project_root / "docs" / "google-docker" / "CONFIGS.md",
        project_root / "src" / "webu" / "google_docker" / "helptext.py",
        project_root / "src" / "webu" / "runtime_settings" / "schema.py",
        project_root / "tests" / "google_docker" / "test_cli.py",
        project_root / "tests" / "google_hub" / "test_hub_server.py",
    ]

    leaked = {}
    for path in target_paths:
        text = path.read_text(encoding="utf-8")
        leaks = find_sensitive_text_leaks(text, sensitive_values=sensitive_values)
        if leaks:
            leaked[str(path)] = leaks

    assert leaked == {}
