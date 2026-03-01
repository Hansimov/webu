"""Google 搜索全流程集成测试。

运行: pytest tests/google-api/test_search.py -xvs -m integration
"""

import asyncio
import pytest

from webu.google_api.proxy_pool import ProxyPool
from webu.google_api.scraper import GoogleScraper
from webu.google_api.parser import GoogleResultParser


@pytest.mark.integration
class TestGoogleSearchIntegration:
    """端到端集成测试。

    需要：
    - MongoDB 在 localhost:27017 运行
    - 网络连接
    - Playwright 浏览器已安装
    """

    TEST_CONFIGS = {
        "host": "localhost",
        "port": 27017,
        "dbname": "webu_test",
    }

    @pytest.fixture
    def pool(self):
        return ProxyPool(configs=self.TEST_CONFIGS, verbose=True)

    def test_collect_proxies(self, pool):
        """测试采集代理 IP。"""
        result = pool.collect()
        print(f"\nCollect result: {result}")
        assert result["total_fetched"] > 0
        assert result["total"] > 0

    def test_pool_stats(self, pool):
        """测试代理池统计。"""
        stats = pool.stats()
        print(f"\nPool stats: {stats}")
        assert "total_ips" in stats
        assert "total_valid" in stats

    @pytest.mark.asyncio
    async def test_check_proxies(self, pool):
        """测试检测代理可用性（仅检测少量）。"""
        # 先采集
        pool.collect()

        # 检测少量（避免测试太慢）
        results = await pool.check_unchecked(limit=5)
        print(f"\nCheck results: {len(results)} checked")
        for r in results:
            status = "✓" if r.get("is_valid") else "×"
            print(f"  {status} {r['proxy_url']} ({r.get('latency_ms', 0)}ms)")

    @pytest.mark.asyncio
    async def test_full_search_flow(self, pool):
        """测试完整搜索流程：采集 → 检测 → 搜索。"""
        # 1. 采集
        collect_result = pool.collect()
        print(f"\n1. Collected: {collect_result['total_fetched']} proxies")

        # 2. 检测少量
        check_results = await pool.check_unchecked(limit=10)
        valid_count = sum(1 for r in check_results if r.get("is_valid"))
        print(f"2. Checked: {len(check_results)}, valid: {valid_count}")

        if valid_count == 0:
            pytest.skip("No valid proxies found, skipping search test")

        # 3. 搜索
        scraper = GoogleScraper(proxy_pool=pool, headless=True)
        await scraper.start()
        try:
            response = await scraper.search(query="Python programming language")
            print(f"3. Search results: {len(response.results)}")
            for r in response.results[:5]:
                print(f"   [{r.position}] {r.title}")
                print(f"       {r.url}")
            assert len(response.results) > 0
        finally:
            await scraper.stop()

    @pytest.mark.asyncio
    async def test_search_direct(self):
        """测试直连搜索（不通过代理）。"""
        pool = ProxyPool(configs=self.TEST_CONFIGS, verbose=True)
        scraper = GoogleScraper(proxy_pool=pool, headless=True)
        await scraper.start()
        try:
            # 直接搜索不使用代理
            response = await scraper.search(
                query="test query one two three",
                proxy_url="direct",  # 不使用代理
            )
            print(f"\nDirect search: {len(response.results)} results")
            if response.error:
                print(f"Error: {response.error}")
            if response.has_captcha:
                print("CAPTCHA detected (expected for direct IP)")
        finally:
            await scraper.stop()
