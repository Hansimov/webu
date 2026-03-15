import json

from copy import deepcopy
from pathlib import Path

from webu.cf_tunnel.cli import build_parser
from webu.cf_tunnel.operations import (
    apply_tunnel,
    config_init,
    docs_sync,
    migrate_dns_to_cloudflare,
)


def _load_local_cf_tunnel_config() -> dict:
    config_path = Path(__file__).resolve().parents[2] / "configs" / "cf_tunnel.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not payload.get("domains"):
        raise AssertionError("configs/cf_tunnel.json must define at least one domain")
    if not payload.get("cf_tunnels"):
        raise AssertionError("configs/cf_tunnel.json must define at least one tunnel")
    return payload


def _local_domain_name() -> str:
    payload = _load_local_cf_tunnel_config()
    return str(payload["domains"][0]["domain_name"]).strip()


def _local_tunnel_name() -> str:
    payload = _load_local_cf_tunnel_config()
    return str(payload["cf_tunnels"][0]["tunnel_name"]).strip()


def test_parser_supports_dns_and_tunnel_commands():
    parser = build_parser()
    domain_name = _local_domain_name()
    tunnel_name = _local_tunnel_name()

    dns_args = parser.parse_args(
        ["dns-migrate", domain_name, "--cf-token-mode", "auto"]
    )
    tunnel_args = parser.parse_args(
        ["tunnel-apply", "--name", tunnel_name, "--install-service"]
    )
    token_args = parser.parse_args(
        ["token-ensure", "--zone-name", domain_name, "--cf-token-mode", "manual"]
    )

    assert dns_args.domain_name == domain_name
    assert dns_args.cf_token_mode == "auto"
    assert tunnel_args.name == tunnel_name
    assert tunnel_args.install_service is True
    assert token_args.zone_name == domain_name
    assert token_args.cf_token_mode == "manual"


def test_config_init_writes_project_config(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))

    config_path = config_init(force=True)

    assert config_path == str(tmp_path / "configs" / "cf_tunnel.json")
    assert (tmp_path / "configs" / "cf_tunnel.json").exists()


def test_migrate_dns_updates_config(monkeypatch, tmp_path):
    local_payload = deepcopy(_load_local_cf_tunnel_config())
    domain_name = str(local_payload["domains"][0]["domain_name"]).strip()
    zone_name = (
        str(local_payload["domains"][0].get("zone_name", "")).strip() or domain_name
    )

    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    local_payload["cf_api_token"] = "existing-token"
    local_payload["domains"][0]["zone_id"] = ""
    local_payload["domains"][0]["cloudflare_nameservers"] = []
    local_payload["domains"][0]["aliyun_task_no"] = ""
    (config_dir / "cf_tunnel.json").write_text(
        json.dumps(local_payload),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    expected_account_id = str(local_payload["cf_account_id"]).strip()
    expected_access_id = str(local_payload["aliyun_access_id"]).strip()
    expected_access_secret = str(local_payload["aliyun_access_secret"]).strip()

    class _FakeCfClient:
        def __init__(self, api_token):
            self.api_token = api_token

        def ensure_zone(self, *, account_id, zone_name):
            assert account_id == expected_account_id
            assert zone_name == zone_name_expected
            return {"id": "zone-1", "name_servers": ["a.ns", "b.ns"]}

    class _FakeAliyunClient:
        def __init__(self, access_key_id, access_key_secret):
            assert access_key_id == expected_access_id
            assert access_key_secret == expected_access_secret

        def modify_domain_dns(self, *, domain_name, nameservers):
            assert domain_name == expected_domain_name
            assert nameservers == ["a.ns", "b.ns"]
            return "task-1"

        def query_task_details(self, *, task_no, current_page=1, page_size=20):
            assert task_no == "task-1"
            return [{"TaskStatus": "EXECUTE_SUCCESS"}]

    monkeypatch.setattr("webu.cf_tunnel.operations.CloudflareClient", _FakeCfClient)
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.AliyunDomainClient", _FakeAliyunClient
    )

    expected_domain_name = domain_name
    zone_name_expected = zone_name

    result = migrate_dns_to_cloudflare(
        domain_name=domain_name,
        zone_name=zone_name,
        cf_token_mode="auto",
        aliyun_credential_mode="existing",
        save_config=True,
    )

    saved = json.loads((config_dir / "cf_tunnel.json").read_text(encoding="utf-8"))
    assert result["zone_id"] == "zone-1"
    assert saved["domains"][0]["zone_id"] == "zone-1"
    assert saved["domains"][0]["cloudflare_nameservers"] == ["a.ns", "b.ns"]


def test_apply_tunnel_updates_config_without_printing_secret(monkeypatch, tmp_path):
    local_payload = deepcopy(_load_local_cf_tunnel_config())
    tunnel = deepcopy(local_payload["cf_tunnels"][0])
    domain_name = str(tunnel["domain_name"]).strip()
    tunnel_name = str(tunnel["tunnel_name"]).strip()
    zone_name = str(tunnel.get("zone_name", "")).strip() or domain_name

    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    local_payload["cf_api_token"] = "existing-token"
    tunnel["tunnel_id"] = ""
    tunnel["tunnel_token"] = ""
    local_payload["cf_tunnels"] = [tunnel]
    (config_dir / "cf_tunnel.json").write_text(
        json.dumps(local_payload),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    class _FakeCfClient:
        def __init__(self, api_token):
            self.api_token = api_token

        def ensure_zone(self, *, account_id, zone_name):
            return {"id": "zone-1", "name_servers": ["a.ns", "b.ns"]}

        def ensure_tunnel(self, *, account_id, tunnel_name):
            return {"id": "tunnel-1", "token": "secret-token"}

        def get_tunnel_token(self, *, account_id, tunnel_id):
            return "secret-token"

        def put_tunnel_configuration(self, *, account_id, tunnel_id, hostname, service):
            return {"ok": True}

        def upsert_cname_record(self, *, zone_id, hostname, content, proxied=True):
            return {"id": "record-1"}

    monkeypatch.setattr("webu.cf_tunnel.operations.CloudflareClient", _FakeCfClient)

    result = apply_tunnel(
        tunnel_name=tunnel_name,
        apply_all=False,
        install_service=False,
        cf_token_mode="auto",
        save_config=True,
    )

    saved = json.loads((config_dir / "cf_tunnel.json").read_text(encoding="utf-8"))
    assert result[0]["tunnel_id"] == "tunnel-1"
    assert result[0]["tunnel_token_saved"] is True
    assert "tunnel_token" not in result[0]
    assert saved["cf_tunnels"][0]["tunnel_token"] == "secret-token"
    assert result[0]["domain_name"] == domain_name
    assert result[0]["zone_name"] == zone_name


def test_docs_sync_writes_markdown(monkeypatch, tmp_path):
    docs_dir = tmp_path / "docs" / "cf-tunnel"
    docs_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.USAGE_DOC_PATH", docs_dir / "USAGE.md"
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.CONFIGS_DOC_PATH", docs_dir / "CONFIGS.md"
    )

    result = docs_sync()

    assert (docs_dir / "USAGE.md").exists()
    assert (docs_dir / "CONFIGS.md").exists()
    assert result["usage"].endswith("USAGE.md")
