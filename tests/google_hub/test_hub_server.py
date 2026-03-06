import json

from fastapi.testclient import TestClient

from webu.google_hub.server import create_google_hub_server


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


def _write_base_configs(config_dir):
    (config_dir / "google_api.json").write_text(
        json.dumps(
            {
                "host": "0.0.0.0",
                "port": 18200,
                "proxy_mode": "auto",
                "services": [
                    {"url": "http://127.0.0.1:18200", "type": "local", "api_token": ""},
                    {"type": "hf-space", "api_token": "hf-search-token"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "google_docker.json").write_text(json.dumps({"admin_token": "hub-secret"}), encoding="utf-8")
    (config_dir / "hf_spaces.json").write_text(
        json.dumps([{"space": "owner/space1", "hf_token": "hf_demo", "enabled": True, "weight": 1}]),
        encoding="utf-8",
    )


def test_hub_admin_backends_requires_token(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    _write_base_configs(config_dir)
    (config_dir / "google_hub.json").write_text(
        json.dumps(
            {
                "admin_token": "hub-secret",
                "backends": [
                    {"name": "local-google-api", "kind": "local-google-api", "base_url": "http://127.0.0.1:18200"}
                ],
            }
        ),
        encoding="utf-8",
    )

    def _fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/health"):
            return _Response(200, {"status": "ok"})
        raise AssertionError(url)

    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr("webu.google_hub.manager.requests.get", _fake_get)

    with TestClient(create_google_hub_server()) as client:
        assert client.get("/admin/backends").status_code == 401
        resp = client.get("/admin/backends", headers={"X-Admin-Token": "hub-secret"})
        assert resp.status_code == 200
        assert resp.json()["healthy_backends"] == 1


def test_hub_search_routes_to_best_backend(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    _write_base_configs(config_dir)
    (config_dir / "google_hub.json").write_text(
        json.dumps(
            {
                "backends": [
                    {"name": "local-google-api", "kind": "local-google-api", "base_url": "http://127.0.0.1:18200", "weight": 2},
                    {"name": "space1", "kind": "hf-space", "space": "owner/space1", "weight": 1},
                ]
            }
        ),
        encoding="utf-8",
    )

    def _fake_get(url, params=None, headers=None, timeout=None):
        if url == "http://127.0.0.1:18200/health":
            return _Response(200, {"status": "ok"})
        if url == "https://owner-space1.hf.space/health":
            return _Response(200, {"status": "ok"})
        if url == "http://127.0.0.1:18200/search":
            return _Response(
                200,
                {
                    "success": True,
                    "query": params["q"],
                    "results": [{"title": "A", "url": "https://example.com"}],
                    "result_count": 1,
                    "total_results_text": "1 result",
                    "has_captcha": False,
                    "error": "",
                },
            )
        raise AssertionError(url)

    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr("webu.google_hub.manager.requests.get", _fake_get)

    with TestClient(create_google_hub_server()) as client:
        resp = client.get("/search", params={"q": "OpenAI news", "num": 5, "lang": "en"})
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["backend"] == "local-google-api"
        assert payload["query"] == "OpenAI news"


def test_hub_search_falls_back_to_next_backend(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    _write_base_configs(config_dir)
    (config_dir / "google_hub.json").write_text(
        json.dumps(
            {
                "backends": [
                    {"name": "local-google-api", "kind": "local-google-api", "base_url": "http://127.0.0.1:18200", "weight": 2},
                    {"name": "space1", "kind": "hf-space", "space": "owner/space1", "weight": 1},
                ]
            }
        ),
        encoding="utf-8",
    )

    def _fake_get(url, params=None, headers=None, timeout=None):
        if url == "http://127.0.0.1:18200/health":
            return _Response(200, {"status": "ok"})
        if url == "https://owner-space1.hf.space/health":
            return _Response(200, {"status": "ok"})
        if url == "http://127.0.0.1:18200/search":
            raise RuntimeError("local timeout")
        if url == "https://owner-space1.hf.space/search":
            return _Response(
                200,
                {
                    "success": True,
                    "query": params["q"],
                    "results": [{"title": "B", "url": "https://example.org"}],
                    "result_count": 1,
                    "total_results_text": "1 result",
                    "has_captcha": False,
                    "error": "",
                },
            )
        raise AssertionError(url)

    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr("webu.google_hub.manager.requests.get", _fake_get)

    with TestClient(create_google_hub_server()) as client:
        resp = client.get("/search", params={"q": "OpenAI news", "num": 5, "lang": "en"})
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["backend"] == "space1"
        assert payload["query"] == "OpenAI news"