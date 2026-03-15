from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import requests


class CloudflareApiError(RuntimeError):
    pass


class AliyunApiError(RuntimeError):
    pass


class CloudflareClient:
    def __init__(self, api_token: str, *, session: requests.Session | None = None):
        self.api_token = str(api_token).strip()
        if not self.api_token:
            raise ValueError("Cloudflare API token is required")
        self.session = session or requests.Session()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> Any:
        response = self.session.request(
            method,
            f"https://api.cloudflare.com/client/v4{path}",
            params=params,
            json=json_body,
            headers={"Authorization": f"Bearer {self.api_token}"},
            timeout=30,
        )
        payload = response.json()
        if response.status_code >= 400 or not payload.get("success", False):
            errors = payload.get("errors") or []
            detail = (
                "; ".join(str(item.get("message", item)) for item in errors)
                or response.text
            )
            raise CloudflareApiError(detail)
        return payload.get("result")

    def verify_token(self) -> dict[str, Any]:
        return self._request("GET", "/user/tokens/verify")

    def list_permission_groups(
        self, *, account_id: str | None = None
    ) -> list[dict[str, Any]]:
        path = "/user/tokens/permission_groups"
        if account_id:
            path = f"/accounts/{account_id}/tokens/permission_groups"
        result = self._request("GET", path)
        return result if isinstance(result, list) else []

    def _permission_group(
        self, groups: list[dict[str, Any]], candidates: list[str], *, scope: str
    ) -> dict[str, Any]:
        normalized_scope = scope.lower()
        lowered_candidates = [item.lower() for item in candidates]
        for group in groups:
            name = str(group.get("name", "")).strip()
            scopes = [str(item).lower() for item in group.get("scopes", [])]
            if normalized_scope not in " ".join(scopes):
                continue
            if name.lower() in lowered_candidates:
                return {"id": group["id"], "name": name}
        raise CloudflareApiError(
            f"Could not find Cloudflare permission group matching {candidates} in scope {scope}"
        )

    def create_api_token(
        self,
        *,
        name: str,
        account_id: str,
        zone_id: str | None = None,
        include_zone_write: bool = False,
        expires_in_days: int | None = None,
    ) -> dict[str, Any]:
        def build_payload(groups: list[dict[str, Any]]) -> dict[str, Any]:
            account_policy = {
                "effect": "allow",
                "resources": {f"com.cloudflare.api.account.{account_id}": "*"},
                "permission_groups": [
                    self._permission_group(
                        groups,
                        [
                            "Cloudflare Tunnel Write",
                            "Cloudflare One Connector: cloudflared Write",
                            "Cloudflare One Connectors Write",
                        ],
                        scope="com.cloudflare.api.account",
                    )
                ],
            }
            if zone_id:
                zone_resources: dict[str, Any] = {
                    f"com.cloudflare.api.account.zone.{zone_id}": "*"
                }
            else:
                zone_resources = {
                    f"com.cloudflare.api.account.{account_id}": {
                        "com.cloudflare.api.account.zone.*": "*"
                    }
                }

            zone_permissions = [
                self._permission_group(
                    groups, ["DNS Write"], scope="com.cloudflare.api.account.zone"
                )
            ]
            if include_zone_write:
                zone_permissions.append(
                    self._permission_group(
                        groups,
                        ["Zone Write", "Zone Edit"],
                        scope="com.cloudflare.api.account.zone",
                    )
                )

            payload: dict[str, Any] = {
                "name": name,
                "policies": [
                    account_policy,
                    {
                        "effect": "allow",
                        "resources": zone_resources,
                        "permission_groups": zone_permissions,
                    },
                ],
            }
            if expires_in_days:
                payload["expires_on"] = (
                    datetime.now(timezone.utc)
                    + timedelta(days=max(1, int(expires_in_days)))
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            return payload

        try:
            groups = self.list_permission_groups()
            result = self._request(
                "POST", "/user/tokens", json_body=build_payload(groups)
            )
        except CloudflareApiError as exc:
            if "Valid user-level authentication not found" not in str(exc):
                raise
            groups = self.list_permission_groups(account_id=account_id)
            result = self._request(
                "POST",
                f"/accounts/{account_id}/tokens",
                json_body=build_payload(groups),
            )

        secret = str(result.get("value") or result.get("token") or "").strip()
        if not secret:
            raise CloudflareApiError("Cloudflare did not return the new token secret")
        return {
            "id": str(result.get("id", "")).strip(),
            "name": str(result.get("name", name)).strip(),
            "value": secret,
        }

    def list_zones(
        self, *, name: str | None = None, account_id: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if name:
            params["name"] = name
        if account_id:
            params["account.id"] = account_id
        result = self._request("GET", "/zones", params=params)
        return result if isinstance(result, list) else []

    def ensure_zone(self, *, account_id: str, zone_name: str) -> dict[str, Any]:
        existing = self.list_zones(name=zone_name, account_id=account_id)
        if existing:
            return existing[0]
        return self._request(
            "POST",
            "/zones",
            json_body={
                "account": {"id": account_id},
                "name": zone_name,
                "type": "full",
            },
        )

    def get_zone(self, zone_id: str) -> dict[str, Any]:
        return self._request("GET", f"/zones/{zone_id}")

    def list_dns_records(
        self, zone_id: str, *, record_type: str | None = None, name: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if record_type:
            params["type"] = record_type
        if name:
            params["name"] = name
        result = self._request("GET", f"/zones/{zone_id}/dns_records", params=params)
        return result if isinstance(result, list) else []

    def upsert_cname_record(
        self, *, zone_id: str, hostname: str, content: str, proxied: bool = True
    ) -> dict[str, Any]:
        existing = self.list_dns_records(zone_id, record_type="CNAME", name=hostname)
        payload = {
            "type": "CNAME",
            "proxied": proxied,
            "name": hostname,
            "content": content,
        }
        if existing:
            record_id = str(existing[0].get("id", "")).strip()
            return self._request(
                "PUT", f"/zones/{zone_id}/dns_records/{record_id}", json_body=payload
            )
        return self._request("POST", f"/zones/{zone_id}/dns_records", json_body=payload)

    def list_tunnels(
        self, account_id: str, *, name: str | None = None
    ) -> list[dict[str, Any]]:
        params = {"name": name} if name else None
        result = self._request(
            "GET", f"/accounts/{account_id}/cfd_tunnel", params=params
        )
        return result if isinstance(result, list) else []

    def ensure_tunnel(self, *, account_id: str, tunnel_name: str) -> dict[str, Any]:
        existing = self.list_tunnels(account_id, name=tunnel_name)
        if existing:
            return existing[0]
        return self._request(
            "POST",
            f"/accounts/{account_id}/cfd_tunnel",
            json_body={"name": tunnel_name, "config_src": "cloudflare"},
        )

    def get_tunnel(self, *, account_id: str, tunnel_id: str) -> dict[str, Any]:
        return self._request("GET", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}")

    def get_tunnel_token(self, *, account_id: str, tunnel_id: str) -> str:
        result = self._request(
            "GET", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token"
        )
        return str(result or "").strip()

    def put_tunnel_configuration(
        self,
        *,
        account_id: str,
        tunnel_id: str,
        hostname: str,
        service: str,
    ) -> dict[str, Any]:
        payload = {
            "config": {
                "ingress": [
                    {"hostname": hostname, "service": service, "originRequest": {}},
                    {"service": "http_status:404"},
                ]
            }
        }
        return self._request(
            "PUT",
            f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
            json_body=payload,
        )


class AliyunDomainClient:
    endpoint = "https://domain.aliyuncs.com/"
    version = "2018-01-29"

    def __init__(
        self,
        access_key_id: str,
        access_key_secret: str,
        *,
        session: requests.Session | None = None,
    ):
        self.access_key_id = str(access_key_id).strip()
        self.access_key_secret = str(access_key_secret).strip()
        if not self.access_key_id or not self.access_key_secret:
            raise ValueError("Aliyun AccessKey credentials are required")
        self.session = session or requests.Session()

    @staticmethod
    def _percent_encode(value: Any) -> str:
        return quote(str(value), safe="~").replace("+", "%20").replace("*", "%2A")

    def _flatten(self, params: dict[str, Any]) -> dict[str, str]:
        flattened: dict[str, str] = {}
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, list):
                for index, item in enumerate(value, start=1):
                    flattened[f"{key}.{index}"] = str(item)
            elif isinstance(value, bool):
                flattened[key] = "true" if value else "false"
            else:
                flattened[key] = str(value)
        return flattened

    def _sign(self, params: dict[str, str]) -> dict[str, str]:
        canonical = "&".join(
            f"{self._percent_encode(key)}={self._percent_encode(value)}"
            for key, value in sorted(params.items())
        )
        string_to_sign = f"POST&%2F&{self._percent_encode(canonical)}"
        digest = hmac.new(
            f"{self.access_key_secret}&".encode(),
            string_to_sign.encode(),
            hashlib.sha1,
        ).digest()
        signature = base64.b64encode(digest).decode()
        return {**params, "Signature": signature}

    def _request(self, action: str, **params: Any) -> dict[str, Any]:
        base_params = {
            "Action": action,
            "Format": "JSON",
            "Version": self.version,
            "AccessKeyId": self.access_key_id,
            "SignatureMethod": "HMAC-SHA1",
            "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "SignatureVersion": "1.0",
            "SignatureNonce": str(uuid.uuid4()),
        }
        signed = self._sign({**base_params, **self._flatten(params)})
        response = self.session.post(self.endpoint, data=signed, timeout=30)
        payload = response.json()
        if response.status_code >= 400 or "Code" in payload:
            message = (
                payload.get("Message") or payload.get("Recommend") or response.text
            )
            raise AliyunApiError(message)
        return payload

    def modify_domain_dns(self, *, domain_name: str, nameservers: list[str]) -> str:
        payload = self._request(
            "SaveBatchTaskForModifyingDomainDns",
            DomainName=[domain_name],
            DomainNameServer=nameservers,
            AliyunDns=False,
        )
        return str(payload.get("TaskNo", "")).strip()

    def query_task_details(
        self, *, task_no: str, current_page: int = 1, page_size: int = 20
    ) -> list[dict[str, Any]]:
        payload = self._request(
            "QueryTaskDetailList",
            TaskNo=task_no,
            PageNum=current_page,
            CurrentPageNum=current_page,
            PageSize=page_size,
        )
        data = payload.get("Data", {})
        task_detail = data.get("TaskDetail", []) if isinstance(data, dict) else []
        return task_detail if isinstance(task_detail, list) else []
