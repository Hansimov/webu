from __future__ import annotations

from importlib import import_module
from typing import Any


def resolve_export(
    name: str,
    package_name: str,
    exports: dict[str, tuple[str, str]],
) -> Any:
    try:
        module_name, attr_name = exports[name]
    except KeyError as exc:
        raise AttributeError(
            f"module {package_name!r} has no attribute {name!r}"
        ) from exc

    module = import_module(module_name, package_name)
    return getattr(module, attr_name)


def exported_names(exports: dict[str, tuple[str, str]]) -> tuple[str, ...]:
    return tuple(exports)
