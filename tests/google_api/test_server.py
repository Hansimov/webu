"""FastAPI 搜索服务测试。

运行: pytest tests/google_api/test_server.py -xvs
"""

import pytest
from urllib.parse import quote
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

from webu.google_api.server import create_google_search_server
from webu.google_api.panel import _build_body as build_google_api_panel_body
from webu.google_api.proxy_manager import DEFAULT_PROXIES
from webu.runtime_settings import (
    DEFAULT_GOOGLE_API_PANEL_PATH,
    resolve_google_api_settings,
)


def _collect_class_names(component):
    names = []
    class_name = getattr(component, "className", None)
    if class_name:
        names.append(str(class_name))
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            names.extend(_collect_class_names(child))
    elif children is not None:
        names.extend(_collect_class_names(children))
    return names


def _collect_text(component):
    if isinstance(component, str):
        return [component]
    values = []
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            values.extend(_collect_text(child))
    elif children is not None:
        values.extend(_collect_text(children))
    return values


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


class _FakeRawHtmlResult:
    def __init__(self, query=""):
        self.query = query
        self.html = "<html><body><div id='search'>fake html</div></body></html>"
        self.final_url = "https://www.google.com/search?q=fake"
        self.proxy_url = "http://127.0.0.1:11119"
        self.elapsed_ms = 123
        self.has_captcha = False
        self.error = ""


class _FakeGoogleScraper:
    last_search_call = None
    last_raw_call = None

    def __init__(
        self, proxy_manager=None, headless=True, profile_dir=None, screenshot_dir=None
    ):
        self.proxy_manager = proxy_manager

    async def start(self):
        return None

    async def stop(self):
        return None

    async def search(self, query, num=10, lang=None, locale=None, proxy_url=None):
        _FakeGoogleScraper.last_search_call = {
            "query": query,
            "num": num,
            "lang": lang,
            "locale": locale,
            "proxy_url": proxy_url,
        }
        result = _FakeSearchResult()
        result.query = query
        return result

    async def fetch_raw_html(
        self,
        query,
        num=10,
        lang=None,
        locale=None,
        proxy_url=None,
    ):
        _FakeGoogleScraper.last_raw_call = {
            "query": query,
            "num": num,
            "lang": lang,
            "locale": locale,
            "proxy_url": proxy_url,
        }
        result = _FakeRawHtmlResult(query=query)
        if proxy_url:
            result.proxy_url = proxy_url
        return result


class TestGoogleSearchServerUnit:
    """FastAPI 服务单元测试（mock 代理和搜索）。"""

    @pytest.fixture
    def client(self):
        _FakeGoogleScraper.last_search_call = None
        _FakeGoogleScraper.last_raw_call = None
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

    def test_search_raw_html(self, client):
        resp = client.get("/search_raw?q=test&proxy_url=http://127.0.0.1:11119")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert resp.headers["x-query"] == "test"
        assert resp.headers["x-proxy-url"] == "http://127.0.0.1:11119"
        assert "fake html" in resp.text

    def test_search_raw_html_non_ascii_query_header_is_encoded(self, client):
        query = "玩机器切片"
        resp = client.get(f"/search_raw?q={quote(query)}")
        assert resp.status_code == 200
        assert resp.headers["x-query"] == quote(query, safe="")

    def test_search_auto_infers_lang_and_locale_from_query(self, client):
        resp = client.get(f"/search?q={quote('玩机器切片')}")
        assert resp.status_code == 200
        assert _FakeGoogleScraper.last_search_call == {
            "query": "玩机器切片",
            "num": 10,
            "lang": None,
            "locale": None,
            "proxy_url": None,
        }

    def test_search_raw_accepts_explicit_locale(self, client):
        resp = client.get("/search_raw?q=wikipedia&lang=fr&locale=fr-FR")
        assert resp.status_code == 200
        assert _FakeGoogleScraper.last_raw_call == {
            "query": "wikipedia",
            "num": 10,
            "lang": "fr",
            "locale": "fr-FR",
            "proxy_url": None,
        }

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
                app = create_google_search_server(
                    settings=resolve_google_api_settings(headless=True)
                )
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
                "{"
                '"host": "0.0.0.0", '
                '"port": 18200, '
                '"proxy_mode": "auto", '
                f'"profile_dir": "{profile_dir}", '
                '"services": [{"type": "local", "api_token": "local-search-token"}]'
                "}"
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
        monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("WEBU_RUNTIME_ENV", "local")
        monkeypatch.setenv("WEBU_ADMIN_TOKEN", "admin-secret")

        with patch("webu.google_api.server.ProxyManager", _FakeProxyManager):
            with patch("webu.google_api.server.GoogleScraper", _FakeGoogleScraper):
                app = create_google_search_server(
                    settings=resolve_google_api_settings(headless=True)
                )
                with TestClient(app) as client:
                    assert client.get("/admin/profile/status").status_code == 401
                    resp = client.get(
                        "/admin/profile/status",
                        headers={"X-Admin-Token": "admin-secret"},
                    )
                    assert resp.status_code == 200
                    assert resp.json()["archive_available"] is True

                    archive_resp = client.get(
                        "/admin/profile/archive?secret=webu",
                        headers={"X-Admin-Token": "admin-secret"},
                    )
                    assert archive_resp.status_code == 200
                    assert (
                        archive_resp.headers["content-type"]
                        == "application/octet-stream"
                    )
                    assert len(archive_resp.content) > 0

    def test_panel_home_redirect_and_page(self):
        with patch("webu.google_api.server.ProxyManager", _FakeProxyManager):
            with patch("webu.google_api.server.GoogleScraper", _FakeGoogleScraper):
                app = create_google_search_server(headless=True, home_mode="panel")
                with TestClient(app) as client:
                    root_resp = client.get("/", follow_redirects=False)
                    assert root_resp.status_code == 200
                    assert DEFAULT_GOOGLE_API_PANEL_PATH in root_resp.text

                    panel_resp = client.get(DEFAULT_GOOGLE_API_PANEL_PATH)
                    assert panel_resp.status_code == 200
                    assert "<title>Google Instance Panel</title>" in panel_resp.text
                    assert "_dash-config" in panel_resp.text
                    assert "/panel/_dash-component-suites/" in panel_resp.text

    def test_search_updates_request_metrics(self):
        with patch("webu.google_api.server.ProxyManager", _FakeProxyManager):
            with patch("webu.google_api.server.GoogleScraper", _FakeGoogleScraper):
                app = create_google_search_server(headless=True)
                with TestClient(app) as client:
                    response = client.get("/search?q=OpenAI+news&num=3")
                    assert response.status_code == 200
                    metrics = app.state.google_api_request_metrics.snapshot()
                    assert metrics.accepted_requests == 1
                    assert metrics.successful_requests == 1

    def test_panel_body_includes_uptime_and_status_bars(self):
        snapshot = {
            "updated_at_human": "2026-03-09 09:00:00",
            "current_time_human": "2026-03-09 09:00:00",
            "timezone_human": "UTC+08 Shanghai",
            "started_at_human": "2026-03-09 08:30:00",
            "uptime_human": "30m 0s",
            "runtime_env": "hf-space",
            "node": {"value": "space-node"},
            "service": {
                "status_label": "healthy",
                "status_note": "hf-space on 0.0.0.0:8000",
            },
            "requests": {
                "accepted_requests": 6,
                "successful_requests": 5,
                "failed_requests": 1,
                "success_rate": 83.3,
                "avg_latency_ms": 210.0,
                "median_latency_ms": 180.0,
                "recent_latency_ms": 180.0,
                "min_latency_ms": 100.0,
                "max_latency_ms": 480.0,
                "last_latency_ms": 180.0,
                "history": [
                    {
                        "label": "08:57",
                        "accepted_requests": 2,
                        "successful_requests": 2,
                        "success_rate": 100.0,
                        "avg_latency_ms": 120.0,
                        "median_latency_ms": 100.0,
                        "recent_latency_ms": 100.0,
                        "last_latency_ms": 100.0,
                    },
                    {
                        "label": "08:58",
                        "accepted_requests": 4,
                        "successful_requests": 3,
                        "success_rate": 75.0,
                        "avg_latency_ms": 240.0,
                        "median_latency_ms": 220.0,
                        "recent_latency_ms": 260.0,
                        "last_latency_ms": 260.0,
                    },
                    {
                        "label": "08:59",
                        "accepted_requests": 6,
                        "successful_requests": 5,
                        "success_rate": 83.3,
                        "avg_latency_ms": 210.0,
                        "median_latency_ms": 180.0,
                        "recent_latency_ms": 180.0,
                        "last_latency_ms": 180.0,
                    },
                ],
                "request_log": [
                    {
                        "ts_label": "09:00:01",
                        "query": "OpenAI news",
                        "success": True,
                        "latency_ms": 180.0,
                        "error": "",
                        "result_preview": "OpenAI news headline | short snippet | example.com",
                        "result_detail": '{\n  "results": [{"title": "OpenAI news headline"}]\n}',
                    }
                ],
            },
        }

        body = build_google_api_panel_body(
            snapshot,
            auth_unlocked=True,
            admin_token_configured=False,
            page=1,
            page_size=10,
        )
        class_names = _collect_class_names(body)
        text_values = _collect_text(body)
        assert any("dash-strip-card" in value for value in class_names)
        assert "UPTIME" in text_values
        assert "30m 0s" in text_values
        assert "OpenAI news headline | short snippet | example.com" in text_values
        assert "recent / mid" not in text_values


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
