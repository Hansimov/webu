#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from webu.safety_scan import scan_staged_files, scan_tracked_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan repository files for secrets")
    parser.add_argument(
        "--fast",
        action="store_true",
        default=False,
        help="Scan only staged files from the git index for faster pre-commit checks",
    )
    parser.add_argument(
        "--root",
        default=str(REPO_ROOT),
        help="Repository root to scan.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    violations = scan_staged_files(root) if args.fast else scan_tracked_files(root)
    mode = "fast staged" if args.fast else "full"

    if violations:
        print(f"Sensitive information scan failed ({mode} mode):")
        for violation in violations:
            print(f"- {violation}")
        return 1

    print(f"Sensitive information scan passed ({mode} mode).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
