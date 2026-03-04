"""代理池 → Google 搜索端到端测试。

流程：
  1. 从免费代理源采集 SOCKS 代理到 MongoDB
  2. Level-1 快速检测（连通性）
  3. 使用 L1 通过的代理，通过 GoogleScraper (UC + Playwright) 搜索并解析结果
  4. 统计成功率和稳定性

注意: 原 Level-2 HTTP 检查已移除。
  L2 使用 raw aiohttp 直接请求 Google Search，
  Google 对非浏览器 HTTP 做了严格检测，导致 0% 通过率。
  现改为 L1 通过后直接用浏览器方案测试。

运行:
  python tests/google_api/run_proxy_search_test.py
  python tests/google_api/run_proxy_search_test.py --query "python programming"
  python tests/google_api/run_proxy_search_test.py --limit 5 --query "machine learning"
  python tests/google_api/run_proxy_search_test.py --skip-collect --socks5-only
"""

import argparse
import asyncio
import time

from collections import Counter, defaultdict
from tclogger import logger, logstr

from webu.proxy_api.mongo import MongoProxyStore
from webu.proxy_api.collector import ProxyCollector
from webu.proxy_api.checker import check_level1_batch, build_proxy_url
from webu.google_api.scraper import GoogleScraper


# ═══════════════════════════════════════════════════════════════
# Step 1: 采集 SOCKS 代理
# ═══════════════════════════════════════════════════════════════


def collect_socks_proxies(store: MongoProxyStore) -> dict:
    """只采集 SOCKS4/SOCKS5 代理源。"""
    from webu.proxy_api.constants import PROXY_SOURCES

    socks_sources = [
        s for s in PROXY_SOURCES if s["protocol"] in ("socks4", "socks5")
    ]
    logger.note(
        f"> Collecting from {logstr.mesg(len(socks_sources))} "
        f"SOCKS sources (skip HTTP/HTTPS) ..."
    )

    collector = ProxyCollector(
        store=store, sources=socks_sources, verbose=True
    )
    result = collector.collect_all()
    return result


# ═══════════════════════════════════════════════════════════════
# Step 2 & 3: 一二级检测
# ═══════════════════════════════════════════════════════════════


async def check_socks_proxies(
    store: MongoProxyStore,
    socks5_only: bool = False,
) -> dict:
    """对数据库中 SOCKS 代理执行 Level-1 检测，返回通过的代理供浏览器测试。

    L2 HTTP 检查已移除（raw aiohttp → Google 0% 通过率）。
    """

    # 获取所有 SOCKS IP
    all_ips = store.get_all_ips(limit=0)
    socks_ips = [
        ip for ip in all_ips if ip["protocol"] in ("socks4", "socks5")
    ]

    if socks5_only:
        socks_ips = [ip for ip in socks_ips if ip["protocol"] == "socks5"]
        logger.mesg("  (socks5 only mode)")

    if not socks_ips:
        logger.warn("  × No SOCKS proxies in database")
        return {"l1_total": 0, "l1_passed": 0, "l1_proxies": []}

    logger.note(
        f"> Total SOCKS proxies in DB: {logstr.mesg(len(socks_ips))} "
        f"(socks4: {sum(1 for x in socks_ips if x['protocol']=='socks4')}, "
        f"socks5: {sum(1 for x in socks_ips if x['protocol']=='socks5')})"
    )

    # ── Level-1 ──
    logger.note("=" * 60)
    l1_start = time.time()
    l1_results = await check_level1_batch(
        socks_ips,
        timeout_s=12,
        concurrency=80,
        verbose=True,
        store=store,
    )
    l1_elapsed = time.time() - l1_start

    l1_passed = [r for r in l1_results if r.get("is_valid")]

    logger.note(
        f"> Level-1 summary: {logstr.mesg(len(l1_passed))}/{len(l1_results)} passed "
        f"in {l1_elapsed:.1f}s"
    )

    # 按协议统计 L1
    for proto in ("socks4", "socks5"):
        total_p = sum(1 for r in l1_results if r["protocol"] == proto)
        passed_p = sum(
            1 for r in l1_passed if r["protocol"] == proto
        )
        if total_p:
            logger.mesg(
                f"  {proto}: {passed_p}/{total_p} "
                f"({passed_p/total_p*100:.1f}%)"
            )

    if not l1_passed:
        logger.warn("  × No proxies passed Level-1")
        return {
            "l1_total": len(l1_results),
            "l1_passed": 0,
            "l1_elapsed": round(l1_elapsed, 1),
            "l1_proxies": [],
        }

    # 按延迟排序
    l1_passed_sorted = sorted(
        l1_passed, key=lambda r: r.get("latency_ms", 99999)
    )

    # L1 延迟分布
    latencies = [r["latency_ms"] for r in l1_passed_sorted]
    logger.mesg(
        f"  L1 latency: min={latencies[0]}ms, "
        f"median={latencies[len(latencies)//2]}ms, "
        f"max={latencies[-1]}ms"
    )

    return {
        "l1_total": len(l1_results),
        "l1_passed": len(l1_passed),
        "l1_elapsed": round(l1_elapsed, 1),
        "l1_proxies": l1_passed_sorted,
    }


# ═══════════════════════════════════════════════════════════════
# Step 3: 用 L1 代理做真实 Google 搜索 (UC + Playwright)
# ═══════════════════════════════════════════════════════════════


def _classify_error(result: dict) -> str:
    """对搜索结果进行失败分类。"""
    if result.get("success"):
        return "success"
    if result.get("has_captcha"):
        return "captcha"
    error = (result.get("error") or "").lower()
    if "timeout" in error or "timed out" in error:
        return "timeout"
    if "net::err_proxy_connection_failed" in error:
        return "proxy_conn_failed"
    if "net::err_socks_connection_failed" in error:
        return "socks_failed"
    if "net::err_empty_response" in error:
        return "empty_response"
    if "net::err_network_changed" in error:
        return "network_changed"
    if "net::err_connection" in error or "connection" in error:
        return "connection_error"
    if not result.get("result_count") and not result.get("error"):
        return "no_results"
    return "other"


async def test_google_search(
    l1_proxies: list[dict],
    query: str = "python programming",
    limit: int = 10,
) -> dict:
    """用通过 L1 的 SOCKS 代理测试 Google 搜索。

    直接使用 UC+Playwright 浏览器方案，跳过无效的 L2 HTTP 检查。
    """
    if not l1_proxies:
        logger.warn("  × No L1 proxies to test")
        return {"total": 0, "success": 0, "captcha": 0, "error": 0}

    # 按延迟排序，取 top N
    proxies_sorted = sorted(
        l1_proxies, key=lambda r: r.get("latency_ms", 99999)
    )
    test_proxies = proxies_sorted[:limit]

    logger.note("=" * 60)
    logger.note(
        f"> Testing Google search with {logstr.mesg(len(test_proxies))} "
        f"L1-passed SOCKS proxies (UC + Playwright)"
    )
    logger.mesg(f"  Query: {logstr.mesg(query)}")

    scraper = GoogleScraper(headless=True, verbose=True)
    results = []

    try:
        await scraper.start()

        for i, proxy in enumerate(test_proxies):
            proxy_url = proxy.get("proxy_url") or build_proxy_url(
                proxy["ip"], proxy["port"], proxy["protocol"]
            )
            logger.note(
                f"> [{i+1}/{len(test_proxies)}] {logstr.mesg(proxy_url)} "
                f"({proxy.get('latency_ms', '?')}ms)"
            )

            start = time.time()
            try:
                result = await scraper.search(
                    query=query,
                    num=5,
                    proxy_url=proxy_url,
                    retry_count=0,
                )
                elapsed = time.time() - start

                entry = {
                    "proxy_url": proxy_url,
                    "protocol": proxy["protocol"],
                    "latency_ms": proxy.get("latency_ms", 0),
                    "elapsed": round(elapsed, 1),
                    "has_captcha": result.has_captcha,
                    "result_count": len(result.results),
                    "error": result.error or "",
                    "success": bool(result.results),
                }
                results.append(entry)

                if result.results:
                    logger.okay(
                        f"  ✓ {len(result.results)} results in {elapsed:.1f}s"
                    )
                    for j, r in enumerate(result.results[:3]):
                        logger.mesg(f"    [{j+1}] {r.title[:60]}")
                elif result.has_captcha:
                    logger.warn(f"  × CAPTCHA in {elapsed:.1f}s")
                else:
                    logger.warn(
                        f"  × No results in {elapsed:.1f}s"
                        f"{': ' + result.error[:80] if result.error else ''}"
                    )

            except Exception as e:
                elapsed = time.time() - start
                results.append({
                    "proxy_url": proxy_url,
                    "protocol": proxy["protocol"],
                    "latency_ms": proxy.get("latency_ms", 0),
                    "elapsed": round(elapsed, 1),
                    "has_captcha": False,
                    "result_count": 0,
                    "error": str(e)[:200],
                    "success": False,
                })
                logger.warn(f"  × Exception: {str(e)[:100]}")

            # 搜索间随机延迟
            if i < len(test_proxies) - 1:
                delay = 2.0
                await asyncio.sleep(delay)

    finally:
        await scraper.stop()

    # ── 统计 ──
    total = len(results)
    success = sum(1 for r in results if r["success"])
    captcha = sum(1 for r in results if r["has_captcha"])
    error = sum(1 for r in results if r["error"] and not r["has_captcha"])

    # 详细错误分类
    categories = Counter()
    for r in results:
        categories[_classify_error(r)] += 1

    return {
        "total": total,
        "success": success,
        "captcha": captcha,
        "error": error,
        "categories": dict(categories.most_common()),
        "results": results,
    }


# ═══════════════════════════════════════════════════════════════
# Step 5: 汇总报告
# ═══════════════════════════════════════════════════════════════


def print_report(check_stats: dict, search_stats: dict):
    """打印最终报告。"""
    print(f"\n{'═' * 60}")
    print(f"  PROXY PIPELINE REPORT")
    print(f"{'═' * 60}")

    print(f"\n  [Level-1] SOCKS connectivity")
    print(f"    Total:  {check_stats.get('l1_total', 0)}")
    print(f"    Passed: {check_stats.get('l1_passed', 0)}")
    rate = (
        check_stats["l1_passed"] / max(1, check_stats["l1_total"]) * 100
        if check_stats.get("l1_total")
        else 0
    )
    print(f"    Rate:   {rate:.1f}%")

    total = search_stats.get("total", 0)
    if total:
        print(f"\n  [Search] GoogleScraper (UC + Playwright)")
        print(f"    Total:   {total}")
        print(f"    Success: {search_stats['success']}")
        print(f"    CAPTCHA: {search_stats['captcha']}")
        print(f"    Error:   {search_stats['error']}")
        print(f"    Success rate: {search_stats['success']/total*100:.1f}%")

        # 详细错误分类
        categories = search_stats.get("categories", {})
        if categories:
            print(f"\n    Error breakdown:")
            for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
                pct = count / max(1, total) * 100
                print(f"      {cat:25s} {count:4d} ({pct:.1f}%)")

        # 按协议分组
        if search_stats.get("results"):
            by_proto = defaultdict(lambda: {"total": 0, "success": 0})
            for r in search_stats["results"]:
                by_proto[r["protocol"]]["total"] += 1
                if r["success"]:
                    by_proto[r["protocol"]]["success"] += 1
            print(f"\n    By protocol:")
            for proto, stats in sorted(by_proto.items()):
                prate = stats["success"] / max(1, stats["total"]) * 100
                print(
                    f"      {proto}: "
                    f"{stats['success']}/{stats['total']} ({prate:.0f}%)"
                )

            # 成功代理的搜索耗时
            success_elapsed = [
                r["elapsed"] for r in search_stats["results"] if r["success"]
            ]
            if success_elapsed:
                print(
                    f"\n    Search time (success): "
                    f"min={min(success_elapsed):.1f}s, "
                    f"avg={sum(success_elapsed)/len(success_elapsed):.1f}s, "
                    f"max={max(success_elapsed):.1f}s"
                )
    else:
        print(f"\n  [Search] No L1 proxies available to test")

    print(f"\n{'═' * 60}")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════


async def main(query: str, limit: int, skip_collect: bool, socks5_only: bool):
    store = MongoProxyStore(verbose=True)

    # Step 1: 采集
    if not skip_collect:
        collect_result = collect_socks_proxies(store)
        logger.okay(
            f"  ✓ Collected: +{collect_result.get('inserted', 0)} new, "
            f"{collect_result.get('updated', 0)} updated"
        )

    # Step 2: L1 检测
    check_stats = await check_socks_proxies(store, socks5_only=socks5_only)

    # Step 3: 浏览器搜索测试 (直接用 L1 通过的代理)
    l1_proxies = check_stats.get("l1_proxies", [])
    search_stats = await test_google_search(
        l1_proxies, query=query, limit=limit
    )

    # Step 4: 报告
    print_report(check_stats, search_stats)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="代理池 → Google 搜索端到端测试"
    )
    parser.add_argument(
        "--query", default="python programming",
        help="搜索关键词 (default: python programming)",
    )
    parser.add_argument(
        "--limit", type=int, default=10,
        help="搜索测试代理数量上限 (default: 10)",
    )
    parser.add_argument(
        "--skip-collect", action="store_true",
        help="跳过代理采集，直接用数据库中已有的",
    )
    parser.add_argument(
        "--socks5-only", action="store_true",
        help="只测试 socks5 代理 (Playwright 原生支持)",
    )
    args = parser.parse_args()

    asyncio.run(main(
        query=args.query,
        limit=args.limit,
        skip_collect=args.skip_collect,
        socks5_only=args.socks5_only,
    ))
