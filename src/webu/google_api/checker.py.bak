"""Google 搜索专用 Level-2 代理检测 + 两级检测编排。

Level 2 (搜索检测): 使用 aiohttp 发送 HTTP 请求到 Google 搜索页面
  - 检查响应状态码、大小、CAPTCHA/sorry 标记
  - 验证代理未被 Google 封禁，可用于搜索请求

ProxyChecker: 统一编排 Level-1 (proxy_api) + Level-2 检测流程。
"""

import asyncio
import time

import aiohttp
from aiohttp_socks import ProxyConnector

from tclogger import logger, logstr

from .constants import (
    GOOGLE_SEARCH_URL,
    GOOGLE_CHECK_QUERY,
    PROXY_CHECK_TIMEOUT,
    CHECK_CONCURRENCY,
    USER_AGENTS,
)
from webu.proxy_api.checker import (
    build_proxy_url,
    _build_proxy_url,
    _random_ua,
    check_level1_batch,
)
from webu.proxy_api.mongo import MongoProxyStore

import random


# ═══════════════════════════════════════════════════════════════
# Level-2: HTTP-based Google 搜索检测
# ═══════════════════════════════════════════════════════════════

_LEVEL2_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

_MIN_SEARCH_RESPONSE_SIZE = 30000


def _has_captcha_markers(body: str, url: str) -> bool:
    """检查响应是否包含 CAPTCHA / sorry 标记。"""
    if "/sorry/" in url:
        return True
    lower = body.lower()
    return any(marker in lower for marker in (
        "captcha", "unusual traffic", "/sorry/", "recaptcha",
    ))


async def check_level2_single(
    ip: str,
    port: int,
    protocol: str,
    timeout_s: int = PROXY_CHECK_TIMEOUT,
) -> dict:
    """Level-2 单个代理检测：使用 aiohttp HTTP 请求 Google 搜索。"""
    proxy_url = build_proxy_url(ip, port, protocol)
    result = {
        "ip": ip,
        "port": port,
        "protocol": protocol,
        "proxy_url": proxy_url,
        "is_valid": False,
        "latency_ms": 0,
        "last_error": "",
        "check_level": 2,
    }

    timeout = aiohttp.ClientTimeout(total=timeout_s)
    headers = {**_LEVEL2_HEADERS, "User-Agent": _random_ua()}
    kwargs: dict = {"ssl": False}

    try:
        is_socks = protocol in ("socks4", "socks5")
        if is_socks:
            connector = ProxyConnector.from_url(proxy_url)
            session = aiohttp.ClientSession(
                connector=connector, headers=headers, timeout=timeout,
            )
        else:
            session = aiohttp.ClientSession(
                headers=headers, timeout=timeout,
            )
            kwargs["proxy"] = proxy_url

        async with session:
            url = (
                f"{GOOGLE_SEARCH_URL}"
                f"?q={GOOGLE_CHECK_QUERY.replace(' ', '+')}"
                f"&num=5&hl=en"
            )
            start = time.time()
            async with session.get(url, **kwargs) as resp:
                body = await resp.text()
                elapsed_ms = int((time.time() - start) * 1000)

                final_url = str(resp.url)

                if _has_captcha_markers(body, final_url):
                    result["last_error"] = "CAPTCHA/sorry detected"
                    result["latency_ms"] = elapsed_ms
                    return result

                if resp.status != 200:
                    result["last_error"] = f"HTTP {resp.status}"
                    result["latency_ms"] = elapsed_ms
                    return result

                if len(body) < _MIN_SEARCH_RESPONSE_SIZE:
                    result["last_error"] = (
                        f"Response too small ({len(body)} chars, "
                        f"min={_MIN_SEARCH_RESPONSE_SIZE})"
                    )
                    result["latency_ms"] = elapsed_ms
                    return result

                result["is_valid"] = True
                result["latency_ms"] = elapsed_ms

    except asyncio.TimeoutError:
        result["last_error"] = "timeout"
    except aiohttp.ClientError as e:
        result["last_error"] = str(e)[:200]
    except Exception as e:
        result["last_error"] = str(e)[:200]

    return result


async def check_level2_batch(
    ip_list: list[dict],
    timeout_s: int = PROXY_CHECK_TIMEOUT,
    concurrency: int = CHECK_CONCURRENCY,
    verbose: bool = True,
) -> list[dict]:
    """Level-2 批量 HTTP 搜索检测。"""
    if not ip_list:
        return []

    total = len(ip_list)
    if verbose:
        logger.note(
            f"> [Level-2] Checking {logstr.mesg(total)} proxies "
            f"(concurrency={concurrency}, timeout={timeout_s}s) ..."
        )

    results = []
    valid_count = 0
    semaphore = asyncio.Semaphore(concurrency)

    async def _check_with_semaphore(item):
        async with semaphore:
            return await check_level2_single(
                ip=item["ip"],
                port=item["port"],
                protocol=item["protocol"],
                timeout_s=timeout_s,
            )

    tasks = [_check_with_semaphore(item) for item in ip_list]
    batch_results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, res in enumerate(batch_results):
        if isinstance(res, Exception):
            item = ip_list[i]
            res = {
                "ip": item["ip"],
                "port": item["port"],
                "protocol": item["protocol"],
                "proxy_url": build_proxy_url(
                    item["ip"], item["port"], item["protocol"]
                ),
                "is_valid": False,
                "latency_ms": 0,
                "last_error": str(res)[:200],
                "check_level": 2,
            }
        results.append(res)
        if res.get("is_valid"):
            valid_count += 1

        if verbose and (i + 1) % 10 == 0:
            logger.mesg(
                f"  [Level-2] Progress: {i + 1}/{total} "
                f"(valid: {valid_count})"
            )

    if verbose:
        logger.okay(
            f"  ✓ [Level-2] Checked {logstr.mesg(total)}: "
            f"{logstr.mesg(valid_count)} valid, "
            f"{logstr.mesg(total - valid_count)} invalid"
        )

    return results


# ═══════════════════════════════════════════════════════════════
# ProxyChecker: 统一两级检测流程
# ═══════════════════════════════════════════════════════════════


class ProxyChecker:
    """两级代理检测器。

    Level 1: aiohttp 快速 HTTP 检测（过滤死亡 IP）— 来自 proxy_api
    Level 2: HTTP Google 搜索检测（验证搜索可用性）— Google 特有

    流程：所有 IP → Level-1 过滤 → Level-2 验证 → 存储结果
    """

    def __init__(
        self,
        store: MongoProxyStore,
        timeout: int = PROXY_CHECK_TIMEOUT,
        concurrency: int = CHECK_CONCURRENCY,
        level1_timeout: int = 10,
        level1_concurrency: int = 100,
        verbose: bool = True,
    ):
        self.store = store
        self.timeout = timeout
        self.concurrency = concurrency
        self.level1_timeout = level1_timeout
        self.level1_concurrency = level1_concurrency
        self.verbose = verbose

    async def check_batch(
        self,
        ip_list: list[dict],
        level: str = "all",
    ) -> list[dict]:
        """两级检测流程。

        Args:
            ip_list: [{"ip", "port", "protocol", ...}]
            level: "1" = 仅 Level-1, "2" = 仅 Level-2, "all" = Level-1 + Level-2
        """
        if not ip_list:
            return []

        total = len(ip_list)
        logger.note(f"> Starting proxy check: {logstr.mesg(total)} IPs, level={level}")

        if level == "1":
            results = await check_level1_batch(
                ip_list,
                timeout_s=self.level1_timeout,
                concurrency=self.level1_concurrency,
                verbose=self.verbose,
                store=self.store,
            )
            return results

        if level == "2":
            results = await check_level2_batch(
                ip_list,
                timeout_s=self.timeout,
                concurrency=self.concurrency,
                verbose=self.verbose,
            )
            self.store.upsert_check_results(results)
            return results

        # level == "all": Level-1 → Level-2
        level1_results = await check_level1_batch(
            ip_list,
            timeout_s=self.level1_timeout,
            concurrency=self.level1_concurrency,
            verbose=self.verbose,
            store=self.store,
        )

        level1_failed = [r for r in level1_results if not r.get("is_valid")]
        level1_passed = [r for r in level1_results if r.get("is_valid")]

        if not level1_passed:
            logger.warn("  × No proxies passed Level-1, skipping Level-2")
            return level1_results

        logger.note(
            f"> {logstr.mesg(len(level1_passed))} passed Level-1 → Level-2 ..."
        )

        level2_results = await check_level2_batch(
            level1_passed,
            timeout_s=self.timeout,
            concurrency=self.concurrency,
            verbose=self.verbose,
        )

        self.store.upsert_check_results(level2_results)

        all_results = level1_failed + level2_results

        valid_count = sum(1 for r in all_results if r.get("is_valid"))
        logger.okay(
            f"  ✓ Final: {logstr.mesg(total)} checked → "
            f"{logstr.mesg(len(level1_passed))} passed L1 → "
            f"{logstr.mesg(valid_count)} passed L2"
        )

        return all_results

    async def check_unchecked(self, limit: int = 500, level: str = "all") -> list[dict]:
        ip_list = self.store.get_unchecked_ips(limit=limit)
        if not ip_list:
            logger.mesg("  No unchecked IPs found")
            return []
        return await self.check_batch(ip_list, level=level)

    async def check_stale(self, limit: int = 200) -> list[dict]:
        ip_list = self.store.get_stale_ips(limit=limit)
        if not ip_list:
            logger.mesg("  No stale IPs found")
            return []
        return await self.check_batch(ip_list)

    async def check_all(self, limit: int = 0) -> list[dict]:
        ip_list = self.store.get_all_ips(limit=limit)
        if not ip_list:
            logger.mesg("  No IPs found in database")
            return []
        return await self.check_batch(ip_list)
