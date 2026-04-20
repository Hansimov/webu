from __future__ import annotations

import json

from subprocess import CompletedProcess

from webu.ali_esa.operations import (
    _list_global_ipv6_candidates,
    _resolve_exposure_record,
    _resolve_origin_address,
    apply_exposure,
    site_origin_pools,
    site_records,
)


def test_list_global_ipv6_candidates_prefers_default_route_stable(monkeypatch):
    def fake_run(command, check=False, capture_output=False, text=False):
        if command == ["ip", "-j", "-6", "route", "show", "default"]:
            return CompletedProcess(
                args=command,
                returncode=0,
                stdout='[{"dst":"default","dev":"eth0"}]',
                stderr="",
            )
        if command == ["ip", "-j", "-6", "addr", "show", "scope", "global", "up"]:
            return CompletedProcess(
                args=command,
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "ifname": "eth0",
                            "addr_info": [
                                {
                                    "family": "inet6",
                                    "local": "2001:db8:1::20",
                                    "scope": "global",
                                    "temporary": True,
                                },
                                {
                                    "family": "inet6",
                                    "local": "2001:db8:1::10",
                                    "scope": "global",
                                    "mngtmpaddr": True,
                                },
                            ],
                        },
                        {
                            "ifname": "tailscale0",
                            "addr_info": [
                                {
                                    "family": "inet6",
                                    "local": "fd7a:115c:a1e0::1",
                                    "scope": "global",
                                }
                            ],
                        },
                    ]
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr("webu.ali_esa.operations.subprocess.run", fake_run)

    candidates = _list_global_ipv6_candidates()

    assert [item["address"] for item in candidates] == [
        "2001:db8:1::10",
        "2001:db8:1::20",
    ]
    assert candidates[0]["default_route"] is True
    assert candidates[0]["temporary"] is False


def test_resolve_origin_address_prefers_site_config_for_auto():
    result = _resolve_origin_address(
        {
            "default_public_origin_ipv4": "198.51.100.10",
            "default_public_origin_ipv6": "2001:db8:1::5",
        },
        {"public_origin_address": "2001:db8:1::10"},
        origin_address="auto",
    )

    assert result == {
        "address": "2001:db8:1::10",
        "family": "ipv6",
        "source": "config",
    }


def test_resolve_exposure_record_requires_ipv4_companion_for_ipv6():
    try:
        _resolve_exposure_record(
            {},
            {"public_origin_address": "2001:db8:1::10"},
            origin_address="auto6",
        )
    except ValueError as exc:
        assert "at least one IPv4" in str(exc)
    else:
        raise AssertionError("expected ValueError for IPv6-only ESA origin")


def test_apply_exposure_uses_dual_stack_record_for_ipv6_origin(monkeypatch):
    recorded: dict[str, object] = {}

    monkeypatch.setattr(
        "webu.ali_esa.operations.load_ali_esa_config",
        lambda validate=False: {"default_public_origin_ipv4": "198.51.100.10"},
    )
    monkeypatch.setattr(
        "webu.ali_esa.operations.ensure_site",
        lambda **kwargs: {
            "site": {
                "site_name": "example.com",
                "site_id": 123,
                "coverage": "overseas",
                "access_type": "NS",
                "instance_id": "instance-1",
                "name_server_list": [],
                "current_ns": [],
                "status": "pending",
                "verify_code": "",
                "public_origin_address": "",
            }
        },
    )
    monkeypatch.setattr(
        "webu.ali_esa.operations._build_esa_client", lambda payload: object()
    )

    def fake_ensure_record(
        client,
        *,
        site_id,
        record_name,
        record_type,
        data_value,
        ttl,
        proxied,
        biz_name,
        purge_conflicts,
        **kwargs,
    ):
        recorded["record_type"] = record_type
        recorded["data_value"] = data_value
        recorded["record_name"] = record_name
        return {"record": {"RecordType": record_type, "Data": {"Value": data_value}}}

    monkeypatch.setattr("webu.ali_esa.operations._ensure_record", fake_ensure_record)
    monkeypatch.setattr(
        "webu.ali_esa.operations._ensure_origin_rule",
        lambda *args, **kwargs: {"rule": {"RuleName": "rule-1"}},
    )
    monkeypatch.setattr(
        "webu.ali_esa.operations._upsert_site_payload",
        lambda *args, **kwargs: {
            "site_name": "example.com",
            "site_id": 123,
            "public_origin_address": kwargs.get("public_origin_address"),
        },
    )
    monkeypatch.setattr(
        "webu.ali_esa.operations._persist_config_if_requested",
        lambda *args, **kwargs: None,
    )

    result = apply_exposure(
        domain_name="dev.example.com",
        local_url="http://127.0.0.1:21012",
        zone_name="example.com",
        origin_address="2001:db8:1::10",
        save_config=False,
    )

    assert recorded["record_name"] == "dev.example.com"
    assert recorded["record_type"] == "A/AAAA"
    assert recorded["data_value"] == "198.51.100.10,2001:db8:1::10"
    assert result["origin"]["public_address_family"] == "ipv6"
    assert result["origin"]["record_family"] == "dual-stack"


def test_site_records_lists_filtered_records(monkeypatch):
    class FakeClient:
        def get_site(self, *, site_name):
            assert site_name == "example.com"
            return {"SiteId": 123, "SiteName": site_name, "Status": "pending"}

        def get_site_current_ns(self, *, site_id):
            assert site_id == 123
            return ["ns1.example.com", "ns2.example.com"]

        def list_records(
            self, *, site_id, record_name=None, record_type=None, page_size=500
        ):
            assert site_id == 123
            assert record_name == "dev.example.com"
            assert record_type == "A/AAAA"
            assert page_size == 500
            return [
                {
                    "RecordId": 9,
                    "RecordName": "dev.example.com",
                    "RecordType": "A/AAAA",
                    "Data": {"Value": "198.51.100.10,2001:db8::10"},
                }
            ]

    monkeypatch.setattr(
        "webu.ali_esa.operations.load_ali_esa_config",
        lambda validate=False: {
            "sites": [
                {
                    "site_name": "example.com",
                    "coverage": "overseas",
                    "access_type": "NS",
                    "instance_id": "instance-1",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "webu.ali_esa.operations._build_esa_client",
        lambda payload: FakeClient(),
    )

    result = site_records(
        site_name="example.com",
        record_name="dev.example.com",
        record_type="A/AAAA",
    )

    assert result["site_name"] == "example.com"
    assert result["count"] == 1
    assert result["current_ns"] == ["ns1.example.com", "ns2.example.com"]
    assert result["records"][0]["RecordName"] == "dev.example.com"
    assert result["config_site"]["site_name"] == "example.com"


def test_site_origin_pools_lists_filtered_pools(monkeypatch):
    observed: dict[str, object] = {}

    class FakeClient:
        def get_site(self, *, site_name):
            assert site_name == "example.com"
            return {"SiteId": 123, "SiteName": site_name, "Status": "pending"}

        def get_site_current_ns(self, *, site_id):
            assert site_id == 123
            return []

        def list_origin_pools(
            self, *, site_id, name=None, match_type=None, order_by=None, page_size=500
        ):
            observed["site_id"] = site_id
            observed["name"] = name
            observed["match_type"] = match_type
            observed["order_by"] = order_by
            observed["page_size"] = page_size
            return [
                {
                    "Id": 21,
                    "Name": "search-prod",
                    "RecordName": "search-prod.origin-pool.example.com",
                }
            ]

    monkeypatch.setattr(
        "webu.ali_esa.operations.load_ali_esa_config",
        lambda validate=False: {"sites": [{"site_name": "example.com"}]},
    )
    monkeypatch.setattr(
        "webu.ali_esa.operations._build_esa_client",
        lambda payload: FakeClient(),
    )

    result = site_origin_pools(
        site_name="example.com",
        name="search",
        match_type="fuzzy",
    )

    assert observed == {
        "site_id": 123,
        "name": "search",
        "match_type": "fuzzy",
        "order_by": None,
        "page_size": 500,
    }
    assert result["site_name"] == "example.com"
    assert result["count"] == 1
    assert result["origin_pools"][0]["Name"] == "search-prod"
