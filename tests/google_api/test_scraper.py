"""scraper 模块单元测试。

运行: pytest tests/google_api/test_scraper.py -xvs
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from webu.google_api.scraper import GoogleScraper
from webu.google_api.proxy_manager import ProxyManager
from webu.google_api.parser import GoogleSearchResponse, GoogleSearchResult


# ═══════════════════════════════════════════════════════════════
# GoogleScraper 单元测试
# ═══════════════════════════════════════════════════════════════


class TestGoogleScraper:
    """GoogleScraper 单元测试。"""

    def setup_method(self):
        self.manager = MagicMock(spec=ProxyManager)
        self.manager.get_proxy.return_value = "http://127.0.0.1:11111"
        self.scraper = GoogleScraper(
            proxy_manager=self.manager,
            headless=True,
            timeout=10,
            verbose=False,
        )

    def test_init_default_params(self):
        """测试默认参数。"""
        manager = MagicMock(spec=ProxyManager)
        scraper = GoogleScraper(proxy_manager=manager)
        assert scraper.headless is True
        assert scraper.timeout > 0
        assert scraper._search_count == 0
        assert scraper._browser is None

    def test_init_custom_params(self):
        """测试自定义参数。"""
        assert self.scraper.timeout == 10
        assert self.scraper.headless is True

    @pytest.mark.asyncio
    async def test_start_stop(self):
        """测试浏览器启动和停止。"""
        await self.scraper.start()
        assert self.scraper._browser is not None
        assert self.scraper._playwright is not None

        await self.scraper.stop()
        assert self.scraper._browser is None
        assert self.scraper._playwright is None

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        """测试未启动时停止不报错。"""
        await self.scraper.stop()  # 不应抛出异常

    @pytest.mark.asyncio
    async def test_double_start(self):
        """测试重复启动不创建多个浏览器。"""
        await self.scraper.start()
        browser1 = self.scraper._browser

        await self.scraper.start()  # 第二次调用应复用
        browser2 = self.scraper._browser

        assert browser1 is browser2
        await self.scraper.stop()


# ═══════════════════════════════════════════════════════════════
# Parser 集成到 Scraper 的测试
# ═══════════════════════════════════════════════════════════════


class TestScraperParserIntegration:
    """测试 Scraper 使用的 Parser。"""

    def test_parser_is_initialized(self):
        """测试 Scraper 初始化时创建了 Parser。"""
        manager = MagicMock(spec=ProxyManager)
        scraper = GoogleScraper(proxy_manager=manager, verbose=False)
        assert scraper.parser is not None

    def test_search_count_tracking(self):
        """测试搜索计数器初始化。"""
        manager = MagicMock(spec=ProxyManager)
        scraper = GoogleScraper(proxy_manager=manager, verbose=False)
        assert scraper._search_count == 0
        assert scraper._max_searches_before_restart == 200


# ═══════════════════════════════════════════════════════════════
# 集成测试（需要 Playwright 和网络）
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestGoogleScraperIntegration:
    """Scraper 集成测试。

    需要 Playwright 浏览器已安装和网络连接。

    运行: pytest tests/google_api/test_scraper.py -xvs -m integration
    """

    @pytest.mark.asyncio
    async def test_search_direct_no_proxy(self):
        """测试直连搜索（不通过代理）。"""
        scraper = GoogleScraper(headless=True, verbose=True)
        await scraper.start()
        try:
            response = await scraper.search(
                query="what is python",
                proxy_url="direct",
                retry_count=0,
            )
            print(f"\nDirect search: {len(response.results)} results")
            if response.error:
                print(f"Error: {response.error}")
            if response.has_captcha:
                print("CAPTCHA detected")
            # 直连可能会被 CAPTCHA（不断言结果数量）
        finally:
            await scraper.stop()

    @pytest.mark.asyncio
    async def test_browser_restart_after_max_searches(self):
        """测试浏览器在达到最大搜索次数后自动重启。"""
        manager = MagicMock(spec=ProxyManager)
        manager.get_proxy.return_value = None

        scraper = GoogleScraper(proxy_manager=manager, headless=True, verbose=False)
        scraper._max_searches_before_restart = 2  # 设置极小值方便测试

        await scraper.start()
        browser1 = scraper._browser

        # 模拟搜索计数超过限制
        scraper._search_count = 3
        await scraper._ensure_browser()
        browser2 = scraper._browser

        # 应该已经重启了浏览器
        assert browser1 is not browser2

        await scraper.stop()
