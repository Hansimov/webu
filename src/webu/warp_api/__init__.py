from webu._lazy_exports import exported_names, resolve_export

_EXPORTS = {
    "WARP_INTERFACE": (".constants", "WARP_INTERFACE"),
    "WARP_PROXY_HOST": (".constants", "WARP_PROXY_HOST"),
    "WARP_PROXY_PORT": (".constants", "WARP_PROXY_PORT"),
    "WARP_API_HOST": (".constants", "WARP_API_HOST"),
    "WARP_API_PORT": (".constants", "WARP_API_PORT"),
    "DATA_DIR": (".constants", "DATA_DIR"),
    "WarpClient": (".warp", "WarpClient"),
    "WarpSocksProxy": (".proxy", "WarpSocksProxy"),
    "fix_tailscale_compat": (".netfix", "fix_tailscale_compat"),
    "check_tailscale_compat": (".netfix", "check_tailscale_compat"),
}

__all__ = exported_names(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, __name__, _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
