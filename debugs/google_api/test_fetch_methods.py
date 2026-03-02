"""测试多种方法获取 Google 搜索的可解析 HTML。

方法 1: Googlebot User-Agent (Google 为搜索引擎爬虫渲染 HTML)
方法 2: HTTP (非 HTTPS) 协议
方法 3: 跟随 noscript 中的重定向
方法 4: Google Webcache
方法 5: google.com/complete/search (JSON 建议 API)
"""

import asyncio
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import aiohttp
from aiohttp_socks import ProxyConnector
from bs4 import BeautifulSoup

from webu.proxy_api.mongo import MongoProxyStore
from webu.google_api.parser import GoogleResultParser
from webu.proxy_api.checker import _build_proxy_url
from webu.google_api.checker import _LEVEL2_HEADERS

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "html_samples")

# 测试方案
TEST_VARIANTS = [
    {
        "name": "googlebot_ua",
        "url": "https://www.google.com/search?q=python+programming&num=10&hl=en",
        "headers": {
            **_LEVEL2_HEADERS,
            "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        },
        "desc": "Googlebot UA",
    },
    {
        "name": "http_plain",
        "url": "http://www.google.com/search?q=python+programming&num=10&hl=en",
        "headers": {
            **_LEVEL2_HEADERS,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
        "desc": "HTTP (非 HTTPS)",
    },
    {
        "name": "old_ua",
        "url": "https://www.google.com/search?q=python+programming&num=10&hl=en",
        "headers": {
            "User-Agent": "Lynx/2.8.9rel.1 libwww-FM/2.14 SSL-MM/1.4.1 GNUTLS/3.6.13",
            "Accept": "text/html",
        },
        "desc": "Lynx (文本浏览器) UA",
    },
    {
        "name": "wget_ua",
        "url": "https://www.google.com/search?q=python+programming&num=10&hl=en",
        "headers": {
            "User-Agent": "Wget/1.21",
            "Accept": "*/*",
        },
        "desc": "Wget UA",
    },
    {
        "name": "curl_ua",
        "url": "https://www.google.com/search?q=python+programming&num=10&hl=en",
        "headers": {
            "User-Agent": "curl/7.81.0",
            "Accept": "*/*",
        },
        "desc": "curl UA",
    },
    {
        "name": "noscript_redirect",
        "url": None,  # 将从第一次请求中提取
        "headers": {
            **_LEVEL2_HEADERS,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
        "desc": "跟随 noscript 重定向",
    },
]


async def fetch_with_proxy(proxy_info: dict, url: str, headers: dict, timeout_s: int = 25, allow_redirect: bool = True) -> tuple[str | None, str]:
    """通过代理获取 URL 内容。返回 (html, final_url)。"""
    proxy_url = _build_proxy_url(proxy_info["ip"], proxy_info["port"], proxy_info["protocol"])
    timeout = aiohttp.ClientTimeout(total=timeout_s)

    try:
        is_socks = proxy_info["protocol"] in ("socks4", "socks5")
        if is_socks:
            connector = ProxyConnector.from_url(proxy_url)
            session = aiohttp.ClientSession(connector=connector, headers=headers, timeout=timeout)
        else:
            session = aiohttp.ClientSession(headers=headers, timeout=timeout)

        kwargs = {"ssl": False, "allow_redirects": allow_redirect}
        if not is_socks:
            kwargs["proxy"] = proxy_url

        async with session:
            async with session.get(url, **kwargs) as resp:
                body = await resp.text()
                final_url = str(resp.url)
                print(f"    status={resp.status} size={len(body)} final_url={final_url[:80]}")
                return body, final_url
    except Exception as e:
        print(f"    error: {e}")
        return None, ""


def analyze_html(html: str, name: str):
    """快速分析 HTML 结构并测试 parser。"""
    soup = BeautifulSoup(html, "html.parser")

    # 关键元素
    div_g = len(soup.select("div.g"))
    rso = len(soup.find_all("div", id="rso"))
    search = len(soup.find_all("div", id="search"))
    h3_count = len(soup.find_all("h3"))
    cite_count = len(soup.find_all("cite"))
    a_ext = len([a for a in soup.find_all("a", href=True)
                 if a["href"].startswith("http") and "google" not in a["href"]])

    print(f"  结构: div.g={div_g} #rso={rso} #search={search} h3={h3_count} cite={cite_count} 外部链接={a_ext}")

    # h3 内容预览
    h3s = soup.find_all("h3")
    if h3s:
        print(f"  h3 标签:")
        for i, h3 in enumerate(h3s[:5]):
            print(f"    [{i+1}] {h3.get_text(strip=True)[:80]}")

    # script 占比
    scripts = soup.find_all("script")
    script_len = sum(len(str(s)) for s in scripts)
    print(f"  Script: {len(scripts)} 个, {script_len}/{len(html)} bytes ({100*script_len//max(1,len(html))}%)")

    # Parser 测试
    parser = GoogleResultParser(verbose=False)
    response = parser.parse(html, query="python programming")
    print(f"  Parser: {len(response.results)} results, captcha={response.has_captcha}, "
          f"clean={response.clean_html_length}")

    if response.results:
        for r in response.results[:3]:
            print(f"    [{r.position}] {r.title}")
            print(f"         {r.url}")

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

    # 找一个能用的代理
    working_proxy = None
    for proxy in l2_proxies[:10]:
        proxy_url = _build_proxy_url(proxy["ip"], proxy["port"], proxy["protocol"])
        print(f"\n在找能用的代理... 试 {proxy_url}")
        html, _ = await fetch_with_proxy(
            proxy,
            "https://www.google.com/search?q=test&num=5&hl=en",
            {**_LEVEL2_HEADERS, "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        if html and len(html) > 10000:
            working_proxy = proxy
            # 提取 noscript 中的重定向 URL
            soup = BeautifulSoup(html, "html.parser")
            noscript = soup.find("noscript")
            if noscript:
                meta = noscript.find("meta", attrs={"http-equiv": "refresh"})
                if meta:
                    content = meta.get("content", "")
                    m = re.search(r'url=(/[^"]+)', content)
                    if m:
                        redirect_path = m.group(1)
                        TEST_VARIANTS[-1]["url"] = f"https://www.google.com{redirect_path}"
                        print(f"  提取到重定向 URL: {TEST_VARIANTS[-1]['url'][:80]}")
            break

    if not working_proxy:
        print("没有找到能用的代理")
        return

    proxy_url = _build_proxy_url(working_proxy["ip"], working_proxy["port"], working_proxy["protocol"])
    print(f"\n使用代理: {proxy_url}")

    for variant in TEST_VARIANTS:
        if variant["url"] is None:
            print(f"\n{'='*60}")
            print(f"跳过: {variant['desc']} (未提取到 URL)")
            continue

        print(f"\n{'='*60}")
        print(f"测试: {variant['desc']}")
        print(f"URL: {variant['url'][:80]}")

        html, final_url = await fetch_with_proxy(
            working_proxy, variant["url"], variant["headers"],
        )

        if html:
            filepath = os.path.join(OUTPUT_DIR, f"google_{variant['name']}.html")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  保存到: {filepath}")
            analyze_html(html, variant["name"])
        else:
            print(f"  获取失败")


if __name__ == "__main__":
    asyncio.run(main())
