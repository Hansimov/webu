"""服务运行时集成测试 — 测试 ggsc 服务启停和 HTTP API。

这些测试验证：
1. CLI 服务管理（start/stop/restart/status）
2. HTTP API 端点（health、proxy/stats、proxy/collect 等）
3. 服务在后台运行的稳定性

前置条件：MongoDB 运行、pip install -e . 已执行。

运行: pytest tests/google_api/test_live_server.py -xvs -m integration
"""

import json
import os
import signal
import subprocess
import sys
import time

import pytest
import requests


# 使用非默认端口避免冲突
TEST_PORT = 18099
TEST_HOST = "127.0.0.1"
BASE_URL = f"http://{TEST_HOST}:{TEST_PORT}"

# ── 通用辅助 ─────────────────────────────────────────────────


def _wait_for_server(url, timeout=30, interval=1):
    """等待服务启动就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{url}/health", timeout=3)
            if resp.status_code == 200:
                return True
        except requests.ConnectionError:
            pass
        time.sleep(interval)
    return False


def _stop_server(proc):
    """优雅停止服务。"""
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


# ═══════════════════════════════════════════════════════════════
# CLI 服务管理测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestCLIServiceManagement:
    """测试 ggsc start/stop/restart/status CLI 命令。"""

    def test_status_when_not_running(self):
        """status 命令在服务未运行时不应报错。"""
        result = subprocess.run(
            [sys.executable, "-m", "webu.google_api", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_stop_when_not_running(self):
        """stop 命令在服务未运行时不应报错。"""
        result = subprocess.run(
            [sys.executable, "-m", "webu.google_api", "stop"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_stats_without_server(self):
        """stats 命令不需要服务运行（直连 MongoDB）。"""
        result = subprocess.run(
            [sys.executable, "-m", "webu.google_api", "stats"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0

    def test_collect_without_server(self):
        """collect 命令不需要服务运行（直连 MongoDB）。"""
        result = subprocess.run(
            [sys.executable, "-m", "webu.google_api", "collect"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0
        # 验证输出包含采集信息
        combined = result.stdout + result.stderr
        assert "total" in combined.lower() or "fetched" in combined.lower() or "Collect" in combined


# ═══════════════════════════════════════════════════════════════
# HTTP API 集成测试（使用 uvicorn 子进程）
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestHTTPAPILive:
    """测试 HTTP API 端点（启动真实服务）。"""

    @pytest.fixture(scope="class")
    def server_proc(self):
        """启动 uvicorn 测试服务（类级别 fixture）。"""
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "webu.google_api.server:app_instance",
                "--host", TEST_HOST,
                "--port", str(TEST_PORT),
                "--factory",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # 等待服务就绪
        if not _wait_for_server(BASE_URL, timeout=45):
            stdout = proc.stdout.read() if proc.stdout else ""
            _stop_server(proc)
            pytest.fail(f"Server failed to start within 45s. Output:\n{stdout}")

        yield proc

        _stop_server(proc)

    def test_health_endpoint(self, server_proc):
        """健康检查端点。"""
        resp = requests.get(f"{BASE_URL}/health", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_swagger_docs(self, server_proc):
        """Swagger 文档页面可访问。"""
        resp = requests.get(f"{BASE_URL}/docs", timeout=5)
        assert resp.status_code == 200
        assert "swagger" in resp.text.lower() or "openapi" in resp.text.lower()

    def test_openapi_schema(self, server_proc):
        """OpenAPI schema 可获取。"""
        resp = requests.get(f"{BASE_URL}/openapi.json", timeout=5)
        assert resp.status_code == 200
        schema = resp.json()
        assert "paths" in schema
        assert "/search" in schema["paths"]
        assert "/health" in schema["paths"]

    def test_proxy_stats(self, server_proc):
        """代理池统计接口。"""
        resp = requests.get(f"{BASE_URL}/proxy/stats", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_ips" in data
        assert "total_valid" in data

    def test_proxy_valid_list(self, server_proc):
        """获取可用代理列表。"""
        resp = requests.get(f"{BASE_URL}/proxy/valid?limit=5", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # 可能为空（如果没有 valid 代理）

    def test_proxy_get(self, server_proc):
        """获取推荐代理（可能 404 如果没有 valid 代理）。"""
        resp = requests.get(f"{BASE_URL}/proxy/get", timeout=10)
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            data = resp.json()
            assert "ip" in data
            assert "port" in data

    def test_proxy_collect(self, server_proc):
        """通过 API 触发代理采集。"""
        resp = requests.post(f"{BASE_URL}/proxy/collect", timeout=120)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_fetched" in data
        assert data["total_fetched"] >= 0

    def test_proxy_check_small_batch(self, server_proc):
        """通过 API 触发代理检测（小批量）。"""
        resp = requests.post(
            f"{BASE_URL}/proxy/check?limit=3&mode=unchecked&level=1",
            timeout=60,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "checked" in data
        assert "valid" in data

    def test_search_get_basic(self, server_proc):
        """GET 搜索接口基本测试。"""
        resp = requests.get(
            f"{BASE_URL}/search?q=test&num=3",
            timeout=60,
        )
        # 即使搜索失败（无可用代理），也应返回 200
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            data = resp.json()
            assert "query" in data
            assert "results" in data

    def test_search_post_basic(self, server_proc):
        """POST 搜索接口基本测试。"""
        resp = requests.post(
            f"{BASE_URL}/search",
            json={"query": "python", "num": 3},
            timeout=60,
        )
        assert resp.status_code in (200, 500)


# ═══════════════════════════════════════════════════════════════
# 实时代理池操作测试（直连 MongoDB，不需要服务运行）
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestProxyPoolOperations:
    """代理池在生产数据库上的操作测试。"""

    def test_real_db_stats(self):
        """查看生产数据库统计。"""
        from webu.google_api.proxy_pool import ProxyPool

        pool = ProxyPool(verbose=True)
        stats = pool.stats()
        print(f"\n  Production DB stats: {stats}")
        assert "total_ips" in stats

    def test_real_db_valid_proxies(self):
        """从生产数据库获取可用代理。"""
        from webu.google_api.mongo import MongoProxyStore

        store = MongoProxyStore(verbose=False)
        proxies = store.get_valid_proxies(limit=10)
        print(f"\n  Got {len(proxies)} valid proxies:")
        for p in proxies[:3]:
            print(f"    {p.get('proxy_url', 'N/A')} latency={p.get('latency_ms', '?')}ms")

    def test_real_db_protocol_distribution(self):
        """检查生产数据库的协议分布。"""
        from webu.google_api.mongo import MongoProxyStore
        from collections import Counter

        store = MongoProxyStore(verbose=False)
        all_ips = store.get_all_ips(limit=0)
        protocols = Counter(ip["protocol"] for ip in all_ips)
        print(f"\n  Protocol distribution: {dict(protocols)}")
        assert len(all_ips) > 0, "Production DB should have IPs"

    @pytest.mark.asyncio
    async def test_level1_quick_check(self):
        """快速 Level-1 检测验证系统正常工作。"""
        from webu.google_api.mongo import MongoProxyStore
        from webu.google_api.proxy_checker import check_level1_batch

        store = MongoProxyStore(verbose=False)
        all_ips = store.get_all_ips(limit=0)
        socks5 = [ip for ip in all_ips if ip["protocol"] == "socks5"][:10]
        if len(socks5) < 3:
            pytest.skip("Not enough SOCKS5 proxies in production DB")

        results = await check_level1_batch(socks5, timeout_s=10, concurrency=10, verbose=True)
        assert len(results) == len(socks5)
        passed = sum(1 for r in results if r["is_valid"])
        print(f"\n  Quick check: {passed}/{len(socks5)} passed")
