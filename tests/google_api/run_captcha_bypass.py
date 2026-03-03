"""测试 CAPTCHA 自动绕过功能。

使用 127.0.0.1:11119 代理（已知会触发 Google CAPTCHA）来验证：
1. CAPTCHA 检测是否正常工作
2. DOM 方式是否能定位 reCAPTCHA iframe
3. 点击 checkbox 后是否能通过验证
4. 通过后是否能获取搜索结果

运行: python tests/google_api/run_captcha_bypass.py
"""

import asyncio
import time

from webu.google_api.scraper import GoogleScraper


CAPTCHA_PROXY = "http://127.0.0.1:11119"  # 已知触发 CAPTCHA
SAFE_PROXY = "http://127.0.0.1:11111"     # 通常不触发


async def test_captcha_bypass():
    """测试 CAPTCHA 绕过。"""
    print("=" * 60)
    print("Test: CAPTCHA bypass with proxy 11119")
    print("=" * 60)

    scraper = GoogleScraper(headless=True, verbose=True)
    try:
        await scraper.start()

        # 用已知触发 CAPTCHA 的代理搜索
        start = time.time()
        result = await scraper.search(
            query="test",
            num=5,
            proxy_url=CAPTCHA_PROXY,
            retry_count=0,  # 不重试，只测一次
        )
        elapsed = time.time() - start

        print(f"\n{'=' * 60}")
        print(f"Result:")
        print(f"  Query: {result.query}")
        print(f"  Results: {len(result.results)}")
        print(f"  CAPTCHA: {result.has_captcha}")
        print(f"  Error: {result.error}")
        print(f"  Time: {elapsed:.1f}s")

        if result.results:
            print(f"\n  Search results:")
            for i, r in enumerate(result.results[:5]):
                print(f"    [{i+1}] {r.title}")
                print(f"        {r.url}")
        elif result.has_captcha:
            print(f"\n  CAPTCHA was not bypassed — check screenshots in data/google_api_screenshots/")
        else:
            print(f"\n  No results and no CAPTCHA — error: {result.error}")

    finally:
        await scraper.stop()


async def test_safe_proxy_after_bypass():
    """测试安全代理（验证不影响正常搜索流程）。"""
    print(f"\n{'=' * 60}")
    print("Test: Normal search with proxy 11111 (should not trigger CAPTCHA)")
    print("=" * 60)

    scraper = GoogleScraper(headless=True, verbose=True)
    try:
        await scraper.start()

        result = await scraper.search(
            query="python programming",
            num=5,
            proxy_url=SAFE_PROXY,
            retry_count=0,
        )

        print(f"\n  Results: {len(result.results)}")
        print(f"  CAPTCHA: {result.has_captcha}")
        if result.results:
            for i, r in enumerate(result.results[:3]):
                print(f"    [{i+1}] {r.title}: {r.url}")

    finally:
        await scraper.stop()


async def main():
    await test_captcha_bypass()
    await test_safe_proxy_after_bypass()


if __name__ == "__main__":
    asyncio.run(main())
