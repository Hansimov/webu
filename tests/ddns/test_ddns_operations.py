from __future__ import annotations

from pathlib import Path

from webu.ddns.operations import (
    _build_ddns_go_config_payload,
    _render_ddns_service_unit,
    config_init,
    target_delete,
    target_prepare,
    target_run_once,
    target_upsert,
)


def test_config_init_writes_project_config(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("WEBU_CONFIG_DIR", raising=False)

    config_path = config_init(force=True)

    assert config_path == str(tmp_path / "configs" / "ddns.json")
    assert (tmp_path / "configs" / "ddns.json").exists()


def test_build_ddns_go_config_payload_uses_canonical_lowercase_keys():
    payload = _build_ddns_go_config_payload(
        access_key_id="ak-test",
        access_key_secret="sk-test",
        domain="pool.origin-pool.example.com?Name=origin-alpha",
        ttl=600,
        ipv6_source_mode="cmd",
        target_ipv6="2001:db8::10",
        ipv6_url="https://api6.ipify.org",
    )

    assert payload["name"] == "aliesa-origin-pool-ipv6"
    assert payload["dns"]["name"] == "aliesa"
    assert payload["dns"]["id"] == "ak-test"
    assert payload["ipv6"]["gettype"] == "cmd"
    assert payload["ipv6"]["cmd"] == "printf '%s\\n' '2001:db8::10'"
    assert payload["httpinterface"] == ""


def test_target_upsert_and_prepare_write_yaml(monkeypatch, tmp_path):
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    config_dir = project_root / "configs"
    config_dir.mkdir()
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    target_upsert(
        name="example-origin-pool",
        site_name="example.com",
        pool_name="example-origin-pool",
        origin_name="origin-alpha",
        save_config=True,
    )

    monkeypatch.setattr(
        "webu.ddns.operations.load_ali_esa_config",
        lambda validate=False: {
            "default_public_origin_ipv6": "2001:db8::10",
            "aliyun_access_id": "ak-test",
            "aliyun_access_secret": "sk-test",
            "sites": [{"site_name": "example.com", "public_origin_address": ""}],
        },
    )
    monkeypatch.setattr(
        "webu.ddns.operations.resolve_credentials",
        lambda payload: {
            "aliyun_access_id": "ak-test",
            "aliyun_access_secret": "sk-test",
            "region_id": "cn-hangzhou",
        },
    )

    class FakeClient:
        def get_site(self, *, site_name):
            assert site_name == "example.com"
            return {"SiteId": 123, "SiteName": site_name}

        def list_origin_pools(
            self, *, site_id, name=None, match_type=None, order_by=None, page_size=500
        ):
            assert site_id == 123
            assert name == "example-origin-pool"
            return []

        def create_origin_pool(self, *, site_id, name, enabled, origins):
            assert site_id == 123
            assert name == "example-origin-pool"
            assert enabled is True
            assert origins[0]["Name"] == "origin-alpha"
            return {"Id": 10}

        def get_origin_pool(self, *, site_id, origin_pool_id):
            return {
                "Id": 10,
                "Name": "example-origin-pool",
                "RecordName": "example-origin-pool.origin-pool.example.com",
                "Origins": [
                    {
                        "Name": "origin-alpha",
                        "Address": "2001:db8::10",
                    }
                ],
            }

    monkeypatch.setattr(
        "webu.ddns.operations._build_esa_client", lambda payload: FakeClient()
    )

    result = target_prepare(name="example-origin-pool", seed_existing=False)

    config_path = Path(result["ddns_go_config_path"])
    assert config_path.exists()
    rendered = config_path.read_text(encoding="utf-8")
    assert "dns:" in rendered
    assert "gettype: cmd" in rendered
    assert "example-origin-pool.origin-pool.example.com?Name=origin-alpha" in rendered


def test_target_delete_removes_existing_target(monkeypatch, tmp_path):
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    config_dir = project_root / "configs"
    config_dir.mkdir()
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    config_init(force=True)
    target_upsert(
        name="example-origin-pool",
        site_name="example.com",
        pool_name="example-origin-pool",
        origin_name="origin-alpha",
        save_config=True,
    )
    target_upsert(
        name="keep-origin-pool",
        site_name="example.com",
        pool_name="keep-origin-pool",
        origin_name="origin-alpha",
        save_config=True,
    )

    result = target_delete(name="example-origin-pool")

    assert result["target"]["name"] == "example-origin-pool"
    assert result["remaining_count"] == 1


def test_target_prepare_can_seed_direct_record(monkeypatch, tmp_path):
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    config_dir = project_root / "configs"
    config_dir.mkdir()
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    target_upsert(
        name="example-direct-record",
        provider="aliesa-record",
        site_name="example.com",
        record_name="home.example.com",
        save_config=True,
    )

    monkeypatch.setattr(
        "webu.ddns.operations.load_ali_esa_config",
        lambda validate=False: {
            "default_public_origin_ipv6": "2001:db8::10",
            "aliyun_access_id": "ak-test",
            "aliyun_access_secret": "sk-test",
            "sites": [{"site_name": "example.com", "public_origin_address": ""}],
        },
    )
    monkeypatch.setattr(
        "webu.ddns.operations.resolve_credentials",
        lambda payload: {
            "aliyun_access_id": "ak-test",
            "aliyun_access_secret": "sk-test",
            "region_id": "cn-hangzhou",
        },
    )

    class FakeClient:
        def __init__(self):
            self.value = "2001:db8::20"
            self.proxied = True

        def get_site(self, *, site_name):
            assert site_name == "example.com"
            return {"SiteId": 123, "SiteName": site_name}

        def list_records(
            self, *, site_id, record_name=None, record_type=None, page_size=500
        ):
            assert site_id == 123
            assert record_name == "home.example.com"
            assert record_type == "A/AAAA"
            return [
                {
                    "RecordId": 11,
                    "RecordName": "home.example.com",
                    "RecordType": "A/AAAA",
                    "Data": {"Value": self.value},
                    "Proxied": self.proxied,
                }
            ]

        def update_record(
            self,
            *,
            record_id,
            record_type,
            ttl,
            data_value,
            proxied=None,
            **kwargs,
        ):
            assert record_id == 11
            assert record_type == "A/AAAA"
            assert ttl == 600
            assert proxied is False
            self.value = data_value
            self.proxied = proxied
            return {"RecordId": record_id}

    fake_client = FakeClient()
    monkeypatch.setattr(
        "webu.ddns.operations._build_esa_client", lambda payload: fake_client
    )

    result = target_prepare(name="example-direct-record", seed_existing=True)

    config_path = Path(result["ddns_go_config_path"])
    assert config_path.exists()
    rendered = config_path.read_text(encoding="utf-8")
    assert "home.example.com" in rendered
    assert result["record_action"] == "seeded"
    assert result["current_record_value"] == "2001:db8::1"


def test_target_prepare_can_create_direct_record_when_absent(monkeypatch, tmp_path):
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    config_dir = project_root / "configs"
    config_dir.mkdir()
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    target_upsert(
        name="example-direct-record",
        provider="aliesa-record",
        site_name="example.com",
        record_name="home.example.com",
        save_config=True,
    )

    monkeypatch.setattr(
        "webu.ddns.operations.load_ali_esa_config",
        lambda validate=False: {
            "default_public_origin_ipv6": "2001:db8::10",
            "aliyun_access_id": "ak-test",
            "aliyun_access_secret": "sk-test",
            "sites": [{"site_name": "example.com", "public_origin_address": ""}],
        },
    )
    monkeypatch.setattr(
        "webu.ddns.operations.resolve_credentials",
        lambda payload: {
            "aliyun_access_id": "ak-test",
            "aliyun_access_secret": "sk-test",
            "region_id": "cn-hangzhou",
        },
    )

    class FakeClient:
        def __init__(self):
            self.record: dict[str, object] | None = None

        def get_site(self, *, site_name):
            assert site_name == "example.com"
            return {"SiteId": 123, "SiteName": site_name}

        def list_records(
            self, *, site_id, record_name=None, record_type=None, page_size=500
        ):
            assert site_id == 123
            assert record_name == "home.example.com"
            assert record_type == "A/AAAA"
            return [self.record] if isinstance(self.record, dict) else []

        def create_record(
            self,
            *,
            site_id,
            record_name,
            record_type,
            ttl,
            data_value,
            proxied=None,
            **kwargs,
        ):
            assert site_id == 123
            assert record_name == "home.example.com"
            assert record_type == "A/AAAA"
            assert ttl == 600
            assert data_value == "2001:db8::1"
            assert proxied is False
            self.record = {
                "RecordId": 11,
                "RecordName": record_name,
                "RecordType": record_type,
                "Data": {"Value": data_value},
                "Proxied": proxied,
            }
            return {"RecordId": 11}

    fake_client = FakeClient()
    monkeypatch.setattr(
        "webu.ddns.operations._build_esa_client", lambda payload: fake_client
    )

    result = target_prepare(name="example-direct-record", seed_existing=True)

    assert result["record_action"] == "seed-created"
    assert result["current_record_value"] == "2001:db8::1"


def test_target_run_once_verifies_origin_pool_after_timeout(monkeypatch, tmp_path):
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    config_dir = project_root / "configs"
    config_dir.mkdir()
    binary_path = project_root / "debugs" / "ddns-go" / "bin"
    binary_path.mkdir(parents=True)
    (binary_path / "ddns-go").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    target_upsert(
        name="example-origin-pool",
        site_name="example.com",
        pool_name="example-origin-pool",
        origin_name="origin-alpha",
        binary_path="debugs/ddns-go/bin/ddns-go",
        save_config=True,
    )

    monkeypatch.setattr(
        "webu.ddns.operations.load_ali_esa_config",
        lambda validate=False: {
            "default_public_origin_ipv6": "2001:db8::10",
            "aliyun_access_id": "ak-test",
            "aliyun_access_secret": "sk-test",
            "sites": [{"site_name": "example.com", "public_origin_address": ""}],
        },
    )
    monkeypatch.setattr(
        "webu.ddns.operations.resolve_credentials",
        lambda payload: {
            "aliyun_access_id": "ak-test",
            "aliyun_access_secret": "sk-test",
            "region_id": "cn-hangzhou",
        },
    )

    class FakeClient:
        def get_site(self, *, site_name):
            return {"SiteId": 123, "SiteName": site_name}

        def list_origin_pools(
            self, *, site_id, name=None, match_type=None, order_by=None, page_size=500
        ):
            return [{"Id": 10, "Name": "example-origin-pool"}]

        def get_origin_pool(self, *, site_id, origin_pool_id):
            return {
                "Id": 10,
                "Name": "example-origin-pool",
                "RecordName": "example-origin-pool.origin-pool.example.com",
                "Origins": [{"Name": "origin-alpha", "Address": "2001:db8::10"}],
            }

        def update_origin_pool(self, *, site_id, origin_pool_id, enabled, origins):
            return {"Id": origin_pool_id}

    monkeypatch.setattr(
        "webu.ddns.operations._build_esa_client", lambda payload: FakeClient()
    )

    def fake_run(
        command, check=False, capture_output=False, text=False, cwd=None, timeout=None
    ):
        import subprocess

        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output="Updated domain example-origin-pool.origin-pool.example.com successfully!",
            stderr="",
        )

    monkeypatch.setattr("webu.ddns.operations.subprocess.run", fake_run)

    result = target_run_once(name="example-origin-pool", timeout_seconds=3)

    assert result["verified"] is True
    assert result["timed_out"] is True
    assert result["log_contains_update"] is True


def test_target_run_once_verifies_direct_record_after_timeout(monkeypatch, tmp_path):
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    config_dir = project_root / "configs"
    config_dir.mkdir()
    binary_path = project_root / "debugs" / "ddns-go" / "bin"
    binary_path.mkdir(parents=True)
    (binary_path / "ddns-go").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    target_upsert(
        name="example-direct-record",
        provider="aliesa-record",
        site_name="example.com",
        record_name="home.example.com",
        binary_path="debugs/ddns-go/bin/ddns-go",
        save_config=True,
    )

    monkeypatch.setattr(
        "webu.ddns.operations.load_ali_esa_config",
        lambda validate=False: {
            "default_public_origin_ipv6": "2001:db8::10",
            "aliyun_access_id": "ak-test",
            "aliyun_access_secret": "sk-test",
            "sites": [{"site_name": "example.com", "public_origin_address": ""}],
        },
    )
    monkeypatch.setattr(
        "webu.ddns.operations.resolve_credentials",
        lambda payload: {
            "aliyun_access_id": "ak-test",
            "aliyun_access_secret": "sk-test",
            "region_id": "cn-hangzhou",
        },
    )

    class FakeClient:
        def get_site(self, *, site_name):
            return {"SiteId": 123, "SiteName": site_name}

        def list_records(
            self, *, site_id, record_name=None, record_type=None, page_size=500
        ):
            return [
                {
                    "RecordId": 11,
                    "RecordName": "home.example.com",
                    "RecordType": "A/AAAA",
                    "Data": {"Value": "2001:db8::10"},
                }
            ]

    monkeypatch.setattr(
        "webu.ddns.operations._build_esa_client", lambda payload: FakeClient()
    )

    def fake_run(
        command, check=False, capture_output=False, text=False, cwd=None, timeout=None
    ):
        import subprocess

        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output="Added domain home.example.com successfully!",
            stderr="",
        )

    monkeypatch.setattr("webu.ddns.operations.subprocess.run", fake_run)

    result = target_run_once(name="example-direct-record", timeout_seconds=3)

    assert result["verified"] is True
    assert result["current_record_value"] == "2001:db8::10"
    assert result["timed_out"] is True
    assert result["log_contains_update"] is True


def test_render_ddns_service_unit_contains_binary_and_config_path():
    from webu.ddns.schema import DdnsTargetConfig

    target = DdnsTargetConfig(
        name="example-origin-pool",
        provider="aliesa-origin-pool",
        site_name="example.com",
        pool_name="example-origin-pool",
        origin_name="origin-alpha",
        record_name="",
        enabled=True,
        target_ipv6="",
        seed_ipv6="2001:db8::1",
        ipv6_source_mode="cmd",
        ipv6_url="https://api6.ipify.org",
        ttl=600,
        binary_path="",
        config_path="",
        run_interval_seconds=300,
        cache_times=1,
        service_name="",
        raw={},
    )

    unit = _render_ddns_service_unit(
        target=target,
        binary_path=Path("/opt/ddns-go/bin/ddns-go"),
        config_path=Path("/srv/webu/debugs/ddns-go/example-origin-pool.yaml"),
    )

    assert (
        "ExecStart=/opt/ddns-go/bin/ddns-go -noweb -c /srv/webu/debugs/ddns-go/example-origin-pool.yaml -f 300 -cacheTimes 1"
        in unit
    )
    assert "Description=wdns target example-origin-pool" in unit
