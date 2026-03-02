"""测试 Playwright 是否能直接访问 Google 搜索。

先验证不通过代理直连，再尝试通过 SSH 隧道代理。
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from webu.google_api.scraper import GoogleScraper
from webu.google_api.pool import GoogleSearchPool as ProxyPool


async def main():
    pool = ProxyPool(verbose=True)

    scraper = GoogleScraper(
        proxy_pool=pool,
        headless=True,
        verbose=True,
    )

    await scraper.start()

    # 测试 1: 直连（无代理）
    print("\n=== 测试 1: 直连 ===")
    try:
        result = await scraper.search(
            query="python programming",
            num=5,
            lang="en",
            proxy_url="direct",
            retry_count=0,
        )
        print(f"  results: {len(result.results)}")
        print(f"  captcha: {result.has_captcha}")
        print(f"  error: {result.error}")
        print(f"  raw_html: {result.raw_html_length}")
        if result.results:
            for r in result.results[:3]:
                print(f"  [{r.position}] {r.title}")
                print(f"       {r.url}")
    except Exception as e:
        print(f"  error: {e}")

    # 测试 2: 通过 SSH 隧道代理 (http://127.0.0.1:11119)
    print("\n=== 测试 2: SSH 隧道代理 ===")
    try:
        result = await scraper.search(
            query="python programming",
            num=5,
            lang="en",
            proxy_url="http://127.0.0.1:11119",
            retry_count=0,
        )
        print(f"  results: {len(result.results)}")
        print(f"  captcha: {result.has_captcha}")
        print(f"  error: {result.error}")
        print(f"  raw_html: {result.raw_html_length}")
        if result.results:
            for r in result.results[:3]:
                print(f"  [{r.position}] {r.title}")
                print(f"       {r.url}")
    except Exception as e:
        print(f"  error: {e}")

    await scraper.stop()


if __name__ == "__main__":
    asyncio.run(main())
