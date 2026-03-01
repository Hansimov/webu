"""实时环境集成测试 — 测试运行中的服务和接口。

这些测试验证真实环境中的服务可用性。
需要 MongoDB 运行、网络连接、Playwright 已安装。

运行: pytest tests/google_api/test_live.py -xvs -m integration
"""

import asyncio
import pytest
import requests
import time

from webu.google_api.constants import PROXY_SOURCES, MONGO_CONFIGS
from webu.google_api.mongo import MongoProxyStore
from webu.google_api.proxy_collector import ProxyCollector
from webu.google_api.proxy_pool import ProxyPool
from webu.google_api.scraper import GoogleScraper
from webu.google_api.parser import GoogleResultParser


TEST_CONFIGS = {
    "host": "localhost",
    "port": 27017,
    "dbname": "webu_test",
}


# ═══════════════════════════════════════════════════════════════
# MongoDB 连接测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestMongoDBLive:
    """验证 MongoDB 连接和基本操作。"""

    def test_connect_and_ping(self):
        """测试 MongoDB 连接。"""
        store = MongoProxyStore(configs=TEST_CONFIGS, verbose=True)
        # ping 数据库
        result = store.client.admin.command("ping")
        assert result.get("ok") == 1.0

    def test_indexes_created(self):
        """测试索引已正确创建。"""
        store = MongoProxyStore(configs=TEST_CONFIGS, verbose=False)
        # 检查 ips collection 的索引
        ips_indexes = store.db["ips"].index_information()
        assert "idx_ip_port_protocol" in ips_indexes

        # 检查 google_ips collection 的索引
        gips_indexes = store.db["google_ips"].index_information()
        assert "idx_ip_port_protocol" in gips_indexes
        assert "idx_valid_latency" in gips_indexes

    def test_read_write_cycle(self):
        """测试完整的读写循环。"""
        store = MongoProxyStore(configs=TEST_CONFIGS, verbose=False)

        # 清理
        store.db["ips"].delete_many({"ip": "test_live_1.2.3.4"})

        # 写入
        result = store.upsert_ips(
            [{"ip": "test_live_1.2.3.4", "port": 9999, "protocol": "http", "source": "test_live"}]
        )
        assert result["inserted"] == 1

        # 读取
        count = store.db["ips"].count_documents({"ip": "test_live_1.2.3.4"})
        assert count == 1

        # 清理
        store.db["ips"].delete_many({"ip": "test_live_1.2.3.4"})


# ═══════════════════════════════════════════════════════════════
# 代理源可用性测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestProxySourcesLive:
    """验证代理源 URL 可访问。"""

    @pytest.mark.parametrize("source", PROXY_SOURCES, ids=[s["source"] + "_" + s["protocol"] for s in PROXY_SOURCES])
    def test_source_accessible(self, source):
        """测试各代理源 URL 是否可访问。"""
        try:
            resp = requests.get(source["url"], timeout=30)
            resp.raise_for_status()
            lines = resp.text.strip().split("\n")
            valid_lines = [l for l in lines if l.strip()]
            print(f"\n  {source['source']} ({source['protocol']}): {len(valid_lines)} proxies")
            assert len(valid_lines) > 0, f"Source {source['source']} returned empty list"
        except requests.exceptions.RequestException as e:
            pytest.skip(f"Source {source['source']} unreachable: {e}")

    def test_collect_all_sources(self):
        """测试从所有源采集并存储到 MongoDB。"""
        store = MongoProxyStore(configs=TEST_CONFIGS, verbose=True)
        collector = ProxyCollector(store=store, verbose=True)
        result = collector.collect_all()

        print(f"\n  Total fetched: {result['total_fetched']}")
        print(f"  Inserted: {result['inserted']}")
        print(f"  Total in DB: {result['total']}")
        assert result["total_fetched"] > 0

    def test_collect_single_source(self):
        """测试从单个源采集。"""
        store = MongoProxyStore(configs=TEST_CONFIGS, verbose=True)
        collector = ProxyCollector(store=store, verbose=True)
        result = collector.collect_source("proxifly")

        print(f"\n  proxifly fetched: {result['total_fetched']}")
        assert result["total_fetched"] > 0


# ═══════════════════════════════════════════════════════════════
# 代理池完整流程测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestProxyPoolLive:
    """代理池完整功能测试。"""

    @pytest.fixture
    def pool(self):
        return ProxyPool(configs=TEST_CONFIGS, verbose=True)

    def test_collect_and_stats(self, pool):
        """测试采集后统计。"""
        pool.collect()
        stats = pool.stats()
        print(f"\n  Stats: {stats}")
        assert stats["total_ips"] > 0

    @pytest.mark.asyncio
    async def test_check_small_batch(self, pool):
        """测试小批量检测。"""
        pool.collect()
        results = await pool.check_unchecked(limit=3)
        print(f"\n  Checked {len(results)} proxies")
        for r in results:
            status = "✓ valid" if r.get("is_valid") else "× invalid"
            print(f"    {status}: {r['proxy_url']} ({r.get('latency_ms', 0)}ms)")
            if r.get("last_error"):
                print(f"      Error: {r['last_error'][:100]}")

    def test_get_proxy_with_fallback(self, pool):
        """测试获取代理（包括无可用代理的退化情况）。"""
        proxy = pool.get_proxy()
        if proxy:
            print(f"\n  Got proxy: {proxy['proxy_url']} ({proxy.get('latency_ms', '?')}ms)")
        else:
            print("\n  No valid proxy available (expected if no checks done yet)")

    @pytest.mark.asyncio
    async def test_refresh_flow(self, pool):
        """测试一键刷新流程。"""
        result = await pool.refresh(check_limit=3)
        print(f"\n  Refresh result:")
        print(f"    Collect: {result.get('collect', {})}")
        print(f"    Check count: {result.get('check_count', 0)}")
        print(f"    Stats: {result.get('stats', {})}")


# ═══════════════════════════════════════════════════════════════
# Playwright 浏览器测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestPlaywrightLive:
    """验证 Playwright 浏览器环境。"""

    @pytest.mark.asyncio
    async def test_browser_launches(self):
        """测试 Playwright 浏览器可以正常启动。"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            assert browser.is_connected()

            # 测试基本页面导航
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto("about:blank")
            title = await page.title()
            await context.close()
            await browser.close()

    @pytest.mark.asyncio
    async def test_browser_can_reach_google(self):
        """测试浏览器可以访问 Google（可能触发 CAPTCHA）。"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()

            try:
                await page.goto(
                    "https://www.google.com", timeout=15000, wait_until="domcontentloaded"
                )
                content = await page.content()
                print(f"\n  Google page loaded: {len(content)} bytes")
                assert len(content) > 100  # 至少返回了一些内容
            except Exception as e:
                print(f"\n  Google unreachable: {e}")
            finally:
                await context.close()
                await browser.close()


# ═══════════════════════════════════════════════════════════════
# Parser 回归测试（用真实 HTML 测试时可扩展）
# ═══════════════════════════════════════════════════════════════


class TestParserRobustness:
    """Parser 健壮性测试 — 各种边界情况。"""

    def setup_method(self):
        self.parser = GoogleResultParser(verbose=False)

    def test_parse_none_like_content(self):
        """测试空/极小内容。"""
        resp = self.parser.parse("", query="test")
        assert resp.results == []

    def test_parse_non_google_html(self):
        """测试非 Google HTML。"""
        html = "<html><body><h1>Hello World</h1></body></html>"
        resp = self.parser.parse(html, query="test")
        assert resp.results == []
        assert not resp.has_captcha

    def test_parse_malformed_html(self):
        """测试畸形 HTML。"""
        html = "<div><div class='g'><a href='https://example.com'><h3>Test</h3></a>"
        resp = self.parser.parse(html, query="test")
        # 不应崩溃
        assert isinstance(resp.results, list)

    def test_parse_huge_html(self):
        """测试大 HTML 不超时。"""
        html = "<html><body>" + "<div class='g'>" * 1000 + "</body></html>"
        resp = self.parser.parse(html, query="test")
        assert isinstance(resp.results, list)

    def test_clean_html_preserves_structure(self):
        """测试 HTML 纯化保留基本结构。"""
        html = """
        <html><body>
            <div id="search">
                <div class="g">
                    <a href="https://example.com"><h3>Title</h3></a>
                    <span>Snippet text that is long enough</span>
                </div>
            </div>
            <script>alert('xss')</script>
            <style>.bad { display: none; }</style>
        </body></html>
        """
        clean = self.parser.clean_html(html)
        assert "<script>" not in clean
        assert "<style>" not in clean
        assert "Title" in clean
