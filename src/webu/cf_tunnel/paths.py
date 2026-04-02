from __future__ import annotations

import os

from pathlib import Path

from webu.schema import find_project_root


DEFAULT_SNAPSHOT_OUTPUT_DIR = Path("debugs/cf-tunnel-snapshots")
SNAPSHOT_OUTPUT_ENV_VAR = "WEBU_CF_TUNNEL_SNAPSHOT_OUTPUT_DIR"


def _resolve_project_root(project_root: Path | None = None) -> Path:
    base = project_root or find_project_root()
    return Path(base).expanduser().resolve()


def _shared_snapshot_root_from_env(project_root: Path) -> Path | None:
    raw_value = os.environ.get(SNAPSHOT_OUTPUT_ENV_VAR, "").strip()
    if not raw_value:
        return None
    candidate = Path(raw_value).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate.resolve()


def _sibling_blbl_dash_snapshot_root(project_root: Path) -> Path | None:
    sibling_root = project_root.parent / "blbl-dash"
    marker = sibling_root / "configs" / "services" / "dash.api.yaml"
    if not marker.exists():
        return None
    return (sibling_root / DEFAULT_SNAPSHOT_OUTPUT_DIR).resolve()


def default_snapshot_output_dir(project_root: Path | None = None) -> Path:
    resolved_project_root = _resolve_project_root(project_root)
    env_override = _shared_snapshot_root_from_env(resolved_project_root)
    if env_override is not None:
        return env_override

    sibling_root = _sibling_blbl_dash_snapshot_root(resolved_project_root)
    if sibling_root is not None:
        return sibling_root

    return (resolved_project_root / DEFAULT_SNAPSHOT_OUTPUT_DIR).resolve()


def resolve_snapshot_output_dir(
    output_dir: Path,
    *,
    project_root: Path | None = None,
) -> Path:
    resolved_project_root = _resolve_project_root(project_root)
    expanded = Path(output_dir).expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    if expanded == DEFAULT_SNAPSHOT_OUTPUT_DIR:
        return default_snapshot_output_dir(resolved_project_root)
    return (resolved_project_root / expanded).resolve()
