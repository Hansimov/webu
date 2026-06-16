import json

from webu.ali_email.clients import (
    build_create_domain_payload,
    build_create_mail_address_payload,
    build_query_domain_payload,
    build_query_mail_address_payload,
    build_single_send_mail_payload,
)
from webu.ali_email.operations import (
    build_verification_email,
    config_check,
    config_init,
)
from webu.ali_email.schema import resolve_runtime_config


def test_build_single_send_mail_payload_requires_body():
    try:
        build_single_send_mail_payload(
            account_name="noreply@example.com",
            to_address="user@example.com",
            subject="Code",
        )
    except ValueError as exc:
        assert "text_body" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_build_create_mail_address_payload_normalizes_trigger_sender():
    payload = build_create_mail_address_payload(
        account_name=" register@example.com ",
        sendtype="trigger",
    )

    assert payload == {
        "account_name": "register@example.com",
        "sendtype": "trigger",
    }


def test_build_create_mail_address_payload_rejects_invalid_sendtype():
    try:
        build_create_mail_address_payload(
            account_name="register@example.com",
            sendtype="other",
        )
    except ValueError as exc:
        assert "sendtype" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_build_create_domain_payload_normalizes_domain():
    assert build_create_domain_payload(domain_name=" example.com ") == {
        "domain_name": "example.com"
    }


def test_build_query_domain_payload_has_pagination_defaults():
    assert build_query_domain_payload(key_word="example.com") == {
        "key_word": "example.com",
        "page_no": 1,
        "page_size": 10,
    }


def test_build_query_mail_address_payload_filters_by_sendtype():
    assert build_query_mail_address_payload(
        key_word="register@example.com",
        sendtype="trigger",
    ) == {
        "key_word": "register@example.com",
        "page_no": 1,
        "page_size": 10,
        "sendtype": "trigger",
    }


def test_build_verification_email_contains_code_and_ttl():
    message = build_verification_email(code="123456", ttl_minutes=7)

    assert message["subject"] == "Account 注册验证码"
    assert "123456" in message["text_body"]
    assert "7 分钟" in message["text_body"]
    assert "如果这不是你本人操作" in message["text_body"]
    assert "<strong>123456</strong>" in message["html_body"]


def test_build_password_reset_email_uses_chinese_purpose_label():
    message = build_verification_email(
        code="654321",
        purpose="password_reset",
        ttl_minutes=2,
        product_name="example.com",
    )

    assert message["subject"] == "example.com 密码重置验证码"
    assert "密码重置验证码" in message["text_body"]
    assert "2 分钟" in message["html_body"]


def test_resolve_runtime_config_falls_back_to_ali_esa(monkeypatch):
    monkeypatch.setattr(
        "webu.ali_email.schema.load_ali_esa_config",
        lambda validate=False: {
            "aliyun_access_id": "ak-from-esa",
            "aliyun_access_secret": "test-sk-from-esa",
        },
    )
    monkeypatch.setattr("webu.ali_email.schema.load_cf_tunnel_config", lambda: {})

    runtime = resolve_runtime_config({"sender_account_name": "noreply@example.com"})

    assert runtime.aliyun_access_id == "ak-from-esa"
    assert runtime.aliyun_access_secret == "test-sk-from-esa"


def test_config_init_writes_template(tmp_path, monkeypatch):
    config_dir = tmp_path / "configs"
    monkeypatch.setenv("WEBU_CONFIG_DIR", str(config_dir))

    output = config_init(force=True)

    path = config_dir / "ali_email.json"
    assert path.exists()
    assert json.loads(path.read_text())["endpoint"] == "dm.aliyuncs.com"
    assert "sender_account_name" in output


def test_config_check_reports_missing_sender_and_credentials(monkeypatch):
    monkeypatch.setattr("webu.ali_email.schema.load_ali_esa_config", lambda **_: {})
    monkeypatch.setattr("webu.ali_email.schema.load_cf_tunnel_config", lambda: {})

    errors = config_check({})

    assert any("sender_account_name" in item for item in errors)
    assert any("aliyun_access_id" in item for item in errors)
