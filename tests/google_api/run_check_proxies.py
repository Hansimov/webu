"""运行代理检测 — 扫描更多代理以找到可用的。

用法: python tests/google_api/run_check_proxies.py [--limit N]
"""

import asyncio
import argparse
from webu.google_api.proxy_pool import ProxyPool

TEST_CONFIGS = {
    "host": "localhost",
    "port": 27017,
    "dbname": "webu_test",
}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=30, help="检测数量")
    args = parser.parse_args()

    pool = ProxyPool(configs=TEST_CONFIGS, verbose=True)
    results = await pool.check_unchecked(limit=args.limit)

    valid = [r for r in results if r.get("is_valid")]
    print(f"\n{'='*60}")
    print(f"RESULT: {len(valid)}/{len(results)} valid proxies")
    print(f"{'='*60}")
    for r in valid:
        print(f"  ✓ {r['proxy_url']} ({r.get('latency_ms', 0)}ms)")

    stats = pool.stats()
    print(f"\nPool stats: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
