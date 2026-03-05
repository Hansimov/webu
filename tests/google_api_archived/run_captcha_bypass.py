"""测试 CAPTCHA 自动绕过功能（E2E 端到端测试）。

使用 127.0.0.1:11119（已知触发 CAPTCHA）和 127.0.0.1:11111 代理测试：
  1. CAPTCHA 检测是否正常工作
  2. DOM 方式能否定位 reCAPTCHA iframe + checkbox
  3. 图片验证 → GridAnnotator → VLM solver → 模拟点击 → Verify
  4. 绕过后能否拿到搜索结果

截图保存在 data/google_api_screenshots/ 目录，用于排查每个阶段的状态。

运行:
  python tests/google_api/run_captcha_bypass.py
  python tests/google_api/run_captcha_bypass.py --proxy 11119
  python tests/google_api/run_captcha_bypass.py --proxy 11111
  python tests/google_api/run_captcha_bypass.py --query "artificial intelligence"
"""

import argparse
import asyncio
import time

from webu.google_api.scraper import GoogleScraper


CAPTCHA_PROXY = "http://127.0.0.1:11119"  # 已知触发 CAPTCHA
SAFE_PROXY = "http://127.0.0.1:11111"     # 通常不触发


def _print_result(label: str, result, elapsed: float):
    """格式化打印搜索结果。"""
    n = len(result.results)
    print(f"\n{'─' * 60}")
    print(f"  [{label}]")
    print(f"  Query:   {result.query}")
    print(f"  Proxy:   {label}")
    print(f"  Results: {n}")
    print(f"  CAPTCHA: {result.has_captcha}")
    print(f"  Error:   {result.error or '(none)'}")
    print(f"  Time:    {elapsed:.1f}s")

    if result.results:
        print(f"\n  Search results:")
        for i, r in enumerate(result.results[:5]):
            print(f"    [{i+1}] {r.title}")
            print(f"        {r.url}")
    elif result.has_captcha:
        print(f"\n  CAPTCHA was not bypassed.")
        print(f"  → Check screenshots: data/google_api_screenshots/")
    else:
        print(f"\n  No results and no CAPTCHA.")


async def test_single_proxy(proxy_url: str, query: str = "test"):
    """用指定代理测试搜索+CAPTCHA绕过。"""
    safe_proxy = proxy_url.split(":")[-1]
    print(f"\n{'═' * 60}")
    print(f"  Test: CAPTCHA bypass — proxy :{safe_proxy}")
    print(f"  Query: {query}")
    print(f"{'═' * 60}")

    scraper = GoogleScraper(headless=True, verbose=True)
    try:
        await scraper.start()

        start = time.time()
        result = await scraper.search(
            query=query,
            num=5,
            proxy_url=proxy_url,
            retry_count=0,
        )
        elapsed = time.time() - start

        _print_result(proxy_url, result, elapsed)
        return result

    finally:
        await scraper.stop()


async def test_both_proxies(query: str = "test"):
    """依次用两个代理测试搜索+CAPTCHA绕过。"""
    scraper = GoogleScraper(headless=True, verbose=True)
    try:
        await scraper.start()

        for proxy_url in [CAPTCHA_PROXY, SAFE_PROXY]:
            safe_proxy = proxy_url.split(":")[-1]
            print(f"\n{'═' * 60}")
            print(f"  Test: proxy :{safe_proxy} — query: {query}")
            print(f"{'═' * 60}")

            start = time.time()
            result = await scraper.search(
                query=query,
                num=5,
                proxy_url=proxy_url,
                retry_count=0,
            )
            elapsed = time.time() - start
            _print_result(proxy_url, result, elapsed)

            # 等待一段时间再测下一个代理
            await asyncio.sleep(2)

    finally:
        await scraper.stop()


async def main():
    parser = argparse.ArgumentParser(description="CAPTCHA bypass E2E test")
    parser.add_argument(
        "--proxy", type=str, default=None,
        help="Proxy port to test (e.g. 11119). Default: test both",
    )
    parser.add_argument(
        "--query", type=str, default="test",
        help="Search query (default: 'test')",
    )
    args = parser.parse_args()

    if args.proxy:
        proxy_url = f"http://127.0.0.1:{args.proxy}"
        await test_single_proxy(proxy_url, args.query)
    else:
        await test_both_proxies(args.query)


if __name__ == "__main__":
    asyncio.run(main())
