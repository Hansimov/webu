"""Google 搜索全流程集成测试。

运行: pytest tests/google_api/test_search.py -xvs -m integration
"""

import asyncio
import pytest

from webu.google_api.proxy_manager import ProxyManager, DEFAULT_PROXIES
from webu.google_api.scraper import GoogleScraper
from webu.google_api.parser import GoogleResultParser


@pytest.mark.integration
class TestGoogleSearchIntegration:
    """端到端集成测试。

    需要：
    - 本地代理端口（11000, 11111, 11119）可用
    - 网络连接
    - Playwright 浏览器已安装
    """

    @pytest.fixture
    async def manager(self):
        m = ProxyManager(verbose=True)
        await m.start()
        yield m
        await m.stop()

    def test_proxy_manager_stats(self):
        """测试代理管理器统计。"""
        manager = ProxyManager(verbose=False)
        stats = manager.stats()
        print(f"\nProxy stats: {stats}")
        assert "total_proxies" in stats
        assert "healthy_proxies" in stats
        assert stats["total_proxies"] == 3

    @pytest.mark.asyncio
    async def test_proxy_health_check(self):
        """测试代理健康检查。"""
        manager = ProxyManager(verbose=True)
        await manager._check_all()
        stats = manager.stats()
        print(f"\nHealth check results:")
        for p in stats["proxies"]:
            print(f"  {p['name']}: healthy={p['healthy']}, latency={p['latency_ms']}ms")
        assert stats["healthy_proxies"] > 0

    @pytest.mark.asyncio
    async def test_search_with_warp_proxy(self, manager):
        """测试通过 warp 代理进行 Google 搜索。"""
        scraper = GoogleScraper(
            proxy_manager=manager,
            headless=True,
            verbose=True,
        )
        await scraper.start()
        try:
            response = await scraper.search(
                query="Python programming language",
                proxy_url="socks5://127.0.0.1:11000",
                retry_count=1,
            )
            print(f"\nWarp search: {len(response.results)} results")
            if response.error:
                print(f"Error: {response.error}")
            if response.has_captcha:
                print("CAPTCHA detected")
            for r in response.results[:5]:
                print(f"  [{r.position}] {r.title}")
                print(f"      {r.url}")
        finally:
            await scraper.stop()

    @pytest.mark.asyncio
    async def test_search_with_auto_proxy(self, manager):
        """测试自动代理选择（ProxyManager）。"""
        scraper = GoogleScraper(
            proxy_manager=manager,
            headless=True,
            verbose=True,
        )
        await scraper.start()
        try:
            response = await scraper.search(
                query="test query",
                retry_count=2,
            )
            print(f"\nAuto proxy search: {len(response.results)} results")
            if response.error:
                print(f"Error: {response.error}")
            if response.has_captcha:
                print("CAPTCHA detected")
        finally:
            await scraper.stop()

    @pytest.mark.asyncio
    async def test_search_direct(self):
        """测试直连搜索（不通过代理）。"""
        scraper = GoogleScraper(headless=True, verbose=True)
        await scraper.start()
        try:
            response = await scraper.search(
                query="test query one two three",
                proxy_url="direct",
            )
            print(f"\nDirect search: {len(response.results)} results")
            if response.error:
                print(f"Error: {response.error}")
            if response.has_captcha:
                print("CAPTCHA detected (expected for direct IP)")
        finally:
            await scraper.stop()

    @pytest.mark.asyncio
    async def test_search_all_proxies(self, manager):
        """测试使用每个代理逐一搜索。"""
        scraper = GoogleScraper(headless=True, verbose=True)
        await scraper.start()
        try:
            for proxy_cfg in DEFAULT_PROXIES:
                url = proxy_cfg["url"]
                print(f"\n> Testing proxy: {url}")
                response = await scraper.search(
                    query="hello world",
                    proxy_url=url,
                    retry_count=0,
                )
                status = "✓" if response.results and not response.has_captcha else "×"
                print(
                    f"  {status} {url}: "
                    f"{len(response.results)} results, "
                    f"captcha={response.has_captcha}"
                )
                await asyncio.sleep(2)
        finally:
            await scraper.stop()
