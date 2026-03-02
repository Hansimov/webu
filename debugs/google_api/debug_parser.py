"""调试 Google 搜索结果解析器。

1. 从数据库获取 L2 有效代理
2. 通过代理获取 Google 搜索 HTML
3. 保存原始 HTML 到文件
4. 分析 HTML 结构（关键元素）
5. 测试 parser 解析效果
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import aiohttp
from aiohttp_socks import ProxyConnector
from bs4 import BeautifulSoup

from webu.proxy_api.mongo import MongoProxyStore
from webu.google_api.parser import GoogleResultParser
from webu.proxy_api.checker import _build_proxy_url, _random_ua
from webu.google_api.checker import _LEVEL2_HEADERS


SEARCH_URL = "https://www.google.com/search?q=python+programming&num=10&hl=en"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "html_samples")


async def fetch_google_html(proxy_info: dict, timeout_s: int = 20) -> str | None:
    """通过代理获取 Google 搜索 HTML。"""
    proxy_url = _build_proxy_url(proxy_info["ip"], proxy_info["port"], proxy_info["protocol"])
    headers = {**_LEVEL2_HEADERS, "User-Agent": _random_ua()}
    timeout = aiohttp.ClientTimeout(total=timeout_s)

    try:
        is_socks = proxy_info["protocol"] in ("socks4", "socks5")
        if is_socks:
            connector = ProxyConnector.from_url(proxy_url)
            session = aiohttp.ClientSession(connector=connector, headers=headers, timeout=timeout)
        else:
            session = aiohttp.ClientSession(headers=headers, timeout=timeout)

        kwargs = {"ssl": False}
        if not is_socks:
            kwargs["proxy"] = proxy_url

        async with session:
            async with session.get(SEARCH_URL, **kwargs) as resp:
                body = await resp.text()
                print(f"  [{proxy_url}] status={resp.status} size={len(body)}")
                if resp.status == 200 and len(body) > 30000:
                    return body
                return None
    except Exception as e:
        print(f"  [{proxy_url}] error: {e}")
        return None


def analyze_html_structure(html: str):
    """分析 Google 搜索 HTML 的关键结构。"""
    soup = BeautifulSoup(html, "html.parser")

    print("\n=== HTML 结构分析 ===")
    print(f"总长度: {len(html)} bytes")

    # 关键元素检测
    checks = [
        ("div.g", soup.select("div.g")),
        ("div#rso", soup.find_all("div", id="rso")),
        ("div#search", soup.find_all("div", id="search")),
        ("div#result-stats", soup.find_all("div", id="result-stats")),
        ("h3", soup.find_all("h3")),
        ("a[href]", soup.find_all("a", href=True)),
        ("cite", soup.find_all("cite")),
    ]

    for name, elements in checks:
        print(f"  {name}: {len(elements)} 个")

    # 检查 h3 内容
    h3s = soup.find_all("h3")
    if h3s:
        print("\n=== h3 标签内容 ===")
        for i, h3 in enumerate(h3s[:15]):
            text = h3.get_text(strip=True)
            parent_a = h3.find_parent("a", href=True)
            href = parent_a["href"] if parent_a else "无链接"
            print(f"  [{i+1}] {text[:80]}")
            print(f"       href: {href[:100]}")

    # 检查 a 标签中有外部链接的
    external_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and "google.com" not in href:
            title = a.get_text(strip=True)
            if title and len(title) > 3:
                external_links.append((title[:60], href[:100]))

    if external_links:
        print(f"\n=== 外部链接 ({len(external_links)} 个) ===")
        for i, (title, href) in enumerate(external_links[:15]):
            print(f"  [{i+1}] {title}")
            print(f"       {href}")

    # 检查 #rso 结构
    rso = soup.find("div", id="rso")
    if rso:
        print(f"\n=== #rso 子元素 ===")
        for i, child in enumerate(rso.children):
            if hasattr(child, "name") and child.name:
                text_preview = child.get_text(strip=True)[:80]
                print(f"  [{i}] <{child.name}> attrs={list(child.attrs.keys())[:5]} text='{text_preview}'")
    else:
        print("\n  ⚠ 没有找到 #rso 元素")

    # 检查可能是搜索结果的 div
    # Google 可能使用 data-* 属性的 div
    search_div = soup.find("div", id="search")
    if search_div:
        print(f"\n=== #search 直接子元素 ===")
        for i, child in enumerate(search_div.children):
            if hasattr(child, "name") and child.name:
                text_preview = child.get_text(strip=True)[:80]
                classes = child.get("class", [])
                print(f"  [{i}] <{child.name}> class={classes} text='{text_preview[:60]}'")

    # 检查是否有 CAPTCHA
    captcha_markers = ["captcha", "unusual traffic", "/sorry/", "recaptcha"]
    html_lower = html.lower()
    for marker in captcha_markers:
        if marker in html_lower:
            print(f"\n  ⚠ 检测到 CAPTCHA 标记: {marker}")


def test_parser(html: str):
    """使用 parser 解析并输出结果。"""
    parser = GoogleResultParser(verbose=True)

    print("\n=== Parser 解析结果 ===")
    response = parser.parse(html, query="python programming")

    print(f"  results: {len(response.results)}")
    print(f"  has_captcha: {response.has_captcha}")
    print(f"  raw_html_length: {response.raw_html_length}")
    print(f"  clean_html_length: {response.clean_html_length}")
    print(f"  total_results_text: {response.total_results_text}")
    print(f"  error: {response.error}")

    for r in response.results[:10]:
        print(f"\n  [{r.position}] {r.title}")
        print(f"      url: {r.url}")
        print(f"      snippet: {r.snippet[:100]}..." if r.snippet else "      snippet: (无)")


async def main():
    # 1. 获取 L2 有效代理
    store = MongoProxyStore()
    store.connect()
    proxies = store.get_valid_proxies(limit=30)
    l2_proxies = [p for p in proxies if p.get("check_level") == 2]
    print(f"L2 有效代理: {len(l2_proxies)} / 总有效: {len(proxies)}")

    if not l2_proxies:
        print("没有 L2 代理，使用所有有效代理")
        l2_proxies = proxies[:10]

    # 2. 尝试获取 Google HTML
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html = None
    for i, proxy in enumerate(l2_proxies[:10]):
        print(f"\n尝试代理 [{i+1}]: {proxy['protocol']}://{proxy['ip']}:{proxy['port']}")
        html = await fetch_google_html(proxy)
        if html:
            # 保存原始 HTML
            filepath = os.path.join(OUTPUT_DIR, f"google_raw_{i+1}.html")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  ✓ 保存到 {filepath}")
            break

    if not html:
        print("\n✗ 所有代理都无法获取 Google HTML")
        return

    # 3. 分析 HTML 结构
    analyze_html_structure(html)

    # 4. 测试 parser
    test_parser(html)


if __name__ == "__main__":
    asyncio.run(main())
