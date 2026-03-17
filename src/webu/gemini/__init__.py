from webu._lazy_exports import exported_names, resolve_export

_EXPORTS = {
    "GeminiAgency": (".agency", "GeminiAgency"),
    "GeminiBrowser": (".browser", "GeminiBrowser"),
    "ChatDatabase": (".chatdb", "ChatDatabase"),
    "ChatSession": (".chatdb", "ChatSession"),
    "ChatMessage": (".chatdb", "ChatMessage"),
    "GeminiClient": (".client", "GeminiClient"),
    "GeminiClientConfig": (".client", "GeminiClientConfig"),
    "GeminiConfig": (".config", "GeminiConfig"),
    "GeminiError": (".errors", "GeminiError"),
    "GeminiLoginRequiredError": (".errors", "GeminiLoginRequiredError"),
    "GeminiNetworkError": (".errors", "GeminiNetworkError"),
    "GeminiTimeoutError": (".errors", "GeminiTimeoutError"),
    "GeminiResponseParseError": (".errors", "GeminiResponseParseError"),
    "GeminiImageGenerationError": (".errors", "GeminiImageGenerationError"),
    "GeminiBrowserError": (".errors", "GeminiBrowserError"),
    "GeminiPageError": (".errors", "GeminiPageError"),
    "GeminiRateLimitError": (".errors", "GeminiRateLimitError"),
    "GeminiServerRollbackError": (".errors", "GeminiServerRollbackError"),
    "GeminiImageDownloadError": (".errors", "GeminiImageDownloadError"),
    "GeminiResponse": (".parser", "GeminiResponse"),
    "GeminiResponseParser": (".parser", "GeminiResponseParser"),
    "GeminiImage": (".parser", "GeminiImage"),
    "GeminiCodeBlock": (".parser", "GeminiCodeBlock"),
    "GeminiRunner": (".run", "GeminiRunner"),
    "create_gemini_server": (".server", "create_gemini_server"),
    "run_gemini_server": (".server", "run_gemini_server"),
}

__all__ = exported_names(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, __name__, _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
