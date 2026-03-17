from webu._lazy_exports import exported_names, resolve_export

_EXPORTS = {
    "run_http_benchmark": (".benchmark", "run_http_benchmark"),
    "run_manager_benchmark": (".benchmark", "run_manager_benchmark"),
    "GoogleHubBackend": (".manager", "GoogleHubBackend"),
    "GoogleHubManager": (".manager", "GoogleHubManager"),
    "GoogleHubSettings": (".manager", "GoogleHubSettings"),
    "resolve_google_hub_settings": (".manager", "resolve_google_hub_settings"),
    "app_instance": (".server", "app_instance"),
    "create_google_hub_server": (".server", "create_google_hub_server"),
}

__all__ = exported_names(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, __name__, _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
