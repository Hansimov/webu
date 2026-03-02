"""Level-1 代理检测 — 使用 aiohttp 快速检测代理连通性。

Level 1 (快速检测): 使用 aiohttp 直接发送 HTTP 请求到 Google 的轻量端点
  - generate_204: 极小流量，仅需返回 204
  - robots.txt: 文本格式，几百字节
  快速过滤掉绝大多数不可用的 IP。
"""

import asyncio
import random
import time

import aiohttp
from aiohttp_socks import ProxyConnector

from tclogger import logger, logstr

from .constants import (
    PROXY_CHECK_TIMEOUT,
    CHECK_CONCURRENCY,
    USER_AGENTS,
    VIEWPORT_SIZES,
    LOCALES,
)


def build_proxy_url(ip: str, port: int, protocol: str) -> str:
    """构建代理 URL。"""
    if protocol in ("http", "https"):
        return f"http://{ip}:{port}"
    elif protocol in ("socks5",):
        return f"socks5://{ip}:{port}"
    elif protocol in ("socks4",):
        return f"socks4://{ip}:{port}"
    return f"http://{ip}:{port}"


# 向后兼容别名
_build_proxy_url = build_proxy_url


def _random_ua() -> str:
    return random.choice(USER_AGENTS)


def _random_viewport() -> dict:
    return random.choice(VIEWPORT_SIZES)


def _random_locale() -> str:
    return random.choice(LOCALES)


# ═══════════════════════════════════════════════════════════════
# Level-1: 快速 HTTP 检测
# ═══════════════════════════════════════════════════════════════

# Google 的轻量检测端点（按可靠性排序）
LEVEL1_ENDPOINTS = [
    {
        "url": "http://connectivitycheck.gstatic.com/generate_204",
        "expect_status": 204,
        "expect_body": None,
        "name": "gstatic_204",
    },
    {
        "url": "http://www.google.com/generate_204",
        "expect_status": 204,
        "expect_body": None,
        "name": "generate_204",
    },
    {
        "url": "http://clients3.google.com/generate_204",
        "expect_status": 204,
        "expect_body": None,
        "name": "clients3_204",
    },
    {
        "url": "https://www.google.com/robots.txt",
        "expect_status": 200,
        "expect_body": "User-agent",
        "name": "robots.txt",
    },
]


async def _check_level1_single(
    session: aiohttp.ClientSession,
    proxy_url: str | None,
    endpoint: dict,
    timeout_s: int = 10,
) -> tuple[bool, int, str]:
    """Level-1 单端点检测。"""
    url = endpoint["url"]
    expect_status = endpoint["expect_status"]
    expect_body = endpoint.get("expect_body")

    kwargs = {
        "timeout": aiohttp.ClientTimeout(total=timeout_s),
        "ssl": False,
    }
    if proxy_url:
        kwargs["proxy"] = proxy_url

    try:
        start = time.time()
        async with session.get(url, **kwargs) as resp:
            elapsed_ms = int((time.time() - start) * 1000)
            body = await resp.text()

            if resp.status != expect_status:
                return False, elapsed_ms, f"status={resp.status} (expected {expect_status})"

            if expect_body and expect_body not in body:
                return False, elapsed_ms, f"body mismatch for {endpoint['name']}"

            return True, elapsed_ms, ""

    except asyncio.TimeoutError:
        return False, 0, "timeout"
    except aiohttp.ClientError as e:
        return False, 0, str(e)[:150]
    except Exception as e:
        return False, 0, str(e)[:150]


async def check_level1_batch(
    ip_list: list[dict],
    timeout_s: int = 10,
    concurrency: int = 50,
    verbose: bool = True,
    store=None,
) -> list[dict]:
    """Level-1 批量快速检测。

    使用 aiohttp 并发检测多个代理 IP 能否访问 Google 的轻量端点。

    Args:
        ip_list: [{"ip", "port", "protocol", ...}]
        timeout_s: 超时秒数
        concurrency: 并发数
        store: MongoProxyStore 实例（可选），每批结果实时写入数据库

    Returns:
        [{"ip", "port", "protocol", "proxy_url", "is_valid",
          "latency_ms", "last_error", "check_level"}]
    """
    if not ip_list:
        return []

    total = len(ip_list)
    if verbose:
        logger.note(
            f"> [Level-1] Checking {logstr.mesg(total)} proxies "
            f"(concurrency={concurrency}, timeout={timeout_s}s) ..."
        )

    primary_endpoint = LEVEL1_ENDPOINTS[0]  # gstatic_204
    valid_count = 0
    semaphore = asyncio.Semaphore(concurrency)

    async def _check_single_proxy(item: dict) -> dict:
        nonlocal valid_count
        proxy_url = build_proxy_url(item["ip"], item["port"], item["protocol"])
        result = {
            "ip": item["ip"],
            "port": item["port"],
            "protocol": item["protocol"],
            "proxy_url": proxy_url,
            "source": item.get("source", ""),
            "is_valid": False,
            "latency_ms": 0,
            "last_error": "",
            "check_level": 1,
        }

        async with semaphore:
            try:
                is_socks = item["protocol"] in ("socks4", "socks5")
                if is_socks:
                    connector = ProxyConnector.from_url(proxy_url)
                    async with aiohttp.ClientSession(
                        connector=connector,
                        headers={"User-Agent": _random_ua()},
                    ) as session:
                        ok, latency, err = await _check_level1_single(
                            session, None, primary_endpoint, timeout_s
                        )
                else:
                    async with aiohttp.ClientSession(
                        headers={"User-Agent": _random_ua()},
                    ) as session:
                        ok, latency, err = await _check_level1_single(
                            session, proxy_url, primary_endpoint, timeout_s
                        )

                if ok:
                    result["is_valid"] = True
                    result["latency_ms"] = latency
                    valid_count += 1
                else:
                    result["last_error"] = err
            except Exception as e:
                result["last_error"] = str(e)[:200]

        return result

    # 分批执行 + 进度日志 + 实时写入数据库
    batch_size = concurrency * 4
    final_results = []
    checked_count = 0

    for batch_start in range(0, total, batch_size):
        batch_end = min(batch_start + batch_size, total)
        batch = ip_list[batch_start:batch_end]
        tasks = [_check_single_proxy(item) for item in batch]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        batch_results = []
        for i, res in enumerate(raw_results):
            if isinstance(res, Exception):
                item = batch[i]
                res = {
                    "ip": item["ip"],
                    "port": item["port"],
                    "protocol": item["protocol"],
                    "proxy_url": build_proxy_url(item["ip"], item["port"], item["protocol"]),
                    "source": item.get("source", ""),
                    "is_valid": False,
                    "latency_ms": 0,
                    "last_error": str(res)[:200],
                    "check_level": 1,
                }
            batch_results.append(res)
            final_results.append(res)

        # 实时写入数据库
        if store is not None:
            store.upsert_check_results(batch_results)

        checked_count += len(batch)
        if verbose:
            logger.mesg(
                f"  [Level-1] Progress: {checked_count}/{total} "
                f"(valid: {valid_count})"
            )

    if verbose:
        logger.okay(
            f"  ✓ [Level-1] Checked {logstr.mesg(total)}: "
            f"{logstr.mesg(valid_count)} passed, "
            f"{logstr.mesg(total - valid_count)} failed"
        )

    return final_results
