"""Google 搜索结果 HTML 解析模块。

功能：
1. 纯化 HTML — 移除 script、style、无用标签，保留核心内容
2. 解析搜索结果 — 提取标题、链接、摘要等结构化数据

设计原则：
- 不依赖特定 CSS class 名（Google 经常更换）
- 以 <a href> + <h3> 组合作为核心锚点，这是最稳定的结构特征
- 分层提取：有机结果 → 视频结果 → 退化提取
- 去重 + 过滤内部链接
"""

import re

from bs4 import BeautifulSoup, Tag
from dataclasses import dataclass, field, asdict
from tclogger import logger, logstr
from typing import Optional
from urllib.parse import unquote, urlparse


# ── 过滤规则 ──────────────────────────────────────

# Google 内部域名（不算有机结果）
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


def _is_google_internal(url: str) -> bool:
    """判断 URL 是否属于 Google 内部链接。"""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return True

    # 白名单：有实际内容的 Google 子域
    _ALLOWED_SUBDOMAINS = {
        "developers.google.com",
        "cloud.google.com",
        "ai.google.dev",
        "colab.research.google.com",
    }
    if host in _ALLOWED_SUBDOMAINS:
        return False

    # 精确匹配 or *.google.com 子域
    if host in _GOOGLE_DOMAINS:
        return True
    for gd in _GOOGLE_DOMAINS:
        if host.endswith("." + gd):
            return True
    if host.endswith(".google.com") or host.endswith(".google.co.uk"):
        return True
    return False


def _normalize_url(href: str) -> str:
    """规范化 Google 搜索结果链接。

    处理 /url?q=... 重定向 和 fragment 链接。
    """
    if href.startswith("/url?"):
        m = re.search(r"[?&]q=([^&]+)", href)
        if m:
            return unquote(m.group(1))
    return href


def _clean_url(url: str) -> str:
    """去掉 #:~:text= 等 fragment（Google 高亮跳转），保留有用 fragment。"""
    if "#:~:text=" in url:
        return url.split("#:~:text=")[0]
    return url


def _dedup_key(url: str) -> str:
    """生成用于去重的 URL key。

    - 去掉 #:~:text= fragment
    - 去掉 Google 的 tracking 参数（ved, sa, usg 等）
    - 保留有意义的 query 参数（如 YouTube 的 v=, list=）
    """
    url = _clean_url(url)
    try:
        parsed = urlparse(url)
        # 去掉常见 tracking 参数，保留有意义参数
        if parsed.query:
            from urllib.parse import parse_qs, urlencode

            params = parse_qs(parsed.query, keep_blank_values=True)
            tracking_keys = {"ved", "sa", "usg", "ei", "source", "opi", "gs_lcrp"}
            clean_params = {
                k: v for k, v in params.items() if k not in tracking_keys
            }
            clean_query = urlencode(clean_params, doseq=True)
            return f"{parsed.scheme}://{parsed.hostname}{parsed.path}" + (
                f"?{clean_query}" if clean_query else ""
            )
        return f"{parsed.scheme}://{parsed.hostname}{parsed.path}"
    except Exception:
        return url


@dataclass
class GoogleSearchResult:
    """单个 Google 搜索结果。"""

    title: str = ""
    url: str = ""
    displayed_url: str = ""
    snippet: str = ""
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
            "results": [r.to_dict() for r in self.results],
            "total_results_text": self.total_results_text,
            "result_count": len(self.results),
            "has_captcha": self.has_captcha,
            "raw_html_length": self.raw_html_length,
            "clean_html_length": self.clean_html_length,
            "error": self.error,
        }


class GoogleResultParser:
    """Google 搜索结果 HTML 解析器。

    核心思路：以 <h3> 为锚点定位有机搜索结果。
    Google 无论怎么改 class / id，<a href="..."><h3>Title</h3></a>
    这个组合始终不变。解析器据此提取标题 + URL，再在上下文中找
    cite（显示 URL）和 snippet（摘要）。
    """

    # 需要移除的标签（用于 clean_html）
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

    # 需要移除的属性（用于 clean_html）
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

    # ── public API ──────────────────────────────────

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
        """检测是否触发了 CAPTCHA。"""
        captcha_indicators = [
            "captcha",
            "unusual traffic",
            "not a robot",
            "recaptcha",
            "Our systems have detected unusual traffic",
            "/sorry/",
        ]
        html_lower = html.lower()
        return any(indicator.lower() in html_lower for indicator in captcha_indicators)

    def parse(self, html: str, query: str = "") -> GoogleSearchResponse:
        """解析 Google 搜索结果 HTML。

        解析策略（由精确到宽松，逐级 fallback）：
        1. h3 锚点法 —— 在 #search 内找所有 <h3>，回溯到包含外链的 <a>
        2. 视频结果 —— 提取 YouTube 等视频链接（不与有机结果重复）
        3. 退化全链接 —— 扫描 #search 内所有外链（最后手段）

        Args:
            html: 原始 HTML 内容
            query: 搜索查询词

        Returns:
            GoogleSearchResponse
        """
        response = GoogleSearchResponse(
            query=query,
            raw_html_length=len(html),
        )

        if self.detect_captcha(html):
            response.has_captcha = True
            response.error = "CAPTCHA detected"
            if self.verbose:
                logger.warn(f"  × CAPTCHA detected for query: {query}")
            return response

        soup = BeautifulSoup(html, "html.parser")

        # 提取搜索结果数量文本
        result_stats = soup.find("div", id="result-stats")
        if result_stats:
            response.total_results_text = result_stats.get_text(strip=True)

        # 确定搜索范围（优先 #search，再 #rso，最后整个页面）
        scope = (
            soup.find("div", id="search")
            or soup.find("div", id="rso")
            or soup
        )

        # ── 策略 1：h3 锚点法（最稳健）──────────────
        results, seen_urls = self._parse_by_h3_anchors(scope)

        # ── 策略 2：视频结果 ──────────────────────
        video_results = self._parse_video_results(scope, seen_urls)
        results.extend(video_results)

        # ── 策略 3：退化全链接法（兜底）────────────
        if not results:
            results = self._parse_fallback_links(scope)

        # 重新编号 position
        for i, r in enumerate(results):
            r.position = i + 1

        response.results = results

        # 纯化 HTML 并记录长度
        clean = self.clean_html(html)
        response.clean_html_length = len(clean)

        if self.verbose:
            n_organic = sum(1 for r in results if r.result_type == "organic")
            n_video = sum(1 for r in results if r.result_type == "video")
            parts = [f"{n_organic} organic"]
            if n_video:
                parts.append(f"{n_video} video")
            logger.okay(
                f"  ✓ Parsed {logstr.mesg(len(results))} results "
                f"({', '.join(parts)}) "
                f"(raw={len(html)}, clean={len(clean)})"
            )

        return response

    # ── 策略 1：h3 锚点法 ────────────────────────

    def _parse_by_h3_anchors(
        self, scope: Tag
    ) -> tuple[list[GoogleSearchResult], set[str]]:
        """以 <h3> 为锚点提取有机搜索结果。

        思路：遍历 scope 内所有 <h3>，对每个 <h3>：
        1. 检查 <h3> 是否在 <a> 中 — 取 <a> 的 href
        2. 若不在 <a> 中，向上查找最近的包含外链 <a> 的祖先容器
        3. 从该容器中提取 cite（显示 URL）和 snippet（摘要）
        """
        results: list[GoogleSearchResult] = []
        seen_urls: set[str] = set()

        for h3 in scope.find_all("h3"):
            title = h3.get_text(strip=True)
            if not title or len(title) < 2:
                continue

            # —— 定位包含外链的 <a> ——
            url = ""
            anchor = h3.find_parent("a")
            if anchor:
                url = self._resolve_href(anchor.get("href", ""))
            if not url:
                # h3 不在 <a> 中，向上找包含外链 <a> 的容器
                container = self._find_result_container(h3)
                if container:
                    a_tag = container.find("a", href=True)
                    if a_tag:
                        url = self._resolve_href(a_tag["href"])

            if not url:
                continue

            # 去重（基于规范化 URL key）
            clean = _clean_url(url)
            key = _dedup_key(url)
            if key in seen_urls:
                continue
            seen_urls.add(key)

            # —— 定位结果容器，提取 cite + snippet ——
            container = self._find_result_container(h3)
            displayed_url = ""
            snippet = ""

            if container:
                cite = container.find("cite")
                if cite:
                    displayed_url = cite.get_text(strip=True)
                snippet = self._extract_snippet(container, title)

            results.append(
                GoogleSearchResult(
                    title=title,
                    url=clean,
                    displayed_url=displayed_url,
                    snippet=snippet,
                    result_type="organic",
                )
            )

        return results, seen_urls

    # ── 策略 2：视频结果 ─────────────────────────

    def _parse_video_results(
        self, scope: Tag, seen_urls: set[str]
    ) -> list[GoogleSearchResult]:
        """提取视频搜索结果（YouTube 等）。

        视频结果的典型结构：
        - 主链接指向 YouTube 视频页面
        - 可能包含视频时间线（带 &t= 参数的链接）
        - 有些是 playlist 链接

        我们只提取主视频链接（不含 &t= 时间线片段）。
        """
        results: list[GoogleSearchResult] = []
        video_domains = {"youtube.com", "youtu.be", "vimeo.com", "dailymotion.com"}

        for a_tag in scope.find_all("a", href=True):
            href = self._resolve_href(a_tag["href"])
            if not href:
                continue

            # 只处理视频域名
            try:
                host = urlparse(href).hostname or ""
            except Exception:
                continue
            is_video = any(vd in host for vd in video_domains)
            if not is_video:
                continue

            # 跳过时间线片段链接（&t=123）
            if "&t=" in href:
                continue
            # 跳过 #:~:text= 高亮链接
            clean = _clean_url(href)
            key = _dedup_key(href)
            if key in seen_urls:
                continue

            # 提取标题：优先 <h3>，其次 <a> 的文本
            h3 = a_tag.find("h3")
            if h3:
                title = h3.get_text(strip=True)
            else:
                title = a_tag.get_text(strip=True)
            # 清理标题中的多余后缀（如 "YouTube·Channel Name"）
            if not title or len(title) < 3:
                continue

            seen_urls.add(key)
            results.append(
                GoogleSearchResult(
                    title=title,
                    url=clean,
                    result_type="video",
                )
            )

        return results

    # ── 策略 3：退化全链接法 ──────────────────────

    def _parse_fallback_links(self, scope: Tag) -> list[GoogleSearchResult]:
        """退化解析 — 扫描所有外链，按出现顺序收集。"""
        results: list[GoogleSearchResult] = []
        seen_urls: set[str] = set()

        for a_tag in scope.find_all("a", href=True):
            href = self._resolve_href(a_tag["href"])
            if not href:
                continue

            base = _clean_url(href)
            if base in seen_urls:
                continue
            seen_urls.add(base)

            # 尝试获取标题
            h3 = a_tag.find("h3")
            title = h3.get_text(strip=True) if h3 else ""
            if not title:
                title = a_tag.get_text(strip=True)
            if not title or len(title) < 3:
                parent = a_tag.find_parent("div")
                if parent:
                    h3 = parent.find("h3")
                    if h3:
                        title = h3.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            results.append(
                GoogleSearchResult(
                    title=title,
                    url=base,
                )
            )

        return results

    # ── 辅助方法 ─────────────────────────────────

    def _resolve_href(self, href: str) -> str:
        """解析 href：过滤无效/内部链接，处理 /url?q= 重定向。"""
        if not href:
            return ""
        href = _normalize_url(href)
        if not href.startswith("http"):
            return ""
        if _is_google_internal(href):
            return ""
        return href

    def _find_result_container(self, element: Tag) -> Optional[Tag]:
        """从一个元素向上查找搜索结果的容器 div。

        启发式：向上遍历祖先，找到同时包含 <h3> 和 <cite> 的最小容器，
        或者包含 class 含 'g' 的 div，或者向上最多 6 层的 div。
        """
        # 先尝试找包含 cite 的最小祖先 div
        for parent in element.parents:
            if not isinstance(parent, Tag) or parent.name == "html":
                break
            if parent.name == "div" and parent.find("cite"):
                return parent
        # 如果没找到 cite，回退到向上 6 层
        depth = 0
        for parent in element.parents:
            if not isinstance(parent, Tag):
                break
            if parent.name == "div":
                depth += 1
                if depth >= 4:
                    return parent
        return None

    def _extract_snippet(self, container: Tag, title: str = "") -> str:
        """从搜索结果容器中提取摘要文本。

        多种策略逐级尝试：
        1. data-sncf 属性（Google 的摘要标记）
        2. data-content-feature="1" 属性
        3. 排除标题/URL 后，最长的文本块
        """
        # 方法 1：data-sncf 属性
        snippet_div = container.find(attrs={"data-sncf": True})
        if snippet_div:
            text = snippet_div.get_text(strip=True)
            if text:
                return text

        # 方法 2：data-content-feature="1"
        content_div = container.find(attrs={"data-content-feature": "1"})
        if content_div:
            text = content_div.get_text(strip=True)
            if len(text) > 20:
                return text

        # 方法 3：启发式 — 在容器内找最长非标题文本
        title_text = title or ""
        cite = container.find("cite")
        cite_text = cite.get_text(strip=True) if cite else ""

        longest = ""
        for elem in container.find_all(["span", "div", "em"]):
            text = elem.get_text(strip=True)
            if len(text) <= len(longest) or len(text) < 30:
                continue
            if text == title_text or text == cite_text:
                continue
            if text.startswith("http"):
                continue
            # 避免选到整个容器的完整文本
            if len(text) > 500:
                continue
            longest = text

        return longest
