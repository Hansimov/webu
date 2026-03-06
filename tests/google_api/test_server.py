"""FastAPI 搜索服务测试。

运行: pytest tests/google_api/test_server.py -xvs
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

from webu.google_api.server import create_google_search_server
from webu.google_api.proxy_manager import DEFAULT_PROXIES
from webu.runtime_settings import resolve_google_api_settings


class _FakeProxyManager:
    def __init__(self, proxies=None, verbose=True):
        self._proxies = proxies or DEFAULT_PROXIES

    async def start(self):
        return None

    async def stop(self):
        return None

    async def _check_all(self):
        return None

    def get_proxy(self):
        if not self._proxies:
            return None
        return self._proxies[0]["url"]

    def stats(self):
        return {
            "total_proxies": len(self._proxies),
            "healthy_proxies": len(self._proxies),
            "unhealthy_proxies": 0,
            "proxies": [
                {
                    "url": proxy["url"],
                    "name": proxy.get("name", proxy["url"]),
                    "healthy": True,
                    "latency_ms": 1,
                    "consecutive_failures": 0,
                    "total_successes": 0,
                    "total_failures": 0,
                    "success_rate": "100.0%",
                    "last_check": "now",
                }
                for proxy in self._proxies
            ],
        }


class _FakeSearchResult:
    def __init__(self):
        self.results = []
        self.query = ""
        self.total_results_text = ""
        self.has_captcha = False
        self.error = ""


class _FakeGoogleScraper:
    def __init__(self, proxy_manager=None, headless=True, profile_dir=None, screenshot_dir=None):
        self.proxy_manager = proxy_manager

    async def start(self):
        return None

    async def stop(self):
        return None

    async def search(self, query, num=10, lang="en", proxy_url=None):
        result = _FakeSearchResult()
        result.query = query
        return result


class TestGoogleSearchServerUnit:
    """FastAPI 服务单元测试（mock 代理和搜索）。"""

    @pytest.fixture
    def client(self):
        with patch("webu.google_api.server.ProxyManager", _FakeProxyManager):
            with patch("webu.google_api.server.GoogleScraper", _FakeGoogleScraper):
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

    def test_search_requires_api_token_when_configured(self, monkeypatch, tmp_path):
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "google_api.json").write_text(
            '{"services": [{"url": "http://127.0.0.1:18200", "type": "local", "api_token": "local-search-token"}]}',
            encoding="utf-8",
        )
        monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
        monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("WEBU_RUNTIME_ENV", "local")
        with patch("webu.google_api.server.ProxyManager", _FakeProxyManager):
            with patch("webu.google_api.server.GoogleScraper", _FakeGoogleScraper):
                app = create_google_search_server(settings=resolve_google_api_settings(headless=True))
                with TestClient(app) as client:
                    resp = client.get("/search?q=test")
                    assert resp.status_code == 401
                    resp = client.get("/search?q=test&api_token=local-search-token")
                    assert resp.status_code == 200
                    resp = client.post(
                        "/search",
                        json={"query": "test"},
                        headers={"X-Api-Token": "local-search-token"},
                    )
                    assert resp.status_code == 200

    def test_admin_profile_status_and_archive(self, monkeypatch, tmp_path):
        config_dir = tmp_path / "configs"
        profile_dir = tmp_path / "profile"
        config_dir.mkdir()
        profile_dir.mkdir()
        (profile_dir / "google_cookies.json").write_text("[]\n", encoding="utf-8")
        (config_dir / "google_api.json").write_text(
            (
                '{'
                '"host": "0.0.0.0", '
                '"port": 18200, '
                '"proxy_mode": "auto", '
                f'"profile_dir": "{profile_dir}", '
                '"services": [{"type": "local", "api_token": "local-search-token"}]'
                '}'
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
        monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("WEBU_RUNTIME_ENV", "local")
        monkeypatch.setenv("WEBU_ADMIN_TOKEN", "admin-secret")

        with patch("webu.google_api.server.ProxyManager", _FakeProxyManager):
            with patch("webu.google_api.server.GoogleScraper", _FakeGoogleScraper):
                app = create_google_search_server(settings=resolve_google_api_settings(headless=True))
                with TestClient(app) as client:
                    assert client.get("/admin/profile/status").status_code == 401
                    resp = client.get("/admin/profile/status", headers={"X-Admin-Token": "admin-secret"})
                    assert resp.status_code == 200
                    assert resp.json()["archive_available"] is True

                    archive_resp = client.get(
                        "/admin/profile/archive?secret=webu",
                        headers={"X-Admin-Token": "admin-secret"},
                    )
                    assert archive_resp.status_code == 200
                    assert archive_resp.headers["content-type"] == "application/octet-stream"
                    assert len(archive_resp.content) > 0


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
