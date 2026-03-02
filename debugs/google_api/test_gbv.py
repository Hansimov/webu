"""测试 Google 基本 HTML 版本 (gbv=1) 能否返回可解析的搜索结果。

Google 对现代浏览器返回 JS SPA，但 gbv=1 参数强制返回基本 HTML 版本。
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

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "html_samples")


# 不同的 URL 参数组合
URL_VARIANTS = [
    {
        "name": "gbv1",
        "url": "https://www.google.com/search?q=python+programming&num=10&hl=en&gbv=1",
        "desc": "基本 HTML 版本 (gbv=1)",
    },
    {
        "name": "gbv2",
        "url": "https://www.google.com/search?q=python+programming&num=10&hl=en&gbv=2",
        "desc": "基本 HTML 版本 (gbv=2)",
    },
    {
        "name": "noscript",
        "url": "https://www.google.com/search?q=python+programming&num=10&hl=en&gbv=1&sei=",
        "desc": "基本 HTML + sei 参数",
    },
]


async def fetch_with_proxy(proxy_info: dict, url: str, timeout_s: int = 20) -> str | None:
    """通过代理获取 URL 内容。"""
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
            async with session.get(url, **kwargs) as resp:
                body = await resp.text()
                print(f"    status={resp.status} size={len(body)}")
                if resp.status == 200:
                    return body
                return None
    except Exception as e:
        print(f"    error: {e}")
        return None


def analyze_and_parse(html: str, name: str):
    """分析 HTML 并用 parser 解析。"""
    soup = BeautifulSoup(html, "html.parser")

    # 关键元素统计
    stats = {
        "div.g": len(soup.select("div.g")),
        "#rso": len(soup.find_all("div", id="rso")),
        "#search": len(soup.find_all("div", id="search")),
        "h3": len(soup.find_all("h3")),
        "a[href]": len(soup.find_all("a", href=True)),
        "cite": len(soup.find_all("cite")),
        "#result-stats": len(soup.find_all("div", id="result-stats")),
    }
    print(f"\n  [{name}] HTML 结构:")
    for k, v in stats.items():
        marker = "✓" if v > 0 else "×"
        print(f"    {marker} {k}: {v}")

    # 显示 h3 内容
    h3s = soup.find_all("h3")
    if h3s:
        print(f"\n  [{name}] h3 标签 (前 5 个):")
        for i, h3 in enumerate(h3s[:5]):
            print(f"    [{i+1}] {h3.get_text(strip=True)[:80]}")

    # 用 parser 解析
    parser = GoogleResultParser(verbose=False)
    response = parser.parse(html, query="python programming")
    print(f"\n  [{name}] Parser 结果:")
    print(f"    results: {len(response.results)}")
    print(f"    captcha: {response.has_captcha}")
    print(f"    raw_html: {response.raw_html_length}")
    print(f"    clean_html: {response.clean_html_length}")
    print(f"    total_results_text: {response.total_results_text}")

    if response.results:
        print(f"\n  [{name}] 搜索结果 (前 5 个):")
        for r in response.results[:5]:
            print(f"    [{r.position}] {r.title}")
            print(f"         url: {r.url}")
            if r.snippet:
                print(f"         snippet: {r.snippet[:80]}...")

    return response


async def main():
    store = MongoProxyStore()
    store.connect()
    proxies = store.get_valid_proxies(limit=30)
    l2_proxies = [p for p in proxies if p.get("check_level") == 2]
    print(f"L2 有效代理: {len(l2_proxies)}")

    if not l2_proxies:
        l2_proxies = proxies[:10]

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for variant in URL_VARIANTS:
        print(f"\n{'='*60}")
        print(f"测试: {variant['desc']}")
        print(f"URL: {variant['url']}")

        html = None
        for i, proxy in enumerate(l2_proxies[:5]):
            proxy_url = _build_proxy_url(proxy["ip"], proxy["port"], proxy["protocol"])
            print(f"\n  尝试代理 [{i+1}]: {proxy_url}")
            html = await fetch_with_proxy(proxy, variant["url"])
            if html:
                filepath = os.path.join(OUTPUT_DIR, f"google_{variant['name']}.html")
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"  ✓ 保存到 {filepath}")
                break

        if html:
            analyze_and_parse(html, variant["name"])
        else:
            print(f"  ✗ 所有代理都无法获取")


if __name__ == "__main__":
    asyncio.run(main())
