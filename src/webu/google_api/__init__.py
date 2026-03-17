"""Google 搜索模块 — 基于 ProxyManager + undetected chromedriver。

本地代理列表从 configs/proxies.json 读取，
包含 round-robin 负载均衡、健康检查、自动故障转移和 CAPTCHA 绕过。
"""

from webu._lazy_exports import exported_names, resolve_export

_EXPORTS = {
    "ProxyManager": (".proxy_manager", "ProxyManager"),
    "ProxyState": (".proxy_manager", "ProxyState"),
    "DEFAULT_PROXIES": (".proxy_manager", "DEFAULT_PROXIES"),
    "GoogleScraper": (".scraper", "GoogleScraper"),
    "GoogleResultParser": (".parser", "GoogleResultParser"),
    "GoogleSearchResult": (".parser", "GoogleSearchResult"),
    "GoogleSearchResponse": (".parser", "GoogleSearchResponse"),
}

__all__ = exported_names(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, __name__, _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
