"""深入诊断代理质量 — 按来源和协议分别测试。

目标：
1. 分别测试不同来源（proxifly, thespeedx）的 IP
2. 分别测试不同协议（http, https, socks5）的 IP
3. 尝试不同的检测端点
4. 验证代理是否真的能路由流量
"""

import asyncio
import time
import aiohttp
from aiohttp_socks import ProxyConnector
from tclogger import logger, logstr


# 测试端点
ENDPOINTS = [
    ("http://www.google.com/generate_204", 204, None),
    ("http://httpbin.org/ip", 200, "origin"),
    ("http://ip-api.com/json", 200, "query"),
    ("https://www.google.com/robots.txt", 200, "User-agent"),
]


async def test_proxy_with_endpoint(
    proxy_url: str,
    protocol: str,
    endpoint_url: str,
    expect_status: int,
    expect_body: str | None,
) -> dict:
    """测试单个代理+端点组合。"""
    result = {
        "proxy": proxy_url,
        "url": endpoint_url,
        "ok": False,
        "latency_ms": 0,
        "error": "",
        "body": "",
    }

    try:
        is_socks = protocol in ("socks4", "socks5")
        timeout = aiohttp.ClientTimeout(total=10)

        if is_socks:
            connector = ProxyConnector.from_url(proxy_url)
            session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            kwargs = {"ssl": False}
        else:
            session = aiohttp.ClientSession(timeout=timeout)
            kwargs = {"proxy": proxy_url, "ssl": False}

        async with session:
            start = time.time()
            async with session.get(endpoint_url, **kwargs) as resp:
                elapsed_ms = int((time.time() - start) * 1000)
                body = await resp.text()
                result["latency_ms"] = elapsed_ms
                result["body"] = body[:200]

                if resp.status == expect_status:
                    if expect_body is None or expect_body in body:
                        result["ok"] = True
                    else:
                        result["error"] = f"body mismatch"
                else:
                    result["error"] = f"status={resp.status}"
    except asyncio.TimeoutError:
        result["error"] = "timeout"
    except Exception as e:
        result["error"] = str(e)[:150]

    return result


async def main():
    from webu.proxy_api.mongo import MongoProxyStore
    from webu.proxy_api.checker import _build_proxy_url

    store = MongoProxyStore(verbose=False)

    # 按来源和协议分组
    all_ips = store.get_all_ips(limit=0)
    logger.note(f"> Total IPs in database: {len(all_ips)}")

    groups = {}
    for ip in all_ips:
        key = f"{ip.get('source', 'unknown')}|{ip['protocol']}"
        if key not in groups:
            groups[key] = []
        groups[key].append(ip)

    logger.note(f"> IP groups:")
    for key, ips in sorted(groups.items()):
        logger.mesg(f"  {key}: {len(ips)} IPs")

    # 从每组中采样测试
    logger.note(f"\n> Testing samples from each group ...")

    # 用最简单的端点：httpbin.org/ip — 可以验证代理是否路由了流量
    endpoint_url = "http://httpbin.org/ip"

    for key, ips in sorted(groups.items()):
        source, protocol = key.split("|")
        sample = ips[:5]  # 测试每组前5个

        logger.note(f"\n> [{source}|{protocol}] Testing {len(sample)}/{len(ips)} ...")

        tasks = []
        for ip in sample:
            proxy_url = _build_proxy_url(ip["ip"], ip["port"], ip["protocol"])
            tasks.append(
                test_proxy_with_endpoint(
                    proxy_url, protocol, endpoint_url, 200, "origin"
                )
            )

        results = await asyncio.gather(*tasks)

        passed = sum(1 for r in results if r["ok"])
        logger.mesg(f"  Passed: {passed}/{len(results)}")
        for r in results:
            if r["ok"]:
                logger.okay(
                    f"    ✓ {r['proxy']} → {r['body'][:80]} ({r['latency_ms']}ms)"
                )
            else:
                logger.warn(f"    × {r['proxy']} → {r['error'][:80]}")

    # 还要测试更多 IP（取每组更多样本）
    logger.note(f"\n> Wider test: 20 IPs from each group with generate_204 ...")

    for key, ips in sorted(groups.items()):
        source, protocol = key.split("|")
        sample = ips[:20]

        tasks = []
        for ip in sample:
            proxy_url = _build_proxy_url(ip["ip"], ip["port"], ip["protocol"])
            tasks.append(
                test_proxy_with_endpoint(
                    proxy_url, protocol, "http://www.google.com/generate_204", 204, None
                )
            )

        results = await asyncio.gather(*tasks)
        passed = sum(1 for r in results if r["ok"])

        # 统计错误类型
        errors = {}
        for r in results:
            if not r["ok"]:
                err = r["error"][:40]
                errors[err] = errors.get(err, 0) + 1

        logger.note(f"  [{source}|{protocol}] {passed}/{len(results)} passed")
        if passed > 0:
            for r in results:
                if r["ok"]:
                    logger.okay(f"    ✓ {r['proxy']} ({r['latency_ms']}ms)")
        if errors:
            for err, count in sorted(errors.items(), key=lambda x: -x[1]):
                logger.mesg(f"    {count}x: {err}")


if __name__ == "__main__":
    asyncio.run(main())
