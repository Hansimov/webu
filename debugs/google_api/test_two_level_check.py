"""大规模两级检测集成测试。

对所有 SOCKS5 代理运行 Level-1 → Level-2 流水线。
"""

import asyncio
from tclogger import logger, logstr
from webu.proxy_api.mongo import MongoProxyStore
from webu.proxy_api.checker import check_level1_batch, _build_proxy_url
from webu.google_api.checker import (
    ProxyChecker,
    check_level2_batch,
)


async def main():
    store = MongoProxyStore(verbose=True)
    
    # 只取 SOCKS5 代理（因为 HTTP 代理全部失败）
    all_ips = store.get_all_ips(limit=0)
    socks5_ips = [ip for ip in all_ips if ip["protocol"] == "socks5"]
    logger.note(f"> Total SOCKS5 IPs: {len(socks5_ips)}")
    
    # Level-1: 大批量快速检测
    logger.note(f"\n{'='*60}")
    logger.note(f"  LEVEL-1: Quick Check (SOCKS5)")
    logger.note(f"{'='*60}")
    
    # 测试前 200 个
    sample = socks5_ips[:200]
    level1_results = await check_level1_batch(
        sample,
        timeout_s=10,
        concurrency=50,
        verbose=True,
    )
    
    level1_passed = [r for r in level1_results if r.get("is_valid")]
    logger.note(f"> Level-1 passed: {len(level1_passed)} / {len(sample)}")
    
    if not level1_passed:
        logger.warn("> No SOCKS5 proxies passed Level-1, stopping")
        return
    
    # 显示 Level-1 通过的代理
    for r in level1_passed[:20]:
        logger.okay(f"  ✓ {r['proxy_url']} ({r['latency_ms']}ms) [{r.get('source','')}]")
    
    # 存储 Level-1 结果
    store.upsert_check_results(level1_results)
    
    # Level-2: 对通过的 IP 做 Playwright 搜索检测
    logger.note(f"\n{'='*60}")
    logger.note(f"  LEVEL-2: Google Search Check")
    logger.note(f"{'='*60}")
    
    # 取最多 20 个进行 Level-2 测试
    level2_candidates = level1_passed[:20]
    
    level2_results = await check_level2_batch(
        level2_candidates,
        timeout_s=25,
        concurrency=5,
        verbose=True,
    )
    
    level2_passed = [r for r in level2_results if r.get("is_valid")]
    logger.note(f"> Level-2 passed: {len(level2_passed)} / {len(level2_candidates)}")
    
    for r in level2_passed:
        logger.okay(f"  ✓ {r['proxy_url']} ({r['latency_ms']}ms)")
    
    for r in level2_results:
        if not r.get("is_valid"):
            logger.warn(f"  × {r['proxy_url']}: {r.get('last_error', '')[:80]}")
    
    # 存储 Level-2 结果
    store.upsert_check_results(level2_results)
    
    # 最终统计
    stats = store.get_stats()
    logger.note(f"\n> Final stats: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
