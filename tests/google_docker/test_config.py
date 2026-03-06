import json

from pathlib import Path

from webu.runtime_settings import (
    resolve_captcha_vlm_settings,
    resolve_gemini_default_proxy,
    resolve_google_api_settings,
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
        json.dumps({"google_api": {"proxies": [{"url": "http://127.0.0.1:11111", "name": "local"}]}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("WEBU_RUNTIME_ENV", "docker")

    settings = resolve_google_api_settings()
    assert settings.proxies[0]["url"] == "http://host.docker.internal:11111"


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