"""测试代理连接性的诊断脚本。

验证：
1. 系统代理是否可用（用于拉取代理列表）
2. 拉取的免费代理 IP 是否能通过 Level-1 检测
3. Playwright 代理集成是否正常
"""

import asyncio
import time
import requests
import aiohttp
from aiohttp_socks import ProxyConnector
from tclogger import logger, logstr


# ═══════════════════════════════════════════════════════════════
# 1. 测试系统代理
# ═══════════════════════════════════════════════════════════════


def test_system_proxy():
    """测试系统代理（127.0.0.1:11119）能否访问外网。"""
    logger.note("> [1] Testing system proxy (127.0.0.1:11119) ...")
    proxy = "http://127.0.0.1:11119"

    # Test httpbin
    try:
        resp = requests.get(
            "https://httpbin.org/ip",
            proxies={"http": proxy, "https": proxy},
            timeout=10,
        )
        logger.okay(f"  ✓ httpbin/ip via system proxy: {resp.json()}")
    except Exception as e:
        logger.warn(f"  × httpbin failed: {e}")

    # Test Google generate_204
    try:
        resp = requests.get(
            "http://www.google.com/generate_204",
            proxies={"http": proxy, "https": proxy},
            timeout=10,
        )
        logger.okay(
            f"  ✓ Google generate_204 via system proxy: status={resp.status_code}"
        )
    except Exception as e:
        logger.warn(f"  × Google generate_204 failed: {e}")


# ═══════════════════════════════════════════════════════════════
# 2. 测试代理源采集
# ═══════════════════════════════════════════════════════════════


def test_proxy_collection():
    """测试从各代理源采集 IP。"""
    logger.note("> [2] Testing proxy collection from sources ...")
    from webu.proxy_api.collector import ProxyCollector
    from webu.proxy_api.mongo import MongoProxyStore

    store = MongoProxyStore(verbose=False)
    collector = ProxyCollector(store=store, verbose=True)

    result = collector.collect_all()
    logger.okay(f"  ✓ Collection result: {result}")
    return result


# ═══════════════════════════════════════════════════════════════
# 3. Level-1 快速检测（aiohttp）
# ═══════════════════════════════════════════════════════════════


async def test_level1_check():
    """测试 Level-1 快速检测。"""
    logger.note("> [3] Testing Level-1 quick check ...")
    from webu.proxy_api.mongo import MongoProxyStore
    from webu.proxy_api.checker import check_level1_batch

    store = MongoProxyStore(verbose=False)

    # 取一些未检测或所有 IP
    ip_list = store.get_all_ips(limit=30)
    if not ip_list:
        logger.warn("  × No IPs in database — run collection first")
        return []

    logger.mesg(f"  Testing {len(ip_list)} IPs ...")
    results = await check_level1_batch(
        ip_list,
        timeout_s=10,
        concurrency=30,
        verbose=True,
    )

    passed = [r for r in results if r.get("is_valid")]
    failed = [r for r in results if not r.get("is_valid")]

    logger.note(f"  Level-1 Results:")
    logger.okay(f"    Passed: {len(passed)}")
    if passed:
        for r in passed[:5]:
            logger.mesg(f"      {r['proxy_url']} ({r['latency_ms']}ms)")

    logger.warn(f"    Failed: {len(failed)}")
    # Show sample errors
    error_types = {}
    for r in failed:
        err = r.get("last_error", "unknown")[:50]
        error_types[err] = error_types.get(err, 0) + 1
    for err, count in sorted(error_types.items(), key=lambda x: -x[1])[:5]:
        logger.mesg(f"      {count}x: {err}")

    return passed


# ═══════════════════════════════════════════════════════════════
# 4. Playwright 代理验证
# ═══════════════════════════════════════════════════════════════


async def test_playwright_proxy():
    """验证 Playwright 代理集成是否工作。

    使用 Playwright 通过代理访问 httpbin.org/ip 来验证：
    1. 代理确实生效了（返回的 IP 不是本机 IP）
    2. Playwright 的 proxy context 配置是正确的
    """
    logger.note("> [4] Testing Playwright proxy integration ...")
    from playwright.async_api import async_playwright
    from webu.proxy_api.mongo import MongoProxyStore

    store = MongoProxyStore(verbose=False)

    # 获取一些 IP（优先取 Level-1 通过的）
    valid_proxies = store.get_valid_proxies(limit=5)
    if not valid_proxies:
        # 退化到所有 IP
        all_ips = store.get_all_ips(limit=5)
        if not all_ips:
            logger.warn("  × No IPs available for Playwright test")
            return
        from webu.proxy_api.checker import _build_proxy_url

        valid_proxies = [
            {"proxy_url": _build_proxy_url(ip["ip"], ip["port"], ip["protocol"]), **ip}
            for ip in all_ips
        ]

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        # First: get our direct IP for comparison
        try:
            ctx_direct = await browser.new_context(ignore_https_errors=True)
            page_direct = await ctx_direct.new_page()
            await page_direct.goto("https://httpbin.org/ip", timeout=15000)
            direct_ip = await page_direct.inner_text("body")
            await ctx_direct.close()
            logger.mesg(f"  Direct IP: {direct_ip.strip()}")
        except Exception as e:
            logger.warn(f"  × Failed to get direct IP: {e}")
            direct_ip = "unknown"

        # Test each proxy
        for proxy_info in valid_proxies[:3]:
            proxy_url = proxy_info.get("proxy_url", proxy_info.get("proxy"))
            logger.note(f"  Testing proxy: {proxy_url}")

            try:
                ctx = await browser.new_context(
                    proxy={"server": proxy_url},
                    ignore_https_errors=True,
                )
                page = await ctx.new_page()

                start = time.time()
                await page.goto("https://httpbin.org/ip", timeout=15000)
                elapsed = int((time.time() - start) * 1000)

                body = await page.inner_text("body")
                await ctx.close()

                logger.okay(f"    ✓ Proxy IP: {body.strip()} ({elapsed}ms)")
            except Exception as e:
                logger.warn(f"    × Failed: {str(e)[:100]}")
                try:
                    await ctx.close()
                except:
                    pass

        await browser.close()


# ═══════════════════════════════════════════════════════════════
# 5. Level-2 搜索检测
# ═══════════════════════════════════════════════════════════════


async def test_level2_check():
    """测试 Level-2 Google 搜索检测。"""
    logger.note("> [5] Testing Level-2 Google search check ...")
    from webu.proxy_api.mongo import MongoProxyStore
    from webu.google_api.checker import check_level2_batch

    store = MongoProxyStore(verbose=False)

    # 获取 Level-1 通过的 IP
    valid_proxies = store.get_valid_proxies(limit=5)
    if not valid_proxies:
        logger.warn("  × No Level-1 passed IPs — skipping Level-2 test")
        return

    results = await check_level2_batch(
        valid_proxies,
        timeout_s=20,
        concurrency=3,
        verbose=True,
    )

    passed = [r for r in results if r.get("is_valid")]
    logger.okay(f"  Level-2 passed: {len(passed)}/{len(results)}")
    for r in passed:
        logger.mesg(f"    {r['proxy_url']} ({r['latency_ms']}ms)")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════


async def main():
    logger.note("=" * 60)
    logger.note("  PROXY CONNECTIVITY DIAGNOSTIC")
    logger.note("=" * 60)

    # Step 1: System proxy
    test_system_proxy()

    # Step 2: Collect proxies
    test_proxy_collection()

    # Step 3: Level-1 check
    level1_passed = await test_level1_check()

    # Step 4: Playwright proxy verification
    await test_playwright_proxy()

    # Step 5: Level-2 check
    if level1_passed:
        await test_level2_check()
    else:
        logger.warn("> [5] Skipping Level-2 — no Level-1 passed IPs")

    logger.note("=" * 60)
    logger.note("  DIAGNOSTIC COMPLETE")
    logger.note("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
