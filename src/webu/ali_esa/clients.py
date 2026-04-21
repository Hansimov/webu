from __future__ import annotations

from typing import Any

from alibabacloud_esa20240910.client import Client as EsaOpenApiClient
from alibabacloud_esa20240910 import models as esa_models
from alibabacloud_tea_openapi import utils_models as open_api_models


class AliyunEsaApiError(RuntimeError):
    pass


def _unwrap_body(response: object) -> dict[str, Any]:
    body = getattr(response, "body", None)
    if hasattr(body, "to_map"):
        payload = body.to_map()
        if isinstance(payload, dict):
            return payload
    if hasattr(response, "to_map"):
        payload = response.to_map()
        if isinstance(payload, dict):
            nested = payload.get("body")
            if isinstance(nested, dict):
                return nested
            return payload
    return {}


def _stringify_exception(exc: Exception) -> str:
    code = str(getattr(exc, "code", "") or "").strip()
    message = str(getattr(exc, "message", "") or str(exc)).strip()
    if code and message:
        return f"{code}: {message}"
    return message or type(exc).__name__


class AliyunEsaClient:
    def __init__(
        self,
        *,
        access_key_id: str,
        access_key_secret: str,
        region_id: str = "cn-hangzhou",
    ):
        normalized_access_key_id = str(access_key_id or "").strip()
        normalized_access_key_secret = str(access_key_secret or "").strip()
        if not normalized_access_key_id or not normalized_access_key_secret:
            raise ValueError("Aliyun ESA AccessKey credentials are required")

        self.region_id = str(region_id or "cn-hangzhou").strip() or "cn-hangzhou"
        self._client = EsaOpenApiClient(
            open_api_models.Config(
                access_key_id=normalized_access_key_id,
                access_key_secret=normalized_access_key_secret,
                region_id=self.region_id,
                endpoint=f"esa.{self.region_id}.aliyuncs.com",
            )
        )

    def _call(self, func, *args, **kwargs) -> dict[str, Any]:
        try:
            return _unwrap_body(func(*args, **kwargs))
        except Exception as exc:  # pragma: no cover - SDK error typing is broad.
            raise AliyunEsaApiError(_stringify_exception(exc)) from exc

    def check_site_name(self, *, site_name: str) -> dict[str, Any]:
        return self._call(
            self._client.check_site_name,
            esa_models.CheckSiteNameRequest(site_name=str(site_name).strip()),
        )

    def list_user_rate_plan_instances(
        self,
        *,
        check_remaining_site_quota: bool = True,
        status: str = "online",
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        payload = self._call(
            self._client.list_user_rate_plan_instances,
            esa_models.ListUserRatePlanInstancesRequest(
                check_remaining_site_quota=(
                    "true" if check_remaining_site_quota else "false"
                ),
                status=str(status or "").strip() or None,
                page_number=1,
                page_size=max(1, min(500, int(page_size))),
            ),
        )
        items = payload.get("InstanceInfo")
        return items if isinstance(items, list) else []

    def list_sites(
        self,
        *,
        site_name: str | None = None,
        site_search_type: str = "exact",
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        payload = self._call(
            self._client.list_sites,
            esa_models.ListSitesRequest(
                site_name=str(site_name or "").strip() or None,
                site_search_type=site_search_type,
                page_number=1,
                page_size=max(1, min(500, int(page_size))),
            ),
        )
        items = payload.get("Sites")
        return items if isinstance(items, list) else []

    def get_site(self, *, site_name: str) -> dict[str, Any] | None:
        normalized_site_name = str(site_name or "").strip().lower()
        for item in self.list_sites(site_name=site_name, site_search_type="exact"):
            item_site_name = str(item.get("SiteName") or "").strip().lower()
            if item_site_name == normalized_site_name:
                return item
        return None

    def create_site(
        self,
        *,
        site_name: str,
        coverage: str,
        access_type: str,
        instance_id: str,
        resource_group_id: str | None = None,
    ) -> dict[str, Any]:
        return self._call(
            self._client.create_site,
            esa_models.CreateSiteRequest(
                site_name=str(site_name).strip(),
                coverage=str(coverage).strip(),
                access_type=str(access_type).strip(),
                instance_id=str(instance_id).strip(),
                resource_group_id=str(resource_group_id or "").strip() or None,
            ),
        )

    def verify_site(self, *, site_id: int) -> dict[str, Any]:
        return self._call(
            self._client.verify_site,
            esa_models.VerifySiteRequest(site_id=int(site_id)),
        )

    def get_site_current_ns(self, *, site_id: int) -> list[str]:
        payload = self._call(
            self._client.get_site_current_ns,
            esa_models.GetSiteCurrentNSRequest(site_id=int(site_id)),
        )
        nameservers = payload.get("NSList")
        return nameservers if isinstance(nameservers, list) else []

    def list_records(
        self,
        *,
        site_id: int,
        record_name: str | None = None,
        record_type: str | None = None,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        payload = self._call(
            self._client.list_records,
            esa_models.ListRecordsRequest(
                site_id=int(site_id),
                record_name=str(record_name or "").strip() or None,
                record_match_type="exact" if record_name else None,
                type=str(record_type or "").strip() or None,
                page_number=1,
                page_size=max(1, min(500, int(page_size))),
            ),
        )
        items = payload.get("Records")
        return items if isinstance(items, list) else []

    def get_origin_pool(
        self,
        *,
        site_id: int,
        origin_pool_id: int,
    ) -> dict[str, Any]:
        payload = self._call(
            self._client.get_origin_pool,
            esa_models.GetOriginPoolRequest(
                site_id=int(site_id),
                id=int(origin_pool_id),
            ),
        )
        origin_pool = payload.get("OriginPool")
        return origin_pool if isinstance(origin_pool, dict) else payload

    def list_origin_pools(
        self,
        *,
        site_id: int,
        name: str | None = None,
        match_type: str | None = None,
        order_by: str | None = None,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        payload = self._call(
            self._client.list_origin_pools,
            esa_models.ListOriginPoolsRequest(
                site_id=int(site_id),
                name=str(name or "").strip() or None,
                match_type=str(match_type or "").strip() or None,
                order_by=str(order_by or "").strip() or None,
                page_number=1,
                page_size=max(1, min(500, int(page_size))),
            ),
        )
        items = payload.get("OriginPools")
        return items if isinstance(items, list) else []

    def get_load_balancer(
        self,
        *,
        site_id: int,
        load_balancer_id: int,
    ) -> dict[str, Any]:
        payload = self._call(
            self._client.get_load_balancer,
            esa_models.GetLoadBalancerRequest(
                site_id=int(site_id),
                id=int(load_balancer_id),
            ),
        )
        load_balancer = payload.get("LoadBalancer")
        return load_balancer if isinstance(load_balancer, dict) else payload

    def list_load_balancers(
        self,
        *,
        site_id: int,
        name: str | None = None,
        match_type: str | None = None,
        order_by: str | None = None,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        payload = self._call(
            self._client.list_load_balancers,
            esa_models.ListLoadBalancersRequest(
                site_id=int(site_id),
                name=str(name or "").strip() or None,
                match_type=str(match_type or "").strip() or None,
                order_by=str(order_by or "").strip() or None,
                page_number=1,
                page_size=max(1, min(500, int(page_size))),
            ),
        )
        items = payload.get("LoadBalancers")
        return items if isinstance(items, list) else []

    def list_load_balancer_origin_status(
        self,
        *,
        site_id: int,
        load_balancer_ids: list[int],
        pool_type: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_ids = [
            str(int(item))
            for item in load_balancer_ids
            if isinstance(item, int) and item > 0
        ]
        if not normalized_ids:
            return []
        payload = self._call(
            self._client.list_load_balancer_origin_status,
            esa_models.ListLoadBalancerOriginStatusRequest(
                site_id=int(site_id),
                load_balancer_ids=",".join(normalized_ids),
                pool_type=str(pool_type or "").strip() or None,
            ),
        )
        items = payload.get("OriginStatus")
        return items if isinstance(items, list) else []

    def create_origin_pool(
        self,
        *,
        site_id: int,
        name: str,
        origins: list[dict[str, Any]],
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        payload = {
            "SiteId": int(site_id),
            "Name": str(name).strip(),
            "Origins": list(origins or []),
        }
        if enabled is not None:
            payload["Enabled"] = bool(enabled)
        request = esa_models.CreateOriginPoolRequest().from_map(payload)
        return self._call(self._client.create_origin_pool, request)

    def update_origin_pool(
        self,
        *,
        site_id: int,
        origin_pool_id: int,
        origins: list[dict[str, Any]],
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        payload = {
            "SiteId": int(site_id),
            "Id": int(origin_pool_id),
            "Origins": list(origins or []),
        }
        if enabled is not None:
            payload["Enabled"] = bool(enabled)
        request = esa_models.UpdateOriginPoolRequest().from_map(payload)
        return self._call(self._client.update_origin_pool, request)

    def create_record(
        self,
        *,
        site_id: int,
        record_name: str,
        record_type: str,
        ttl: int,
        data_value: str,
        proxied: bool | None = None,
        biz_name: str | None = None,
        source_type: str | None = None,
        comment: str | None = None,
        host_policy: str | None = None,
        data_extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "SiteId": int(site_id),
            "RecordName": str(record_name).strip(),
            "Type": str(record_type).strip(),
            "Ttl": int(ttl),
            "Data": {"Value": str(data_value).strip()},
        }
        if data_extra:
            payload["Data"].update(data_extra)
        if proxied is not None:
            payload["Proxied"] = bool(proxied)
        if biz_name:
            payload["BizName"] = str(biz_name).strip()
        if source_type:
            payload["SourceType"] = str(source_type).strip()
        if comment:
            payload["Comment"] = str(comment).strip()
        if host_policy:
            payload["HostPolicy"] = str(host_policy).strip()
        request = esa_models.CreateRecordRequest().from_map(payload)
        return self._call(self._client.create_record, request)

    def update_record(
        self,
        *,
        record_id: int,
        record_type: str,
        ttl: int,
        data_value: str,
        proxied: bool | None = None,
        biz_name: str | None = None,
        source_type: str | None = None,
        comment: str | None = None,
        host_policy: str | None = None,
        data_extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "RecordId": int(record_id),
            "Type": str(record_type).strip(),
            "Ttl": int(ttl),
            "Data": {"Value": str(data_value).strip()},
        }
        if data_extra:
            payload["Data"].update(data_extra)
        if proxied is not None:
            payload["Proxied"] = bool(proxied)
        if biz_name:
            payload["BizName"] = str(biz_name).strip()
        if source_type:
            payload["SourceType"] = str(source_type).strip()
        if comment:
            payload["Comment"] = str(comment).strip()
        if host_policy:
            payload["HostPolicy"] = str(host_policy).strip()
        request = esa_models.UpdateRecordRequest().from_map(payload)
        return self._call(self._client.update_record, request)

    def delete_record(self, *, record_id: int) -> dict[str, Any]:
        return self._call(
            self._client.delete_record,
            esa_models.DeleteRecordRequest(record_id=int(record_id)),
        )

    def list_origin_rules(
        self,
        *,
        site_id: int,
        rule_name: str | None = None,
        config_type: str = "rule",
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        payload = self._call(
            self._client.list_origin_rules,
            esa_models.ListOriginRulesRequest(
                site_id=int(site_id),
                rule_name=str(rule_name or "").strip() or None,
                config_type=str(config_type or "").strip() or None,
                page_number=1,
                page_size=max(1, min(500, int(page_size))),
            ),
        )
        items = payload.get("Configs")
        return items if isinstance(items, list) else []

    def create_origin_rule(
        self,
        *,
        site_id: int,
        rule_name: str,
        rule: str,
        rule_enable: str,
        origin_scheme: str,
        origin_host: str | None = None,
        origin_http_port: str | None = None,
        origin_https_port: str | None = None,
        origin_sni: str | None = None,
        origin_verify: str | None = None,
        origin_read_timeout: str | None = None,
        sequence: int | None = None,
    ) -> dict[str, Any]:
        request = esa_models.CreateOriginRuleRequest(
            site_id=int(site_id),
            rule_name=str(rule_name).strip(),
            rule=str(rule).strip(),
            rule_enable=str(rule_enable).strip(),
            origin_scheme=str(origin_scheme).strip(),
            origin_host=str(origin_host or "").strip() or None,
            origin_http_port=str(origin_http_port or "").strip() or None,
            origin_https_port=str(origin_https_port or "").strip() or None,
            origin_sni=str(origin_sni or "").strip() or None,
            origin_verify=str(origin_verify or "").strip() or None,
            origin_read_timeout=str(origin_read_timeout or "").strip() or None,
            sequence=sequence,
        )
        return self._call(self._client.create_origin_rule, request)

    def update_origin_rule(
        self,
        *,
        site_id: int,
        config_id: int,
        rule_name: str,
        rule: str,
        rule_enable: str,
        origin_scheme: str,
        origin_host: str | None = None,
        origin_http_port: str | None = None,
        origin_https_port: str | None = None,
        origin_sni: str | None = None,
        origin_verify: str | None = None,
        origin_read_timeout: str | None = None,
        sequence: int | None = None,
    ) -> dict[str, Any]:
        request = esa_models.UpdateOriginRuleRequest(
            site_id=int(site_id),
            config_id=int(config_id),
            rule_name=str(rule_name).strip(),
            rule=str(rule).strip(),
            rule_enable=str(rule_enable).strip(),
            origin_scheme=str(origin_scheme).strip(),
            origin_host=str(origin_host or "").strip() or None,
            origin_http_port=str(origin_http_port or "").strip() or None,
            origin_https_port=str(origin_https_port or "").strip() or None,
            origin_sni=str(origin_sni or "").strip() or None,
            origin_verify=str(origin_verify or "").strip() or None,
            origin_read_timeout=str(origin_read_timeout or "").strip() or None,
            sequence=sequence,
        )
        return self._call(self._client.update_origin_rule, request)

    def list_esa_ip_info(self, *, ips: list[str]) -> list[dict[str, Any]]:
        normalized_ips = [str(item).strip() for item in ips if str(item).strip()]
        if not normalized_ips:
            return []
        payload = self._call(
            self._client.list_esaipinfo,
            esa_models.ListESAIPInfoRequest(vip_info=",".join(normalized_ips[:20])),
        )
        items = payload.get("Content")
        return items if isinstance(items, list) else []
