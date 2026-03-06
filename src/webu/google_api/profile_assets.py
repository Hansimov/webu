from __future__ import annotations

import os

from pathlib import Path

from .profile_bootstrap import DEFAULT_BOOTSTRAP_ARCHIVE_NAME


DEFAULT_SHARED_PROFILE_SECRET = "webu"
TRACKED_PROFILE_ARCHIVE_PATH = (
    Path(__file__).resolve().parent / "assets" / DEFAULT_BOOTSTRAP_ARCHIVE_NAME
)


def resolve_bootstrap_secret() -> str:
    return (
        os.getenv("WEBU_GOOGLE_PROFILE_BOOTSTRAP_SECRET", "").strip()
        or os.getenv("WEBU_GOOGLE_API_TOKEN", "").strip()
        or DEFAULT_SHARED_PROFILE_SECRET
    )


def resolve_default_bootstrap_archive_path() -> Path:
    env_path = os.getenv("WEBU_GOOGLE_PROFILE_BOOTSTRAP_ARCHIVE", "").strip()
    if env_path:
        return Path(env_path).expanduser()
    return TRACKED_PROFILE_ARCHIVE_PATH
