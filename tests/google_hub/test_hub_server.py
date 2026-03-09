import json
import asyncio
import time

import pytest

from dash import dcc, html
from dash.exceptions import PreventUpdate
from fastapi.testclient import TestClient

from webu.runtime_settings import DEFAULT_GOOGLE_API_PANEL_PATH
from webu.fastapis.panel_components import build_backend_instance_cards
from webu.google_hub.manager import (
    GoogleHubBackend,
    GoogleHubManager,
    GoogleHubSettings,
    sanitize_hf_control_error,
    sanitize_hub_search_error,
)
from webu.google_hub.panel import _accepted_admin_tokens
from webu.google_hub.panel import _build_body as build_google_hub_panel_body
from webu.google_hub.panel import _resolve_search_state
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
            {
                "accounts": [
                    {
                        "account": "owner",
                        "hf_token": "hf_demo",
                        "spaces": [
                            {
                                "name": "space1",
                                "enabled": True,
                                "weight": 1,
                            }
                        ],
                    }
                ]
            }
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


def _find_component_by_id(component, component_id: str):
    if getattr(component, "id", None) == component_id:
        return component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            match = _find_component_by_id(child, component_id)
            if match is not None:
                return match
    elif children is not None:
        return _find_component_by_id(children, component_id)
    return None


def _collect_details_with_class_token(component, class_token: str):
    matches = []
    class_name = str(getattr(component, "className", "") or "")
    if isinstance(component, html.Details) and class_token in class_name.split():
        matches.append(component)
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            matches.extend(_collect_details_with_class_token(child, class_token))
    elif children is not None:
        matches.extend(_collect_details_with_class_token(children, class_token))
    return matches


def _detail_contains_component_id(component, component_id: str) -> bool:
    if getattr(component, "id", None) == component_id:
        return True
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        return any(
            _detail_contains_component_id(child, component_id) for child in children
        )
    if children is not None:
        return _detail_contains_component_id(children, component_id)
    return False


def test_hub_admin_backends_requires_token(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    _write_base_configs(config_dir)
    (config_dir / "google_hub.json").write_text(
        json.dumps(
            {
                "admin_token": "hub-secret",
                "exclude_nodes": ["owner/space1"],
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


def test_hub_search_skips_recently_timed_out_backend(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    _write_base_configs(config_dir)
    (config_dir / "google_hub.json").write_text(
        json.dumps(
            {
                "request_timeout_sec": 30,
                "backends": [
                    {
                        "name": "space1",
                        "kind": "hf-space",
                        "space": "owner/space1",
                        "weight": 2,
                    },
                    {
                        "name": "space2",
                        "kind": "hf-space",
                        "space": "owner/space2",
                        "weight": 1,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    calls = []

    def _fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, timeout))
        if url.endswith("/health"):
            return _Response(200, {"status": "ok"})
        if url == "https://owner-space1.hf.space/search":
            raise RuntimeError("Read timed out")
        if url == "https://owner-space2.hf.space/search":
            return _Response(
                200,
                {
                    "success": True,
                    "query": params["q"],
                    "results": [{"title": "B", "url": "https://example.com/b"}],
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
        resp = client.get("/search", params={"q": "python", "num": 3})
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["backend"] == "space2"
        assert payload["results"][0]["title"] == "B"

        backend_resp = client.get(
            "/admin/backends", headers={"X-Admin-Token": "hub-secret"}
        )
        assert backend_resp.status_code == 200
        backends = {item["name"]: item for item in backend_resp.json()["backends"]}
        assert backends["space1"]["healthy"] is True
        assert backends["space1"]["search_cooldown_until_ts"] > 0

    search_timeouts = [timeout for url, timeout in calls if url.endswith("/search")]
    assert 18 in search_timeouts


def test_hub_search_returns_summarized_auto_failure(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    _write_base_configs(config_dir)
    (config_dir / "google_hub.json").write_text(
        json.dumps(
            {
                "exclude_nodes": ["owner/space1"],
                "backends": [
                    {
                        "name": "space3",
                        "kind": "hf-space",
                        "space": "owner/space3",
                        "weight": 1,
                    },
                    {
                        "name": "space4",
                        "kind": "hf-space",
                        "space": "owner/space4",
                        "weight": 1,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    def _fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/health"):
            return _Response(200, {"status": "ok"})
        if url.endswith("/search"):
            raise RuntimeError(
                "HTTPSConnectionPool(host='owner-space4.hf.space', port=443): Read timed out."
            )
        raise AssertionError(url)

    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))
    monkeypatch.setattr("webu.google_hub.manager.requests.get", _fake_get)

    with TestClient(create_google_hub_server()) as client:
        resp = client.get("/search", params={"q": "bilibili", "num": 5})
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert "hub search failed across 2 backend(s)" in detail
        assert "space3 timeout" in detail
        assert "space4 timeout" in detail
        assert "HTTPSConnectionPool" not in detail


def test_hub_search_requires_real_submit_click():
    with pytest.raises(PreventUpdate):
        _resolve_search_state(0, "OpenAI news", "", lambda *_args: {"success": True})

    result = _resolve_search_state(
        1,
        "OpenAI news",
        "space1",
        lambda query, num, lang, backend: {
            "success": True,
            "query": query,
            "results": [],
            "result_count": 0,
            "selection_mode": "manual",
            "backend": backend,
        },
    )
    assert result["status"] == "ok"
    assert result["backend"] == "space1"


def test_sanitize_hub_search_error_scrubs_legacy_timeout_string():
    message = (
        "all hub backends failed: HTTPSConnectionPool(host='owner-b-space4.hf.space', "
        "port=443): Max retries exceeded with url: /search?q=test "
        "(Caused by ReadTimeoutError(\"HTTPSConnectionPool(host='owner-b-space4.hf.space', "
        'port=443): Read timed out. (read timeout=60)"))'
    )
    sanitized = sanitize_hub_search_error(message)
    assert sanitized == (
        "hub search failed across available backends: timeout. "
        "Try again or pin another healthy instance."
    )


def test_resolve_search_state_sanitizes_provider_exception():
    result = _resolve_search_state(
        1,
        "OpenAI news",
        "",
        lambda *_args: (_ for _ in ()).throw(
            RuntimeError(
                "all hub backends failed: HTTPSConnectionPool(host='owner-b-space4.hf.space', port=443): Read timed out."
            )
        ),
    )
    assert result["status"] == "error"
    assert "timeout" in result["error"]
    assert "HTTPSConnectionPool" not in result["error"]


def test_hub_panel_sanitizes_stale_search_state_error():
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
            "successful_requests": 0,
            "failed_requests": 1,
            "success_rate": 0.0,
            "avg_latency_ms": 100.0,
            "median_latency_ms": 100.0,
            "recent_latency_ms": 100.0,
            "last_latency_ms": 100.0,
            "history": [],
            "request_log": [],
        },
        "backends": [],
    }
    body = build_google_hub_panel_body(
        snapshot,
        auth_unlocked=True,
        admin_token_configured=True,
        page=1,
        page_size=10,
        search_state={
            "status": "error",
            "query": "test",
            "backend": "",
            "result": {},
            "error": "all hub backends failed: HTTPSConnectionPool(host='owner-b-space4.hf.space', port=443): Read timed out.",
        },
    )
    text_values = _collect_text(body)
    assert any("hub search failed" in value for value in text_values)
    assert not any("HTTPSConnectionPool" in value for value in text_values)


def test_hub_panel_shows_pending_search_feedback():
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
            "accepted_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "success_rate": 0.0,
            "avg_latency_ms": 0.0,
            "median_latency_ms": 0.0,
            "recent_latency_ms": 0.0,
            "last_latency_ms": 0.0,
            "history": [],
            "request_log": [],
        },
        "backends": [],
    }
    body = build_google_hub_panel_body(
        snapshot,
        auth_unlocked=True,
        admin_token_configured=True,
        page=1,
        page_size=10,
        search_state={
            "request_id": 2,
            "status": "pending",
            "query": "OpenAI news",
            "backend": "",
            "result": {},
            "error": "",
        },
        control_state={"status": "ok", "message": "start requested for 4 HF space(s)"},
    )
    text_values = _collect_text(body)
    assert "Submitted. Searching across hub routing..." in text_values
    assert "Searching for OpenAI news..." in text_values
    assert "start requested for 4 HF space(s)" not in text_values


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


def test_hub_search_can_pin_specific_healthy_backend(monkeypatch, tmp_path):
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
        if url == "https://owner-space1.hf.space/search":
            return _Response(
                200,
                {
                    "success": True,
                    "query": params["q"],
                    "results": [{"title": "Pinned", "url": "https://example.org"}],
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
            "/search",
            params={"q": "OpenAI news", "num": 5, "lang": "en", "backend": "space1"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["backend"] == "space1"
        assert payload["requested_backend"] == "space1"
        assert payload["selection_mode"] == "manual"


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


def test_hub_health_refresh_resolves_ipv4_for_healthy_hf_backend(monkeypatch):
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
                name="space1",
                kind="hf-space",
                base_url="https://owner-space1.hf.space",
                enabled=True,
                weight=1,
                space_name="owner/space1",
            )
        ],
        project_root="/tmp",
        config_dir="/tmp/configs",
    )

    def _fake_get(url, timeout=None):
        assert url == "https://owner-space1.hf.space/health"
        return _Response(200, {"status": "ok"})

    monkeypatch.setattr("webu.google_hub.manager.requests.get", _fake_get)
    monkeypatch.setattr(
        "webu.google_hub.manager.socket.gethostbyname",
        lambda hostname: "10.20.30.40",
    )

    manager = GoogleHubManager(settings)
    snapshot = asyncio.run(manager.refresh_backend_health("space1"))

    assert snapshot["healthy"] is True
    assert snapshot["resolved_ipv4"] == "10.20.30.40"


def test_hub_control_backend_toggle_start_for_paused_space(monkeypatch):
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
                name="space1",
                kind="hf-space",
                base_url="https://owner-space1.hf.space",
                enabled=True,
                weight=1,
                space_name="owner/space1",
            )
        ],
        project_root="/tmp",
        config_dir="/tmp/configs",
    )

    class _Runtime:
        def __init__(self, stage):
            self.stage = type("_Stage", (), {"value": stage})()
            self.sleep_time = 3600

    class _FakeApi:
        def __init__(self, token=None):
            self.token = token

        def get_space_runtime(self, repo_id, token=None):
            assert repo_id == "owner/space1"
            return _Runtime("PAUSED")

        def restart_space(self, repo_id, token=None, factory_reboot=False):
            assert repo_id == "owner/space1"
            assert factory_reboot is False
            return _Runtime("RUNNING")

    monkeypatch.setattr("webu.google_hub.manager.HfApi", _FakeApi)
    monkeypatch.setattr(
        "webu.google_hub.manager.resolve_hf_space_settings",
        lambda space_name: type(
            "_Settings",
            (),
            {
                "repo_id": space_name,
                "hf_token": "hf-token",
                "space_host": "https://owner-space1.hf.space",
            },
        )(),
    )
    monkeypatch.setattr(
        "webu.google_hub.manager.requests.get",
        lambda url, timeout=None: _Response(200, {"status": "ok"}),
    )
    monkeypatch.setattr(
        "webu.google_hub.manager.socket.gethostbyname",
        lambda hostname: "10.20.30.40",
    )

    manager = GoogleHubManager(settings)
    result = asyncio.run(manager.control_backend("space1", "toggle"))

    assert result["action"] == "start"
    assert result["backend"] == "space1"
    assert result["snapshot"]["runtime_stage"] == "RUNNING"


def test_sanitize_hf_control_error_scrubs_network_failure():
    assert sanitize_hf_control_error("[Errno 101] Network is unreachable") == (
        "HF control request failed: network unreachable. Retry later or switch the control endpoint."
    )


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
                "base_url": "http://127.0.0.1:18200",
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
                "kind": "hf-space",
                "base_url": "https://owner-space.hf.space",
                "resolved_ipv4": "10.20.30.40",
                "runtime_stage": "RUNNING",
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
        search_state={
            "status": "ok",
            "query": "OpenAI news",
            "backend": "remote",
            "result": {
                "query": "OpenAI news",
                "backend": "remote",
                "selection_mode": "manual",
                "result_count": 1,
                "total_results_text": "1 result",
                "has_captcha": False,
                "results": [
                    {
                        "title": "OpenAI news headline",
                        "url": "https://example.com/openai",
                        "snippet": "short snippet",
                        "position": 1,
                    }
                ],
            },
            "error": "",
        },
    )
    class_names = _collect_class_names(body)
    text_values = _collect_text(body)
    ids = _collect_ids(body)
    section_titles = [
        component.children
        for component in _collect_components_by_class(body, "dash-section-title")
    ]
    collapse_icons = _collect_components_by_class(body, "dash-collapse-icon")
    search_input = _find_component_by_id(body, "google-hub-panel-search-query")
    assert any("dash-strip-card" in value for value in class_names)
    assert "UPTIME" in text_values
    assert "1h 0m 0s" in text_values
    assert "disabled" in text_values
    assert "10.20.30.40" in text_values
    assert "127.0.0.1" not in text_values
    assert "OpenAI news headline | short snippet | example.com" in text_values
    assert "1/1 HEALTHY" in text_values
    assert "google-hub-panel-search-query" in ids
    assert isinstance(search_input, dcc.Textarea)
    assert "Start All" in text_values
    assert "Stop All" in text_values
    assert "Restart All" in text_values
    assert "Rebuild All" in text_values
    assert "Squash All" in text_values
    assert "Restart" in text_values
    assert "dash-action-row dash-action-row-compact" in class_names
    assert any(
        isinstance(component, html.Details)
        for component in _collect_components_by_class(body, "dash-collapse")
    )
    assert "Search" in section_titles
    assert "Search" in text_values
    assert "Results" in text_values
    assert "Results · 1" not in text_values
    assert "HF controls" not in text_values
    assert len(collapse_icons) >= 2
    assert "Use auto routing for the best healthy instance" not in text_values
    assert "{'type': 'google-hub-panel-history-page-button', 'page': 1}" in ids

    search_details = [
        detail
        for detail in _collect_details_with_class_token(body, "dash-collapse")
        if _detail_contains_component_id(detail, "google-hub-panel-search-query")
    ]
    section_details = _collect_details_with_class_token(body, "dash-section-collapse")
    assert search_details and search_details[0].open is False
    assert search_details[0].__dict__["data-webu-collapse-key"] == "google-hub-search"
    assert search_details[0].__dict__["data-webu-collapse-open"] == "0"
    keyed_details = {
        str(detail.__dict__.get("data-webu-collapse-key", "")): detail
        for detail in section_details
    }
    assert keyed_details["google-hub-controls"].open is False
    assert (
        keyed_details["google-hub-controls"].__dict__["data-webu-collapse-open"] == "0"
    )
    assert keyed_details["google-hub-trends"].open is True
    assert keyed_details["google-hub-trends"].__dict__["data-webu-collapse-open"] == "1"
    assert keyed_details["google-hub-requests"].open is True
    assert (
        keyed_details["google-hub-requests"].__dict__["data-webu-collapse-open"] == "1"
    )


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
    assert "Unlock access to view request history." in text_values


def test_hub_panel_hides_strategy_note_and_uses_two_line_search_box():
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
            "request_log": [],
        },
        "backends": [],
    }

    body = build_google_hub_panel_body(
        snapshot,
        auth_unlocked=True,
        admin_token_configured=True,
        page=1,
        page_size=10,
    )
    text_values = _collect_text(body)
    search_input = _find_component_by_id(body, "google-hub-panel-search-query")

    assert "Strategy adaptive" not in text_values
    assert isinstance(search_input, dcc.Textarea)
    assert search_input.rows == 2
    assert "recent / mid" not in text_values


def test_hub_instance_cards_place_disabled_last_and_dim_them():
    cards = build_backend_instance_cards(
        [
            {
                "name": "local",
                "kind": "google-api",
                "base_url": "http://127.0.0.1:18200",
                "healthy": False,
                "enabled": False,
                "disabled_reason": "excluded by hub settings",
                "request_count": 5,
                "success_rate": 100.0,
                "avg_request_latency_ms": 110.0,
            },
            {
                "name": "space2",
                "kind": "hf-space",
                "space_name": "owner/space2",
                "base_url": "https://owner-space2.hf.space",
                "resolved_ipv4": "10.20.30.41",
                "healthy": False,
                "enabled": True,
                "disabled_reason": "",
                "request_count": 1,
                "success_rate": 0.0,
                "avg_request_latency_ms": 420.0,
            },
            {
                "name": "space1",
                "kind": "hf-space",
                "space_name": "owner/space1",
                "base_url": "https://owner-space1.hf.space",
                "resolved_ipv4": "10.20.30.40",
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

    assert instance_names == ["owner/space1", "owner/space2", "local"]
    assert cards[-1].style["opacity"] == 0.58
    assert "10.20.30.40" in _collect_text(cards[0])
    assert "10.20.30.41" not in _collect_text(cards[1])
    assert "127.0.0.1" not in _collect_text(cards[-1])
    assert "owner/space1" not in _collect_text(cards[0])[1:]
    assert "excluded by hub settings" not in _collect_text(cards[-1])
    assert "google-api" not in _collect_text(cards[-1])


def test_hub_panel_index_includes_persistent_collapse_script():
    from webu.fastapis.dashboard_ui import create_dash_app

    app = create_dash_app(
        name="test-google-hub-panel",
        title="Google Hub Panel",
        panel_path=DEFAULT_GOOGLE_API_PANEL_PATH,
    )

    assert "webu-collapse:" in app.index_string
    assert "details[data-webu-collapse-key]" in app.index_string


def test_hub_panel_accepts_env_admin_token_alias(monkeypatch):
    monkeypatch.setenv("WEBU_HUB_ADMIN_TOKEN", "hub-token")
    monkeypatch.setenv("WEBU_ADMIN_TOKEN", "shared-token")
    monkeypatch.setattr(
        "webu.google_hub.panel.resolve_google_docker_settings",
        lambda: type("_Settings", (), {"admin_token": "docker-token"})(),
    )

    assert _accepted_admin_tokens("panel-token") == {
        "panel-token",
        "docker-token",
        "hub-token",
        "shared-token",
    }


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
