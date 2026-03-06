from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from webu.runtime_settings import resolve_google_api_settings, resolve_google_docker_settings
from webu.google_docker.server import create_google_docker_server


def _base_app():
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def _fake_google_search_app(home_mode="swagger"):
    app = _base_app()

    @app.get("/", response_class=HTMLResponse)
    async def root():
        if home_mode == "hidden":
            return "Static workspace content is available. Interactive routes are not published from this path."
        return "swagger-root"

    return app


def test_admin_logs_requires_token(monkeypatch, tmp_path):
    log_path = tmp_path / "service.log"
    log_path.write_text("line-1\nline-2\n", encoding="utf-8")
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_SERVICE_LOG", str(log_path))
    monkeypatch.setenv("WEBU_ADMIN_TOKEN", "secret")

    monkeypatch.setattr(
        "webu.google_docker.server.create_google_search_server",
        lambda settings=None, home_mode="swagger": _fake_google_search_app(home_mode),
    )

    app = create_google_docker_server(
        google_api_settings=resolve_google_api_settings(headless=True),
        docker_settings=resolve_google_docker_settings(),
    )
    client = TestClient(app)

    assert client.get("/admin/logs").status_code == 401
    resp = client.get("/admin/logs", headers={"X-Admin-Token": "secret"})
    assert resp.status_code == 200
    assert "line-2" in resp.json()["content"]


def test_admin_config_masks_token(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_ADMIN_TOKEN", "secret")
    monkeypatch.setattr(
        "webu.google_docker.server.create_google_search_server",
        lambda settings=None, home_mode="swagger": _fake_google_search_app(home_mode),
    )

    app = create_google_docker_server(
        google_api_settings=resolve_google_api_settings(headless=True),
        docker_settings=resolve_google_docker_settings(),
    )
    client = TestClient(app)
    resp = client.get("/admin/config", headers={"X-Admin-Token": "secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["admin_token_configured"] is True


def test_hf_space_root_page_is_hidden(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_RUNTIME_ENV", "hf-space")
    monkeypatch.setattr(
        "webu.google_docker.server.create_google_search_server",
        lambda settings=None, home_mode="swagger": _fake_google_search_app(home_mode),
    )
    app = create_google_docker_server(
        google_api_settings=resolve_google_api_settings(headless=True),
        docker_settings=resolve_google_docker_settings(),
    )
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Static workspace content is available" in resp.text