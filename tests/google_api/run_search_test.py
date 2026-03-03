"""测试 UC+CDP Google 搜索 — 本地代理 + 数据库有效代理。

1. 先用本地代理 (127.0.0.1:11111, 11119) 确认方案可行
2. 再用数据库中 L2 验证通过的代理测试成功率

运行: python tests/google_api/run_search_test.py
"""

import asyncio
import time
import json

from pathlib import Path
from webu.google_api.scraper import GoogleScraper
from webu.proxy_api.mongo import MongoProxyStore


SELF_BUILT_PROXIES = [
    "http://127.0.0.1:11111",
    "http://127.0.0.1:11119",
]

TEST_QUERIES = [
    "python programming",
    "machine learning tutorial",
    "weather today",
]

RESULT_FILE = Path("data/google_api/search_test_results.json")


async def test_single_proxy(scraper: GoogleScraper, proxy_url: str, query: str) -> dict:
    """单个代理搜索测试。"""
    start = time.time()
    try:
        result = await scraper.search(
            query=query,
            num=5,
            proxy_url=proxy_url,
            retry_count=0,
        )
        elapsed_ms = int((time.time() - start) * 1000)

        return {
            "proxy_url": proxy_url,
            "query": query,
            "success": bool(result.results and not result.has_captcha),
            "result_count": len(result.results),
            "has_captcha": result.has_captcha,
            "error": result.error,
            "latency_ms": elapsed_ms,
            "titles": [r.title for r in result.results[:3]],
        }
    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "proxy_url": proxy_url,
            "query": query,
            "success": False,
            "result_count": 0,
            "has_captcha": False,
            "error": str(e)[:200],
            "latency_ms": elapsed_ms,
            "titles": [],
        }


async def main():
    all_results = []

    # ── Phase 1: 本地代理测试 ──────────────────────────────
    print("=" * 60)
    print("Phase 1: Testing with self-built local proxies")
    print("=" * 60)

    scraper = GoogleScraper(headless=True, verbose=True)
    try:
        await scraper.start()

        for proxy_url in SELF_BUILT_PROXIES:
            for query in TEST_QUERIES[:1]:  # 每个代理只测一个 query
                result = await test_single_proxy(scraper, proxy_url, query)
                all_results.append(result)
                status = "✓" if result["success"] else "×"
                captcha = " [CAPTCHA]" if result["has_captcha"] else ""
                print(
                    f"  {status} {proxy_url} → "
                    f"{result['result_count']} results ({result['latency_ms']}ms)"
                    f"{captcha}"
                )
                if result["titles"]:
                    for t in result["titles"]:
                        print(f"    - {t}")
                await asyncio.sleep(1)
    finally:
        await scraper.stop()

    # ── Phase 2: 数据库 L2 有效代理测试 ───────────────────────
    print("\n" + "=" * 60)
    print("Phase 2: Testing with L2-validated proxies from DB")
    print("=" * 60)

    store = MongoProxyStore(verbose=False)
    l2_proxies = store.get_valid_proxies(limit=10, max_latency_ms=15000)
    # 优先选 L2
    l2_only = [p for p in l2_proxies if p.get("check_level") == 2]
    test_proxies = l2_only[:5] if l2_only else l2_proxies[:5]

    if not test_proxies:
        print("  No L2 valid proxies available, skipping Phase 2")
    else:
        print(f"  Testing {len(test_proxies)} proxies ...")
        scraper = GoogleScraper(headless=True, verbose=True)
        try:
            await scraper.start()

            for proxy_info in test_proxies:
                proxy_url = proxy_info["proxy_url"]
                query = "python programming"
                result = await test_single_proxy(scraper, proxy_url, query)
                all_results.append(result)
                status = "✓" if result["success"] else "×"
                captcha = " [CAPTCHA]" if result["has_captcha"] else ""
                print(
                    f"  {status} {proxy_url} → "
                    f"{result['result_count']} results ({result['latency_ms']}ms)"
                    f"{captcha}"
                )
                if result["titles"]:
                    for t in result["titles"]:
                        print(f"    - {t}")
                await asyncio.sleep(2)
        finally:
            await scraper.stop()

    # ── Summary ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    total = len(all_results)
    success = sum(1 for r in all_results if r["success"])
    captcha = sum(1 for r in all_results if r["has_captcha"])
    print(f"  Total tests: {total}")
    print(f"  Successful: {success} ({success/max(1,total)*100:.0f}%)")
    print(f"  CAPTCHA blocked: {captcha}")
    print(f"  Other failures: {total - success - captcha}")

    # 保存结果
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
    print(f"\n  Results saved to: {RESULT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
