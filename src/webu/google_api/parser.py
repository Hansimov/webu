"""Google 搜索结果 HTML 解析模块。

功能：
1. 纯化 HTML — 移除 script、style、无用标签，保留核心内容
2. 解析搜索结果 — 提取标题、链接、摘要等结构化数据
"""

import re

from bs4 import BeautifulSoup, Tag
from dataclasses import dataclass, field, asdict
from tclogger import logger, logstr
from typing import Optional


@dataclass
class GoogleSearchResult:
    """单个 Google 搜索结果。"""

    title: str = ""
    url: str = ""
    displayed_url: str = ""
    snippet: str = ""
    position: int = 0

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
    """Google 搜索结果 HTML 解析器。"""

    # 需要移除的标签
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

    # 需要移除的属性（清理冗余）
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

        # 移除无用标签
        for tag_name in self.REMOVE_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # 移除无用属性
        for tag in soup.find_all(True):
            for attr in list(tag.attrs.keys()):
                if attr in self.REMOVE_ATTRS or attr.startswith("data-"):
                    del tag[attr]

        # 移除空标签（递归）
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

        Args:
            html: 原始 HTML 内容
            query: 搜索查询词（用于记录）

        Returns:
            GoogleSearchResponse 结构化搜索结果
        """
        response = GoogleSearchResponse(
            query=query,
            raw_html_length=len(html),
        )

        # 检测 CAPTCHA
        if self.detect_captcha(html):
            response.has_captcha = True
            response.error = "CAPTCHA detected"
            if self.verbose:
                logger.warn(f"  × CAPTCHA detected for query: {query}")
            return response

        soup = BeautifulSoup(html, "html.parser")

        # 提取搜索结果数量文本（如 "About 1,000,000 results"）
        result_stats = soup.find("div", id="result-stats")
        if result_stats:
            response.total_results_text = result_stats.get_text(strip=True)

        # ── 策略 1：标准搜索结果（div.g 容器）──────────────

        results = self._parse_standard_results(soup)

        # ── 策略 2：如果策略 1 未找到，尝试 #rso 内的直接子元素 ──

        if not results:
            results = self._parse_rso_results(soup)

        # ── 策略 3：退化到所有带 href 的链接 ──────────────

        if not results:
            results = self._parse_fallback_links(soup)

        response.results = results

        # 纯化 HTML 并记录长度
        clean = self.clean_html(html)
        response.clean_html_length = len(clean)

        if self.verbose:
            logger.okay(
                f"  ✓ Parsed {logstr.mesg(len(results))} results "
                f"(raw={len(html)}, clean={len(clean)})"
            )

        return response

    def _parse_standard_results(self, soup: BeautifulSoup) -> list[GoogleSearchResult]:
        """策略 1：解析标准 div.g 搜索结果。"""
        results = []
        g_divs = soup.select("div.g")

        for i, g in enumerate(g_divs):
            result = self._extract_result_from_g(g, position=i + 1)
            if result and result.url and result.title:
                results.append(result)

        return results

    def _parse_rso_results(self, soup: BeautifulSoup) -> list[GoogleSearchResult]:
        """策略 2：从 #rso 容器中解析。"""
        results = []
        rso = soup.find("div", id="rso")
        if not rso:
            return results

        # 遍历 #rso 的直接子元素
        for i, child in enumerate(rso.children):
            if not isinstance(child, Tag):
                continue
            result = self._extract_result_from_g(child, position=i + 1)
            if result and result.url and result.title:
                results.append(result)

        return results

    def _parse_fallback_links(self, soup: BeautifulSoup) -> list[GoogleSearchResult]:
        """策略 3：退化解析 — 从所有链接中提取搜索结果。"""
        results = []
        search_div = soup.find("div", id="search") or soup

        seen_urls = set()
        position = 0
        for a_tag in search_div.find_all("a", href=True):
            href = a_tag["href"]

            # 过滤非搜索结果链接
            if not href.startswith("http") or "google.com" in href:
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 3:
                # 尝试从父元素获取标题
                parent = a_tag.find_parent("div")
                if parent:
                    h3 = parent.find("h3")
                    if h3:
                        title = h3.get_text(strip=True)

            if title and len(title) >= 3:
                position += 1
                results.append(
                    GoogleSearchResult(
                        title=title,
                        url=href,
                        position=position,
                    )
                )

        return results

    def _extract_result_from_g(
        self, element: Tag, position: int
    ) -> Optional[GoogleSearchResult]:
        """从一个搜索结果容器中提取结构化数据。"""
        result = GoogleSearchResult(position=position)

        # 提取标题（h3 标签）
        h3 = element.find("h3")
        if h3:
            result.title = h3.get_text(strip=True)

        # 提取链接（a 标签的 href）
        a_tag = element.find("a", href=True)
        if a_tag:
            href = a_tag["href"]
            if href.startswith("http") and "google.com" not in href:
                result.url = href
            elif href.startswith("/url?q="):
                # Google 有时使用重定向链接
                match = re.search(r"/url\?q=([^&]+)", href)
                if match:
                    from urllib.parse import unquote
                    result.url = unquote(match.group(1))

        # 提取显示 URL（cite 标签）
        cite = element.find("cite")
        if cite:
            result.displayed_url = cite.get_text(strip=True)

        # 提取摘要
        snippet = self._extract_snippet(element)
        if snippet:
            result.snippet = snippet

        return result

    def _extract_snippet(self, element: Tag) -> str:
        """从搜索结果容器中提取摘要文本。"""
        # 方法 1：查找 data-sncf 属性的元素（Google 摘要容器）
        snippet_div = element.find(attrs={"data-sncf": True})
        if snippet_div:
            return snippet_div.get_text(strip=True)

        # 方法 2：查找 class 包含 "VwiC3b" 的 span（常见的摘要 class）
        for span in element.find_all("span"):
            text = span.get_text(strip=True)
            # 摘要通常较长（>40 chars）且不是标题或 URL
            if len(text) > 40 and not text.startswith("http"):
                return text

        # 方法 3：从 div 中提取最长的文本
        longest_text = ""
        for div in element.find_all("div"):
            text = div.get_text(strip=True)
            if (
                len(text) > len(longest_text)
                and len(text) > 40
                and not text.startswith("http")
            ):
                # 排除标题和 URL 文本
                h3 = element.find("h3")
                if h3 and text == h3.get_text(strip=True):
                    continue
                longest_text = text

        return longest_text
