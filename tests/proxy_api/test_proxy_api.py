"""proxy_api 模块基础测试。

验证代理池基础设施的核心功能：
- constants 配置完整性
- MongoProxyStore CRUD 操作
- ProxyCollector 解析逻辑
- checker L1 检测
- ProxyPool 编排

运行: pytest tests/proxy_api/test_proxy_api.py -xvs
"""

import pytest
from unittest.mock import MagicMock, patch


# ═══════════════════════════════════════════════════════════════
# 导入测试
# ═══════════════════════════════════════════════════════════════


class TestImports:
    """验证 proxy_api 模块导入正常。"""

    def test_import_constants(self):
        from webu.proxy_api.constants import (
            MONGO_CONFIGS,
            PROXY_SOURCES,
            MongoConfigsType,
            ProxySourceType,
            ABANDONED_FAIL_THRESHOLD,
            FETCH_PROXY,
            USER_AGENTS,
            VIEWPORT_SIZES,
            LOCALES,
        )
        assert MONGO_CONFIGS["dbname"] == "webu"
        assert len(PROXY_SOURCES) > 0
        assert len(USER_AGENTS) > 0
        assert len(VIEWPORT_SIZES) > 0
        assert len(LOCALES) > 0

    def test_import_mongo(self):
        from webu.proxy_api.mongo import MongoProxyStore, TZ_SHANGHAI, _now_shanghai
        assert TZ_SHANGHAI is not None
        ts = _now_shanghai()
        assert len(ts) == 19  # YYYY-MM-DD HH:MM:SS

    def test_import_collector(self):
        from webu.proxy_api.collector import ProxyCollector
        assert ProxyCollector is not None

    def test_import_checker(self):
        from webu.proxy_api.checker import (
            build_proxy_url,
            _build_proxy_url,
            _random_ua,
            _random_viewport,
            _random_locale,
            LEVEL1_ENDPOINTS,
            check_level1_batch,
        )
        assert len(LEVEL1_ENDPOINTS) > 0
        assert build_proxy_url("1.2.3.4", 8080, "http") == "http://1.2.3.4:8080"

    def test_import_pool(self):
        from webu.proxy_api.pool import ProxyPool
        assert ProxyPool is not None

    def test_import_package(self):
        from webu.proxy_api import (
            MongoProxyStore,
            ProxyCollector,
            check_level1_batch,
            build_proxy_url,
            ProxyPool,
        )
        assert all([
            MongoProxyStore, ProxyCollector, check_level1_batch,
            build_proxy_url, ProxyPool,
        ])


# ═══════════════════════════════════════════════════════════════
# Constants 测试
# ═══════════════════════════════════════════════════════════════


class TestConstants:
    """验证 proxy_api 常量配置。"""

    def test_mongo_configs(self):
        from webu.proxy_api.constants import MONGO_CONFIGS
        assert "host" in MONGO_CONFIGS
        assert "port" in MONGO_CONFIGS
        assert "dbname" in MONGO_CONFIGS

    def test_proxy_sources_structure(self):
        from webu.proxy_api.constants import PROXY_SOURCES
        for src in PROXY_SOURCES:
            assert "url" in src
            assert "protocol" in src
            assert "source" in src
            assert src["protocol"] in ("http", "https", "socks4", "socks5")

    def test_abandoned_thresholds(self):
        from webu.proxy_api.constants import (
            ABANDONED_FAIL_THRESHOLD,
            ABANDONED_STALE_HOURS,
            ABANDONED_COOLDOWN_HOURS,
        )
        assert ABANDONED_FAIL_THRESHOLD > 0
        assert ABANDONED_STALE_HOURS > 0
        assert ABANDONED_COOLDOWN_HOURS >= ABANDONED_STALE_HOURS


# ═══════════════════════════════════════════════════════════════
# Checker 单元测试
# ═══════════════════════════════════════════════════════════════


class TestChecker:
    """proxy_api checker 单元测试。"""

    def test_build_proxy_url_http(self):
        from webu.proxy_api.checker import build_proxy_url
        assert build_proxy_url("1.2.3.4", 8080, "http") == "http://1.2.3.4:8080"

    def test_build_proxy_url_https(self):
        from webu.proxy_api.checker import build_proxy_url
        assert build_proxy_url("1.2.3.4", 8080, "https") == "http://1.2.3.4:8080"

    def test_build_proxy_url_socks5(self):
        from webu.proxy_api.checker import build_proxy_url
        assert build_proxy_url("1.2.3.4", 1080, "socks5") == "socks5://1.2.3.4:1080"

    def test_random_ua(self):
        from webu.proxy_api.checker import _random_ua
        ua = _random_ua()
        assert isinstance(ua, str)
        assert "Mozilla" in ua

    def test_random_viewport(self):
        from webu.proxy_api.checker import _random_viewport
        vp = _random_viewport()
        assert "width" in vp
        assert "height" in vp

    def test_random_locale(self):
        from webu.proxy_api.checker import _random_locale
        loc = _random_locale()
        assert isinstance(loc, str)
        assert "-" in loc  # e.g., "en-US"

    def test_level1_endpoints(self):
        from webu.proxy_api.checker import LEVEL1_ENDPOINTS
        for ep in LEVEL1_ENDPOINTS:
            assert "url" in ep
            assert "name" in ep
            assert ep["url"].startswith("http")

    async def test_level1_empty_list(self):
        from webu.proxy_api.checker import check_level1_batch
        results = await check_level1_batch([])
        assert results == []


# ═══════════════════════════════════════════════════════════════
# MongoProxyStore 集成测试（需要 MongoDB）
# ═══════════════════════════════════════════════════════════════


class TestMongoIntegration:
    """需要运行的 MongoDB 进行测试。"""

    @pytest.mark.integration
    def test_store_init(self):
        from webu.proxy_api.mongo import MongoProxyStore
        store = MongoProxyStore(verbose=False)
        assert store is not None

    @pytest.mark.integration
    def test_store_stats(self):
        from webu.proxy_api.mongo import MongoProxyStore
        store = MongoProxyStore(verbose=False)
        stats = store.get_stats()
        assert "total_ips" in stats


# ═══════════════════════════════════════════════════════════════
# ProxyPool 集成测试（需要 MongoDB）
# ═══════════════════════════════════════════════════════════════


class TestPoolIntegration:
    """需要运行的 MongoDB 进行测试。"""

    @pytest.mark.integration
    def test_pool_init(self):
        from webu.proxy_api.pool import ProxyPool
        pool = ProxyPool(verbose=False)
        assert pool is not None
        assert pool.store is not None
        assert pool.collector is not None

    @pytest.mark.integration
    def test_pool_stats(self):
        from webu.proxy_api.pool import ProxyPool
        pool = ProxyPool(verbose=False)
        stats = pool.stats()
        assert isinstance(stats, dict)
        assert "total_ips" in stats


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
