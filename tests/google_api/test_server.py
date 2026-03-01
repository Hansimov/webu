"""FastAPI 搜索服务测试。

运行: pytest tests/google-api/test_server.py -xvs
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

from webu.google_api.server import create_google_search_server


@pytest.mark.integration
class TestGoogleSearchServerIntegration:
    """FastAPI 服务集成测试。

    需要 MongoDB 在 localhost:27017 运行。

    运行: pytest tests/google-api/test_server.py -xvs -m integration
    """

    TEST_CONFIGS = {
        "host": "localhost",
        "port": 27017,
        "dbname": "webu_test",
    }

    @pytest.fixture
    def client(self):
        app = create_google_search_server(configs=self.TEST_CONFIGS, headless=True)
        with TestClient(app) as c:
            yield c

    def test_health(self, client):
        """测试健康检查。"""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_proxy_stats(self, client):
        """测试代理池统计。"""
        resp = client.get("/proxy/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_ips" in data
        assert "total_valid" in data

    def test_proxy_collect(self, client):
        """测试代理采集。"""
        resp = client.post("/proxy/collect")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_fetched" in data
        assert data["total_fetched"] > 0

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
