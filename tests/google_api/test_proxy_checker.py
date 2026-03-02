"""两级代理检测模块测试。

单元测试（无需网络/数据库）:
  - _build_proxy_url
  - LEVEL1_ENDPOINTS 配置
  - check result 数据结构

集成测试（需要 MongoDB + 网络）:
  - Level-1 aiohttp 快速检测
  - Level-2 Playwright 搜索检测
  - 两级联合检测流程

运行: pytest tests/google_api/test_proxy_checker.py -xvs
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from webu.proxy_api.checker import (
    _build_proxy_url,
    _random_ua,
    _random_viewport,
    _random_locale,
    LEVEL1_ENDPOINTS,
    check_level1_batch,
)
from webu.google_api.checker import (
    check_level2_batch,
    ProxyChecker,
)


# ═══════════════════════════════════════════════════════════════
# 单元测试
# ═══════════════════════════════════════════════════════════════


class TestBuildProxyUrl:
    """代理 URL 构建测试。"""

    def test_http(self):
        assert _build_proxy_url("1.2.3.4", 8080, "http") == "http://1.2.3.4:8080"

    def test_https(self):
        assert _build_proxy_url("1.2.3.4", 443, "https") == "http://1.2.3.4:443"

    def test_socks5(self):
        assert _build_proxy_url("1.2.3.4", 1080, "socks5") == "socks5://1.2.3.4:1080"

    def test_socks4(self):
        assert _build_proxy_url("1.2.3.4", 1080, "socks4") == "socks4://1.2.3.4:1080"

    def test_unknown_defaults_to_http(self):
        assert _build_proxy_url("1.2.3.4", 8080, "unknown") == "http://1.2.3.4:8080"


class TestRandomHelpers:
    """随机辅助函数测试。"""

    def test_random_ua_returns_string(self):
        ua = _random_ua()
        assert isinstance(ua, str)
        assert "Mozilla" in ua

    def test_random_viewport_returns_dict(self):
        vp = _random_viewport()
        assert "width" in vp
        assert "height" in vp

    def test_random_locale_returns_string(self):
        locale = _random_locale()
        assert isinstance(locale, str)
        assert "-" in locale  # e.g. "en-US"


class TestLevel1Endpoints:
    """Level-1 端点配置测试。"""

    def test_endpoints_exist(self):
        assert len(LEVEL1_ENDPOINTS) >= 1

    def test_generate_204_endpoint(self):
        ep = LEVEL1_ENDPOINTS[0]
        assert ep["name"] == "gstatic_204"
        assert ep["expect_status"] == 204
        assert "gstatic" in ep["url"]

    def test_robots_txt_endpoint(self):
        # robots.txt is now at index 3 after reordering
        ep = next(e for e in LEVEL1_ENDPOINTS if e["name"] == "robots.txt")
        assert ep["expect_status"] == 200
        assert "robots.txt" in ep["url"]


class TestLevel1BatchEmpty:
    """Level-1 批量检测 — 空输入。"""

    @pytest.mark.asyncio
    async def test_empty_list(self):
        results = await check_level1_batch([], verbose=False)
        assert results == []


class TestLevel2BatchEmpty:
    """Level-2 批量检测 — 空输入。"""

    @pytest.mark.asyncio
    async def test_empty_list(self):
        results = await check_level2_batch([], verbose=False)
        assert results == []


class TestProxyCheckerInit:
    """ProxyChecker 初始化测试。"""

    def test_init_with_mock_store(self):
        store = MagicMock()
        checker = ProxyChecker(store=store, verbose=False)
        assert checker.store is store
        assert checker.timeout > 0
        assert checker.concurrency > 0
        assert checker.level1_timeout > 0
        assert checker.level1_concurrency > 0


class TestProxyCheckerBatchLevels:
    """ProxyChecker.check_batch level 参数测试。"""

    @pytest.mark.asyncio
    async def test_empty_batch(self):
        store = MagicMock()
        checker = ProxyChecker(store=store, verbose=False)
        results = await checker.check_batch([], level="all")
        assert results == []


# ═══════════════════════════════════════════════════════════════
# 集成测试 — 需要网络
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestLevel1Integration:
    """Level-1 实际网络检测（需要可达 Google 的网络环境）。"""

    @pytest.mark.asyncio
    async def test_level1_with_fake_proxy(self):
        """使用一个假代理测试，应该返回失败。"""
        fake_ips = [
            {"ip": "127.0.0.1", "port": 19999, "protocol": "http", "source": "test"},
        ]
        results = await check_level1_batch(fake_ips, timeout_s=5, verbose=True)
        assert len(results) == 1
        assert not results[0]["is_valid"]
        assert results[0]["check_level"] == 1

    @pytest.mark.asyncio
    async def test_level1_result_structure(self):
        """验证 Level-1 结果字段结构。"""
        fake_ips = [
            {"ip": "192.0.2.1", "port": 8080, "protocol": "http", "source": "test"},
        ]
        results = await check_level1_batch(fake_ips, timeout_s=3, verbose=False)
        r = results[0]
        assert "ip" in r
        assert "port" in r
        assert "protocol" in r
        assert "proxy_url" in r
        assert "is_valid" in r
        assert "latency_ms" in r
        assert "last_error" in r
        assert "check_level" in r
        assert r["check_level"] == 1


@pytest.mark.integration
class TestLevel1WithRealProxies:
    """Level-1 使用真实代理测试（需要 MongoDB 中有数据）。"""

    @pytest.mark.asyncio
    async def test_level1_socks5_sample(self):
        """从 MongoDB 取 SOCKS5 代理样本做 Level-1 测试。"""
        from webu.proxy_api.mongo import MongoProxyStore
        store = MongoProxyStore(verbose=False)
        all_ips = store.get_all_ips(limit=0)
        socks5 = [ip for ip in all_ips if ip["protocol"] == "socks5"]
        if len(socks5) < 10:
            pytest.skip("Not enough SOCKS5 proxies in database")

        sample = socks5[:20]
        results = await check_level1_batch(sample, timeout_s=10, concurrency=20, verbose=True)

        assert len(results) == len(sample)
        passed = [r for r in results if r["is_valid"]]
        # 期待至少有一些通过（免费 SOCKS5 代理的通过率约 10-20%）
        print(f"Level-1 pass rate: {len(passed)}/{len(results)}")
        # 不做比率断言，因为免费代理质量波动大


@pytest.mark.integration
class TestTwoLevelPipeline:
    """两级联合检测集成测试。"""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_mock_store(self):
        """使用 mock store 测试完整流水线逻辑。"""
        store = MagicMock()
        store.upsert_check_results = MagicMock()
        store.get_unchecked_ips = MagicMock(return_value=[
            {"ip": "127.0.0.1", "port": 19999, "protocol": "http", "source": "test"},
        ])

        checker = ProxyChecker(
            store=store,
            timeout=5,
            concurrency=1,
            level1_timeout=3,
            level1_concurrency=1,
            verbose=True,
        )

        results = await checker.check_unchecked(limit=1, level="1")
        assert len(results) == 1
        assert not results[0]["is_valid"]
        # store 应该被调用来保存结果
        store.upsert_check_results.assert_called()
