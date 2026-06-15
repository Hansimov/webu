from __future__ import annotations

import json

from typing import Any

from webu.cf_tunnel.clients import (
    DEFAULT_CLOUDFLARE_API_TIMEOUT_SECONDS,
    CloudflareApiError,
    CloudflareClient,
)


class CloudflareEmailClient(CloudflareClient):
    def _request_multipart(self, method: str, path: str, *, files: dict[str, Any]) -> Any:
        url = f"https://api.cloudflare.com/client/v4{path}"
        response = self.session.request(
            method,
            url,
            files=files,
            headers={"Authorization": f"Bearer {self.api_token}"},
            timeout=DEFAULT_CLOUDFLARE_API_TIMEOUT_SECONDS,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        payload = payload if isinstance(payload, dict) else {}
        if response.status_code >= 400 or not payload.get("success", False):
            errors = payload.get("errors") or []
            detail = (
                "; ".join(str(item.get("message", item)) for item in errors)
                or response.text
            )
            raise CloudflareApiError(detail)
        return payload.get("result")

    def get_email_routing_settings(self, *, zone_id: str) -> dict[str, Any]:
        result = self._request("GET", f"/zones/{zone_id}/email/routing")
        return result if isinstance(result, dict) else {}

    def enable_email_routing_dns(self, *, zone_id: str) -> dict[str, Any]:
        result = self._request("POST", f"/zones/{zone_id}/email/routing/dns")
        return result if isinstance(result, dict) else {}

    def list_destination_addresses(self, *, account_id: str) -> list[dict[str, Any]]:
        result = self._request("GET", f"/accounts/{account_id}/email/routing/addresses")
        return result if isinstance(result, list) else []

    def create_destination_address(
        self, *, account_id: str, email: str
    ) -> dict[str, Any]:
        result = self._request(
            "POST",
            f"/accounts/{account_id}/email/routing/addresses",
            json_body={"email": str(email).strip()},
        )
        return result if isinstance(result, dict) else {}

    def list_routing_rules(self, *, zone_id: str) -> list[dict[str, Any]]:
        result = self._request("GET", f"/zones/{zone_id}/email/routing/rules")
        return result if isinstance(result, list) else []

    def create_routing_rule(
        self,
        *,
        zone_id: str,
        address: str,
        action_type: str,
        action_values: list[str] | None = None,
        name: str | None = None,
        enabled: bool = True,
        priority: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name or f"Route {address}",
            "enabled": bool(enabled),
            "matchers": [{"type": "literal", "field": "to", "value": address}],
            "actions": [{"type": action_type, "value": action_values or []}],
        }
        if priority is not None:
            payload["priority"] = int(priority)
        result = self._request(
            "POST", f"/zones/{zone_id}/email/routing/rules", json_body=payload
        )
        return result if isinstance(result, dict) else {}

    def update_routing_rule(
        self,
        *,
        zone_id: str,
        rule_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        result = self._request(
            "PUT",
            f"/zones/{zone_id}/email/routing/rules/{rule_id}",
            json_body=payload,
        )
        return result if isinstance(result, dict) else {}

    def upload_worker_script(
        self,
        *,
        account_id: str,
        script_name: str,
        script: str,
        compatibility_date: str = "2026-06-15",
    ) -> dict[str, Any]:
        metadata = {
            "main_module": "worker.js",
            "compatibility_date": compatibility_date,
        }
        result = self._request_multipart(
            "PUT",
            f"/accounts/{account_id}/workers/scripts/{script_name}",
            files={
                "metadata": (None, json.dumps(metadata), "application/json"),
                "worker.js": ("worker.js", script, "application/javascript+module"),
            },
        )
        return result if isinstance(result, dict) else {}

    def put_worker_secret(
        self,
        *,
        account_id: str,
        script_name: str,
        name: str,
        text: str,
    ) -> dict[str, Any]:
        result = self._request(
            "PUT",
            f"/accounts/{account_id}/workers/scripts/{script_name}/secrets",
            json_body={
                "name": str(name).strip(),
                "text": str(text),
                "type": "secret_text",
            },
        )
        return result if isinstance(result, dict) else {}
