from __future__ import annotations

import json

from subprocess import CompletedProcess

from webu.ali_esa.operations import (
    _list_global_ipv6_candidates,
    _normalize_load_balancer_name,
    _resolve_exposure_record,
    _resolve_origin_address,
    apply_exposure,
    site_load_balancer_create,
    site_load_balancer_delete,
    site_load_balancer_origin_status,
    site_load_balancers,
    site_origin_pool_cname_apply,
    site_origin_pool_cname_delete,
    site_origin_pools,
    site_records,
)
from webu.ali_esa.clients import AliyunEsaApiError


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


def test_site_load_balancers_lists_filtered_items(monkeypatch):
    observed: dict[str, object] = {}

    class FakeClient:
        def get_site(self, *, site_name):
            assert site_name == "example.com"
            return {"SiteId": 123, "SiteName": site_name, "Status": "pending"}

        def get_site_current_ns(self, *, site_id):
            assert site_id == 123
            return []

        def list_load_balancers(
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
                    "Name": "search-prod-lb",
                    "DefaultPools": [101],
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

    result = site_load_balancers(
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
    assert result["load_balancers"][0]["Name"] == "search-prod-lb"


def test_site_load_balancer_origin_status_uses_explicit_ids(monkeypatch):
    observed: dict[str, object] = {}

    class FakeClient:
        def get_site(self, *, site_name):
            assert site_name == "example.com"
            return {"SiteId": 123, "SiteName": site_name, "Status": "pending"}

        def get_site_current_ns(self, *, site_id):
            assert site_id == 123
            return []

        def list_load_balancer_origin_status(
            self, *, site_id, load_balancer_ids, pool_type=None
        ):
            observed["site_id"] = site_id
            observed["load_balancer_ids"] = load_balancer_ids
            observed["pool_type"] = pool_type
            return [
                {
                    "LoadBalancerId": 21,
                    "OriginId": 31,
                    "PoolId": 101,
                    "PoolType": "default_pool",
                    "Status": "healthy",
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

    result = site_load_balancer_origin_status(
        site_name="example.com",
        load_balancer_ids=[21, 22],
        pool_type="default_pool",
    )

    assert observed == {
        "site_id": 123,
        "load_balancer_ids": [21, 22],
        "pool_type": "default_pool",
    }
    assert result["site_name"] == "example.com"
    assert result["load_balancer_ids"] == [21, 22]
    assert result["count"] == 1
    assert result["origin_status"][0]["Status"] == "healthy"


def test_normalize_load_balancer_name_expands_bare_label():
    assert (
        _normalize_load_balancer_name("lb-probe", site_name="example.com")
        == "lb-probe.example.com"
    )


def test_site_load_balancer_create_resolves_pool_names(monkeypatch):
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
            assert site_id == 123
            assert match_type == "exact"
            if name == "search-prod":
                return [{"Id": 101, "Name": "search-prod"}]
            raise AssertionError(f"unexpected pool name: {name}")

        def create_load_balancer(
            self,
            *,
            site_id,
            name,
            default_pools,
            fallback_pool,
            monitor,
            steering_policy,
            description=None,
            enabled=None,
            session_affinity=None,
            ttl=None,
            random_steering=None,
        ):
            observed.update(
                {
                    "site_id": site_id,
                    "name": name,
                    "default_pools": default_pools,
                    "fallback_pool": fallback_pool,
                    "monitor": monitor,
                    "steering_policy": steering_policy,
                    "description": description,
                    "enabled": enabled,
                    "session_affinity": session_affinity,
                    "ttl": ttl,
                    "random_steering": random_steering,
                }
            )
            return {"Id": 301, "RequestId": "req-1"}

        def get_load_balancer(self, *, site_id, load_balancer_id):
            assert site_id == 123
            assert load_balancer_id == 301
            return {"Id": 301, "Name": "lb-probe.example.com", "DefaultPools": [101]}

    monkeypatch.setattr(
        "webu.ali_esa.operations.load_ali_esa_config",
        lambda validate=False: {"sites": [{"site_name": "example.com"}]},
    )
    monkeypatch.setattr(
        "webu.ali_esa.operations._build_esa_client",
        lambda payload: FakeClient(),
    )

    result = site_load_balancer_create(
        site_name="example.com",
        name="lb-probe",
        default_pool_names=["search-prod"],
        monitor_type="off",
        steering_policy="order",
        description="probe",
    )

    assert observed == {
        "site_id": 123,
        "name": "lb-probe.example.com",
        "default_pools": [101],
        "fallback_pool": 101,
        "monitor": {"Type": "off"},
        "steering_policy": "order",
        "description": "probe",
        "enabled": True,
        "session_affinity": "off",
        "ttl": 30,
        "random_steering": None,
    }
    assert result["resolved_default_pool_ids"] == [101]
    assert result["resolved_fallback_pool_id"] == 101
    assert result["load_balancer"]["Id"] == 301


def test_site_load_balancer_delete_resolves_name(monkeypatch):
    observed: dict[str, object] = {}

    class FakeClient:
        def get_site(self, *, site_name):
            assert site_name == "example.com"
            return {"SiteId": 123, "SiteName": site_name, "Status": "pending"}

        def get_site_current_ns(self, *, site_id):
            assert site_id == 123
            return []

        def list_load_balancers(
            self, *, site_id, name=None, match_type=None, order_by=None, page_size=500
        ):
            assert site_id == 123
            if name == "lb-probe.example.com":
                if observed.get("deleted"):
                    return []
                return [{"Id": 301, "Name": "lb-probe.example.com"}]
            raise AssertionError(f"unexpected load balancer lookup: {name}")

        def get_load_balancer(self, *, site_id, load_balancer_id):
            assert site_id == 123
            assert load_balancer_id == 301
            return {"Id": 301, "Name": "lb-probe.example.com"}

        def delete_load_balancer(self, *, site_id, load_balancer_id):
            assert site_id == 123
            assert load_balancer_id == 301
            observed["deleted"] = True
            return {"RequestId": "req-2"}

    monkeypatch.setattr(
        "webu.ali_esa.operations.load_ali_esa_config",
        lambda validate=False: {"sites": [{"site_name": "example.com"}]},
    )
    monkeypatch.setattr(
        "webu.ali_esa.operations._build_esa_client",
        lambda payload: FakeClient(),
    )

    result = site_load_balancer_delete(
        site_name="example.com",
        name="lb-probe.example.com",
    )

    assert result["load_balancer"]["Id"] == 301
    assert result["deleted"] is True


def test_site_load_balancer_create_reports_quota_failure(monkeypatch):
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
            return [{"Id": 101, "Name": "search-prod"}]

        def create_load_balancer(self, **kwargs):
            raise AliyunEsaApiError(
                "LoadBalancerQuotaCheckFailed: code: 400, Load balancer enable quota check failed. request id: req-3"
            )

    monkeypatch.setattr(
        "webu.ali_esa.operations.load_ali_esa_config",
        lambda validate=False: {"sites": [{"site_name": "example.com"}]},
    )
    monkeypatch.setattr(
        "webu.ali_esa.operations._build_esa_client",
        lambda payload: FakeClient(),
    )

    try:
        site_load_balancer_create(
            site_name="example.com",
            name="lb-probe",
            default_pool_names=["search-prod"],
            monitor_type="off",
        )
    except ValueError as exc:
        assert "does not expose usable load balancer quota" in str(exc)
    else:
        raise AssertionError("expected quota failure to be translated into ValueError")


def test_site_origin_pool_cname_apply_creates_op_backed_cname(monkeypatch):
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
            assert site_id == 123
            return [{"Id": 101, "Name": "search-prod"}]

        def get_origin_pool(self, *, site_id, origin_pool_id):
            assert site_id == 123
            assert origin_pool_id == 101
            return {
                "Id": 101,
                "Name": "search-prod",
                "RecordName": "search-prod.origin-pool.example.com",
                "References": observed.get(
                    "references",
                    {"DnsRecords": [], "IPARecords": [], "LoadBalancers": []},
                ),
                "ReferenceLBCount": 0,
            }

        def list_records(
            self, *, site_id, record_name=None, record_type=None, page_size=500
        ):
            assert site_id == 123
            if observed.get("record") is None:
                return []
            return [observed["record"]]

        def create_record(
            self,
            *,
            site_id,
            record_name,
            record_type,
            ttl,
            data_value,
            proxied=None,
            biz_name=None,
            source_type=None,
            comment=None,
            host_policy=None,
            data_extra=None,
        ):
            observed["record"] = {
                "RecordId": 401,
                "RecordName": record_name,
                "RecordType": record_type,
                "RecordSourceType": source_type,
                "BizName": biz_name,
                "HostPolicy": host_policy or "",
                "Proxied": proxied,
                "Ttl": ttl,
                "Data": {"Value": data_value},
            }
            observed["references"] = {
                "DnsRecords": [{"Id": 401, "Name": record_name}],
                "IPARecords": [],
                "LoadBalancers": [],
            }
            return {"RecordId": 401}

        def update_record(self, **kwargs):
            raise AssertionError("update_record should not be called in this scenario")

    monkeypatch.setattr(
        "webu.ali_esa.operations.load_ali_esa_config",
        lambda validate=False: {"sites": [{"site_name": "example.com"}]},
    )
    monkeypatch.setattr(
        "webu.ali_esa.operations._build_esa_client",
        lambda payload: FakeClient(),
    )

    result = site_origin_pool_cname_apply(
        site_name="example.com",
        record_name="op-probe",
        pool_name="search-prod",
        biz_name="web",
        host_policy="follow_hostname",
        comment="probe",
    )

    assert result["record"]["created"] is True
    assert result["record"]["record"]["RecordSourceType"] == "OP"
    assert result["record"]["record"]["RecordName"] == "op-probe.example.com"
    assert result["after_references"]["DnsRecords"][0]["Name"] == "op-probe.example.com"


def test_site_origin_pool_cname_delete_removes_op_backed_record(monkeypatch):
    class FakeClient:
        def get_site(self, *, site_name):
            assert site_name == "example.com"
            return {"SiteId": 123, "SiteName": site_name, "Status": "pending"}

        def get_site_current_ns(self, *, site_id):
            assert site_id == 123
            return []

        def list_records(
            self, *, site_id, record_name=None, record_type=None, page_size=500
        ):
            assert site_id == 123
            if getattr(self, "deleted", False):
                return []
            return [
                {
                    "RecordId": 401,
                    "RecordName": "op-probe.example.com",
                    "RecordType": "CNAME",
                    "RecordSourceType": "OP",
                }
            ]

        def delete_record(self, *, record_id):
            assert record_id == 401
            self.deleted = True
            return {"RequestId": "req-4"}

    fake_client = FakeClient()
    monkeypatch.setattr(
        "webu.ali_esa.operations.load_ali_esa_config",
        lambda validate=False: {"sites": [{"site_name": "example.com"}]},
    )
    monkeypatch.setattr(
        "webu.ali_esa.operations._build_esa_client",
        lambda payload: fake_client,
    )

    result = site_origin_pool_cname_delete(
        site_name="example.com",
        record_name="op-probe",
    )

    assert result["deleted_count"] == 1
    assert result["remaining_count"] == 0
