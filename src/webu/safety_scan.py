from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from webu.runtime_settings import (
    collect_sensitive_local_values,
    find_sensitive_text_leaks,
)


TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".env",
    ".gitignore",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
HIGH_CONFIDENCE_PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:[A-Z ]+)?PRIVATE KEY-----"),
    "openai-key": re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{16,}"),
    "github-token": re.compile(
        r"(?<![A-Za-z0-9])(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"
    ),
    "google-api-key": re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z\-_]{20,}"),
}
ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|secret|password)\s*[\"']?\s*[:=]\s*[\"']([^\"'\n]{8,})[\"']"
)
SENSITIVE_CONFIG_NAME_TOKENS = ("secret", "token", "credential", "password")
SENSITIVE_RUNTIME_CONFIG_BASENAMES = {"ali_esa.json", "cf_tunnel.json", "ddns.json"}
SAFE_TEMPLATE_MARKERS = (".example", ".sample", ".template")
SAFE_BINARY_EXTENSIONS = {".crt", ".example", ".md", ".sample", ".template"}


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    files: list[Path] = []
    for rel_path in result.stdout.split(b"\0"):
        if not rel_path:
            continue
        path = root / rel_path.decode("utf-8")
        if path.exists():
            files.append(path)
    return files


def staged_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [
        root / rel_path.decode("utf-8")
        for rel_path in result.stdout.split(b"\0")
        if rel_path
    ]


def should_scan(path: Path) -> bool:
    return (
        any(suffix in TEXT_SUFFIXES for suffix in path.suffixes)
        or path.name in TEXT_SUFFIXES
    )


def read_text_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def read_staged_text_file(path: Path, root: Path) -> str | None:
    rel_path = path.relative_to(root).as_posix()
    try:
        result = subprocess.run(
            ["git", "show", f":{rel_path}"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        return None

    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def is_placeholder_secret(value: str) -> bool:
    stripped = value.strip()
    lowered = stripped.lower()
    if not stripped:
        return True
    if "*" in stripped:
        return True
    if stripped.startswith("${{") or stripped.startswith("$"):
        return True
    if stripped.startswith("<") and stripped.endswith(">"):
        return True
    if re.fullmatch(r"[A-Z][A-Z0-9_]{5,}", stripped):
        return True
    if all(ch in "*._-" for ch in stripped):
        return True
    if lowered.startswith(("test-", "dummy-", "fake-", "mock-", "example-")):
        return True
    if lowered.startswith(("your-", "your_", "set-", "replace-")):
        return True
    if lowered in {"test-key", "dummy-key", "fake-key", "mock-key"}:
        return True
    if "example" in lowered or "placeholder" in lowered or "replace-me" in lowered:
        return True
    if re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+){0,4}", lowered):
        placeholder_tokens = {
            "admin",
            "bootstrap",
            "dev",
            "demo",
            "dummy",
            "example",
            "existing",
            "fake",
            "local",
            "mock",
            "new",
            "sample",
            "secret",
            "test",
            "token",
        }
        parts = re.split(r"[-_]", lowered)
        if any(part in placeholder_tokens or part.startswith("demo") for part in parts):
            return True
    if stripped.startswith("http://") or stripped.startswith("https://"):
        return True
    return False


def _is_safe_template_path(relpath: str) -> bool:
    lowered = relpath.lower()
    return any(marker in lowered for marker in SAFE_TEMPLATE_MARKERS)


def find_forbidden_tracked_paths(tracked_relpaths: set[str]) -> list[str]:
    violations: list[str] = []
    for relpath in sorted(tracked_relpaths):
        lowered = relpath.lower()
        file_name = Path(relpath).name.lower()
        suffix = Path(relpath).suffix.lower()
        if file_name.startswith(".env") and not _is_safe_template_path(relpath):
            violations.append(f"{relpath} should not be tracked directly")
            continue
        if (
            relpath.startswith("configs/")
            and file_name in SENSITIVE_RUNTIME_CONFIG_BASENAMES
            and not _is_safe_template_path(relpath)
        ):
            violations.append(
                f"{relpath} is a local runtime config and should stay out of git"
            )
            continue
        if (
            relpath.startswith("configs/")
            and any(token in file_name for token in SENSITIVE_CONFIG_NAME_TOKENS)
            and not _is_safe_template_path(relpath)
        ):
            violations.append(
                f"{relpath} should be kept out of git or stored as an example template"
            )
            continue
        if suffix in {".key", ".pem", ".p12"} and suffix not in SAFE_BINARY_EXTENSIONS:
            violations.append(
                f"{relpath} looks like a key or certificate artifact and should not be tracked"
            )
            continue
        if lowered.endswith(".env") and not _is_safe_template_path(relpath):
            violations.append(f"{relpath} should not be tracked directly")
    return violations


def display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _local_sensitive_leak_violations(
    path: Path,
    text: str,
    *,
    root: Path,
    sensitive_values: list[str],
) -> list[str]:
    relpath = display_path(path, root)
    if relpath.startswith("configs/"):
        return []
    leaks = find_sensitive_text_leaks(text, sensitive_values=sensitive_values)
    if not leaks:
        return []
    preview = ", ".join(sorted(set(leaks))[:3])
    return [f"{relpath}: leaked local sensitive values ({preview})"]


def scan_text(
    path: Path,
    text: str,
    *,
    root: Path,
    sensitive_values: list[str],
) -> list[str]:
    violations: list[str] = []
    for label, pattern in HIGH_CONFIDENCE_PATTERNS.items():
        if pattern.search(text):
            violations.append(f"{display_path(path, root)}: matched {label}")

    for match in ASSIGNMENT_PATTERN.finditer(text):
        key_name = match.group(1)
        value = match.group(2)
        if not is_placeholder_secret(value):
            violations.append(
                f"{display_path(path, root)}: {key_name} appears to contain a live secret"
            )

    violations.extend(
        _local_sensitive_leak_violations(
            path,
            text,
            root=root,
            sensitive_values=sensitive_values,
        )
    )
    return violations


def scan_tracked_files(root: Path) -> list[str]:
    violations: list[str] = []
    tracked = tracked_files(root)
    tracked_relpaths = {path.relative_to(root).as_posix() for path in tracked}
    sensitive_values = collect_sensitive_local_values(root / "configs")
    violations.extend(find_forbidden_tracked_paths(tracked_relpaths))

    for path in tracked:
        if not should_scan(path):
            continue
        text = read_text_file(path)
        if text is None:
            continue
        violations.extend(
            scan_text(path, text, root=root, sensitive_values=sensitive_values)
        )

    return violations


def scan_staged_files(root: Path) -> list[str]:
    violations: list[str] = []
    staged = staged_files(root)
    staged_relpaths = {path.relative_to(root).as_posix() for path in staged}
    sensitive_values = collect_sensitive_local_values(root / "configs")
    violations.extend(find_forbidden_tracked_paths(staged_relpaths))

    for path in staged:
        if not should_scan(path):
            continue
        text = read_staged_text_file(path, root)
        if text is None:
            continue
        violations.extend(
            scan_text(path, text, root=root, sensitive_values=sensitive_values)
        )

    return violations


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
        default=".",
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
