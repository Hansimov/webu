"""IP 可用性检测模块 — 两级检测系统。

Level 1 (快速检测): 使用 aiohttp 直接发送 HTTP 请求到 Google 的轻量端点
  - generate_204: 极小流量，仅需返回 204
  - robots.txt: 文本格式，几百字节
  快速过滤掉绝大多数不可用的 IP。

Level 2 (搜索检测): 使用 Playwright 访问 Google 搜索页面
  - 验证搜索功能是否完整可用
  - 检测 CAPTCHA / 封禁
  从 Level-1 通过的 IP 中进一步筛选出可用于搜索的 IP。
"""

import asyncio
import time

import aiohttp
from aiohttp_socks import ProxyConnector

from playwright.async_api import async_playwright
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

    对于 aiohttp (Level-1): http 代理需要 http:// 前缀，socks5 需要 socks5://
    对于 Playwright (Level-2): http 代理用 http://, socks5 用 socks5://
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

# Google 的轻量检测端点
LEVEL1_ENDPOINTS = [
    {
        "url": "http://www.google.com/generate_204",
        "expect_status": 204,
        "expect_body": None,
        "name": "generate_204",
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
) -> list[dict]:
    """Level-1 批量快速检测。

    使用 aiohttp 并发检测多个代理 IP 能否访问 Google 的轻量端点。
    对 HTTP 代理使用 aiohttp 原生 proxy 参数，对 SOCKS 代理使用 aiohttp-socks。

    Args:
        ip_list: [{"ip", "port", "protocol", ...}]
        timeout_s: 超时秒数
        concurrency: 并发数

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

    endpoint = LEVEL1_ENDPOINTS[0]  # generate_204 — 最快
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
                    # SOCKS 代理：使用 ProxyConnector
                    connector = ProxyConnector.from_url(proxy_url)
                    async with aiohttp.ClientSession(
                        connector=connector,
                        headers={"User-Agent": _random_ua()},
                    ) as session:
                        ok, latency, err = await _check_level1_single(
                            session, None, endpoint, timeout_s
                        )
                else:
                    # HTTP 代理：使用 aiohttp 原生 proxy 参数
                    async with aiohttp.ClientSession(
                        headers={"User-Agent": _random_ua()},
                    ) as session:
                        ok, latency, err = await _check_level1_single(
                            session, proxy_url, endpoint, timeout_s
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

    tasks = [_check_single_proxy(item) for item in ip_list]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # 处理异常
    final_results = []
    for i, res in enumerate(raw_results):
        if isinstance(res, Exception):
            item = ip_list[i]
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
        final_results.append(res)

    if verbose:
        logger.okay(
            f"  ✓ [Level-1] Checked {logstr.mesg(total)}: "
            f"{logstr.mesg(valid_count)} passed, "
            f"{logstr.mesg(total - valid_count)} failed"
        )

    return final_results


# ═══════════════════════════════════════════════════════════════
# Level-2: Playwright 搜索页面检测
# ═══════════════════════════════════════════════════════════════


async def check_level2_single(
    browser,
    ip: str,
    port: int,
    protocol: str,
    timeout_s: int = PROXY_CHECK_TIMEOUT,
) -> dict:
    """Level-2 单个代理检测：使用 Playwright 访问 Google 搜索页面。

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

    context = None
    try:
        ua = _random_ua()
        viewport = _random_viewport()
        locale = _random_locale()

        context = await browser.new_context(
            proxy={"server": proxy_url},
            user_agent=ua,
            viewport=viewport,
            locale=locale,
            ignore_https_errors=True,
        )

        page = await context.new_page()

        url = f"{GOOGLE_SEARCH_URL}?q={GOOGLE_CHECK_QUERY}&num=5&hl=en"
        start_time = time.time()

        await page.goto(url, timeout=timeout_s * 1000, wait_until="domcontentloaded")

        # 等待搜索结果
        try:
            await page.wait_for_selector(
                "#search, #rso, .g", timeout=timeout_s * 1000
            )
        except Exception:
            content = await page.content()
            if "captcha" in content.lower() or "unusual traffic" in content.lower():
                result["last_error"] = "CAPTCHA detected"
                return result
            if len(content) < 1000:
                result["last_error"] = f"Page too small ({len(content)} bytes)"
                return result

        elapsed_ms = int((time.time() - start_time) * 1000)

        content = await page.content()
        has_results = (
            '<div id="search"' in content
            or '<div id="rso"' in content
            or 'class="g"' in content
        )

        if has_results and len(content) > 5000:
            result["is_valid"] = True
            result["latency_ms"] = elapsed_ms
        else:
            result["last_error"] = f"No search results (content_len={len(content)})"

    except Exception as e:
        result["last_error"] = str(e)[:200]
    finally:
        if context:
            try:
                await context.close()
            except Exception:
                pass

    return result


async def check_level2_batch(
    ip_list: list[dict],
    timeout_s: int = PROXY_CHECK_TIMEOUT,
    concurrency: int = CHECK_CONCURRENCY,
    verbose: bool = True,
) -> list[dict]:
    """Level-2 批量 Playwright 检测。

    Args:
        ip_list: [{"ip", "port", "protocol", ...}]

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

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        semaphore = asyncio.Semaphore(concurrency)

        async def _check_with_semaphore(item):
            async with semaphore:
                return await check_level2_single(
                    browser=browser,
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

        await browser.close()

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
        level1_concurrency: int = 50,
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
            # 仅 Level-1 检测
            results = await check_level1_batch(
                ip_list,
                timeout_s=self.level1_timeout,
                concurrency=self.level1_concurrency,
                verbose=self.verbose,
            )
            self.store.upsert_check_results(results)
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
        # ── Level-1 ──
        level1_results = await check_level1_batch(
            ip_list,
            timeout_s=self.level1_timeout,
            concurrency=self.level1_concurrency,
            verbose=self.verbose,
        )

        # 存储 Level-1 失败的结果
        level1_failed = [r for r in level1_results if not r.get("is_valid")]
        if level1_failed:
            self.store.upsert_check_results(level1_failed)

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
