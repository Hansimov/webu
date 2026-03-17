from webu._lazy_exports import exported_names, resolve_export

_EXPORTS = {
    "main": (".cli", "main"),
    "app_instance": (".server", "app_instance"),
    "create_google_docker_server": (".server", "create_google_docker_server"),
}

__all__ = exported_names(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, __name__, _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
