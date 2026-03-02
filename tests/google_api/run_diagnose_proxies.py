#!/usr/bin/env python3
"""诊断脚本 — 测试网络连通性和代理可用性。

检测：
1. 直连 Google 端点（无代理）
2. 通过本地代理访问 Google
3. 通过数据库中的代理访问 Google
4. 按协议/来源统计通过率
"""

import asyncio
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import aiohttp
from aiohttp_socks import ProxyConnector
from tclogger import logger, logstr

from webu.proxy_api.checker import (
    LEVEL1_ENDPOINTS,
    _build_proxy_url,
    _random_ua,
    check_level1_batch,
)
from webu.proxy_api.mongo import MongoProxyStore


async def test_direct_access():
    """测试直连 Google 端点（无代理）。"""
    logger.note("=" * 60)
    logger.note("> Test 1: Direct access to Google endpoints (no proxy)")
    logger.note("=" * 60)

    for ep in LEVEL1_ENDPOINTS:
        url = ep["url"]
        name = ep["name"]
        expect_status = ep["expect_status"]

        try:
            start = time.time()
            async with aiohttp.ClientSession(
                headers={"User-Agent": _random_ua()}
            ) as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=10),
                    ssl=False,
                ) as resp:
                    elapsed = int((time.time() - start) * 1000)
                    body = await resp.text()
                    ok = resp.status == expect_status
                    status_str = "✓" if ok else "×"
                    logger.mesg(
                        f"  {status_str} {name}: status={resp.status} "
                        f"(expect {expect_status}), {elapsed}ms, body={len(body)} bytes"
                    )
        except Exception as e:
            logger.warn(f"  × {name}: {e}")


async def test_local_proxy_access():
    """测试通过本地代理访问 Google。"""
    logger.note("=" * 60)
    logger.note("> Test 2: Access via local proxy (http://127.0.0.1:11119)")
    logger.note("=" * 60)

    proxy_url = "http://127.0.0.1:11119"
    ep = LEVEL1_ENDPOINTS[0]  # generate_204

    try:
        start = time.time()
        async with aiohttp.ClientSession(
            headers={"User-Agent": _random_ua()}
        ) as session:
            async with session.get(
                ep["url"],
                proxy=proxy_url,
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=False,
            ) as resp:
                elapsed = int((time.time() - start) * 1000)
                logger.okay(f"  ✓ Status: {resp.status}, {elapsed}ms")
    except Exception as e:
        logger.warn(f"  × Error: {e}")


async def test_db_proxies_sample():
    """从数据库取样本，按协议分别测试。"""
    logger.note("=" * 60)
    logger.note("> Test 3: Sample proxies from database (by protocol)")
    logger.note("=" * 60)

    store = MongoProxyStore(verbose=False)
    all_ips = store.get_all_ips(limit=0)

    # 按协议分组
    by_proto = defaultdict(list)
    for ip in all_ips:
        by_proto[ip["protocol"]].append(ip)

    logger.note(f"> Total IPs: {len(all_ips)}")
    for proto, ips in sorted(by_proto.items()):
        logger.mesg(f"  {proto}: {len(ips)}")

    # 每种协议取 100 个样本测试
    for proto in ["http", "https", "socks4", "socks5"]:
        ips = by_proto.get(proto, [])
        if not ips:
            logger.mesg(f"\n  [{proto}] No proxies found")
            continue

        sample = ips[:100]
        logger.note(f"\n> Testing {len(sample)} {proto} proxies (Level-1) ...")

        results = await check_level1_batch(
            sample, timeout_s=12, concurrency=50, verbose=False
        )

        passed = [r for r in results if r.get("is_valid")]
        failed = [r for r in results if not r.get("is_valid")]

        logger.mesg(
            f"  [{proto}] {len(passed)}/{len(results)} passed "
            f"({len(passed)/len(results)*100:.1f}%)"
        )

        # 错误分类
        err_counter = Counter()
        for r in failed:
            err = r.get("last_error", "unknown").lower()
            if "timeout" in err:
                err_counter["timeout"] += 1
            elif "connection" in err or "connect" in err:
                err_counter["connection"] += 1
            elif "refused" in err:
                err_counter["refused"] += 1
            elif "reset" in err:
                err_counter["reset"] += 1
            elif "socks" in err:
                err_counter["socks_error"] += 1
            elif "ssl" in err:
                err_counter["ssl"] += 1
            elif "status=" in err:
                err_counter["wrong_status"] += 1
            else:
                err_counter["other"] += 1

        for err, cnt in err_counter.most_common(5):
            logger.mesg(f"    {err}: {cnt}")

        # 打印通过的代理
        if passed:
            latencies = [r["latency_ms"] for r in passed]
            avg_lat = sum(latencies) // len(latencies)
            logger.okay(
                f"  [{proto}] Avg latency: {avg_lat}ms, "
                f"min: {min(latencies)}ms, max: {max(latencies)}ms"
            )
            for r in sorted(passed, key=lambda x: x["latency_ms"])[:5]:
                logger.okay(f"    ✓ {r['proxy_url']} ({r['latency_ms']}ms)")


async def test_db_proxies_by_source():
    """按来源分别测试。"""
    logger.note("=" * 60)
    logger.note("> Test 4: Sample proxies from database (by source)")
    logger.note("=" * 60)

    store = MongoProxyStore(verbose=False)
    all_ips = store.get_all_ips(limit=0)

    by_source = defaultdict(list)
    for ip in all_ips:
        by_source[ip.get("source", "unknown")].append(ip)

    for src, ips in sorted(by_source.items()):
        sample = ips[:50]
        logger.note(f"> [{src}] Testing {len(sample)}/{len(ips)} proxies ...")

        results = await check_level1_batch(
            sample, timeout_s=12, concurrency=50, verbose=False
        )

        passed = [r for r in results if r.get("is_valid")]
        rate = len(passed) / len(results) * 100 if results else 0
        logger.mesg(f"  [{src}] {len(passed)}/{len(results)} passed ({rate:.1f}%)")

        if passed:
            for r in sorted(passed, key=lambda x: x["latency_ms"])[:3]:
                logger.okay(f"    ✓ {r['proxy_url']} ({r['protocol']}, {r['latency_ms']}ms)")


async def main():
    await test_direct_access()
    await test_local_proxy_access()
    await test_db_proxies_sample()
    await test_db_proxies_by_source()


if __name__ == "__main__":
    asyncio.run(main())
