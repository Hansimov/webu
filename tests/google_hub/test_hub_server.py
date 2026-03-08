import json
import time

from fastapi.testclient import TestClient

from webu.runtime_settings import DEFAULT_GOOGLE_API_PANEL_PATH
from webu.fastapis.panel_components import build_backend_instance_cards
from webu.google_hub.manager import (
    GoogleHubBackend,
    GoogleHubManager,
    GoogleHubSettings,
)
from webu.google_hub.panel import _build_body as build_google_hub_panel_body
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
    (config_dir / "google_docker.json").write_text(
        json.dumps({"admin_token": "hub-secret"}), encoding="utf-8"
    )
    (config_dir / "hf_spaces.json").write_text(
        json.dumps(
            [
                {
                    "space": "owner/space1",
                    "hf_token": "hf_demo",
                    "enabled": True,
                    "weight": 1,
                }
            ]
        ),
        encoding="utf-8",
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


def _collect_ids(component):
    ids = []
    component_id = getattr(component, "id", None)
    if component_id:
        ids.append(str(component_id))
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            ids.extend(_collect_ids(child))
    elif children is not None:
        ids.extend(_collect_ids(children))
    return ids


def _collect_components_by_class(component, class_name: str):
    matches = []
    if getattr(component, "className", None) == class_name:
        matches.append(component)
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            matches.extend(_collect_components_by_class(child, class_name))
    elif children is not None:
        matches.extend(_collect_components_by_class(children, class_name))
    return matches


def test_hub_admin_backends_requires_token(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    _write_base_configs(config_dir)
    (config_dir / "google_hub.json").write_text(
        json.dumps(
            {
                "admin_token": "hub-secret",
                "backends": [
                    {
                        "name": "local-google-api",
                        "kind": "local-google-api",
                        "base_url": "http://127.0.0.1:18200",
                    }
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
                    {
                        "name": "local-google-api",
                        "kind": "local-google-api",
                        "base_url": "http://127.0.0.1:18200",
                        "weight": 2,
                    },
                    {
                        "name": "space1",
                        "kind": "hf-space",
                        "space": "owner/space1",
                        "weight": 1,
                    },
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

    app = create_google_hub_server()
    with TestClient(app) as client:
        resp = client.get(
            "/search", params={"q": "OpenAI news", "num": 5, "lang": "en"}
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["backend"] == "local-google-api"
        assert payload["query"] == "OpenAI news"
        metrics = app.state.google_hub_manager.request_metrics.snapshot()
        assert metrics.accepted_requests == 1
        assert metrics.successful_requests == 1


def test_hub_search_falls_back_to_next_backend(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    _write_base_configs(config_dir)
    (config_dir / "google_hub.json").write_text(
        json.dumps(
            {
                "backends": [
                    {
                        "name": "local-google-api",
                        "kind": "local-google-api",
                        "base_url": "http://127.0.0.1:18200",
                        "weight": 2,
                    },
                    {
                        "name": "space1",
                        "kind": "hf-space",
                        "space": "owner/space1",
                        "weight": 1,
                    },
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
        resp = client.get(
            "/search", params={"q": "OpenAI news", "num": 5, "lang": "en"}
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["backend"] == "space1"
        assert payload["query"] == "OpenAI news"


def test_hub_fallback_counts_single_request_metric(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    _write_base_configs(config_dir)
    (config_dir / "google_hub.json").write_text(
        json.dumps(
            {
                "backends": [
                    {
                        "name": "local-google-api",
                        "kind": "local-google-api",
                        "base_url": "http://127.0.0.1:18200",
                        "weight": 2,
                    },
                    {
                        "name": "space1",
                        "kind": "hf-space",
                        "space": "owner/space1",
                        "weight": 1,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    def _fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/health"):
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

    app = create_google_hub_server()
    with TestClient(app) as client:
        resp = client.get("/search", params={"q": "fallback", "num": 5, "lang": "en"})
        assert resp.status_code == 200
        metrics = app.state.google_hub_manager.request_metrics.snapshot()
        assert metrics.accepted_requests == 1
        assert metrics.successful_requests == 1
        assert metrics.failed_requests == 0


def test_adaptive_strategy_prefers_fast_and_stable_backend():
    settings = GoogleHubSettings(
        host="0.0.0.0",
        port=18180,
        admin_token="",
        strategy="adaptive",
        request_timeout_sec=30,
        health_timeout_sec=5,
        health_interval_sec=30,
        excluded_nodes=[],
        backends=[
            GoogleHubBackend(
                name="fast-stable",
                kind="google-api",
                base_url="http://fast",
                enabled=True,
                weight=1,
            ),
            GoogleHubBackend(
                name="slow-flaky",
                kind="google-api",
                base_url="http://slow",
                enabled=True,
                weight=1,
            ),
        ],
        project_root="/tmp",
        config_dir="/tmp/configs",
    )
    manager = GoogleHubManager(settings)
    fast = manager.states["fast-stable"]
    slow = manager.states["slow-flaky"]
    fast.healthy = True
    slow.healthy = True

    for _ in range(4):
        fast.record_request(45.0, True)
        slow.record_request(320.0, False)
    slow.record_request(280.0, True)

    ordered = manager.ordered_backends()
    assert ordered[0].backend.name == "fast-stable"
    assert ordered[0].compute_selection_score() < ordered[1].compute_selection_score()


def test_hub_panel_body_includes_uptime_and_status_bars():
    snapshot = {
        "updated_at_human": "2026-03-09 09:00:00",
        "current_time_human": "2026-03-09 09:00:00",
        "timezone_human": "UTC+08 Shanghai",
        "started_at_human": "2026-03-09 08:00:00",
        "uptime_human": "1h 0m 0s",
        "strategy": "adaptive",
        "node": {"value": "hub-node"},
        "health": {"healthy_backends": 1, "backend_count": 2, "enabled_backends": 1},
        "requests": {
            "accepted_requests": 8,
            "successful_requests": 7,
            "failed_requests": 1,
            "success_rate": 87.5,
            "avg_latency_ms": 180.0,
            "median_latency_ms": 130.0,
            "recent_latency_ms": 130.0,
            "min_latency_ms": 90.0,
            "max_latency_ms": 420.0,
            "last_latency_ms": 130.0,
            "history": [
                {
                    "label": "08:57",
                    "accepted_requests": 4,
                    "successful_requests": 4,
                    "success_rate": 100.0,
                    "avg_latency_ms": 120.0,
                    "median_latency_ms": 110.0,
                    "recent_latency_ms": 110.0,
                    "last_latency_ms": 110.0,
                },
                {
                    "label": "08:58",
                    "accepted_requests": 6,
                    "successful_requests": 5,
                    "success_rate": 83.3,
                    "avg_latency_ms": 190.0,
                    "median_latency_ms": 180.0,
                    "recent_latency_ms": 210.0,
                    "last_latency_ms": 210.0,
                },
                {
                    "label": "08:59",
                    "accepted_requests": 8,
                    "successful_requests": 7,
                    "success_rate": 87.5,
                    "avg_latency_ms": 180.0,
                    "median_latency_ms": 130.0,
                    "recent_latency_ms": 130.0,
                    "last_latency_ms": 130.0,
                },
            ],
            "request_log": [
                {
                    "ts_label": "09:00:01",
                    "query": "OpenAI news",
                    "backend": "space1",
                    "success": True,
                    "latency_ms": 210.0,
                    "error": "",
                    "result_preview": "OpenAI news headline | short snippet | example.com",
                    "result_detail": '{\n  "results": [{"title": "OpenAI news headline"}]\n}',
                }
            ],
        },
        "backends": [
            {
                "name": "local",
                "kind": "google-api",
                "healthy": False,
                "enabled": False,
                "disabled_reason": "excluded by hub settings",
                "request_count": 5,
                "success_rate": 100.0,
                "avg_request_latency_ms": 110.0,
            },
            {
                "name": "remote",
                "space_name": "owner/space",
                "healthy": True,
                "enabled": True,
                "disabled_reason": "",
                "request_count": 3,
                "success_rate": 66.7,
                "avg_request_latency_ms": 260.0,
            },
        ],
    }

    body = build_google_hub_panel_body(
        snapshot,
        auth_unlocked=True,
        admin_token_configured=True,
        page=1,
        page_size=10,
    )
    class_names = _collect_class_names(body)
    text_values = _collect_text(body)
    assert any("dash-strip-card" in value for value in class_names)
    assert "UPTIME" in text_values
    assert "1h 0m 0s" in text_values
    assert "disabled" in text_values
    assert "OpenAI news headline | short snippet | example.com" in text_values
    assert "1/1 HEALTHY" in text_values


def test_hub_panel_masks_server_ip_and_hides_request_history_when_locked():
    snapshot = {
        "updated_at_human": "2026-03-09 09:00:00",
        "current_time_human": "2026-03-09 09:00:00",
        "timezone_human": "UTC+08 Shanghai",
        "started_at_human": "2026-03-09 08:00:00",
        "uptime_human": "1h 0m 0s",
        "strategy": "adaptive",
        "node": {"label": "Server IP", "value": "1.2.3.4"},
        "health": {"healthy_backends": 1, "backend_count": 1, "enabled_backends": 1},
        "requests": {
            "accepted_requests": 1,
            "successful_requests": 1,
            "failed_requests": 0,
            "success_rate": 100.0,
            "avg_latency_ms": 100.0,
            "median_latency_ms": 100.0,
            "recent_latency_ms": 100.0,
            "last_latency_ms": 100.0,
            "history": [],
            "request_log": [
                {
                    "ts_label": "09:00:01",
                    "query": "secret query",
                    "backend": "space1",
                    "success": True,
                    "latency_ms": 100.0,
                    "error": "",
                    "result_preview": "secret preview",
                    "result_detail": "secret detail",
                }
            ],
        },
        "backends": [],
    }

    body = build_google_hub_panel_body(
        snapshot,
        auth_unlocked=False,
        admin_token_configured=True,
        page=1,
        page_size=10,
    )
    text_values = _collect_text(body)

    assert "**.**.**.**" in text_values
    assert "secret preview" not in text_values


def test_hub_instance_cards_place_disabled_last_and_dim_them():
    cards = build_backend_instance_cards(
        [
            {
                "name": "local",
                "kind": "google-api",
                "healthy": False,
                "enabled": False,
                "disabled_reason": "excluded by hub settings",
                "request_count": 5,
                "success_rate": 100.0,
                "avg_request_latency_ms": 110.0,
            },
            {
                "name": "space2",
                "space_name": "owner/space2",
                "healthy": False,
                "enabled": True,
                "disabled_reason": "",
                "request_count": 1,
                "success_rate": 0.0,
                "avg_request_latency_ms": 420.0,
            },
            {
                "name": "space1",
                "space_name": "owner/space1",
                "healthy": True,
                "enabled": True,
                "disabled_reason": "",
                "request_count": 3,
                "success_rate": 66.7,
                "avg_request_latency_ms": 260.0,
            },
        ]
    )

    instance_names = []
    for card in cards:
        name_nodes = _collect_components_by_class(card, "dash-inst-name")
        instance_names.append(name_nodes[0].children)

    assert instance_names == ["space1", "space2", "local"]
    assert cards[-1].style["opacity"] == 0.58


def test_hub_panel_root_redirect_and_page(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    _write_base_configs(config_dir)
    (config_dir / "google_hub.json").write_text(
        json.dumps(
            {
                "backends": [
                    {
                        "name": "local-google-api",
                        "kind": "local-google-api",
                        "base_url": "http://127.0.0.1:18200",
                        "weight": 2,
                    }
                ]
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

    app = create_google_hub_server()
    with TestClient(app) as client:
        root_resp = client.get("/", follow_redirects=False)
        assert root_resp.status_code == 307
        assert root_resp.headers["location"] == DEFAULT_GOOGLE_API_PANEL_PATH

        panel_resp = client.get(DEFAULT_GOOGLE_API_PANEL_PATH)
        assert panel_resp.status_code == 200
        assert "<title>Google Hub Panel</title>" in panel_resp.text
        assert "/panel/_dash-component-suites/" in panel_resp.text
