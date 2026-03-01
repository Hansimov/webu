"""代理检测器单元测试。

运行: pytest tests/google_api/test_proxy_checker.py -xvs
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from webu.google_api.proxy_checker import (
    _build_proxy_url,
    _random_ua,
    _random_viewport,
    _random_locale,
    ProxyChecker,
)
from webu.google_api.mongo import MongoProxyStore
from webu.google_api.constants import USER_AGENTS, VIEWPORT_SIZES, LOCALES


# ═══════════════════════════════════════════════════════════════
# 辅助函数测试
# ═══════════════════════════════════════════════════════════════


class TestHelperFunctions:
    """代理检测辅助函数测试。"""

    def test_build_proxy_url_http(self):
        """测试 HTTP 代理 URL 构建。"""
        assert _build_proxy_url("1.2.3.4", 8080, "http") == "http://1.2.3.4:8080"

    def test_build_proxy_url_https(self):
        """测试 HTTPS 代理 URL 构建（仍使用 http:// 前缀）。"""
        assert _build_proxy_url("1.2.3.4", 443, "https") == "http://1.2.3.4:443"

    def test_build_proxy_url_socks5(self):
        """测试 SOCKS5 代理 URL 构建。"""
        assert _build_proxy_url("10.0.0.1", 1080, "socks5") == "socks5://10.0.0.1:1080"

    def test_build_proxy_url_socks4(self):
        """测试 SOCKS4 代理 URL 构建。"""
        assert _build_proxy_url("10.0.0.1", 1080, "socks4") == "socks4://10.0.0.1:1080"

    def test_build_proxy_url_unknown(self):
        """测试未知协议回退到 http。"""
        assert _build_proxy_url("1.2.3.4", 8080, "unknown") == "http://1.2.3.4:8080"

    def test_random_ua_from_list(self):
        """测试随机 UA 在预定义列表中。"""
        for _ in range(20):
            assert _random_ua() in USER_AGENTS

    def test_random_viewport_valid(self):
        """测试随机视口在预定义列表中。"""
        for _ in range(20):
            vp = _random_viewport()
            assert vp in VIEWPORT_SIZES
            assert "width" in vp
            assert "height" in vp

    def test_random_locale_valid(self):
        """测试随机语言在预定义列表中。"""
        for _ in range(20):
            assert _random_locale() in LOCALES


# ═══════════════════════════════════════════════════════════════
# ProxyChecker 单元测试
# ═══════════════════════════════════════════════════════════════


class TestProxyChecker:
    """ProxyChecker 单元测试（mock Playwright）。"""

    def setup_method(self):
        self.store = MagicMock(spec=MongoProxyStore)
        self.checker = ProxyChecker(
            store=self.store, timeout=5, concurrency=2, verbose=False
        )

    def test_init_default_params(self):
        """测试默认参数初始化。"""
        store = MagicMock(spec=MongoProxyStore)
        checker = ProxyChecker(store=store)
        assert checker.timeout > 0
        assert checker.concurrency > 0

    @pytest.mark.asyncio
    async def test_check_batch_empty(self):
        """测试空列表返回空结果。"""
        results = await self.checker.check_batch([])
        assert results == []

    @pytest.mark.asyncio
    async def test_check_unchecked_no_ips(self):
        """测试无未检测 IP 时的行为。"""
        self.store.get_unchecked_ips.return_value = []
        results = await self.checker.check_unchecked()
        assert results == []

    @pytest.mark.asyncio
    async def test_check_stale_no_ips(self):
        """测试无过期 IP 时的行为。"""
        self.store.get_stale_ips.return_value = []
        results = await self.checker.check_stale()
        assert results == []

    @pytest.mark.asyncio
    async def test_check_all_no_ips(self):
        """测试无 IP 时的行为。"""
        self.store.get_all_ips.return_value = []
        results = await self.checker.check_all()
        assert results == []


# ═══════════════════════════════════════════════════════════════
# 集成测试（需要 Playwright 和网络）
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestProxyCheckerIntegration:
    """代理检测器集成测试。

    需要：
    - MongoDB 运行
    - Playwright 浏览器已安装
    - 网络连接

    运行: pytest tests/google_api/test_proxy_checker.py -xvs -m integration
    """

    TEST_CONFIGS = {
        "host": "localhost",
        "port": 27017,
        "dbname": "webu_test",
    }

    @pytest.mark.asyncio
    async def test_check_single_direct(self):
        """测试直连检测 Google（不通过代理）。"""
        from playwright.async_api import async_playwright

        store = MagicMock(spec=MongoProxyStore)
        checker = ProxyChecker(store=store, timeout=15, verbose=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            # 使用一个无效的代理来测试失败路径
            result = await checker.check_single_proxy(
                browser=browser,
                ip="127.0.0.1",
                port=1,  # 无效端口
                protocol="http",
            )
            await browser.close()

        assert result["ip"] == "127.0.0.1"
        assert result["is_valid"] is False
        assert result["last_error"] != ""
