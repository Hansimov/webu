from __future__ import annotations

import getpass
import json
import sys

from typing import Any, Iterable


def print_json(payload: Any):
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def add_examples_epilog(examples: Iterable[str]) -> str:
    items = [str(example).strip() for example in examples if str(example).strip()]
    if not items:
        return ""
    lines = ["Examples:"]
    lines.extend(f"  {item}" for item in items)
    return "\n".join(lines)


def root_epilog(
    *, quick_start: Iterable[str] = (), examples: Iterable[str] = ()
) -> str:
    lines: list[str] = []
    quick_items = [str(item).strip() for item in quick_start if str(item).strip()]
    if quick_items:
        lines.append("Quick Start:")
        lines.extend(f"  {item}" for item in quick_items)
        lines.append("")
    example_block = add_examples_epilog(examples)
    if example_block:
        lines.append(example_block)
    return "\n".join(lines).rstrip()


def _ensure_interactive() -> None:
    if not sys.stdin.isatty():
        raise RuntimeError(
            "interactive input is required; pass the value via CLI option or environment variable"
        )


def prompt_text(prompt: str, *, default: str = "", allow_empty: bool = False) -> str:
    _ensure_interactive()
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if default:
            return default
        if allow_empty:
            return ""


def prompt_secret(prompt: str) -> str:
    _ensure_interactive()
    while True:
        value = getpass.getpass(f"{prompt}: ").strip()
        if value:
            return value


def prompt_choice(
    prompt: str, choices: list[str], *, default: str | None = None
) -> str:
    normalized = [str(item).strip() for item in choices if str(item).strip()]
    if not normalized:
        raise ValueError("choices must not be empty")
    _ensure_interactive()
    display = "/".join(normalized)
    default_value = default or normalized[0]
    while True:
        value = input(f"{prompt} [{display}] (default: {default_value}): ").strip()
        selected = value or default_value
        if selected in normalized:
            return selected
