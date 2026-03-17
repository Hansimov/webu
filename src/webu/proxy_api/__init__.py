from webu._lazy_exports import exported_names, resolve_export

_EXPORTS = {
    "MONGO_CONFIGS": (".constants", "MONGO_CONFIGS"),
    "PROXY_SOURCES": (".constants", "PROXY_SOURCES"),
    "MongoConfigsType": (".constants", "MongoConfigsType"),
    "ProxySourceType": (".constants", "ProxySourceType"),
    "ABANDONED_FAIL_THRESHOLD": (".constants", "ABANDONED_FAIL_THRESHOLD"),
    "ABANDONED_STALE_HOURS": (".constants", "ABANDONED_STALE_HOURS"),
    "ABANDONED_COOLDOWN_HOURS": (".constants", "ABANDONED_COOLDOWN_HOURS"),
    "FETCH_PROXY": (".constants", "FETCH_PROXY"),
    "PROXY_CHECK_TIMEOUT": (".constants", "PROXY_CHECK_TIMEOUT"),
    "CHECK_CONCURRENCY": (".constants", "CHECK_CONCURRENCY"),
    "USER_AGENTS": (".constants", "USER_AGENTS"),
    "VIEWPORT_SIZES": (".constants", "VIEWPORT_SIZES"),
    "LOCALES": (".constants", "LOCALES"),
    "MongoProxyStore": (".mongo", "MongoProxyStore"),
    "ProxyCollector": (".collector", "ProxyCollector"),
    "check_level1_batch": (".checker", "check_level1_batch"),
    "build_proxy_url": (".checker", "build_proxy_url"),
    "ProxyPool": (".pool", "ProxyPool"),
}

__all__ = exported_names(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, __name__, _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
