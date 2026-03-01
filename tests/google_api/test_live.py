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
from webu.google_api.proxy_checker import (
    ProxyChecker,
    check_level1_batch,
    check_level2_batch,
    _build_proxy_url,
)
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


# ═══════════════════════════════════════════════════════════════
# 两级代理检测集成测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestTwoLevelCheckLive:
    """两级代理检测实时测试。"""

    @pytest.mark.asyncio
    async def test_level1_filters_dead_ips(self):
        """Level-1 应该能快速过滤掉不可用的 IP。"""
        store = MongoProxyStore(configs=TEST_CONFIGS, verbose=False)
        collector = ProxyCollector(store=store, verbose=True)
        collector.collect_all()

        all_ips = store.get_all_ips(limit=0)
        socks5 = [ip for ip in all_ips if ip["protocol"] == "socks5"][:30]
        if len(socks5) < 5:
            pytest.skip("Not enough SOCKS5 proxies")

        results = await check_level1_batch(socks5, timeout_s=10, concurrency=30, verbose=True)

        assert len(results) == len(socks5)
        passed = [r for r in results if r["is_valid"]]
        failed = [r for r in results if not r["is_valid"]]

        print(f"\n  Level-1: {len(passed)} passed, {len(failed)} failed out of {len(socks5)}")

        # 验证结果字段
        for r in results:
            assert "ip" in r
            assert "port" in r
            assert "protocol" in r
            assert "proxy_url" in r
            assert "is_valid" in r
            assert "check_level" in r
            assert r["check_level"] == 1

    @pytest.mark.asyncio
    async def test_level1_http_proxies_low_pass_rate(self):
        """HTTP 代理应该有很低的通过率（大部分死亡）。"""
        store = MongoProxyStore(configs=TEST_CONFIGS, verbose=False)
        all_ips = store.get_all_ips(limit=0)
        http_ips = [ip for ip in all_ips if ip["protocol"] == "http"][:20]
        if len(http_ips) < 5:
            pytest.skip("Not enough HTTP proxies")

        results = await check_level1_batch(http_ips, timeout_s=8, concurrency=20, verbose=True)
        passed = [r for r in results if r["is_valid"]]
        print(f"\n  HTTP Level-1: {len(passed)}/{len(http_ips)} passed")

    @pytest.mark.asyncio
    async def test_full_two_level_pipeline(self):
        """完整两级检测流水线测试。"""
        store = MongoProxyStore(configs=TEST_CONFIGS, verbose=True)
        checker = ProxyChecker(
            store=store,
            timeout=20,
            concurrency=3,
            level1_timeout=10,
            level1_concurrency=30,
            verbose=True,
        )

        all_ips = store.get_all_ips(limit=0)
        socks5 = [ip for ip in all_ips if ip["protocol"] == "socks5"][:50]
        if len(socks5) < 5:
            pytest.skip("Not enough SOCKS5 proxies")

        results = await checker.check_batch(socks5, level="all")
        assert len(results) > 0

        stats = store.get_stats()
        print(f"\n  Stats after two-level check: {stats}")


# ═══════════════════════════════════════════════════════════════
# Playwright 代理集成验证
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestPlaywrightProxyIntegration:
    """验证 Playwright 代理集成是否正确。"""

    @pytest.mark.asyncio
    async def test_playwright_socks5_proxy_routes_traffic(self):
        """验证 SOCKS5 代理通过 Playwright 确实路由了流量。"""
        from playwright.async_api import async_playwright

        store = MongoProxyStore(configs=TEST_CONFIGS, verbose=False)
        all_ips = store.get_all_ips(limit=0)
        socks5 = [ip for ip in all_ips if ip["protocol"] == "socks5"]

        # 先运行 Level-1 找一些活的代理
        if len(socks5) < 5:
            pytest.skip("Not enough SOCKS5 proxies")

        results = await check_level1_batch(socks5[:30], timeout_s=10, verbose=False)
        passed = [r for r in results if r["is_valid"]]
        if not passed:
            pytest.skip("No SOCKS5 proxies passed Level-1")

        proxy_url = passed[0]["proxy_url"]
        print(f"\n  Using proxy: {proxy_url}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])

            # Direct IP
            ctx_direct = await browser.new_context(ignore_https_errors=True)
            page_direct = await ctx_direct.new_page()
            await page_direct.goto("https://httpbin.org/ip", timeout=15000)
            direct_ip = await page_direct.inner_text("body")
            await ctx_direct.close()

            # Proxy IP
            ctx_proxy = await browser.new_context(
                proxy={"server": proxy_url},
                ignore_https_errors=True,
            )
            page_proxy = await ctx_proxy.new_page()
            await page_proxy.goto("https://httpbin.org/ip", timeout=15000)
            proxy_ip = await page_proxy.inner_text("body")
            await ctx_proxy.close()

            await browser.close()

        print(f"  Direct IP: {direct_ip.strip()}")
        print(f"  Proxy IP:  {proxy_ip.strip()}")

        # 代理 IP 应该不同于直连 IP
        assert direct_ip.strip() != proxy_ip.strip(), (
            "Proxy IP should differ from direct IP — proxy not working!"
        )

