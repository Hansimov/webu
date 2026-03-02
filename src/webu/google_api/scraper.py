"""Google 搜索抓取器 — 使用 undetected-chromedriver + Playwright CDP 绕过自动化检测。

架构：
1. 使用 undetected-chromedriver (UC) 启动 Chrome — 去除自动化浏览器指纹
2. 通过 Playwright 连接到 UC 启动的 Chrome 实例（CDP 协议）— 享受 Playwright 的高级 API
3. 每次搜索创建新的 BrowserContext，指定代理 IP 和随机化浏览器指纹

这种方案结合了 UC 的反检测能力和 Playwright 的易用性，
有效规避 Google 对自动化浏览器的严格识别。
"""

import asyncio
import random
import time
import subprocess
import socket
import os
import signal

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


def _find_free_port() -> int:
    """找到一个可用的端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _launch_uc_chrome(
    headless: bool = True,
    debug_port: int = None,
    proxy_url: str = None,
) -> tuple[subprocess.Popen, int]:
    """使用 undetected-chromedriver 启动 Chrome 浏览器。

    UC 会自动 patch chromedriver 并启动 Chrome，
    去除 navigator.webdriver、window.chrome 等自动化指纹。

    Returns:
        (process, debug_port) — Chrome 进程和远程调试端口
    """
    import undetected_chromedriver as uc
    import shutil

    if debug_port is None:
        debug_port = _find_free_port()

    # 检测系统 Chrome 版本
    chrome_version_main = None
    try:
        result = subprocess.run(
            ["google-chrome", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        ver_str = result.stdout.strip().split()[-1]  # e.g. "138.0.7204.168"
        chrome_version_main = int(ver_str.split(".")[0])
    except Exception:
        pass

    # 检测系统 chromedriver — 优先使用用户可写的副本
    # UC 需要 patch chromedriver 二进制，系统目录通常没有写权限
    system_chromedriver = None
    user_chromedriver = os.path.expanduser("~/.local/bin/chromedriver")
    if os.path.isfile(user_chromedriver) and os.access(user_chromedriver, os.X_OK):
        system_chromedriver = user_chromedriver
    else:
        found = shutil.which("chromedriver")
        if found and os.access(found, os.W_OK):
            system_chromedriver = found

    options = uc.ChromeOptions()
    options.add_argument(f"--remote-debugging-port={debug_port}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")

    if headless:
        options.add_argument("--headless=new")

    if proxy_url:
        # UC Chrome 命令行代理仅支持 http/socks5 scheme
        options.add_argument(f"--proxy-server={proxy_url}")

    uc_kwargs = {
        "options": options,
        "use_subprocess": True,
    }

    # 固定 Chrome 主版本号 — 防止 UC 下载不匹配的 chromedriver
    if chrome_version_main:
        uc_kwargs["version_main"] = chrome_version_main

    # 使用系统 chromedriver（如果与 Chrome 版本匹配）
    if system_chromedriver:
        uc_kwargs["driver_executable_path"] = system_chromedriver

    # UC 的 Chrome() 会启动 Chrome 并返回 driver
    # 我们只需要 Chrome 进程，后续通过 Playwright CDP 控制
    driver = uc.Chrome(**uc_kwargs)

    # 从 driver capabilities 获取实际的调试端口
    # UC/chromedriver 会自动分配端口，不一定使用我们指定的
    actual_port = debug_port
    try:
        debug_address = driver.capabilities.get(
            "goog:chromeOptions", {}
        ).get("debuggerAddress", "")
        if debug_address and ":" in debug_address:
            actual_port = int(debug_address.split(":")[-1])
    except (ValueError, KeyError):
        pass

    return driver, actual_port


class GoogleScraper:
    """undetected-chromedriver + Playwright CDP 驱动的 Google 搜索抓取器。

    架构：
    - 使用 UC 启动 Chrome（去除自动化指纹）
    - 通过 Playwright CDP 连接浏览器（高级 API）
    - 每次搜索创建新的 BrowserContext（指定代理 + 随机化指纹）
    """

    def __init__(
        self,
        proxy_pool=None,
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
        self._uc_driver = None
        self._debug_port: int = 0
        self._search_count = 0
        self._max_searches_before_restart = 200

    async def start(self):
        """启动浏览器（UC Chrome + Playwright CDP）。"""
        if self._browser:
            return

        logger.note("> Starting undetected Chrome + Playwright CDP ...")

        # Step 1: 用 UC 启动 Chrome
        self._debug_port = _find_free_port()
        try:
            self._uc_driver, self._debug_port = _launch_uc_chrome(
                headless=self.headless,
                debug_port=self._debug_port,
            )
        except Exception as e:
            logger.warn(f"  × UC Chrome failed: {e}, falling back to Playwright")
            await self._start_playwright_fallback()
            return

        # Step 2: 等待 Chrome 的 CDP 端口就绪
        await self._wait_for_cdp_port(self._debug_port)

        # Step 3: 用 Playwright 连接到 Chrome CDP
        self._playwright = await async_playwright().start()
        cdp_url = f"http://127.0.0.1:{self._debug_port}"
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
            self._search_count = 0
            logger.okay(
                f"  ✓ Connected to UC Chrome via CDP (port {self._debug_port})"
            )
        except Exception as e:
            logger.warn(f"  × CDP connection failed: {e}, falling back to Playwright")
            self._cleanup_uc()
            await self._start_playwright_fallback()

    async def _start_playwright_fallback(self):
        """Playwright 回退方案（如果 UC 不可用）。"""
        logger.note("> Starting Playwright browser (fallback) ...")
        if not self._playwright:
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
        logger.okay("  ✓ Playwright browser started (fallback mode)")

    async def _wait_for_cdp_port(self, port: int, timeout: float = 15.0):
        """等待 CDP 端口可连接。"""
        start = time.time()
        while time.time() - start < timeout:
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
                await writer.wait_closed()
                return
            except (ConnectionRefusedError, OSError):
                await asyncio.sleep(0.3)
        raise TimeoutError(f"CDP port {port} not ready after {timeout}s")

    def _cleanup_uc(self):
        """清理 UC Chrome 进程。"""
        if self._uc_driver:
            try:
                self._uc_driver.quit()
            except Exception:
                pass
            self._uc_driver = None

    async def stop(self):
        """关闭浏览器。"""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._cleanup_uc()
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
        """
        await self._ensure_browser()

        for attempt in range(retry_count + 1):
            # 获取代理
            if proxy_url == "direct":
                current_proxy = None
            elif proxy_url:
                current_proxy = proxy_url
            else:
                if self.proxy_pool:
                    proxy_info = self.proxy_pool.get_proxy()
                    if proxy_info:
                        current_proxy = proxy_info["proxy_url"]
                    else:
                        current_proxy = None
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

            # 注入额外的反检测脚本
            await page.add_init_script("""
                // 隐藏 webdriver 属性
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                });
                // 伪造 plugins
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });
                // 伪造 languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en'],
                });
                // 隐藏 chrome 自动化标志
                window.chrome = {
                    runtime: {},
                };
            """)

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
        """批量搜索（顺序执行，带随机延迟）。"""
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
