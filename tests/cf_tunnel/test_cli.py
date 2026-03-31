import json

from copy import deepcopy
from pathlib import Path
from subprocess import CompletedProcess

from webu.cf_tunnel.cli import build_parser
from webu.cf_tunnel.operations import (
    _render_cloudflared_tunnel_service_unit,
    access_diagnose,
    apply_tunnel,
    client_canary_bundle,
    client_override_plan,
    client_report_summary,
    client_report_template,
    config_init,
    docs_sync,
    edge_trace,
    migrate_dns_to_cloudflare,
    page_audit,
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
        [
            "tunnel-apply",
            "--name",
            tunnel_name,
            "--domain",
            domain_name,
            "--local-url",
            "http://127.0.0.1:21002",
            "--cloudflared-run-json",
            '{"protocol":"http2"}',
            "--install-service",
        ]
    )
    token_args = parser.parse_args(
        ["token-ensure", "--zone-name", domain_name, "--cf-token-mode", "manual"]
    )
    diagnose_args = parser.parse_args(["access-diagnose", "--name", tunnel_name])
    page_audit_args = parser.parse_args(["page-audit", "--name", tunnel_name])
    edge_trace_args = parser.parse_args(["edge-trace", "--name", tunnel_name])
    client_override_args = parser.parse_args(
        ["client-override-plan", "--name", tunnel_name, "--prefer-family", "ipv4"]
    )
    client_bundle_args = parser.parse_args(
        ["client-canary-bundle", "--name", tunnel_name, "--prefer-family", "ipv4"]
    )
    client_template_args = parser.parse_args(
        ["client-report-template", "--name", tunnel_name, "--prefer-family", "ipv4"]
    )
    client_summary_args = parser.parse_args(
        ["client-report-summary", "reports/client-canary.json"]
    )

    assert dns_args.domain_name == domain_name
    assert dns_args.cf_token_mode == "auto"
    assert tunnel_args.name == tunnel_name
    assert tunnel_args.domain_name == domain_name
    assert tunnel_args.local_url == "http://127.0.0.1:21002"
    assert tunnel_args.cloudflared_run_json == '{"protocol":"http2"}'
    assert tunnel_args.install_service is True
    assert token_args.zone_name == domain_name
    assert token_args.cf_token_mode == "manual"
    assert diagnose_args.name == tunnel_name
    assert page_audit_args.name == tunnel_name
    assert edge_trace_args.name == tunnel_name
    assert client_override_args.name == tunnel_name
    assert client_override_args.prefer_family == "ipv4"
    assert client_bundle_args.name == tunnel_name
    assert client_template_args.name == tunnel_name
    assert client_summary_args.report_file == "reports/client-canary.json"


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

        def put_tunnel_configuration(
            self,
            *,
            account_id,
            tunnel_id,
            hostname,
            service,
            origin_request=None,
        ):
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


def test_apply_tunnel_pushes_origin_request_settings(monkeypatch, tmp_path):
    local_payload = deepcopy(_load_local_cf_tunnel_config())
    tunnel = deepcopy(local_payload["cf_tunnels"][0])
    tunnel_name = str(tunnel["tunnel_name"]).strip()

    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    local_payload["cf_api_token"] = "existing-token"
    tunnel["tunnel_id"] = ""
    tunnel["tunnel_token"] = ""
    tunnel["origin_request"] = {
        "connect_timeout": 5,
        "keep_alive_connections": 256,
        "keep_alive_timeout": 120,
    }
    local_payload["cf_tunnels"] = [tunnel]
    (config_dir / "cf_tunnel.json").write_text(
        json.dumps(local_payload),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    recorded = {}

    class _FakeCfClient:
        def __init__(self, api_token):
            self.api_token = api_token

        def ensure_zone(self, *, account_id, zone_name):
            return {"id": "zone-1", "name_servers": ["a.ns", "b.ns"]}

        def ensure_tunnel(self, *, account_id, tunnel_name):
            return {"id": "tunnel-1", "token": "secret-token"}

        def get_tunnel_token(self, *, account_id, tunnel_id):
            return "secret-token"

        def put_tunnel_configuration(
            self,
            *,
            account_id,
            tunnel_id,
            hostname,
            service,
            origin_request=None,
        ):
            recorded["origin_request"] = origin_request
            return {"ok": True}

        def upsert_cname_record(self, *, zone_id, hostname, content, proxied=True):
            return {"id": "record-1"}

    monkeypatch.setattr("webu.cf_tunnel.operations.CloudflareClient", _FakeCfClient)

    apply_tunnel(
        tunnel_name=tunnel_name,
        apply_all=False,
        install_service=False,
        cf_token_mode="auto",
        save_config=True,
    )

    assert recorded["origin_request"] == {
        "connectTimeout": 5,
        "keepAliveConnections": 256,
        "keepAliveTimeout": 120,
    }


def test_apply_tunnel_persists_runtime_overrides(monkeypatch, tmp_path):
    local_payload = deepcopy(_load_local_cf_tunnel_config())
    tunnel = deepcopy(local_payload["cf_tunnels"][0])
    tunnel_name = str(tunnel["tunnel_name"]).strip()

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

        def put_tunnel_configuration(
            self,
            *,
            account_id,
            tunnel_id,
            hostname,
            service,
            origin_request=None,
        ):
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
        domain_name="dev.blbl.top",
        local_url="http://127.0.0.1:21012",
        zone_name="blbl.top",
        origin_request={
            "connect_timeout": 5,
            "keep_alive_connections": 256,
            "keep_alive_timeout": 120,
        },
        cloudflared_run={
            "protocol": "http2",
            "edge_ip_version": "4",
            "dns_resolver_addrs": ["1.1.1.1:53", "1.0.0.1:53"],
        },
    )

    saved = json.loads((config_dir / "cf_tunnel.json").read_text(encoding="utf-8"))
    assert saved["cf_tunnels"][0]["cloudflared_run"] == {
        "protocol": "http2",
        "edge_ip_version": "4",
        "dns_resolver_addrs": ["1.1.1.1:53", "1.0.0.1:53"],
    }
    assert result[0]["cloudflared_run"] == {
        "protocol": "http2",
        "edge_ip_version": "4",
        "dns_resolver_addrs": ["1.1.1.1:53", "1.0.0.1:53"],
    }


def test_apply_tunnel_installs_dedicated_systemd_service(monkeypatch, tmp_path):
    local_payload = deepcopy(_load_local_cf_tunnel_config())
    tunnel = deepcopy(local_payload["cf_tunnels"][0])
    domain_name = str(tunnel["domain_name"]).strip()
    tunnel_name = str(tunnel["tunnel_name"]).strip()

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
        statuses = [
            {"status": "degraded", "connections": [{"id": "conn-1"}]},
            {
                "status": "healthy",
                "connections": [
                    {"id": "conn-1"},
                    {"id": "conn-2"},
                    {"id": "conn-3"},
                    {"id": "conn-4"},
                ],
            },
        ]

        def __init__(self, api_token):
            self.api_token = api_token

        def ensure_zone(self, *, account_id, zone_name):
            return {"id": "zone-1", "name_servers": ["a.ns", "b.ns"]}

        def ensure_tunnel(self, *, account_id, tunnel_name):
            return {"id": "tunnel-1", "token": "secret-token"}

        def get_tunnel_token(self, *, account_id, tunnel_id):
            return "secret-token"

        def get_tunnel(self, *, account_id, tunnel_id):
            if len(self.statuses) > 1:
                return self.statuses.pop(0)
            return self.statuses[0]

        def put_tunnel_configuration(
            self,
            *,
            account_id,
            tunnel_id,
            hostname,
            service,
            origin_request=None,
        ):
            return {"ok": True}

        def upsert_cname_record(self, *, zone_id, hostname, content, proxied=True):
            return {"id": "record-1"}

    recorded_commands = []

    def fake_sudo_run(command, **kwargs):
        recorded_commands.append(command)
        return CompletedProcess(args=command, returncode=0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr("webu.cf_tunnel.operations.CloudflareClient", _FakeCfClient)
    monkeypatch.setattr("webu.cf_tunnel.operations.sudo_run", fake_sudo_run)
    monkeypatch.setattr(
        "webu.cf_tunnel.operations.shutil.which", lambda name: "/usr/bin/cloudflared"
    )

    result = apply_tunnel(
        tunnel_name=tunnel_name,
        apply_all=False,
        install_service=True,
        cf_token_mode="auto",
        save_config=True,
        cloudflared_run={
            "protocol": "http2",
            "edge_ip_version": "4",
            "dns_resolver_addrs": ["1.1.1.1:53", "1.0.0.1:53"],
        },
    )

    install_result = result[0]["install_result"]
    assert install_result["service_name"] == "cloudflared-tunnel-dev-blbl-top.service"
    assert [command[:2] for command in recorded_commands[1:]] == [
        ["rm", "-f"],
        ["systemctl", "daemon-reload"],
        ["systemctl", "enable"],
        ["systemctl", "restart"],
        ["systemctl", "show"],
    ]
    assert recorded_commands[0][:4] == ["install", "-D", "-m", "644"]
    assert result[0]["verification"]["status_before_restart"] == "degraded"
    assert result[0]["verification"]["status_after_restart"] == "healthy"


def test_render_cloudflared_tunnel_service_unit_uses_faster_restart_defaults():
    rendered = _render_cloudflared_tunnel_service_unit(
        tunnel_name="blbl.top",
        tunnel_token="secret-token",
        cloudflared_run={
            "protocol": "http2",
            "edge_ip_version": "4",
            "dns_resolver_addrs": ["1.1.1.1:53", "1.0.0.1:53"],
        },
    )

    assert "Type=notify" in rendered
    assert "TimeoutStartSec=0" in rendered
    assert "RestartSec=2s" in rendered
    assert "--protocol http2" in rendered
    assert "--edge-ip-version 4" in rendered
    assert "--dns-resolver-addrs 1.1.1.1:53" in rendered


def test_access_diagnose_reports_dns_mismatch(monkeypatch, tmp_path):
    local_payload = deepcopy(_load_local_cf_tunnel_config())
    tunnel = deepcopy(local_payload["cf_tunnels"][0])

    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    local_payload["cf_tunnels"] = [tunnel]
    (config_dir / "cf_tunnel.json").write_text(
        json.dumps(local_payload),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    monkeypatch.setattr(
        "webu.cf_tunnel.operations._resolve_system_addresses",
        lambda hostname: ["203.0.113.10"],
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations._authoritative_dns_records",
        lambda payload, hostname: [
            {
                "type": "CNAME",
                "name": hostname,
                "content": "example-tunnel.cfargotunnel.com",
                "proxied": True,
            }
        ],
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations._resolve_cloudflare_addresses",
        lambda hostname, record_type="A": (
            ["104.21.57.71"] if record_type == "A" else []
        ),
    )
    monkeypatch.setattr(
        "webu.cf_tunnel.operations._resolve_authoritative_nameserver_addresses",
        lambda payload, hostname, record_type="A": ["104.21.57.71"],
    )

    def fake_probe(hostname, ip_address):
        if ip_address == "203.0.113.10":
            return {"ip": ip_address, "success": False, "error": "tls failed"}
        return {
            "ip": ip_address,
            "success": True,
            "tls_version": "TLSv1.3",
            "status_code": 404,
            "subject_alt_names": [hostname],
        }

    monkeypatch.setattr("webu.cf_tunnel.operations._probe_https_endpoint", fake_probe)

    result = access_diagnose(tunnel_name=tunnel["tunnel_name"], hostname=None)

    assert result["hostname"] == tunnel["domain_name"]
    assert result["dns"]["mismatch"] is True
    assert result["dns"]["cloudflare_authoritative"]["records"][0]["proxied"] is True
    assert result["https"]["system_resolver"][0]["success"] is False
    assert result["https"]["cloudflare_doh"][0]["success"] is True
    assert any("DNS" in item for item in result["diagnosis"])


def test_page_audit_flags_dev_server_and_broken_assets(monkeypatch, tmp_path):
    local_payload = deepcopy(_load_local_cf_tunnel_config())
    tunnel = deepcopy(local_payload["cf_tunnels"][0])

    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    local_payload["cf_tunnels"] = [tunnel]
    (config_dir / "cf_tunnel.json").write_text(
        json.dumps(local_payload),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    monkeypatch.setattr(
        "webu.cf_tunnel.operations.access_diagnose",
        lambda tunnel_name=None, hostname=None: {
            "hostname": tunnel["domain_name"],
            "tunnel_name": tunnel["tunnel_name"],
            "dns": {
                "system_resolver": {"addresses": ["203.0.113.10"]},
                "cloudflare_doh": {"addresses": ["104.21.57.71"]},
                "cloudflare_authoritative_ns": {"addresses": ["104.21.57.71"]},
            },
        },
    )

    def fake_fetch(hostname, ip_address, path="/", method="GET", max_body_bytes=262144):
        if path == "/":
            return {
                "ip": ip_address,
                "path": path,
                "method": method,
                "success": True,
                "status_code": 200,
                "content_type": "text/html",
                "body_preview": '<html><head><script type="module" src="/@vite/client"></script><script type="module" src="/.quasar/client-entry.js"></script></head><body><img src="http://cdn.example.com/logo.png"></body></html>',
            }
        return {
            "ip": ip_address,
            "path": path,
            "method": method,
            "success": True,
            "status_code": 404,
            "content_type": "text/javascript",
            "body_preview": "",
        }

    monkeypatch.setattr("webu.cf_tunnel.operations._fetch_https_endpoint", fake_fetch)

    result = page_audit(tunnel_name=tunnel["tunnel_name"], hostname=None, path="/")

    assert result["fetches"]["selected_source"] == "cloudflare_authoritative_ns"
    assert result["page"]["findings"]["development_markers"]
    assert result["page"]["findings"]["explicit_insecure_refs"] == [
        "http://cdn.example.com/logo.png"
    ]
    assert any("development entrypoint" in item for item in result["diagnosis"])
    assert any("4xx" in item for item in result["diagnosis"])


def test_edge_trace_reports_colos_and_measurement_guidance(monkeypatch, tmp_path):
    local_payload = deepcopy(_load_local_cf_tunnel_config())
    tunnel = deepcopy(local_payload["cf_tunnels"][0])

    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    local_payload["cf_tunnels"] = [tunnel]
    (config_dir / "cf_tunnel.json").write_text(
        json.dumps(local_payload),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    monkeypatch.setattr(
        "webu.cf_tunnel.operations.access_diagnose",
        lambda tunnel_name=None, hostname=None: {
            "hostname": tunnel["domain_name"],
            "tunnel_name": tunnel["tunnel_name"],
            "dns": {
                "system_resolver": {"addresses": ["104.21.57.71"]},
                "cloudflare_doh": {"addresses": ["172.67.160.241"]},
                "cloudflare_authoritative_ns": {"addresses": ["104.21.57.71"]},
            },
        },
    )

    def fake_fetch(
        hostname, ip_address, path="/cdn-cgi/trace", method="GET", max_body_bytes=32768
    ):
        if ip_address == "104.21.57.71":
            return {
                "ip": ip_address,
                "success": True,
                "status_code": 200,
                "content_type": "text/plain",
                "headers": {"cf-ray": "abc123-HKG", "server": "cloudflare"},
                "body_preview": "fl=29f1\nh=example.com\nip=198.51.100.1\ncolo=HKG\nhttp=http/2\ntls=TLSv1.3\n",
            }
        return {
            "ip": ip_address,
            "success": True,
            "status_code": 200,
            "content_type": "text/plain",
            "headers": {"cf-ray": "def456-NRT", "server": "cloudflare"},
            "body_preview": "fl=29f1\nh=example.com\nip=198.51.100.1\ncolo=NRT\nhttp=http/2\ntls=TLSv1.3\n",
        }

    monkeypatch.setattr("webu.cf_tunnel.operations._fetch_https_endpoint", fake_fetch)

    result = edge_trace(tunnel_name=tunnel["tunnel_name"], hostname=None)

    assert result["hostname"] == tunnel["domain_name"]
    assert {item["colo"] for item in result["unique_edge_results"]} == {"HKG", "NRT"}
    assert any("Anycast" in item for item in result["diagnosis"])
    assert any("measurement-only" in item for item in result["recommendations"])


def test_client_override_plan_exports_hosts_candidates(monkeypatch, tmp_path):
    local_payload = deepcopy(_load_local_cf_tunnel_config())
    tunnel = deepcopy(local_payload["cf_tunnels"][0])

    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    local_payload["cf_tunnels"] = [tunnel]
    (config_dir / "cf_tunnel.json").write_text(
        json.dumps(local_payload),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    monkeypatch.setattr(
        "webu.cf_tunnel.operations.edge_trace",
        lambda tunnel_name=None, hostname=None: {
            "hostname": tunnel["domain_name"],
            "tunnel_name": tunnel["tunnel_name"],
            "unique_edge_results": [
                {
                    "ip": "172.67.160.241",
                    "success": True,
                    "colo": "LAX",
                    "cf_ray": "abc-LAX",
                },
                {
                    "ip": "2606:4700:3030::ac43:a0f1",
                    "success": True,
                    "colo": "LAX",
                    "cf_ray": "def-LAX",
                },
            ],
        },
    )

    result = client_override_plan(
        tunnel_name=tunnel["tunnel_name"],
        hostname=None,
        prefer_family="ipv4",
        max_candidates=2,
    )

    assert result["hostname"] == tunnel["domain_name"]
    assert len(result["candidates"]) == 1
    assert (
        result["candidates"][0]["hosts_line"]
        == f"172.67.160.241 {tunnel['domain_name']}"
    )
    assert result["distribution"]["linux_macos_hosts"][0].startswith("172.67.160.241 ")
    assert any("canary" in item for item in result["recommendations"])


def test_client_canary_bundle_contains_platform_guides(monkeypatch, tmp_path):
    local_payload = deepcopy(_load_local_cf_tunnel_config())
    tunnel = deepcopy(local_payload["cf_tunnels"][0])

    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    local_payload["cf_tunnels"] = [tunnel]
    (config_dir / "cf_tunnel.json").write_text(
        json.dumps(local_payload),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    monkeypatch.setattr(
        "webu.cf_tunnel.operations.client_override_plan",
        lambda **kwargs: {
            "hostname": tunnel["domain_name"],
            "tunnel_name": tunnel["tunnel_name"],
            "candidates": [
                {
                    "ip": "172.67.160.241",
                    "family": "ipv4",
                    "colo": "LAX",
                    "cf_ray": "abc-LAX",
                    "hosts_line": f"172.67.160.241 {tunnel['domain_name']}",
                }
            ],
        },
    )

    result = client_canary_bundle(
        tunnel_name=tunnel["tunnel_name"],
        hostname=None,
        prefer_family="ipv4",
        max_candidates=1,
    )

    assert result["platforms"]["windows"]["hosts_lines"][0].startswith(
        "172.67.160.241 "
    )
    assert result["platforms"]["android"]["method"] == "local-dns-override"
    assert result["report_template"]["reports"][0]["candidate_ip"] == "172.67.160.241"


def test_client_report_summary_ranks_by_isp_and_platform(tmp_path):
    report_file = tmp_path / "client-canary.json"
    report_file.write_text(
        json.dumps(
            {
                "reports": [
                    {
                        "isp": "cmcc",
                        "platform": "windows",
                        "candidate_ip": "104.21.57.71",
                        "success": True,
                        "ttfb_ms": 260,
                        "trace_colo": "NRT",
                    },
                    {
                        "isp": "cmcc",
                        "platform": "android",
                        "candidate_ip": "104.21.57.71",
                        "success": True,
                        "ttfb_ms": 280,
                        "trace_colo": "NRT",
                    },
                    {
                        "isp": "cmcc",
                        "platform": "windows",
                        "candidate_ip": "172.67.160.241",
                        "success": False,
                        "ttfb_ms": None,
                        "trace_colo": "",
                    },
                    {
                        "isp": "ctcc",
                        "platform": "ios",
                        "candidate_ip": "172.67.160.241",
                        "success": True,
                        "ttfb_ms": 190,
                        "trace_colo": "HKG",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = client_report_summary(report_file=str(report_file))

    assert result["sample_count"] == 4
    assert result["overall"][0]["candidate_ip"] in {"104.21.57.71", "172.67.160.241"}
    assert "cmcc" in result["per_isp"]
    assert "windows" in result["per_platform"]


def test_client_report_template_contains_candidates(monkeypatch, tmp_path):
    local_payload = deepcopy(_load_local_cf_tunnel_config())
    tunnel = deepcopy(local_payload["cf_tunnels"][0])

    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='webu'\n", encoding="utf-8"
    )
    local_payload["cf_tunnels"] = [tunnel]
    (config_dir / "cf_tunnel.json").write_text(
        json.dumps(local_payload),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBU_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    monkeypatch.setattr(
        "webu.cf_tunnel.operations.client_canary_bundle",
        lambda **kwargs: {
            "report_template": {
                "hostname": tunnel["domain_name"],
                "tunnel_name": tunnel["tunnel_name"],
                "reports": [{"candidate_ip": "104.21.57.71"}],
            }
        },
    )

    result = client_report_template(
        tunnel_name=tunnel["tunnel_name"],
        hostname=None,
        prefer_family="ipv4",
        max_candidates=1,
    )

    assert result["reports"][0]["candidate_ip"] == "104.21.57.71"


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
