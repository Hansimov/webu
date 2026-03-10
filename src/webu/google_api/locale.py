from __future__ import annotations

import re

from dataclasses import dataclass


_LANGUAGE_LOCALE_DEFAULTS = {
    "ar": "ar-SA",
    "de": "de-DE",
    "en": "en-US",
    "es": "es-ES",
    "fr": "fr-FR",
    "he": "he-IL",
    "hi": "hi-IN",
    "it": "it-IT",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "pt": "pt-BR",
    "ru": "ru-RU",
    "th": "th-TH",
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh-tw": "zh-TW",
}

_SCRIPT_RULES = [
    (re.compile(r"[\u3040-\u30ff]"), "ja", "ja-JP"),
    (re.compile(r"[\uac00-\ud7af]"), "ko", "ko-KR"),
    (re.compile(r"[\u0400-\u04ff]"), "ru", "ru-RU"),
    (re.compile(r"[\u0600-\u06ff]"), "ar", "ar-SA"),
    (re.compile(r"[\u0590-\u05ff]"), "he", "he-IL"),
    (re.compile(r"[\u0e00-\u0e7f]"), "th", "th-TH"),
    (re.compile(r"[\u0900-\u097f]"), "hi", "hi-IN"),
]

_TRADITIONAL_CHINESE_MARKERS = set("體臺萬與專業學習關鍵網頁資訊裡這麼讓還應搜尋軟體")
_SIMPLIFIED_CHINESE_MARKERS = set("体台万与专业学习关键网页资讯里这么让还应搜索软件")

_LATIN_LANGUAGE_HINTS = {
    "fr": {
        "tokens": {"avec", "bonjour", "comment", "dans", "pour", "une"},
        "chars": set("àâçéèêëîïôùûüÿœæ"),
        "locale": "fr-FR",
    },
    "de": {
        "tokens": {"bitte", "danke", "für", "mit", "und", "wie"},
        "chars": set("äöüß"),
        "locale": "de-DE",
    },
    "es": {
        "tokens": {"como", "con", "para", "por", "que", "una"},
        "chars": set("áéíñóúü¿¡"),
        "locale": "es-ES",
    },
    "pt": {
        "tokens": {"como", "com", "para", "por", "que", "uma"},
        "chars": set("ãáâàçéêíóôõú"),
        "locale": "pt-BR",
    },
    "it": {
        "tokens": {"come", "con", "della", "per", "una", "ciao"},
        "chars": set("àèéìíîòóù"),
        "locale": "it-IT",
    },
}


@dataclass(frozen=True)
class SearchLocaleProfile:
    lang: str
    locale: str
    navigator_languages: list[str]
    accept_language_header: str


def _normalize_token(value: str | None) -> str:
    return str(value or "").strip().replace("_", "-")


def _lang_from_locale(locale: str) -> str:
    normalized = _normalize_token(locale).lower()
    if normalized.startswith("zh-"):
        return normalized.upper().replace("ZH-", "zh-")
    return normalized.split("-", 1)[0] if normalized else ""


def _base_language(value: str) -> str:
    normalized = _normalize_token(value).lower()
    return normalized.split("-", 1)[0] if normalized else ""


def _default_locale_for_lang(lang: str) -> str:
    normalized = _normalize_token(lang).lower()
    if not normalized:
        return _LANGUAGE_LOCALE_DEFAULTS["en"]
    return _LANGUAGE_LOCALE_DEFAULTS.get(normalized) or _LANGUAGE_LOCALE_DEFAULTS.get(
        normalized.split("-", 1)[0],
        _LANGUAGE_LOCALE_DEFAULTS["en"],
    )


def _build_accept_language_header(locale: str, lang: str) -> str:
    values: list[str] = []
    for candidate in [locale, lang, "en-US", "en"]:
        normalized = _normalize_token(candidate)
        if normalized and normalized not in values:
            values.append(normalized)
    weighted: list[str] = []
    for index, value in enumerate(values):
        if index == 0:
            weighted.append(value)
        else:
            quality = max(0.1, 1.0 - index * 0.1)
            weighted.append(f"{value};q={quality:.1f}")
    return ", ".join(weighted)


def _infer_cjk_language(query: str) -> tuple[str, str] | None:
    if not re.search(r"[\u3400-\u9fff]", query):
        return None
    if any(char in _TRADITIONAL_CHINESE_MARKERS for char in query):
        return ("zh-TW", "zh-TW")
    if any(char in _SIMPLIFIED_CHINESE_MARKERS for char in query):
        return ("zh-CN", "zh-CN")
    return ("zh-CN", "zh-CN")


def _infer_latin_language(query: str) -> tuple[str, str] | None:
    lowered = str(query or "").lower()
    tokens = set(re.findall(r"[a-zA-ZÀ-ÿ]+", lowered))
    if not tokens and not re.search(r"[A-Za-zÀ-ÿ]", lowered):
        return None

    best_lang = ""
    best_score = 0
    for lang, hint in _LATIN_LANGUAGE_HINTS.items():
        score = 0
        score += sum(2 for token in tokens if token in hint["tokens"])
        score += sum(1 for char in lowered if char in hint["chars"])
        if score > best_score:
            best_lang = lang
            best_score = score

    if best_lang and best_score > 0:
        return best_lang, (
            hint["locale"]
            if (hint := _LATIN_LANGUAGE_HINTS[best_lang])
            else _default_locale_for_lang(best_lang)
        )
    return ("en", "en-US")


def infer_query_language_locale(query: str) -> tuple[str, str]:
    text = str(query or "")
    for pattern, lang, locale in _SCRIPT_RULES:
        if pattern.search(text):
            return lang, locale

    cjk_match = _infer_cjk_language(text)
    if cjk_match:
        return cjk_match

    latin_match = _infer_latin_language(text)
    if latin_match:
        return latin_match

    return ("en", "en-US")


def resolve_search_locale_profile(
    query: str,
    *,
    lang: str | None = None,
    locale: str | None = None,
) -> SearchLocaleProfile:
    normalized_lang = _normalize_token(lang)
    normalized_locale = _normalize_token(locale)

    inferred_lang, inferred_locale = infer_query_language_locale(query)
    final_locale = normalized_locale or inferred_locale
    final_lang = normalized_lang or _lang_from_locale(final_locale) or inferred_lang

    if not normalized_locale:
        final_locale = _default_locale_for_lang(final_lang)
        if inferred_locale and _lang_from_locale(inferred_locale) == _lang_from_locale(
            final_lang
        ):
            final_locale = inferred_locale

    navigator_languages: list[str] = []
    for value in [
        final_locale,
        _base_language(final_locale),
        final_lang,
        _base_language(final_lang),
        "en-US",
        "en",
    ]:
        normalized = _normalize_token(value)
        if normalized and normalized not in navigator_languages:
            navigator_languages.append(normalized)

    return SearchLocaleProfile(
        lang=final_lang,
        locale=final_locale,
        navigator_languages=navigator_languages,
        accept_language_header=_build_accept_language_header(final_locale, final_lang),
    )
