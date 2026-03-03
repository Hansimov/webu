"""运行 Level-2 Google 搜索检测。

从数据库获取 Level-1 通过的代理，进行 Level-2 Google 搜索可用性检测。

运行: python tests/google_api/run_level2_check.py
"""

import asyncio

from webu.proxy_api.mongo import MongoProxyStore
from webu.google_api.checker import check_level2_batch


async def main():
    store = MongoProxyStore(verbose=True)

    # 获取所有 Level-1 有效代理
    proxies = store.get_valid_proxies(limit=300, max_latency_ms=15000)
    print(f"\nL1 valid proxies to check: {len(proxies)}")

    if not proxies:
        print("No valid proxies found, skipping L2 check")
        return

    # 运行 Level-2 检测
    results = await check_level2_batch(
        proxies, timeout_s=20, concurrency=15, verbose=True
    )
    store.upsert_check_results(results)

    valid = sum(1 for r in results if r.get("is_valid"))
    captcha = sum(
        1 for r in results
        if not r.get("is_valid") and "captcha" in r.get("last_error", "").lower()
    )
    print(f"\n=== Level-2 Results ===")
    print(f"Checked: {len(results)}")
    print(f"Valid (can search Google): {valid}")
    print(f"CAPTCHA blocked: {captcha}")
    print(f"Other failures: {len(results) - valid - captcha}")

    # 打印有效代理
    if valid:
        print(f"\n=== Valid L2 Proxies ===")
        for r in results:
            if r.get("is_valid"):
                print(f"  {r['proxy_url']} ({r['latency_ms']}ms)")

    # 打印统计
    print(f"\n=== Database Stats ===")
    stats = store.get_stats()
    for key, val in stats.items():
        print(f"  {key}: {val}")


if __name__ == "__main__":
    asyncio.run(main())
