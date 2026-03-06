import json

from pathlib import Path

from webu.google_hub import resolve_google_hub_settings
from webu.runtime_settings import (
    load_json_config,
    resolve_captcha_vlm_settings,
    resolve_gemini_default_proxy,
    resolve_google_api_settings,
    resolve_google_api_service_profile,
    resolve_hf_space_settings,
    resolve_proxy_api_fetch_proxy,
    resolve_searches_chrome_proxy,
)


def test_google_api_settings_disable_proxy_in_hf_space(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("WEBU_RUNTIME_ENV", "hf-space")

    settings = resolve_google_api_settings()
    assert settings.runtime_env == "hf-space"
    assert settings.proxies == []


def test_google_api_settings_rewrite_local_proxy_for_docker(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "proxies.json").write_text(
        json.dumps(
            {
                "google_api": {
                    "proxies": [{"url": "http://127.0.0.1:11111", "name": "local"}]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("WEBU_RUNTIME_ENV", "docker")

    settings = resolve_google_api_settings()
    assert settings.proxies[0]["url"] == "http://host.docker.internal:11111"


def test_google_api_service_profile_resolves_by_type(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "google_api.json").write_text(
        json.dumps(
            {
                "services": [
                    {"url": "http://127.0.0.1:18200", "type": "local", "api_token": ""},
                    {"type": "hf-space", "api_token": "hf-token"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "hf_spaces.json").write_text(
        json.dumps([{"space": "owner/demo-space", "hf_token": "hf_demo"}]),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    profile = resolve_google_api_service_profile(
        runtime_env="hf-space", service_type="hf-space"
    )
    assert profile["url"] == "https://owner-demo-space.hf.space"
    assert profile["type"] == "hf-space"
    assert profile["api_token"] == "hf-token"


def test_proxy_helpers_read_local_proxy_config(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "proxies.json").write_text(
        json.dumps(
            {
                "gemini": {"default_proxy": "http://127.0.0.1:11119"},
                "proxy_api": {"fetch_proxy": "http://127.0.0.1:11119"},
                "searches": {"chrome_proxy": "http://127.0.0.1:11111"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    assert resolve_gemini_default_proxy() == "http://127.0.0.1:11119"
    assert resolve_proxy_api_fetch_proxy() == "http://127.0.0.1:11119"
    assert resolve_searches_chrome_proxy() == "http://127.0.0.1:11111"


def test_captcha_settings_merge_llm_profile(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "llms.json").write_text(
        json.dumps(
            {
                "vlm_profile": {
                    "endpoint": "https://example.com/v1/chat/completions",
                    "api_key": "secret",
                    "model": "qwen-vl",
                }
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "captcha.json").write_text(
        json.dumps({"vlm": {"profile": "vlm_profile"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    settings = resolve_captcha_vlm_settings()
    assert settings.endpoint == "https://example.com/v1/chat/completions"
    assert settings.api_key == "secret"
    assert settings.model == "qwen-vl"


def test_hf_space_settings_reads_token(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "hf_spaces.json").write_text(
        json.dumps([{"space": "owner/demo", "hf_token": "hf_demo"}]),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    settings = resolve_hf_space_settings("owner/demo")
    assert settings.hf_token == "hf_demo"
    assert settings.space_host == "https://owner-demo.hf.space"


def test_load_json_config_validates_known_configs(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "google_api.json").write_text(
        json.dumps(
            {"host": "0.0.0.0", "port": "18200", "proxy_mode": "auto", "services": []}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    try:
        load_json_config("google_api")
        assert False, "expected validation error"
    except ValueError as exc:
        assert "Invalid config 'google_api'" in str(exc)
        assert "expected integer" in str(exc)


def test_load_json_config_allows_disabling_validation(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "google_api.json").write_text(
        json.dumps(
            {"host": "0.0.0.0", "port": "18200", "proxy_mode": "auto", "services": []}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("WEBU_VALIDATE_CONFIGS", "false")

    payload = load_json_config("google_api")
    assert payload["port"] == "18200"


def test_google_api_config_allows_runtime_defaults(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "google_api.json").write_text(
        json.dumps(
            {"services": [{"type": "local", "api_token": "local-search-token"}]}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    payload = load_json_config("google_api")
    assert payload["services"][0]["api_token"] == "local-search-token"


def test_google_hub_settings_resolve_backends(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
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
        json.dumps({"admin_token": "admin-token"}), encoding="utf-8"
    )
    (config_dir / "hf_spaces.json").write_text(
        json.dumps(
            [
                {
                    "space": "owner/space1",
                    "hf_token": "hf_demo",
                    "enabled": True,
                    "weight": 1,
                },
                {
                    "space": "owner/space2",
                    "hf_token": "hf_demo",
                    "enabled": True,
                    "weight": 2,
                },
            ]
        ),
        encoding="utf-8",
    )
    (config_dir / "google_hub.json").write_text(
        json.dumps(
            {
                "port": 18100,
                "backends": [
                    {
                        "name": "local-google-api",
                        "kind": "local-google-api",
                        "base_url": "http://127.0.0.1:18200",
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
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    settings = resolve_google_hub_settings()
    assert settings.port == 18100
    assert [backend.name for backend in settings.backends] == [
        "local-google-api",
        "space2",
    ]
    assert settings.backends[1].base_url == "https://owner-space2.hf.space"


def test_google_hub_settings_normalize_local_backend_for_docker(monkeypatch, tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
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
        json.dumps({"admin_token": "admin-token"}), encoding="utf-8"
    )
    (config_dir / "google_hub.json").write_text(
        json.dumps(
            {
                "port": 18100,
                "backends": [
                    {
                        "name": "local-google-api",
                        "kind": "local-google-api",
                        "base_url": "http://127.0.0.1:18200",
                        "weight": 2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("WEBU_RUNTIME_ENV", "docker")

    settings = resolve_google_hub_settings()
    assert settings.backends[0].base_url == "http://host.docker.internal:18200"
