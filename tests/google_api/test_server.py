"""FastAPI 搜索服务测试。

运行: pytest tests/google_api/test_server.py -xvs
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

from webu.google_api.server import create_google_search_server
from webu.google_api.proxy_manager import DEFAULT_PROXIES


class TestGoogleSearchServerUnit:
    """FastAPI 服务单元测试（mock 代理和搜索）。"""

    @pytest.fixture
    def client(self):
        app = create_google_search_server(headless=True)
        with TestClient(app) as c:
            yield c

    def test_health(self, client):
        """测试健康检查。"""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_proxy_status(self, client):
        """测试代理状态接口。"""
        resp = client.get("/proxy/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_proxies" in data
        assert "healthy_proxies" in data
        assert "proxies" in data

    def test_proxy_current(self, client):
        """测试当前代理接口。"""
        resp = client.get("/proxy/current")
        assert resp.status_code == 200
        data = resp.json()
        assert "proxy_url" in data

    def test_search_get_missing_query(self, client):
        """测试 GET 搜索接口缺少 query 参数。"""
        resp = client.get("/search")
        # Should return 422 or handle gracefully
        assert resp.status_code in (200, 422)


@pytest.mark.integration
class TestGoogleSearchServerIntegration:
    """FastAPI 服务集成测试。

    需要代理端口（11111, 11119）可用。

    运行: pytest tests/google_api/test_server.py -xvs -m integration
    """

    @pytest.fixture
    def client(self):
        app = create_google_search_server(headless=True)
        with TestClient(app) as c:
            yield c

    def test_health(self, client):
        """测试健康检查。"""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_proxy_status(self, client):
        """测试代理状态。"""
        resp = client.get("/proxy/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_proxies"] == len(DEFAULT_PROXIES)

    def test_search_get(self, client):
        """测试 GET 搜索接口。"""
        resp = client.get("/search?q=test&num=5")
        assert resp.status_code == 200
        data = resp.json()
        assert "query" in data
        assert data["query"] == "test"
        assert "results" in data

    def test_search_post(self, client):
        """测试 POST 搜索接口。"""
        resp = client.post("/search", json={"query": "test", "num": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert "query" in data

    def test_proxy_check(self, client):
        """测试代理检查接口。"""
        resp = client.post("/proxy/check")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_proxies" in data
