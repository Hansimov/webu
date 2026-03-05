"""Google 搜索抓取器 — 使用 Playwright + 反检测策略绕过自动化检测。

架构：
1. 使用 Playwright 启动 Chromium，附加反检测参数（禁用 automation 指纹等）
2. 每次搜索创建独立 BrowserContext，在 context 级别设置代理
3. 注入反检测脚本（隐藏 webdriver、伪造 plugins/languages 等）
4. Cookie 文件持久化，跨搜索共享 CAPTCHA 绕过状态

性能优化：
- Cookie 持久化：已通过的 CAPTCHA 验证自动恢复
- Context 级别代理：切换代理无需重启浏览器
- 内置性能计时：定位各阶段耗时瓶颈
"""

import asyncio
import json
import random
import time

from datetime import datetime, timezone, timedelta
from pathlib import Path
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
from .proxy_manager import ProxyManager
from webu.captcha import CaptchaBypass

# 截图保存目录
SCREENSHOT_DIR = Path("data/google_api_screenshots")
TZ_SHANGHAI = timezone(timedelta(hours=8))

# Cookie 持久化目录
DEFAULT_PROFILE_DIR = Path("data/google_api/chrome_profile")


# ═══════════════════════════════════════════════════════════════
# 性能计时器
# ═══════════════════════════════════════════════════════════════


class PerfTimer:
    """轻量级多阶段性能计时器。

    用法::

        perf = PerfTimer()
        perf.start("stage_a")
        ...  # 做一些事情
        perf.stop()
        perf.start("stage_b")
        ...  # 做另一些事情
        perf.stop()
        print(perf.summary())
    """

    def __init__(self):
        self._stages: list[tuple[str, float]] = []
        self._wall_start = time.time()
        self._cur_name: str | None = None
        self._cur_start: float | None = None

    def start(self, name: str):
        """开始计时一个新阶段（自动结束上一个未结束的阶段）。"""
        if self._cur_name is not None:
            self.stop()
        self._cur_name = name
        self._cur_start = time.time()

    def stop(self):
        """结束当前阶段计时。"""
        if self._cur_name and self._cur_start:
            elapsed = time.time() - self._cur_start
            self._stages.append((self._cur_name, elapsed))
        self._cur_name = None
        self._cur_start = None

    @property
    def total(self) -> float:
        """从创建计时器到现在的总耗时（秒）。"""
        return time.time() - self._wall_start

    @property
    def stages(self) -> list[tuple[str, float]]:
        """所有已完成阶段的 (名称, 耗时秒) 列表。"""
        return list(self._stages)

    def summary(self) -> str:
        """格式化的性能报告。"""
        if self._cur_name:
            self.stop()
        lines = []
        for name, elapsed in self._stages:
            bar = "█" * min(int(elapsed * 5), 40)  # 每 0.2s 一个方块
            lines.append(f"  {name:.<30s} {elapsed:>6.2f}s  {bar}")
        lines.append(f"  {'TOTAL':.<30s} {self.total:>6.2f}s")
        return "\n".join(lines)


def _save_screenshot_and_html(
    page_content: str,
    screenshot_bytes: bytes | None,
    query: str,
    proxy_url: str,
    reason: str = "captcha",
    base_dir: Path | None = None,
):
    """保存截图和 HTML 到本地目录，用于调试分析。"""
    out_dir = base_dir or SCREENSHOT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(TZ_SHANGHAI).strftime("%Y%m%d_%H%M%S")
    safe_query = query[:30].replace(" ", "_").replace("/", "_")
    safe_proxy = (proxy_url or "direct").replace("://", "_").replace(":", "_").replace("/", "")
    base_name = f"{ts}_{reason}_{safe_query}_{safe_proxy}"

    if screenshot_bytes:
        png_path = out_dir / f"{base_name}.png"
        png_path.write_bytes(screenshot_bytes)
        logger.mesg(f"  📸 Screenshot saved: {png_path}")

    html_path = out_dir / f"{base_name}.html"
    html_path.write_text(page_content, encoding="utf-8")
    logger.mesg(f"  📄 HTML saved: {html_path}")


class GoogleScraper:
    """Playwright 驱动的 Google 搜索抓取器。

    架构：
    - 使用 Playwright 启动 Chromium，附加反检测参数
    - 每次搜索创建新 BrowserContext 并设置 **context 级别代理**
    - 注入反检测脚本（隐藏 webdriver / 伪造 plugins 等）
    - 通过 ProxyManager 管理代理切换 / 负载均衡 / 故障转移

    设计优势：
    - 代理在 context 级别设置，**无需重启浏览器即可切换代理**
    - Cookie 通过文件持久化，CAPTCHA 绕过状态在 context 间共享
    - 无外部依赖（不需要 chromedriver / undetected-chromedriver）
    """

    def __init__(
        self,
        proxy_manager: ProxyManager = None,
        headless: bool = True,
        timeout: int = SEARCH_TIMEOUT,
        verbose: bool = True,
        proxy_url: str = None,
        profile_dir: str | Path = None,
    ):
        self.proxy_manager = proxy_manager
        self.headless = headless
        self.timeout = timeout
        self.verbose = verbose
        self.parser = GoogleResultParser(verbose=verbose)

        # 指定的固定代理（CLI --proxy 传入时使用）
        self._fixed_proxy = proxy_url
        # 持久化目录（Cookie / Chrome Profile）
        self._profile_dir = Path(profile_dir) if profile_dir else DEFAULT_PROFILE_DIR
        # Cookie 持久化文件
        self._cookie_file = self._profile_dir / "google_cookies.json"

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._search_count = 0
        self._max_searches_before_restart = 200

        # 性能计时器 — start() 时重建
        self.perf = PerfTimer()

    async def start(self):
        """启动 Playwright 浏览器。

        浏览器不设置代理 — 代理在每次搜索的 context 级别设置。
        这样可以在不重启浏览器的情况下切换代理。
        """
        if self._browser:
            return

        self.perf = PerfTimer()
        logger.note("> Starting Playwright browser ...")
        if self._fixed_proxy:
            logger.mesg(f"  Fixed proxy: {logstr.file(self._fixed_proxy)}")
        elif self.proxy_manager:
            logger.mesg(f"  Proxy: via ProxyManager (context-level)")
        else:
            logger.mesg(f"  Proxy: none (direct)")

        self.perf.start("browser_launch")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-features=DnsOverHttps",
                "--disable-background-networking",
            ],
        )
        self._search_count = 0
        self.perf.stop()
        logger.okay("  ✓ Playwright browser started")

        if self.verbose:
            logger.mesg(f"\n> Startup timing:\n{self.perf.summary()}\n")

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

        代理选择优先级：
        1. proxy_url 参数（CLI --proxy 指定）
        2. self._fixed_proxy（构造时设置）
        3. ProxyManager 自动选取
        4. 无代理（direct）

        重试策略：
        - 失败时自动从 ProxyManager 获取下一个代理
        - 不同代理通过 context-level 切换，无需重启浏览器

        Args:
            query: 搜索关键词
            num: 期望的结果数量
            lang: 搜索语言
            proxy_url: 指定代理 URL（覆盖 fixed_proxy 和 ProxyManager）
            retry_count: 重试次数
        """
        await self._ensure_browser()

        # 确定首次使用的代理
        requested_proxy = proxy_url or self._fixed_proxy

        for attempt in range(retry_count + 1):
            # 获取当前代理
            if requested_proxy == "direct":
                current_proxy = None
            elif requested_proxy:
                current_proxy = requested_proxy
            elif self.proxy_manager:
                current_proxy = self.proxy_manager.get_proxy()
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
                # 成功 — 报告代理成功
                if current_proxy and self.proxy_manager:
                    self.proxy_manager.report_success(current_proxy)
                return result

            if result.has_captcha:
                # CAPTCHA — 报告代理失败，切换代理重试
                if current_proxy and self.proxy_manager:
                    self.proxy_manager.report_failure(current_proxy)
                logger.warn(
                    f"  × CAPTCHA detected (attempt {attempt + 1}), "
                    f"switching proxy ..."
                )
                # 清除 requested_proxy 以便下次从 ProxyManager 获取新代理
                requested_proxy = None
                continue

            if not result.results and attempt < retry_count:
                # 无结果（超时等） — 报告代理失败，切换代理重试
                if current_proxy and self.proxy_manager:
                    self.proxy_manager.report_failure(current_proxy)
                logger.warn(
                    f"  × No results (attempt {attempt + 1}), retrying ..."
                )
                requested_proxy = None
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
        """执行单次搜索（内部方法）。

        架构策略：
        - 每次搜索创建新 BrowserContext，设置 context 级别代理
        - 反检测脚本在每个 page 中注入（隐藏 webdriver 等）
        - Cookie 通过文件持久化，搜索前自动恢复
        """
        search_perf = PerfTimer()
        context = None
        page = None
        response = GoogleSearchResponse(query=query)

        try:
            search_perf.start("context_setup")
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

            # 恢复已持久化的 Cookie（CAPTCHA 绕过状态等）
            await self._load_cookies(context)

            page = await context.new_page()
            if self.verbose:
                proxy_display = proxy_url or "direct"
                logger.mesg(f"  ◆ Context created (proxy: {proxy_display})")
            search_perf.stop()

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

            # 添加随机延迟（模拟人类行为）— 首次搜索稍长，后续减少
            if self._search_count == 0:
                await asyncio.sleep(random.uniform(0.5, 1.5))
            else:
                await asyncio.sleep(random.uniform(0.2, 0.8))

            # 导航到搜索页
            search_perf.start("page_navigation")
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
            search_perf.stop()

            elapsed_ms = int((time.time() - start_time) * 1000)

            # 获取页面 HTML
            search_perf.start("get_html")
            html = await page.content()
            response.raw_html_length = len(html)
            search_perf.stop()

            if self.verbose:
                logger.mesg(
                    f"  Page loaded: {logstr.mesg(f'{len(html)} bytes')} "
                    f"in {logstr.mesg(f'{elapsed_ms}ms')}"
                )

            # 解析搜索结果
            search_perf.start("parse_results")
            response = self.parser.parse(html, query=query)
            search_perf.stop()

            # 如果检测到 CAPTCHA，先尝试自动绕过
            if response.has_captcha:
                search_perf.start("captcha_bypass")
                # 创建本次运行的截图子目录
                run_ts = datetime.now(TZ_SHANGHAI).strftime("%Y%m%d_%H%M%S")
                run_dir = SCREENSHOT_DIR / run_ts
                run_dir.mkdir(parents=True, exist_ok=True)

                # 保存截图用于分析
                try:
                    screenshot_bytes = await page.screenshot(full_page=True)
                except Exception:
                    screenshot_bytes = None
                _save_screenshot_and_html(
                    page_content=html,
                    screenshot_bytes=screenshot_bytes,
                    query=query,
                    proxy_url=proxy_url or "direct",
                    reason="captcha",
                    base_dir=run_dir,
                )

                # 尝试自动绕过 CAPTCHA
                bypasser = CaptchaBypass(
                    max_wait_after_click=15.0,
                    save_screenshots=True,
                    verbose=self.verbose,
                    run_dir=run_dir,
                )
                bypass_ok = await bypasser.attempt_bypass(
                    page, proxy_url=proxy_url or "direct"
                )

                if bypass_ok:
                    # 绕过成功 — 重新获取页面内容并解析
                    html = await page.content()
                    response = self.parser.parse(html, query=query)
                    response.raw_html_length = len(html)
                    if self.verbose:
                        if response.results:
                            logger.okay(
                                f"  ✓ CAPTCHA bypassed! "
                                f"Got {len(response.results)} results"
                            )
                        else:
                            logger.warn(
                                "  ⚠ CAPTCHA bypassed but no results parsed"
                            )
                    # 保存绕过后的页面截图
                    try:
                        shot = await page.screenshot(full_page=True)
                        _save_screenshot_and_html(
                            page_content=html,
                            screenshot_bytes=shot,
                            query=query,
                            proxy_url=proxy_url or "direct",
                            reason="captcha_bypassed",
                            base_dir=run_dir,
                        )
                    except Exception:
                        pass
                search_perf.stop()

            self._search_count += 1

        except Exception as e:
            error_msg = str(e)[:300]
            response.error = error_msg
            if self.verbose:
                logger.warn(f"  × Search error: {error_msg}")
            # 对错误情况也保存截图
            if context:
                try:
                    pages = context.pages
                    if pages:
                        screenshot_bytes = await pages[0].screenshot(full_page=True)
                        html_content = await pages[0].content()
                        _save_screenshot_and_html(
                            page_content=html_content,
                            screenshot_bytes=screenshot_bytes,
                            query=query,
                            proxy_url=proxy_url or "direct",
                            reason="error",
                        )
                except Exception:
                    pass
        finally:
            # 保存 Cookie（用于 CAPTCHA bypass 状态持久化）
            if context:
                await self._save_cookies(context)
            # 关闭 page 和 context（每次搜索使用新 context）
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            if context:
                try:
                    await context.close()
                except Exception:
                    pass

        if self.verbose:
            logger.mesg(f"  Search timing:\n{search_perf.summary()}")

        return response

    # ── Cookie 持久化 ─────────────────────────────────────────

    async def _save_cookies(self, context):
        """保存 context 的 Cookie 到文件（持久化 CAPTCHA bypass 状态）。"""
        try:
            cookies = await context.cookies()
            # 只保存 Google 域名的 Cookie
            google_cookies = [
                c for c in cookies
                if c.get("domain", "").endswith(".google.com")
                or c.get("domain", "").endswith("google.com")
            ]
            if google_cookies:
                self._cookie_file.parent.mkdir(parents=True, exist_ok=True)
                self._cookie_file.write_text(
                    json.dumps(google_cookies, indent=2, ensure_ascii=False)
                )
        except Exception:
            pass  # Cookie 保存失败不影响搜索

    async def _load_cookies(self, context):
        """从文件恢复 Cookie 到 context（恢复 CAPTCHA bypass 状态）。"""
        try:
            if self._cookie_file.exists():
                cookies = json.loads(self._cookie_file.read_text())
                if cookies:
                    await context.add_cookies(cookies)
        except Exception:
            pass  # Cookie 恢复失败不影响搜索

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
