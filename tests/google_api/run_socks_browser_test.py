"""测试 L1 通过的 SOCKS 代理能否通过 UC+Playwright 获取 Google 搜索结果。

跳过 L2 HTTP 检查（raw aiohttp 被 Google 完全屏蔽,0% 通过率）,
直接用浏览器方案测试 SOCKS 代理的可用性。

诊断结论:
  L2 检查使用 raw aiohttp HTTP 请求访问 Google Search,
  Google 对非浏览器流量做了严格检测，导致:
    - 141 timeout (代理慢 + Google 拒绝)
    - 48 other (连接错误/断开)
    - 11 CAPTCHA (Google 检测到自动化访问)
  
  因此 L2 HTTP 检查对 SOCKS 代理完全失效。
  正确的方法是直接用 UC+Playwright 浏览器方案 (反检测),
  让 L1 通过的 SOCKS 代理直接上浏览器测试。

运行: python tests/google_api/run_socks_browser_test.py [--limit N] [--query Q]
"""

import argparse
import asyncio
import json
import time

from datetime import datetime, timezone, timedelta
from pathlib import Path

from webu.google_api.scraper import GoogleScraper
from webu.proxy_api.mongo import MongoProxyStore

TZ_SHANGHAI = timezone(timedelta(hours=8))
RESULT_FILE = Path("data/google_api/socks_browser_test_results.json")

DEFAULT_QUERY = "python programming"
DEFAULT_LIMIT = 20


def get_l1_socks_proxies(limit: int = 50, max_latency_ms: int = 8000) -> list[dict]:
    """从数据库中获取 L1 通过的 SOCKS 代理。

    优先选择 socks5 (Playwright 原生支持),其次 socks4。
    """
    store = MongoProxyStore(verbose=False)
    coll = store.db[store.check_collection]

    # 查询 L1 通过的 SOCKS 代理
    filter_doc = {
        "is_valid": True,
        "protocol": {"$in": ["socks5", "socks4"]},
        "latency_ms": {"$gt": 0, "$lte": max_latency_ms},
        "$or": [
            {"is_abandoned": {"$ne": True}},
            {"is_abandoned": {"$exists": False}},
        ],
    }

    cursor = (
        coll.find(filter_doc, {"_id": 0})
        .sort("latency_ms", 1)
        .limit(limit * 2)  # 多取一些，分 socks5/socks4
    )
    results = list(cursor)

    # 优先 socks5
    socks5 = [r for r in results if r.get("protocol") == "socks5"]
    socks4 = [r for r in results if r.get("protocol") == "socks4"]

    # socks5 优先，然后补充 socks4
    selected = socks5[:limit]
    remaining = limit - len(selected)
    if remaining > 0:
        selected.extend(socks4[:remaining])

    return selected


async def test_single_proxy(
    scraper: GoogleScraper,
    proxy_url: str,
    query: str,
    timeout_extra: int = 0,
) -> dict:
    """用浏览器测试单个代理的 Google 搜索。"""
    start = time.time()
    try:
        result = await scraper.search(
            query=query,
            num=5,
            proxy_url=proxy_url,
            retry_count=0,  # 不重试，直接测单次成功率
        )
        elapsed_ms = int((time.time() - start) * 1000)

        return {
            "proxy_url": proxy_url,
            "query": query,
            "success": bool(result.results and not result.has_captcha),
            "result_count": len(result.results),
            "has_captcha": result.has_captcha,
            "captcha_bypassed": (
                result.has_captcha is False
                and result.results
                and "captcha" not in (result.error or "").lower()
            ),
            "error": result.error,
            "latency_ms": elapsed_ms,
            "titles": [r.title for r in result.results[:3]],
        }
    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        error_str = str(e)[:300]
        return {
            "proxy_url": proxy_url,
            "query": query,
            "success": False,
            "result_count": 0,
            "has_captcha": False,
            "captcha_bypassed": False,
            "error": error_str,
            "latency_ms": elapsed_ms,
            "titles": [],
        }


def classify_error(result: dict) -> str:
    """对失败结果分类。"""
    if result["success"]:
        return "success"
    if result["has_captcha"]:
        return "captcha"
    error = (result.get("error") or "").lower()
    if "timeout" in error or "timed out" in error:
        return "timeout"
    if "net::err_proxy_connection_failed" in error:
        return "proxy_conn_failed"
    if "net::err_connection" in error or "connection" in error:
        return "connection_error"
    if "net::err_socks_connection_failed" in error:
        return "socks_failed"
    if not result["result_count"] and not result["error"]:
        return "no_results"
    return "other"


async def main():
    parser = argparse.ArgumentParser(description="SOCKS 代理浏览器搜索测试")
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        help=f"测试代理数量 (默认 {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--query", type=str, default=DEFAULT_QUERY,
        help=f"搜索关键词 (默认 '{DEFAULT_QUERY}')",
    )
    parser.add_argument(
        "--max-latency", type=int, default=8000,
        help="L1 最大延迟阈值(ms) (默认 8000)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("SOCKS Proxy Browser Test (UC + Playwright)")
    print("=" * 70)
    print(f"  Query:       {args.query}")
    print(f"  Max proxies: {args.limit}")
    print(f"  Max latency: {args.max_latency}ms")
    print()

    # ── Step 1: 获取 L1 SOCKS 代理 ──────────────────────────
    print("[Step 1] Fetching L1-passed SOCKS proxies from DB ...")
    proxies = get_l1_socks_proxies(limit=args.limit, max_latency_ms=args.max_latency)

    if not proxies:
        print("  × No L1-passed SOCKS proxies found in DB!")
        print("  Run the proxy collection + L1 check first.")
        return

    socks5_count = sum(1 for p in proxies if p.get("protocol") == "socks5")
    socks4_count = sum(1 for p in proxies if p.get("protocol") == "socks4")
    print(f"  Found {len(proxies)} proxies (socks5={socks5_count}, socks4={socks4_count})")
    print(f"  Latency range: {proxies[0].get('latency_ms', '?')}ms "
          f"- {proxies[-1].get('latency_ms', '?')}ms")
    print()

    # ── Step 2: 启动浏览器并逐个测试 ────────────────────────
    print("[Step 2] Starting UC+Playwright browser ...")
    scraper = GoogleScraper(headless=True, verbose=True)
    all_results = []

    try:
        await scraper.start()
        print()
        print(f"[Step 3] Testing {len(proxies)} proxies ...")
        print("-" * 70)

        for i, proxy_info in enumerate(proxies):
            proxy_url = proxy_info.get("proxy_url", "")
            if not proxy_url:
                # 从字段构建
                proto = proxy_info.get("protocol", "socks5")
                ip = proxy_info.get("ip", "")
                port = proxy_info.get("port", 0)
                proxy_url = f"{proto}://{ip}:{port}"

            l1_latency = proxy_info.get("latency_ms", "?")
            print(f"\n  [{i+1}/{len(proxies)}] {proxy_url} (L1: {l1_latency}ms)")

            result = await test_single_proxy(scraper, proxy_url, args.query)
            result["l1_latency_ms"] = l1_latency
            result["protocol"] = proxy_info.get("protocol", "?")
            all_results.append(result)

            category = classify_error(result)
            if result["success"]:
                print(f"    ✓ SUCCESS — {result['result_count']} results "
                      f"in {result['latency_ms']}ms")
                if result["titles"]:
                    for t in result["titles"][:2]:
                        print(f"      - {t}")
            else:
                captcha_mark = " [CAPTCHA]" if result["has_captcha"] else ""
                error_short = (result.get("error") or "unknown")[:100]
                print(f"    × FAIL ({category}){captcha_mark} "
                      f"in {result['latency_ms']}ms")
                print(f"      {error_short}")

            # 搜索间隔 — 避免太快触发 Google 检测
            if i < len(proxies) - 1:
                await asyncio.sleep(2)

    finally:
        await scraper.stop()

    # ── Step 4: 汇总报告 ──────────────────────────────────
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    total = len(all_results)
    success = sum(1 for r in all_results if r["success"])
    captcha = sum(1 for r in all_results if r["has_captcha"])

    # 按错误分类
    categories = {}
    for r in all_results:
        cat = classify_error(r)
        categories[cat] = categories.get(cat, 0) + 1

    print(f"  Total tested:  {total}")
    print(f"  Successful:    {success} ({success/max(1,total)*100:.1f}%)")
    print(f"  CAPTCHA:       {captcha}")
    print(f"  Failed:        {total - success}")
    print()
    print("  Error breakdown:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        pct = count / max(1, total) * 100
        print(f"    {cat:25s} {count:4d} ({pct:.1f}%)")

    if success > 0:
        success_results = [r for r in all_results if r["success"]]
        avg_latency = sum(r["latency_ms"] for r in success_results) / len(success_results)
        print(f"\n  Avg success latency: {avg_latency:.0f}ms")
        print(f"  Success proxy protocols:")
        s5 = sum(1 for r in success_results if r.get("protocol") == "socks5")
        s4 = sum(1 for r in success_results if r.get("protocol") == "socks4")
        print(f"    socks5: {s5}, socks4: {s4}")

    # ── 保存结果 ──────────────────────────────────────────
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "test_time": datetime.now(TZ_SHANGHAI).strftime("%Y-%m-%d %H:%M:%S"),
        "query": args.query,
        "total": total,
        "success": success,
        "captcha": captcha,
        "categories": categories,
        "results": all_results,
    }
    RESULT_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n  Results saved to: {RESULT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
