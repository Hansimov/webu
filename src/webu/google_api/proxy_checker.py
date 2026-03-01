"""IP 可用性检测模块 — 通过代理访问 Google 检测 IP 是否可用。"""

import asyncio
import time

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
    """构建代理 URL。"""
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


class ProxyChecker:
    """使用 Playwright 检测代理 IP 对 Google 搜索的可用性。

    对每个代理 IP：
    1. 创建一个新的 BrowserContext（设置该代理）
    2. 导航到 Google 搜索页
    3. 检查是否成功加载搜索结果
    4. 记录延迟和成功/失败信息
    """

    def __init__(
        self,
        store: MongoProxyStore,
        timeout: int = PROXY_CHECK_TIMEOUT,
        concurrency: int = CHECK_CONCURRENCY,
        verbose: bool = True,
    ):
        self.store = store
        self.timeout = timeout
        self.concurrency = concurrency
        self.verbose = verbose

    async def check_single_proxy(
        self,
        browser,
        ip: str,
        port: int,
        protocol: str,
    ) -> dict:
        """检测单个代理 IP 的 Google 可用性。

        Returns:
            {"ip", "port", "protocol", "proxy_url", "is_valid", "latency_ms", "last_error"}
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

            url = f"{GOOGLE_SEARCH_URL}?q={GOOGLE_CHECK_QUERY}&num=5"
            start_time = time.time()

            await page.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")

            # 等待搜索结果出现（Google 使用 #search 或 #rso 容器）
            try:
                await page.wait_for_selector(
                    "#search, #rso, .g", timeout=self.timeout * 1000
                )
            except Exception:
                # 如果没有搜索结果选择器，检查是否有 CAPTCHA
                content = await page.content()
                if "captcha" in content.lower() or "unusual traffic" in content.lower():
                    result["last_error"] = "CAPTCHA detected"
                    return result
                # 可能只是超时但页面已加载
                if len(content) < 1000:
                    result["last_error"] = "Page too small, likely blocked"
                    return result

            elapsed_ms = int((time.time() - start_time) * 1000)

            # 验证页面内容包含搜索结果
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
                result["last_error"] = f"No search results found (content_len={len(content)})"

        except Exception as e:
            error_msg = str(e)[:200]
            result["last_error"] = error_msg
        finally:
            if context:
                try:
                    await context.close()
                except Exception:
                    pass

        return result

    async def check_batch(
        self,
        ip_list: list[dict],
    ) -> list[dict]:
        """批量检测代理 IP。

        Args:
            ip_list: list of {"ip", "port", "protocol"}

        Returns:
            list of check results
        """
        if not ip_list:
            return []

        total = len(ip_list)
        logger.note(
            f"> Checking {logstr.mesg(total)} proxies "
            f"(concurrency={self.concurrency}, timeout={self.timeout}s) ..."
        )

        results = []
        valid_count = 0

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            semaphore = asyncio.Semaphore(self.concurrency)

            async def check_with_semaphore(item):
                async with semaphore:
                    return await self.check_single_proxy(
                        browser=browser,
                        ip=item["ip"],
                        port=item["port"],
                        protocol=item["protocol"],
                    )

            tasks = [check_with_semaphore(item) for item in ip_list]
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
                    }
                results.append(res)
                if res.get("is_valid"):
                    valid_count += 1

                # 进度日志
                if self.verbose and (i + 1) % 10 == 0:
                    logger.mesg(
                        f"  Progress: {i + 1}/{total} "
                        f"(valid: {valid_count})"
                    )

            await browser.close()

        # 存储结果到 MongoDB
        self.store.upsert_check_results(results)

        logger.okay(
            f"  ✓ Checked {logstr.mesg(total)} proxies: "
            f"{logstr.mesg(valid_count)} valid, "
            f"{logstr.mesg(total - valid_count)} invalid"
        )

        return results

    async def check_unchecked(self, limit: int = 500) -> list[dict]:
        """检测尚未检测过的 IP。"""
        ip_list = self.store.get_unchecked_ips(limit=limit)
        if not ip_list:
            logger.mesg("  No unchecked IPs found")
            return []
        return await self.check_batch(ip_list)

    async def check_stale(self, limit: int = 200) -> list[dict]:
        """重新检测过期的 IP。"""
        ip_list = self.store.get_stale_ips(limit=limit)
        if not ip_list:
            logger.mesg("  No stale IPs found")
            return []
        return await self.check_batch(ip_list)

    async def check_all(self, limit: int = 0) -> list[dict]:
        """检测所有 IP（谨慎使用，耗时较长）。"""
        ip_list = self.store.get_all_ips(limit=limit)
        if not ip_list:
            logger.mesg("  No IPs found in database")
            return []
        return await self.check_batch(ip_list)
