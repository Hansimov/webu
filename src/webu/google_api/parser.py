"""Google 搜索结果 HTML 解析模块。

功能：
1. 纯化 HTML —— 移除 script、style、无用标签，保留核心内容
2. 解析搜索结果 —— 提取站点标题、页面标题、URL、展示 URL、摘要和时间信息

设计原则：
- 不依赖单一 CSS class 名，优先使用稳定的结构特征
- 以外链 + 标题为主锚点，再从结果容器中提取 site title / cite / snippet
- 兼容 Google 常规有机结果与视频卡片
- 尽量清理翻译提示、Read more、About this result、时间线子链接等噪声
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag
from dataclasses import asdict, dataclass, field
from tclogger import logger, logstr
from typing import Optional
from urllib.parse import parse_qs, unquote, urlencode, urlparse


_GOOGLE_DOMAINS = {
    "google.com",
    "google.co.uk",
    "google.co.jp",
    "google.de",
    "google.fr",
    "google.es",
    "google.it",
    "google.ca",
    "google.com.au",
    "google.com.br",
    "google.co.in",
    "googleapis.com",
    "gstatic.com",
    "googleusercontent.com",
    "google.com.hk",
    "google.co.kr",
    "google.ru",
    "accounts.google.com",
    "support.google.com",
    "policies.google.com",
    "maps.google.com",
}

_ALLOWED_GOOGLE_SUBDOMAINS = {
    "developers.google.com",
    "cloud.google.com",
    "ai.google.dev",
    "colab.research.google.com",
}

_RESULT_CONTAINER_CLASS_HINTS = {
    "A6K0A",
    "tF2Cxc",
    "asEBEc",
    "KYaZsb",
    "X4T0U",
    "vtSz8d",
    "N54PNb",
}

_NOISE_EXACT_TEXTS = {
    "Read more",
    "About this result",
    "View all",
    "More results",
    "Videos",
}

_NOISE_PHRASES = {
    "Translate this page",
    "翻译此页",
    "About this result",
    "Read more",
    "Web Result with Site Links",
}

_METRIC_WORDS = {
    "followers",
    "views",
    "comments",
    "posts",
    "subscribers",
    "likes",
}

_MONTH_PATTERN = (
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|"
    r"January|February|March|April|June|July|August|September|October|November|December)"
)

_DATE_PREFIX_PATTERNS = [
    rf"\d{{1,2}}\s+{_MONTH_PATTERN}\s+\d{{4}}",
    rf"{_MONTH_PATTERN}\s+\d{{1,2}},?\s+\d{{4}}",
    r"\d{4}年\d{1,2}月\d{1,2}日",
    r"\d+\s+(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+ago",
    r"\d+\s*(?:秒|分钟|小时|天|周|个月|年)前",
]

_TIME_INFO_RE = re.compile(
    rf"^(?P<time>(?:{'|'.join(_DATE_PREFIX_PATTERNS)}))$",
    re.IGNORECASE,
)

_LEADING_TIME_RE = re.compile(
    rf"^(?P<time>(?:{'|'.join(_DATE_PREFIX_PATTERNS)}))\s*[—–-]\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

_EMBEDDED_TIME_RE = re.compile(
    rf"(?P<time>(?:{'|'.join(_DATE_PREFIX_PATTERNS)}))",
    re.IGNORECASE,
)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _normalize_display_text(text: str) -> str:
    text = _normalize_whitespace(text)
    text = text.replace("›", ">")
    text = re.sub(r"\s*>\s*", " > ", text)
    text = re.sub(r"\s*·\s*", " · ", text)
    return _normalize_whitespace(text)


def _looks_like_time_info(text: str) -> bool:
    return bool(_TIME_INFO_RE.match(_normalize_whitespace(text)))


def _extract_inline_time_info(text: str) -> str:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return ""
    if _looks_like_time_info(normalized):
        return normalized
    stripped = normalized.rstrip("—–- ").strip()
    if _looks_like_time_info(stripped):
        return stripped
    match = _LEADING_TIME_RE.match(normalized)
    if match:
        return match.group("time")
    embedded = _EMBEDDED_TIME_RE.search(normalized)
    return embedded.group("time") if embedded else ""


def _looks_like_url_or_path(text: str) -> bool:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return False
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return True
    if ">" in normalized and ("." in normalized or normalized.startswith("/")):
        return True
    return normalized.count("/") >= 2 and "." in normalized


def _looks_like_display_url_text(text: str) -> bool:
    normalized = _normalize_display_text(text)
    if not normalized:
        return False
    if _looks_like_url_or_path(normalized):
        return True
    return bool(re.search(r"(?:^|\s)[\w.-]+\.[A-Za-z]{2,}(?:$|\s)", normalized))


def _looks_like_metric_text(text: str) -> bool:
    normalized = _normalize_display_text(text).lower()
    if not normalized:
        return False
    if any(word in normalized for word in _METRIC_WORDS):
        return True
    return bool(re.search(r"\b\d+\s+years?\s+ago\b", normalized))


def _is_noise_text(text: str) -> bool:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return True
    if normalized in _NOISE_EXACT_TEXTS:
        return True
    return any(phrase.lower() in normalized.lower() for phrase in _NOISE_PHRASES)


def _is_google_internal(url: str) -> bool:
    """判断 URL 是否属于 Google 内部链接。"""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return True

    if host in _ALLOWED_GOOGLE_SUBDOMAINS:
        return False
    if host in _GOOGLE_DOMAINS:
        return True
    if host.endswith(".google.com") or host.endswith(".google.co.uk"):
        return True
    for domain in _GOOGLE_DOMAINS:
        if host.endswith("." + domain):
            return True
    return False


def _normalize_url(href: str) -> str:
    """规范化 Google 搜索结果链接。"""
    if href.startswith("/url?"):
        match = re.search(r"[?&]q=([^&]+)", href)
        if match:
            return unquote(match.group(1))
    return href


def _clean_url(url: str) -> str:
    """去掉 Google 高亮 fragment，保留正常 fragment。"""
    if "#:~:text=" in url:
        return url.split("#:~:text=")[0]
    return url


def _dedup_key(url: str) -> str:
    """生成去重 key，去掉 tracking 参数，保留有意义参数。"""
    url = _clean_url(url)
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        tracking_keys = {"ved", "sa", "usg", "ei", "source", "opi", "gs_lcrp"}
        cleaned = {
            key: value for key, value in params.items() if key not in tracking_keys
        }
        clean_query = urlencode(cleaned, doseq=True)
        base = f"{parsed.scheme}://{parsed.hostname}{parsed.path}"
        return base + (f"?{clean_query}" if clean_query else "")
    except Exception:
        return url


@dataclass
class GoogleSearchResult:
    """单个 Google 搜索结果。"""

    title: str = ""
    url: str = ""
    site_title: str = ""
    displayed_url: str = ""
    snippet: str = ""
    time_info: str = ""
    position: int = 0
    result_type: str = "organic"  # organic | video | featured | knowledge

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GoogleSearchResponse:
    """Google 搜索响应（解析后的完整结果）。"""

    query: str = ""
    results: list[GoogleSearchResult] = field(default_factory=list)
    total_results_text: str = ""
    has_captcha: bool = False
    raw_html_length: int = 0
    clean_html_length: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "results": [result.to_dict() for result in self.results],
            "total_results_text": self.total_results_text,
            "result_count": len(self.results),
            "has_captcha": self.has_captcha,
            "raw_html_length": self.raw_html_length,
            "clean_html_length": self.clean_html_length,
            "error": self.error,
        }


class GoogleResultParser:
    """Google 搜索结果 HTML 解析器。"""

    REMOVE_TAGS = [
        "script",
        "style",
        "noscript",
        "iframe",
        "svg",
        "path",
        "link",
        "meta",
        "header",
        "footer",
    ]

    REMOVE_ATTRS = [
        "style",
        "onclick",
        "onload",
        "onerror",
        "class",
        "id",
        "data-ved",
        "data-lk",
        "data-surl",
        "jscontroller",
        "jsaction",
        "jsname",
        "jsmodel",
        "jsshadow",
        "jsdata",
    ]

    def __init__(self, verbose: bool = True):
        self.verbose = verbose

    def clean_html(self, html: str) -> str:
        """纯化 HTML：移除 script/style/无用标签和属性。"""
        soup = BeautifulSoup(html, "html.parser")

        for tag_name in self.REMOVE_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        for tag in soup.find_all(True):
            for attr in list(tag.attrs.keys()):
                if attr in self.REMOVE_ATTRS or attr.startswith("data-"):
                    del tag[attr]

        for tag in soup.find_all(True):
            if not tag.get_text(strip=True) and not tag.find_all(
                ["img", "a", "input", "br"]
            ):
                tag.decompose()

        return str(soup)

    def detect_captcha(self, html: str) -> bool:
        captcha_indicators = [
            "captcha",
            "unusual traffic",
            "not a robot",
            "recaptcha",
            "Our systems have detected unusual traffic",
            "/sorry/",
        ]
        lowered = html.lower()
        return any(indicator.lower() in lowered for indicator in captcha_indicators)

    def detect_consent(self, html: str) -> bool:
        return "before you continue" in html.lower()

    def _detect_no_results(self, soup: BeautifulSoup) -> str:
        text = soup.get_text(separator=" ", strip=True).lower()
        if "did not match any documents" in text:
            return "did not match any documents"
        if "no results found" in text:
            return "no results found"
        if "no results containing all your search terms" in text:
            return "no results containing all your search terms"
        return ""

    def parse(self, html: str, query: str = "") -> GoogleSearchResponse:
        response = GoogleSearchResponse(query=query, raw_html_length=len(html))

        if self.detect_captcha(html):
            response.has_captcha = True
            response.error = "CAPTCHA detected"
            if self.verbose:
                logger.warn(f"  × CAPTCHA detected for query: {query}")
            return response

        soup = BeautifulSoup(html, "html.parser")
        result_stats = soup.find("div", id="result-stats")
        if result_stats:
            response.total_results_text = _normalize_whitespace(
                result_stats.get_text(" ", strip=True)
            )

        scope = soup.find("div", id="search") or soup.find("div", id="rso") or soup

        results, seen_urls = self._parse_by_h3_anchors(scope)
        results.extend(self._parse_video_results(scope, seen_urls))
        if not results:
            results = self._parse_fallback_links(scope)

        if not results:
            no_results_msg = self._detect_no_results(soup)
            if no_results_msg:
                response.error = no_results_msg
                if self.verbose:
                    logger.mesg(f"  ℹ Google: {no_results_msg}")

        for index, result in enumerate(results, start=1):
            result.position = index

        response.results = results
        clean = self.clean_html(html)
        response.clean_html_length = len(clean)

        if self.verbose:
            n_organic = sum(1 for result in results if result.result_type == "organic")
            n_video = sum(1 for result in results if result.result_type == "video")
            parts = [f"{n_organic} organic"]
            if n_video:
                parts.append(f"{n_video} video")
            logger.okay(
                f"  ✓ Parsed {logstr.mesg(len(results))} results "
                f"({', '.join(parts)}) "
                f"(raw={len(html)}, clean={len(clean)})"
            )

        return response

    def _parse_by_h3_anchors(
        self, scope: Tag
    ) -> tuple[list[GoogleSearchResult], set[str]]:
        results: list[GoogleSearchResult] = []
        seen_urls: set[str] = set()

        for h3 in scope.find_all("h3"):
            title = _normalize_whitespace(h3.get_text(" ", strip=True))
            if not title or len(title) < 2 or _is_noise_text(title):
                continue

            anchor = h3.find_parent("a")
            url = self._resolve_href(anchor.get("href", "") if anchor else "")
            if not url:
                container = self._find_result_container(h3, "")
                anchor = self._find_primary_anchor(container, "") if container else None
                url = self._resolve_href(anchor.get("href", "") if anchor else "")
            if not url:
                continue

            clean_url = _clean_url(url)
            key = _dedup_key(url)
            if key in seen_urls:
                continue

            container = self._find_result_container(h3, clean_url)
            if container is None:
                continue

            anchor = self._find_primary_anchor(container, clean_url) or anchor
            meta = self._extract_result_metadata(container, anchor, title, clean_url)
            if not title or title == meta["site_title"]:
                continue

            seen_urls.add(key)
            results.append(
                GoogleSearchResult(
                    title=title,
                    url=clean_url,
                    site_title=meta["site_title"],
                    displayed_url=meta["displayed_url"],
                    snippet=meta["snippet"],
                    time_info=meta["time_info"],
                    result_type="organic",
                )
            )

        return results, seen_urls

    def _parse_video_results(
        self, scope: Tag, seen_urls: set[str]
    ) -> list[GoogleSearchResult]:
        results: list[GoogleSearchResult] = []
        video_domains = {"youtube.com", "youtu.be", "vimeo.com", "dailymotion.com"}

        for anchor in scope.find_all("a", href=True):
            href = self._resolve_href(anchor["href"])
            if not href:
                continue

            try:
                host = urlparse(href).hostname or ""
                query = parse_qs(urlparse(href).query)
            except Exception:
                continue

            if not any(domain in host for domain in video_domains):
                continue
            if "t" in query or anchor.has_attr("data-time"):
                continue

            clean_url = _clean_url(href)
            key = _dedup_key(clean_url)
            if key in seen_urls:
                continue

            container = self._find_result_container(anchor, clean_url)
            title = self._extract_video_title(anchor, container)
            if not title or len(title) < 3:
                continue

            meta = self._extract_result_metadata(
                container or anchor, anchor, title, clean_url
            )
            seen_urls.add(key)
            results.append(
                GoogleSearchResult(
                    title=title,
                    url=clean_url,
                    site_title=meta["site_title"],
                    displayed_url=meta["displayed_url"],
                    snippet=meta["snippet"],
                    time_info=meta["time_info"],
                    result_type="video",
                )
            )

        return results

    def _parse_fallback_links(self, scope: Tag) -> list[GoogleSearchResult]:
        results: list[GoogleSearchResult] = []
        seen_urls: set[str] = set()

        for anchor in scope.find_all("a", href=True):
            href = self._resolve_href(anchor["href"])
            if not href:
                continue

            clean_url = _clean_url(href)
            key = _dedup_key(clean_url)
            if key in seen_urls:
                continue

            title = self._extract_video_title(anchor, None)
            if not title:
                h3 = anchor.find("h3")
                title = (
                    _normalize_whitespace(h3.get_text(" ", strip=True))
                    if h3
                    else _normalize_whitespace(anchor.get_text(" ", strip=True))
                )
            if not title or len(title) < 3 or _is_noise_text(title):
                continue

            container = self._find_result_container(anchor, clean_url)
            meta = self._extract_result_metadata(
                container or anchor, anchor, title, clean_url
            )
            seen_urls.add(key)
            results.append(
                GoogleSearchResult(
                    title=title,
                    url=clean_url,
                    site_title=meta["site_title"],
                    displayed_url=meta["displayed_url"],
                    snippet=meta["snippet"],
                    time_info=meta["time_info"],
                )
            )

        return results

    def _resolve_href(self, href: str) -> str:
        if not href:
            return ""
        href = _normalize_url(href)
        if not href.startswith("http"):
            return ""
        if _is_google_internal(href):
            return ""
        return href

    def _find_result_container(self, element: Tag, url: str) -> Optional[Tag]:
        best: Optional[Tag] = None
        best_score = -10

        for depth, parent in enumerate(element.parents, start=1):
            if not isinstance(parent, Tag):
                continue
            if parent.name in {"body", "html"}:
                break
            if parent.name not in {"div", "article", "section"}:
                continue

            score = 0
            classes = set(parent.get("class", []))
            text_len = len(_normalize_whitespace(parent.get_text(" ", strip=True)))
            heading_count = len(parent.find_all("h3"))
            external_links = [
                candidate
                for candidate in parent.find_all("a", href=True)
                if self._resolve_href(candidate.get("href", ""))
            ]

            if parent.find("h3"):
                score += 2
            if parent.find("cite"):
                score += 3
            if parent.find(class_="VuuXrf"):
                score += 2
            if parent.find(class_="Sg4azc"):
                score += 3
            if parent.find(attrs={"data-sncf": True}) or parent.find(
                attrs={"data-content-feature": "1"}
            ):
                score += 3
            if parent.get("data-rpos") is not None:
                score += 2
            if classes & _RESULT_CONTAINER_CLASS_HINTS:
                score += 3
            if external_links:
                score += 1
            if url and any(
                _clean_url(self._resolve_href(candidate.get("href", ""))) == url
                for candidate in external_links
            ):
                score += 3
            if 40 <= text_len <= 1800:
                score += 1
            elif text_len > 3200:
                score -= 3
            if heading_count > 1:
                score -= min(heading_count - 1, 4) * 2
            if len(external_links) > 8:
                score -= 2
            if depth > 2:
                score -= min(depth - 2, 4)

            if score > best_score:
                best = parent
                best_score = score

        return best

    def _find_primary_anchor(self, container: Optional[Tag], url: str) -> Optional[Tag]:
        if container is None:
            return None

        resolved: list[Tag] = []
        for anchor in container.find_all("a", href=True):
            href = self._resolve_href(anchor.get("href", ""))
            if not href:
                continue
            if url and _clean_url(href) != url:
                continue
            resolved.append(anchor)

        if not resolved:
            return None
        for anchor in resolved:
            if anchor.find("h3"):
                return anchor
        for anchor in resolved:
            if anchor.find(attrs={"role": "heading"}):
                return anchor
        return resolved[0]

    def _extract_result_metadata(
        self,
        container: Tag,
        primary_anchor: Optional[Tag],
        title: str,
        url: str,
    ) -> dict[str, str]:
        displayed_url = self._extract_displayed_url(container, primary_anchor, url)
        site_title = self._extract_site_title(
            container, primary_anchor, title, displayed_url
        )
        time_info = self._extract_time_info(
            container, primary_anchor, title, site_title, displayed_url
        )
        snippet = self._extract_snippet(
            container, primary_anchor, title, site_title, displayed_url, time_info
        )
        return {
            "site_title": site_title,
            "displayed_url": displayed_url,
            "snippet": snippet,
            "time_info": time_info,
        }

    def _extract_displayed_url(
        self,
        container: Tag,
        primary_anchor: Optional[Tag],
        url: str,
    ) -> str:
        for root in [primary_anchor, container]:
            if root is None:
                continue
            cite = root.find("cite")
            if cite:
                text = _normalize_display_text(cite.get_text(" ", strip=True))
                if (
                    text
                    and _looks_like_display_url_text(text)
                    and not _looks_like_metric_text(text)
                ):
                    return text
        return self._format_display_url_from_url(url)

    def _extract_site_title(
        self,
        container: Tag,
        primary_anchor: Optional[Tag],
        title: str,
        displayed_url: str,
    ) -> str:
        for root in [primary_anchor, container]:
            if root is None:
                continue
            preferred = root.find(class_="VuuXrf")
            if preferred:
                text = _normalize_whitespace(preferred.get_text(" ", strip=True))
                if text and text != title and not _looks_like_time_info(text):
                    return text
            video_meta = root.find(class_="Sg4azc")
            if video_meta:
                text = self._clean_site_title_candidate(
                    video_meta.get_text(" ", strip=True), title
                )
                if text:
                    return text

        seen: set[str] = set()
        for root in [primary_anchor, container]:
            if root is None:
                continue
            for node in root.find_all(["span", "div"], limit=80):
                text = self._clean_site_title_candidate(
                    node.get_text(" ", strip=True), title
                )
                if text in seen:
                    continue
                seen.add(text)
                if not text or len(text) > 80:
                    continue
                if text.endswith("..."):
                    continue
                if len(text.split()) > 6 and " · " not in text:
                    continue
                if text == title or text == displayed_url:
                    continue
                if (
                    _is_noise_text(text)
                    or _looks_like_url_or_path(text)
                    or _looks_like_time_info(text)
                ):
                    continue
                if " · " in text and text.split(" · ", 1)[0].lower() in {
                    "youtube",
                    "vimeo",
                }:
                    return text
                if len(text) >= 2:
                    return text
        return ""

    def _extract_time_info(
        self,
        container: Tag,
        primary_anchor: Optional[Tag],
        title: str,
        site_title: str,
        displayed_url: str,
    ) -> str:
        for root in [primary_anchor, container]:
            if root is None:
                continue
            for node in root.find_all(["span", "div"], limit=120):
                text = _normalize_whitespace(node.get_text(" ", strip=True))
                if not text or text in {title, site_title, displayed_url}:
                    continue
                extracted = _extract_inline_time_info(text)
                if extracted:
                    return extracted

        snippet_root = container.find(attrs={"data-sncf": True}) or container.find(
            attrs={"data-content-feature": "1"}
        )
        if snippet_root is not None:
            text = self._extract_text_without_links(snippet_root)
            time_info, _ = self._split_leading_time_info(text)
            if time_info:
                return time_info
            extracted = _extract_inline_time_info(text)
            if extracted:
                return extracted
        return ""

    def _extract_snippet(
        self,
        container: Tag,
        primary_anchor: Optional[Tag],
        title: str,
        site_title: str,
        displayed_url: str,
        time_info: str,
    ) -> str:
        candidates: list[str] = []

        prioritized = [
            container.find(attrs={"data-sncf": True}),
            container.find(attrs={"data-content-feature": "1"}),
        ]
        for candidate in prioritized:
            if candidate is None:
                continue
            text = self._extract_text_without_links(candidate)
            if text:
                candidates.append(text)

        for node in container.find_all(["div", "span", "p"], limit=120):
            if primary_anchor is not None and primary_anchor in node.parents:
                continue
            text = self._extract_text_without_links(node)
            if not text or len(text) < 25 or len(text) > 450:
                continue
            candidates.append(text)

        best = ""
        for candidate in candidates:
            cleaned = self._clean_snippet(
                candidate, title, site_title, displayed_url, time_info
            )
            if len(cleaned) > len(best):
                best = cleaned
        return best

    def _clean_snippet(
        self,
        snippet: str,
        title: str,
        site_title: str,
        displayed_url: str,
        time_info: str,
    ) -> str:
        snippet = _normalize_whitespace(snippet)
        if not snippet:
            return ""

        for phrase in _NOISE_PHRASES:
            snippet = re.sub(re.escape(phrase), " ", snippet, flags=re.IGNORECASE)
        snippet = re.sub(r"\bRead more\b", " ", snippet, flags=re.IGNORECASE)
        snippet = re.sub(
            r"\bWeb Result with Site Links\b", " ", snippet, flags=re.IGNORECASE
        )
        snippet = _normalize_whitespace(snippet)

        normalized_site_title = _normalize_whitespace(site_title)
        if normalized_site_title:
            site_prefix_re = re.compile(
                rf"^{re.escape(normalized_site_title)}(?:\s+(?:{'|'.join(_DATE_PREFIX_PATTERNS)}))?\s*[—–-]?\s*",
                re.IGNORECASE,
            )
            snippet = site_prefix_re.sub("", snippet)

        extracted_time, remainder = self._split_leading_time_info(snippet)
        if extracted_time:
            snippet = remainder
        elif time_info and snippet.startswith(time_info):
            snippet = snippet[len(time_info) :].lstrip(" \t\n·—-–:：.。")

        for prefix in [title, site_title, displayed_url]:
            normalized_prefix = _normalize_whitespace(prefix)
            if normalized_prefix and snippet.startswith(normalized_prefix):
                snippet = snippet[len(normalized_prefix) :].lstrip(" \t\n·—-–:：.。>")

        snippet = re.sub(r"^https?://\S+\s*(?:>|›)?\s*", "", snippet)
        snippet = re.sub(r"\s+", " ", snippet).strip(" ·—-–:：.。")

        if _is_noise_text(snippet) or snippet in {title, site_title, displayed_url}:
            return ""
        return snippet

    def _split_leading_time_info(self, text: str) -> tuple[str, str]:
        normalized = _normalize_whitespace(text)
        match = _LEADING_TIME_RE.match(normalized)
        if not match:
            return "", normalized
        return match.group("time"), _normalize_whitespace(match.group("rest"))

    def _extract_video_title(self, anchor: Tag, container: Optional[Tag]) -> str:
        h3 = anchor.find("h3")
        if h3:
            return _normalize_whitespace(h3.get_text(" ", strip=True))

        for selector in [
            "span.cHaqb",
            "span.QOGdqf",
            "div[role='heading']",
            "span[role='heading']",
        ]:
            node = anchor.select_one(selector)
            if node:
                text = _normalize_whitespace(node.get_text(" ", strip=True))
                if text and not _is_noise_text(text):
                    return text

        label = _normalize_whitespace(anchor.get("aria-label", ""))
        if " by " in label:
            return label.split(" by ", 1)[0].strip(" .")

        text = _normalize_whitespace(anchor.get_text(" ", strip=True))
        if " · " in text:
            text = text.split(" · ", 1)[0]
        return self._clean_video_title(text)

    def _clean_video_title(self, title: str) -> str:
        if not title:
            return ""
        title = _normalize_whitespace(title)
        title = re.sub(r"\s*YouTube[·|\s].*$", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(r"\s*Bilibili[·|\s].*$", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(r"\s*Vimeo[·|\s].*$", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(
            r"\s*·?\s*\d+\s*(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+ago\s*$",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()
        title = re.sub(
            r"\s*·?\s*\d+\s*(?:秒|分钟|小时|天|周|个月|年)前\s*$", "", title
        ).strip()
        return title

    def _clean_site_title_candidate(self, text: str, title: str) -> str:
        cleaned = _normalize_display_text(text)
        if not cleaned:
            return ""
        if title and cleaned.startswith(title):
            cleaned = cleaned[len(title) :].lstrip(" ·—–-:：")
        trailing_time = _extract_inline_time_info(cleaned.split(" > ")[-1])
        if trailing_time and cleaned.endswith(trailing_time):
            cleaned = cleaned[: -len(trailing_time)].rstrip(" ·—–-:：")
        return _normalize_whitespace(cleaned)

    def _extract_text_without_links(self, tag: Tag) -> str:
        clone = BeautifulSoup(str(tag), "html.parser")
        for removable in clone.find_all(["a", "button", "svg", "img", "cite"]):
            removable.decompose()
        return _normalize_whitespace(clone.get_text(" ", strip=True))

    def _format_display_url_from_url(self, url: str) -> str:
        try:
            parsed = urlparse(url)
        except Exception:
            return _normalize_display_text(url)

        if not parsed.scheme or not parsed.hostname:
            return _normalize_display_text(url)

        parts = [f"{parsed.scheme}://{parsed.hostname}"]
        parts.extend(part for part in parsed.path.split("/") if part)
        return _normalize_display_text(" > ".join(parts))
