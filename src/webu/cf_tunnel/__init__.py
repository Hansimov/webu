from webu._lazy_exports import exported_names, resolve_export

_EXPORTS = {
    "build_parser": (".cli", "build_parser"),
    "main": (".cli", "main"),
    "access_diagnose": (".operations", "access_diagnose"),
    "apply_tunnel": (".operations", "apply_tunnel"),
    "capture_canary_snapshot": (".snapshot", "capture_canary_snapshot"),
    "client_canary_bundle": (".operations", "client_canary_bundle"),
    "client_override_plan": (".operations", "client_override_plan"),
    "client_report_summary": (".operations", "client_report_summary"),
    "client_report_template": (".operations", "client_report_template"),
    "config_check": (".operations", "config_check"),
    "config_init": (".operations", "config_init"),
    "docs_sync": (".operations", "docs_sync"),
    "edge_trace": (".operations", "edge_trace"),
    "ensure_token": (".operations", "ensure_token"),
    "guard_tunnel_quality": (".operations", "guard_tunnel_quality"),
    "migrate_dns_to_cloudflare": (".operations", "migrate_dns_to_cloudflare"),
    "page_audit": (".operations", "page_audit"),
    "stabilize_tunnel": (".operations", "stabilize_tunnel"),
    "tunnel_status": (".operations", "tunnel_status"),
}

__all__ = exported_names(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, __name__, _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
