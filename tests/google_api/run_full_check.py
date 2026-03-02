"""对数据库中的代理执行完整的两级检测。

1. 取一批代理 (前 500 个)
2. Level-1 快速过滤
3. Level-2 Google 搜索检测 (对 Level-1 通过者)
4. 结果写入数据库
"""

import asyncio

from tclogger import logger

from webu.proxy_api.mongo import MongoProxyStore
from webu.google_api.checker import ProxyChecker


async def main():
    store = MongoProxyStore()

    checker = ProxyChecker(
        store=store,
        timeout=20,          # Level-2 超时
        concurrency=30,      # Level-2 并发
        level1_timeout=8,    # Level-1 超时
        level1_concurrency=100,  # Level-1 并发
        verbose=True,
    )

    # 获取未检测的代理
    ip_list = store.get_unchecked_ips(limit=500)
    logger.note(f"Unchecked IPs to test: {len(ip_list)}")

    if not ip_list:
        logger.warn("No unchecked IPs!")
        return

    # 执行两级检测
    results = await checker.check_batch(ip_list, level="all")

    # 统计
    l1_passed = [r for r in results if r.get("check_level") == 1 and r.get("is_valid")]
    l2_passed = [r for r in results if r.get("check_level") == 2 and r.get("is_valid")]
    total = len(results)

    logger.okay(f"\n{'='*60}")
    logger.okay(f"RESULTS:")
    logger.okay(f"  Total checked: {total}")
    logger.okay(f"  Level-1 passed: {len(l1_passed)}")
    logger.okay(f"  Level-2 passed: {len(l2_passed)}")
    if total > 0:
        logger.okay(f"  L2 pass rate: {len(l2_passed)/total*100:.1f}%")

    if l2_passed:
        logger.okay("\nLevel-2 valid proxies:")
        for r in l2_passed:
            logger.okay(
                f"  {r['ip']}:{r['port']} ({r['protocol']}) "
                f"latency={r['latency_ms']}ms"
            )

    # Error distribution for Level-2
    l2_results = [r for r in results if r.get("check_level") == 2]
    l2_invalid = [r for r in l2_results if not r.get("is_valid")]
    if l2_invalid:
        errors = {}
        for r in l2_invalid:
            err = r.get("last_error", "unknown")[:60]
            errors[err] = errors.get(err, 0) + 1
        logger.note("\nLevel-2 error distribution:")
        for err, count in sorted(errors.items(), key=lambda x: -x[1]):
            logger.note(f"  {err}: {count}")

    logger.okay(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
