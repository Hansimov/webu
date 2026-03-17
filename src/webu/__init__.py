from ._lazy_exports import exported_names, resolve_export

_EXPORTS = {
    "ChromeClientConfigType": (".browsers.chrome", "ChromeClientConfigType"),
    "ChromeClient": (".browsers.chrome", "ChromeClient"),
    "LLMConfigsType": (".llms.client", "LLMConfigsType"),
    "LLMClient": (".llms.client", "LLMClient"),
    "LLMClientByConfig": (".llms.client", "LLMClientByConfig"),
    "EmbedConfigsType": (".embed", "EmbedConfigsType"),
    "EmbedClient": (".embed", "EmbedClient"),
    "EmbedClientByConfig": (".embed", "EmbedClientByConfig"),
    "GoogleSearchConfigType": (".searches.google", "GoogleSearchConfigType"),
    "GoogleSearcher": (".searches.google", "GoogleSearcher"),
    "WeiboSearchConfigType": (".searches.weibo", "WeiboSearchConfigType"),
    "WeiboSearcher": (".searches.weibo", "WeiboSearcher"),
    "setup_swagger_ui": (".fastapis.styles", "setup_swagger_ui"),
    "GeminiAgency": (".gemini", "GeminiAgency"),
    "GeminiClient": (".gemini", "GeminiClient"),
    "GeminiClientConfig": (".gemini", "GeminiClientConfig"),
    "GeminiBrowser": (".gemini", "GeminiBrowser"),
    "GeminiConfig": (".gemini", "GeminiConfig"),
    "IPv6DBClient": (".ipv6.client", "IPv6DBClient"),
    "IPv6Session": (".ipv6.session", "IPv6Session"),
}

__all__ = exported_names(_EXPORTS)


def __getattr__(name: str):
    if name in {"IPv6DBClient", "IPv6Session"}:
        try:
            return resolve_export(name, __name__, _EXPORTS)
        except Exception:
            return None
    return resolve_export(name, __name__, _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
