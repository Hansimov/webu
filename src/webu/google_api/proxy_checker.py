"""IP 可用性检测模块 — 两级检测系统。

Level 1 (快速检测): 使用 aiohttp 直接发送 HTTP 请求到 Google 的轻量端点
  - generate_204: 极小流量，仅需返回 204
  - robots.txt: 文本格式，几百字节
  快速过滤掉绝大多数不可用的 IP。

Level 2 (搜索检测): 使用 aiohttp 发送 HTTP 请求到 Google 搜索页面
  - 通过 HTTP 请求（非浏览器自动化）访问 Google 搜索 URL
  - 检查响应状态码、大小、CAPTCHA/sorry 标记
  - HTTP 请求不会触发 Google 的浏览器自动化检测
  - 正常响应约 86KB（JS 搜索页面），CAPTCHA/sorry 响应 < 10KB
  - 验证代理未被 Google 封禁，可用于搜索请求
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
    VIEWPORT_SIZES,
    LOCALES,
)
from .mongo import MongoProxyStore

import random


def _build_proxy_url(ip: str, port: int, protocol: str) -> str:
    """构建代理 URL。

    对于 aiohttp: http 代理需要 http:// 前缀，socks5 需要 socks5://
    """
    if protocol in ("http", "https"):
        return f"http://{ip}:{port}"
    elif protocol in ("socks5",):
        return f"socks5://{ip}:{port}"
    elif protocol in ("socks4",):
        return f"socks4://{ip}:{port}"
    return f"http://{ip}:{port}"


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
    """Level-1 单端点检测。

    Args:
        session: aiohttp session
        proxy_url: HTTP proxy URL, or None if proxy is set via connector (SOCKS)
        endpoint: endpoint config dict
        timeout_s: timeout in seconds

    Returns:
        (success, latency_ms, error_msg)
    """
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
    对 HTTP 代理使用 aiohttp 原生 proxy 参数，对 SOCKS 代理使用 aiohttp-socks。

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

    # 使用主端点（gstatic_204 最快最可靠）
    primary_endpoint = LEVEL1_ENDPOINTS[0]  # gstatic_204
    valid_count = 0
    semaphore = asyncio.Semaphore(concurrency)

    async def _check_single_proxy(item: dict) -> dict:
        nonlocal valid_count
        proxy_url = _build_proxy_url(item["ip"], item["port"], item["protocol"])
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
    batch_size = concurrency * 4  # 每批处理的数量
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
                    "proxy_url": _build_proxy_url(item["ip"], item["port"], item["protocol"]),
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


# ═══════════════════════════════════════════════════════════════
# Level-2: HTTP-based Google 搜索检测
# ═══════════════════════════════════════════════════════════════

# Google 搜索请求的 HTTP 头部（模拟正常浏览器 HTTP 请求）
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

# 正常 Google 搜索响应的最小大小 (bytes)
# 正常: ~86KB (JS 搜索页面), CAPTCHA/sorry: <10KB
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
    """Level-2 单个代理检测：使用 aiohttp HTTP 请求 Google 搜索。

    通过 HTTP 请求（非浏览器自动化）检测代理是否可以访问 Google 搜索。
    HTTP 请求不会触发 Google 的浏览器自动化检测（JavaScript 环境检测）。

    检测标准：
    - HTTP 200 响应
    - 响应大小 > 30KB（正常搜索页面约 86KB）
    - 无 CAPTCHA / sorry 重定向

    Returns:
        {"ip", "port", "protocol", "proxy_url", "is_valid",
         "latency_ms", "last_error", "check_level"}
    """
    proxy_url = _build_proxy_url(ip, port, protocol)
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

                # 检测 CAPTCHA / sorry
                if _has_captcha_markers(body, final_url):
                    result["last_error"] = "CAPTCHA/sorry detected"
                    result["latency_ms"] = elapsed_ms
                    return result

                # 检查 HTTP 状态码
                if resp.status != 200:
                    result["last_error"] = f"HTTP {resp.status}"
                    result["latency_ms"] = elapsed_ms
                    return result

                # 检查响应大小
                if len(body) < _MIN_SEARCH_RESPONSE_SIZE:
                    result["last_error"] = (
                        f"Response too small ({len(body)} chars, "
                        f"min={_MIN_SEARCH_RESPONSE_SIZE})"
                    )
                    result["latency_ms"] = elapsed_ms
                    return result

                # 通过所有检查
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
    """Level-2 批量 HTTP 搜索检测。

    使用 aiohttp 并发检测多个代理是否可以访问 Google 搜索。
    比 Playwright 更快、更可靠，且不会触发浏览器自动化检测。

    Args:
        ip_list: [{"ip", "port", "protocol", ...}]
        timeout_s: 单个检测超时秒数
        concurrency: 并发数

    Returns:
        检测结果列表
    """
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
                "proxy_url": _build_proxy_url(
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

        # 进度日志
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

    Level 1: aiohttp 快速 HTTP 检测（过滤死亡 IP）
    Level 2: Playwright Google 搜索检测（验证搜索可用性）

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

        Returns:
            最终检测结果列表
        """
        if not ip_list:
            return []

        total = len(ip_list)
        logger.note(f"> Starting proxy check: {logstr.mesg(total)} IPs, level={level}")

        if level == "1":
            # 仅 Level-1 检测（实时写入数据库）
            results = await check_level1_batch(
                ip_list,
                timeout_s=self.level1_timeout,
                concurrency=self.level1_concurrency,
                verbose=self.verbose,
                store=self.store,
            )
            return results

        if level == "2":
            # 仅 Level-2 检测（跳过 Level-1）
            results = await check_level2_batch(
                ip_list,
                timeout_s=self.timeout,
                concurrency=self.concurrency,
                verbose=self.verbose,
            )
            self.store.upsert_check_results(results)
            return results

        # level == "all": 先 Level-1 过滤，再对通过的 IP 进行 Level-2 验证
        # ── Level-1 ──（实时写入数据库）
        level1_results = await check_level1_batch(
            ip_list,
            timeout_s=self.level1_timeout,
            concurrency=self.level1_concurrency,
            verbose=self.verbose,
            store=self.store,
        )

        # Level-1 结果已由 check_level1_batch 实时写入数据库
        level1_failed = [r for r in level1_results if not r.get("is_valid")]

        # Level-1 通过的 IP 进入 Level-2
        level1_passed = [r for r in level1_results if r.get("is_valid")]
        if not level1_passed:
            logger.warn("  × No proxies passed Level-1, skipping Level-2")
            return level1_results

        logger.note(
            f"> {logstr.mesg(len(level1_passed))} passed Level-1 → Level-2 ..."
        )

        # ── Level-2 ──
        level2_results = await check_level2_batch(
            level1_passed,
            timeout_s=self.timeout,
            concurrency=self.concurrency,
            verbose=self.verbose,
        )

        # 存储 Level-2 结果
        self.store.upsert_check_results(level2_results)

        # 合并结果：Level-1 失败 + Level-2 结果
        all_results = level1_failed + level2_results

        valid_count = sum(1 for r in all_results if r.get("is_valid"))
        logger.okay(
            f"  ✓ Final: {logstr.mesg(total)} checked → "
            f"{logstr.mesg(len(level1_passed))} passed L1 → "
            f"{logstr.mesg(valid_count)} passed L2"
        )

        return all_results

    async def check_unchecked(self, limit: int = 500, level: str = "all") -> list[dict]:
        """检测尚未检测过的 IP。"""
        ip_list = self.store.get_unchecked_ips(limit=limit)
        if not ip_list:
            logger.mesg("  No unchecked IPs found")
            return []
        return await self.check_batch(ip_list, level=level)

    async def check_stale(self, limit: int = 200) -> list[dict]:
        """重新检测过期的 IP。"""
        ip_list = self.store.get_stale_ips(limit=limit)
        if not ip_list:
            logger.mesg("  No stale IPs found")
            return []
        return await self.check_batch(ip_list)

    async def check_all(self, limit: int = 0) -> list[dict]:
        """检测所有 IP。"""
        ip_list = self.store.get_all_ips(limit=limit)
        if not ip_list:
            logger.mesg("  No IPs found in database")
            return []
        return await self.check_batch(ip_list)
