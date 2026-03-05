"""ProxyManager 单元测试。

运行: pytest tests/google_api/test_proxy_manager.py -xvs
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, patch, MagicMock

from webu.google_api.proxy_manager import (
    ProxyManager,
    ProxyState,
    ProxyRole,
    DEFAULT_PROXIES,
    check_proxy_health,
)


# ═══════════════════════════════════════════════════════════════
# ProxyState 测试
# ═══════════════════════════════════════════════════════════════


class TestProxyState:
    """ProxyState 数据类测试。"""

    def test_init_defaults(self):
        state = ProxyState(
            url="socks5://127.0.0.1:11000",
            name="warp",
            role=ProxyRole.PRIMARY,
        )
        assert state.healthy is True
        assert state.latency_ms == 0
        assert state.consecutive_failures == 0
        assert state.is_primary is True

    def test_success_rate_empty(self):
        state = ProxyState(url="x", name="x", role=ProxyRole.PRIMARY)
        assert state.success_rate == 1.0

    def test_success_rate(self):
        state = ProxyState(
            url="x", name="x", role=ProxyRole.BACKUP,
            total_successes=7, total_failures=3,
        )
        assert abs(state.success_rate - 0.7) < 0.01

    def test_to_dict(self):
        state = ProxyState(
            url="socks5://127.0.0.1:11000",
            name="warp",
            role=ProxyRole.PRIMARY,
        )
        d = state.to_dict()
        assert d["url"] == "socks5://127.0.0.1:11000"
        assert d["role"] == "primary"
        assert d["healthy"] is True


# ═══════════════════════════════════════════════════════════════
# ProxyManager 单元测试
# ═══════════════════════════════════════════════════════════════


class TestProxyManager:
    """ProxyManager 单元测试。"""

    def test_init_default_proxies(self):
        manager = ProxyManager(verbose=False)
        assert len(manager._proxies) == 3

    def test_init_custom_proxies(self):
        proxies = [
            {"url": "socks5://1.2.3.4:1080", "role": "primary", "name": "p1"},
            {"url": "http://5.6.7.8:8080", "role": "backup", "name": "b1"},
        ]
        manager = ProxyManager(proxies=proxies, verbose=False)
        assert len(manager._proxies) == 2
        assert manager._proxies[0].url == "socks5://1.2.3.4:1080"
        assert manager._proxies[0].is_primary is True

    def test_get_proxy_all_healthy(self):
        """所有代理健康时，应返回主代理。"""
        manager = ProxyManager(verbose=False)
        url = manager.get_proxy()
        assert url == "socks5://127.0.0.1:11000"

    def test_get_proxy_primary_down(self):
        """主代理不健康时，应返回备用代理。"""
        manager = ProxyManager(verbose=False)
        # 标记主代理为不健康
        for p in manager._proxies:
            if p.is_primary:
                p.healthy = False
        url = manager.get_proxy()
        assert url in ["http://127.0.0.1:11111", "http://127.0.0.1:11119"]

    def test_get_proxy_all_unhealthy(self):
        """所有代理不健康时，应返回失败次数最少的。"""
        manager = ProxyManager(verbose=False)
        for p in manager._proxies:
            p.healthy = False
            p.consecutive_failures = 10
        manager._proxies[1].consecutive_failures = 1
        url = manager.get_proxy()
        assert url == manager._proxies[1].url

    def test_report_success(self):
        manager = ProxyManager(verbose=False)
        url = "socks5://127.0.0.1:11000"
        manager.report_success(url)
        state = manager._find_proxy(url)
        assert state.total_successes == 1
        assert state.consecutive_successes == 1

    def test_report_failure_triggers_unhealthy(self):
        manager = ProxyManager(failure_threshold=2, verbose=False)
        url = "socks5://127.0.0.1:11000"
        manager.report_failure(url)
        state = manager._find_proxy(url)
        assert state.healthy is True  # 1 failure < threshold 2

        manager.report_failure(url)
        assert state.healthy is False  # 2 failures = threshold 2

    def test_report_success_recovers_proxy(self):
        manager = ProxyManager(verbose=False)
        url = "socks5://127.0.0.1:11000"
        state = manager._find_proxy(url)
        state.healthy = False
        manager.report_success(url)
        assert state.healthy is True

    def test_backup_rotation(self):
        """备用代理应轮换使用。"""
        manager = ProxyManager(verbose=False)
        for p in manager._proxies:
            if p.is_primary:
                p.healthy = False

        urls = set()
        for _ in range(4):
            urls.add(manager.get_proxy())
        # 应该轮换到至少 2 个不同的备用代理
        assert len(urls) == 2

    def test_stats(self):
        manager = ProxyManager(verbose=False)
        stats = manager.stats()
        assert stats["total_proxies"] == 3
        assert stats["healthy_proxies"] == 3
        assert stats["primary_healthy"] is True
        assert len(stats["proxies"]) == 3

    def test_get_all_proxies(self):
        manager = ProxyManager(verbose=False)
        urls = manager.get_all_proxies()
        assert len(urls) == 3


# ═══════════════════════════════════════════════════════════════
# ProxyManager async 测试
# ═══════════════════════════════════════════════════════════════


class TestProxyManagerAsync:
    """ProxyManager 异步方法测试。"""

    @pytest.mark.asyncio
    async def test_start_stop(self):
        manager = ProxyManager(verbose=False)
        with patch(
            "webu.google_api.proxy_manager.check_proxy_health",
            new_callable=AsyncMock,
            return_value=(True, 50, ""),
        ):
            await manager.start()
            assert manager._running is True
            assert manager._check_task is not None

            await manager.stop()
            assert manager._running is False

    @pytest.mark.asyncio
    async def test_check_all(self):
        manager = ProxyManager(verbose=False)
        with patch(
            "webu.google_api.proxy_manager.check_proxy_health",
            new_callable=AsyncMock,
            return_value=(True, 100, ""),
        ):
            await manager._check_all()
            for p in manager._proxies:
                assert p.healthy is True
                assert p.latency_ms == 100

    @pytest.mark.asyncio
    async def test_check_single_failure(self):
        manager = ProxyManager(failure_threshold=2, verbose=False)
        with patch(
            "webu.google_api.proxy_manager.check_proxy_health",
            new_callable=AsyncMock,
            return_value=(False, 0, "connection refused"),
        ):
            proxy = manager._proxies[0]
            await manager._check_single(proxy)
            assert proxy.consecutive_failures == 1
            assert proxy.healthy is True  # 1 < threshold 2

            await manager._check_single(proxy)
            assert proxy.consecutive_failures == 2
            assert proxy.healthy is False  # 2 = threshold 2


# ═══════════════════════════════════════════════════════════════
# 集成测试（需要实际代理端口）
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestProxyManagerIntegration:
    """ProxyManager 集成测试。

    需要本地代理端口（11000, 11111, 11119）实际运行。

    运行: pytest tests/google_api/test_proxy_manager.py -xvs -m integration
    """

    @pytest.mark.asyncio
    async def test_health_check_real(self):
        """测试对实际代理端口的健康检查。"""
        manager = ProxyManager(verbose=True)
        await manager._check_all()
        stats = manager.stats()
        print(f"\nProxy stats: {stats}")

        for p in stats["proxies"]:
            print(f"  {p['name']}: healthy={p['healthy']}, latency={p['latency_ms']}ms")

        # 至少应有一个代理健康
        assert stats["healthy_proxies"] > 0

    @pytest.mark.asyncio
    async def test_start_stop_real(self):
        """测试实际启动和停止。"""
        manager = ProxyManager(verbose=True)
        await manager.start()

        url = manager.get_proxy()
        print(f"\nSelected proxy: {url}")
        assert url is not None

        await manager.stop()

    @pytest.mark.asyncio
    async def test_failover_simulation(self):
        """模拟主代理故障，验证自动切换到备用。"""
        manager = ProxyManager(verbose=True)
        await manager._check_all()

        # 手动标记主代理为不健康
        for p in manager._proxies:
            if p.is_primary:
                p.healthy = False
                p.consecutive_failures = 5

        url = manager.get_proxy()
        print(f"\nAfter primary failure, using: {url}")
        assert url != "socks5://127.0.0.1:11000"
        assert url in ["http://127.0.0.1:11111", "http://127.0.0.1:11119"]
