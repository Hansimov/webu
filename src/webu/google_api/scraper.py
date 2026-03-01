"""Playwright Google 抓取器 — 使用浏览器池 + 代理轮换获取搜索结果。"""

import asyncio
import random
import time

from playwright.async_api import async_playwright, Browser, Playwright
from tclogger import logger, logstr
from typing import Optional
from urllib.parse import urlencode

from .constants import (
    GOOGLE_SEARCH_URL,
    SEARCH_TIMEOUT,
    USER_AGENTS,
    VIEWPORT_SIZES,
    LOCALES,
)
from .parser import GoogleResultParser, GoogleSearchResponse
from .proxy_pool import ProxyPool


class GoogleScraper:
    """Playwright 驱动的 Google 搜索抓取器。

    架构：策略 B — 持久浏览器 + 每次搜索创建新上下文
    - 维护一个持久的浏览器实例
    - 每次搜索创建新的 BrowserContext（指定代理 IP）
    - 搜索完成后关闭上下文释放内存
    """

    def __init__(
        self,
        proxy_pool: ProxyPool,
        headless: bool = True,
        timeout: int = SEARCH_TIMEOUT,
        verbose: bool = True,
    ):
        self.proxy_pool = proxy_pool
        self.headless = headless
        self.timeout = timeout
        self.verbose = verbose
        self.parser = GoogleResultParser(verbose=verbose)

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._search_count = 0
        self._max_searches_before_restart = 200

    async def start(self):
        """启动浏览器。"""
        if self._browser:
            return

        logger.note("> Starting Playwright browser ...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        self._search_count = 0
        logger.okay("  ✓ Browser started")

    async def stop(self):
        """关闭浏览器。"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.note("> Browser stopped")

    async def _ensure_browser(self):
        """确保浏览器可用，必要时重启。"""
        if (
            self._browser
            and self._search_count < self._max_searches_before_restart
        ):
            return

        if self._browser:
            logger.note(
                f"> Restarting browser after {self._search_count} searches ..."
            )
            await self.stop()

        await self.start()

    async def search(
        self,
        query: str,
        num: int = 10,
        lang: str = "en",
        proxy_url: str = None,
        retry_count: int = 2,
    ) -> GoogleSearchResponse:
        """执行 Google 搜索。

        Args:
            query: 搜索关键词
            num: 期望的结果数量
            lang: 搜索语言
            proxy_url: 指定代理 URL（为 None 则自动从代理池获取）
            retry_count: 重试次数

        Returns:
            GoogleSearchResponse 解析后的搜索结果
        """
        await self._ensure_browser()

        for attempt in range(retry_count + 1):
            # 获取代理
            if proxy_url == "direct":
                current_proxy = None  # 直连模式，不使用代理
            elif proxy_url:
                current_proxy = proxy_url
            else:
                proxy_info = self.proxy_pool.get_proxy()
                if proxy_info:
                    current_proxy = proxy_info["proxy_url"]
                else:
                    current_proxy = None

            if self.verbose:
                proxy_display = current_proxy or "direct"
                logger.note(
                    f"> Search [{attempt + 1}/{retry_count + 1}]: "
                    f"{logstr.mesg(query)} via {logstr.file(proxy_display)}"
                )

            result = await self._do_search(
                query=query,
                num=num,
                lang=lang,
                proxy_url=current_proxy,
            )

            if result.results and not result.has_captcha:
                return result

            if result.has_captcha:
                logger.warn(
                    f"  × CAPTCHA detected (attempt {attempt + 1}), "
                    f"switching proxy ..."
                )
                # 标记该代理为无效
                if proxy_info := getattr(result, "_proxy_info", None):
                    self.proxy_pool.store.upsert_check_result(
                        {
                            **proxy_info,
                            "is_valid": False,
                            "last_error": "CAPTCHA detected during search",
                        }
                    )
                proxy_url = None  # 下次重试使用新代理
                continue

            if not result.results and attempt < retry_count:
                logger.warn(
                    f"  × No results (attempt {attempt + 1}), retrying ..."
                )
                proxy_url = None
                await asyncio.sleep(random.uniform(1, 3))
                continue

        return result

    async def _do_search(
        self,
        query: str,
        num: int,
        lang: str,
        proxy_url: str = None,
    ) -> GoogleSearchResponse:
        """执行单次搜索（内部方法）。"""
        context = None
        response = GoogleSearchResponse(query=query)

        try:
            # 随机化浏览器指纹
            ua = random.choice(USER_AGENTS)
            viewport = random.choice(VIEWPORT_SIZES)
            locale = random.choice(LOCALES)

            context_opts = {
                "user_agent": ua,
                "viewport": viewport,
                "locale": locale,
                "ignore_https_errors": True,
            }
            if proxy_url:
                context_opts["proxy"] = {"server": proxy_url}

            context = await self._browser.new_context(**context_opts)
            page = await context.new_page()

            # 构建搜索 URL
            params = {"q": query, "num": num, "hl": lang}
            url = f"{GOOGLE_SEARCH_URL}?{urlencode(params)}"

            # 添加随机延迟（模拟人类行为）
            await asyncio.sleep(random.uniform(0.5, 2.0))

            # 导航到搜索页
            start_time = time.time()
            await page.goto(
                url, timeout=self.timeout * 1000, wait_until="domcontentloaded"
            )

            # 等待搜索结果渲染
            try:
                await page.wait_for_selector(
                    "#search, #rso, div.g", timeout=self.timeout * 1000
                )
            except Exception:
                pass  # 可能超时但页面已部分加载

            elapsed_ms = int((time.time() - start_time) * 1000)

            # 获取页面 HTML
            html = await page.content()
            response.raw_html_length = len(html)

            if self.verbose:
                logger.mesg(
                    f"  Page loaded: {logstr.mesg(f'{len(html)} bytes')} "
                    f"in {logstr.mesg(f'{elapsed_ms}ms')}"
                )

            # 解析搜索结果
            response = self.parser.parse(html, query=query)

            self._search_count += 1

        except Exception as e:
            error_msg = str(e)[:300]
            response.error = error_msg
            if self.verbose:
                logger.warn(f"  × Search error: {error_msg}")
        finally:
            if context:
                try:
                    await context.close()
                except Exception:
                    pass

        return response

    async def search_batch(
        self,
        queries: list[str],
        num: int = 10,
        lang: str = "en",
        delay_range: tuple = (2, 5),
    ) -> list[GoogleSearchResponse]:
        """批量搜索（顺序执行，带随机延迟）。

        Args:
            queries: 搜索查询列表
            num: 每个查询期望的结果数量
            lang: 搜索语言
            delay_range: 两次搜索之间的随机延迟范围（秒）

        Returns:
            搜索结果列表
        """
        results = []
        total = len(queries)

        logger.note(f"> Batch search: {logstr.mesg(total)} queries")

        for i, query in enumerate(queries):
            logger.note(f"> [{i + 1}/{total}] Searching: {logstr.mesg(query)}")
            result = await self.search(query=query, num=num, lang=lang)
            results.append(result)

            if i < total - 1:
                delay = random.uniform(*delay_range)
                if self.verbose:
                    logger.mesg(f"  Waiting {delay:.1f}s ...")
                await asyncio.sleep(delay)

        success_count = sum(1 for r in results if r.results)
        logger.okay(
            f"  ✓ Batch done: {logstr.mesg(success_count)}/{total} successful"
        )

        return results
