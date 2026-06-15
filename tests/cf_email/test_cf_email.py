import json

from webu.cf_email.clients import CloudflareEmailClient
from webu.cf_email.operations import (
    build_email_routing_token_payload,
    build_worker_script,
    config_init,
    deploy_worker,
    ensure_worker_rule,
    extract_verification_codes,
    parse_email_message,
    routing_plan,
)
from webu.cf_email.schema import CfEmailRuntimeConfig, resolve_runtime_config


RAW_EMAIL = """From: sender@example.com
To: account-dev@example.com
Subject: Your code is 654321
Message-ID: <message-1@example.com>
Content-Type: text/plain; charset=utf-8

Use 654321 to finish registration.
"""


def _runtime() -> CfEmailRuntimeConfig:
    return CfEmailRuntimeConfig(
        cf_account_id="acct-1",
        cf_api_token="token-1",
        zone_name="example.com",
        zone_id="zone-1",
        worker_name="account-email-inbox",
        route_local_part="account-dev",
        webhook_url="http://127.0.0.1:14567/api/dev/email/inbound",
        webhook_secret="secret",
        code_regex=r"\b([0-9]{6})\b",
    )


def test_parse_email_message_and_extract_code():
    parsed = parse_email_message(RAW_EMAIL)

    assert parsed["from"] == "sender@example.com"
    assert parsed["to"] == "account-dev@example.com"
    assert parsed["subject"] == "Your code is 654321"
    assert extract_verification_codes(RAW_EMAIL) == ["654321"]


def test_routing_plan_masks_account_id():
    plan = routing_plan(
        {
            "cf_account_id": "acct-1",
            "cf_api_token": "token-1",
            "zone_name": "example.com",
            "zone_id": "zone-1",
            "route_local_part": "account-dev",
            "worker_name": "worker-1",
            "webhook_url": "http://127.0.0.1:14567/hook",
        }
    )

    assert plan["account_id"] == "***"
    assert plan["route_address"] == "account-dev@example.com"


def test_resolve_runtime_config_falls_back_to_cf_tunnel(monkeypatch):
    monkeypatch.setattr(
        "webu.cf_email.schema.load_cf_tunnel_config",
        lambda: {
            "cf_account_id": "acct-1",
            "cf_api_token": "token-1",
            "domains": [
                {
                    "domain_name": "example.com",
                    "zone_name": "example.com",
                    "zone_id": "zone-1",
                }
            ],
        },
    )

    runtime = resolve_runtime_config({"zone_name": "example.com"})

    assert runtime.cf_account_id == "acct-1"
    assert runtime.zone_id == "zone-1"


def test_cloudflare_email_client_builds_rule_payload(monkeypatch):
    client = CloudflareEmailClient("token")
    recorded = {}

    def fake_request(method, path, *, params=None, json_body=None):
        recorded.update({"method": method, "path": path, "json_body": json_body})
        return {"id": "rule-1"}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.create_routing_rule(
        zone_id="zone-1",
        address="account-dev@example.com",
        action_type="worker",
        action_values=["worker-1"],
    )

    assert result["id"] == "rule-1"
    assert recorded["method"] == "POST"
    assert recorded["path"] == "/zones/zone-1/email/routing/rules"
    assert recorded["json_body"]["actions"] == [
        {"type": "worker", "value": ["worker-1"]}
    ]


def test_build_email_routing_token_payload_uses_zone_and_account_scopes():
    groups = [
        {"id": "addr-r", "name": "Email Routing Addresses Read", "scopes": ["com.cloudflare.api.account"]},
        {"id": "addr-w", "name": "Email Routing Addresses Write", "scopes": ["com.cloudflare.api.account"]},
        {"id": "worker-r", "name": "Workers Scripts Read", "scopes": ["com.cloudflare.api.account"]},
        {"id": "worker-w", "name": "Workers Scripts Write", "scopes": ["com.cloudflare.api.account"]},
        {"id": "zone-r", "name": "Zone Read", "scopes": ["com.cloudflare.api.account.zone"]},
        {"id": "dns-r", "name": "DNS Read", "scopes": ["com.cloudflare.api.account.zone"]},
        {"id": "dns-w", "name": "DNS Write", "scopes": ["com.cloudflare.api.account.zone"]},
        {"id": "rules-r", "name": "Email Routing Rules Read", "scopes": ["com.cloudflare.api.account.zone"]},
        {"id": "rules-w", "name": "Email Routing Rules Write", "scopes": ["com.cloudflare.api.account.zone"]},
    ]

    payload = build_email_routing_token_payload(
        groups=groups,
        name="cfem-apiw-top-email-routing",
        account_id="acct-1",
        zone_id="zone-1",
        expires_in_days=None,
    )

    assert payload["name"] == "cfem-apiw-top-email-routing"
    assert "expires_on" not in payload
    assert payload["policies"][0]["resources"] == {"com.cloudflare.api.account.acct-1": "*"}
    assert payload["policies"][1]["resources"] == {"com.cloudflare.api.account.zone.zone-1": "*"}
    assert {item["id"] for item in payload["policies"][1]["permission_groups"]} == {
        "zone-r",
        "dns-r",
        "dns-w",
        "rules-r",
        "rules-w",
    }


def test_ensure_worker_rule_skips_existing(monkeypatch):
    runtime = _runtime()

    class FakeClient:
        def __init__(self, token):
            assert token == "token-1"

        def list_routing_rules(self, *, zone_id):
            assert zone_id == "zone-1"
            return [
                {
                    "id": "rule-1",
                    "matchers": [
                        {
                            "type": "literal",
                            "field": "to",
                            "value": runtime.route_address,
                        }
                    ],
                }
            ]

    monkeypatch.setattr("webu.cf_email.operations.CloudflareEmailClient", FakeClient)

    result = ensure_worker_rule(runtime=runtime)

    assert result["changed"] is False
    assert result["rule"]["id"] == "rule-1"


def test_deploy_worker_uploads_script_and_secret(monkeypatch):
    runtime = _runtime()
    calls = []

    class FakeClient:
        def __init__(self, token):
            assert token == "token-1"

        def upload_worker_script(self, *, account_id, script_name, script):
            calls.append(("upload", account_id, script_name, "message.raw" in script))
            return {"id": "script-1"}

        def put_worker_secret(self, *, account_id, script_name, name, text):
            calls.append(("secret", account_id, script_name, name, text == "secret"))
            return {"name": name}

    monkeypatch.setattr("webu.cf_email.operations.CloudflareEmailClient", FakeClient)

    result = deploy_worker(runtime=runtime)

    assert result["deployed"] is True
    assert result["script_id"] == "script-1"
    assert result["secret_set"] is True
    assert calls == [
        ("upload", "acct-1", "account-email-inbox", True),
        ("secret", "acct-1", "account-email-inbox", "WEBHOOK_SECRET", True),
    ]


def test_worker_script_contains_webhook_and_secret_binding():
    script = build_worker_script(_runtime())

    assert "http://127.0.0.1:14567/api/dev/email/inbound" in script
    assert "env.WEBHOOK_SECRET" in script
    assert "message.raw" in script


def test_config_init_writes_template(tmp_path, monkeypatch):
    config_dir = tmp_path / "configs"
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    output = config_init(force=True)

    path = config_dir / "cf_email.json"
    assert path.exists()
    assert json.loads(path.read_text())["worker_name"] == "account-email-inbox"
    assert "route_local_part" in output
