from __future__ import annotations

from typing import Any

from alibabacloud_tea_openapi import models as open_api_models


class AliDirectMailError(RuntimeError):
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
            return nested if isinstance(nested, dict) else payload
    return {}


def _stringify_exception(exc: Exception) -> str:
    code = str(getattr(exc, "code", "") or "").strip()
    message = str(getattr(exc, "message", "") or str(exc)).strip()
    return f"{code}: {message}" if code and message else message or type(exc).__name__


def build_single_send_mail_payload(
    *,
    account_name: str,
    to_address: str,
    subject: str,
    text_body: str | None = None,
    html_body: str | None = None,
    address_type: int = 1,
    reply_to_address: bool = False,
    from_alias: str | None = None,
    tag_name: str | None = None,
) -> dict[str, Any]:
    if not text_body and not html_body:
        raise ValueError("Either text_body or html_body is required")
    payload: dict[str, Any] = {
        "account_name": str(account_name).strip(),
        "address_type": int(address_type),
        "reply_to_address": bool(reply_to_address),
        "to_address": str(to_address).strip(),
        "subject": str(subject).strip(),
    }
    if text_body:
        payload["text_body"] = text_body
    if html_body:
        payload["html_body"] = html_body
    if from_alias:
        payload["from_alias"] = str(from_alias).strip()
    if tag_name:
        payload["tag_name"] = str(tag_name).strip()
    return payload


def build_create_mail_address_payload(
    *,
    account_name: str,
    sendtype: str = "trigger",
    reply_address: str | None = None,
) -> dict[str, Any]:
    normalized_account = str(account_name).strip()
    if not normalized_account:
        raise ValueError("account_name is required")
    normalized_sendtype = str(sendtype or "trigger").strip()
    if normalized_sendtype not in {"batch", "trigger"}:
        raise ValueError("sendtype must be one of: batch, trigger")
    payload: dict[str, Any] = {
        "account_name": normalized_account,
        "sendtype": normalized_sendtype,
    }
    if reply_address:
        payload["reply_address"] = str(reply_address).strip()
    return payload


def build_create_domain_payload(
    *,
    domain_name: str,
    dkim_selector: str | None = None,
) -> dict[str, Any]:
    normalized_domain = str(domain_name).strip()
    if not normalized_domain:
        raise ValueError("domain_name is required")
    payload: dict[str, Any] = {"domain_name": normalized_domain}
    if dkim_selector:
        payload["dkim_selector"] = str(dkim_selector).strip()
    return payload


def build_query_domain_payload(
    *,
    key_word: str = "",
    page_no: int = 1,
    page_size: int = 10,
    status: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "page_no": int(page_no),
        "page_size": int(page_size),
    }
    if key_word:
        payload["key_word"] = str(key_word).strip()
    if status is not None:
        payload["status"] = int(status)
    return payload


def build_query_mail_address_payload(
    *,
    key_word: str = "",
    page_no: int = 1,
    page_size: int = 10,
    sendtype: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "page_no": int(page_no),
        "page_size": int(page_size),
    }
    if key_word:
        payload["key_word"] = str(key_word).strip()
    if sendtype:
        normalized_sendtype = str(sendtype).strip()
        if normalized_sendtype not in {"batch", "trigger"}:
            raise ValueError("sendtype must be one of: batch, trigger")
        payload["sendtype"] = normalized_sendtype
    return payload


class AliDirectMailClient:
    def __init__(
        self,
        *,
        access_key_id: str,
        access_key_secret: str,
        endpoint: str = "dm.aliyuncs.com",
        region_id: str = "cn-hangzhou",
    ):
        self.access_key_id = str(access_key_id or "").strip()
        self.access_key_secret = str(access_key_secret or "").strip()
        if not self.access_key_id or not self.access_key_secret:
            raise ValueError("Aliyun DirectMail AccessKey credentials are required")
        self.endpoint = str(endpoint or "dm.aliyuncs.com").strip()
        self.region_id = str(region_id or "cn-hangzhou").strip()
        self._client = self._build_client()

    def _build_client(self):
        try:
            from alibabacloud_dm20151123.client import Client as DmClient
        except ImportError as exc:  # pragma: no cover - optional dependency.
            raise ImportError(
                "Alibaba Cloud DirectMail support requires alibabacloud_dm20151123. "
                "Install it with `pip install webu[ali-email]`."
            ) from exc
        return DmClient(
            open_api_models.Config(
                access_key_id=self.access_key_id,
                access_key_secret=self.access_key_secret,
                endpoint=self.endpoint,
                region_id=self.region_id,
            )
        )

    def single_send_mail(self, **kwargs) -> dict[str, Any]:
        try:
            from alibabacloud_dm20151123 import models as dm_models

            payload = build_single_send_mail_payload(**kwargs)
            request = dm_models.SingleSendMailRequest(**payload)
            return _unwrap_body(self._client.single_send_mail(request))
        except Exception as exc:  # pragma: no cover - SDK typing is broad.
            if isinstance(exc, (ValueError, ImportError)):
                raise
            raise AliDirectMailError(_stringify_exception(exc)) from exc

    def create_mail_address(self, **kwargs) -> dict[str, Any]:
        try:
            from alibabacloud_dm20151123 import models as dm_models

            payload = build_create_mail_address_payload(**kwargs)
            request = dm_models.CreateMailAddressRequest(**payload)
            return _unwrap_body(self._client.create_mail_address(request))
        except Exception as exc:  # pragma: no cover - SDK typing is broad.
            if isinstance(exc, (ValueError, ImportError)):
                raise
            raise AliDirectMailError(_stringify_exception(exc)) from exc

    def create_domain(self, **kwargs) -> dict[str, Any]:
        try:
            from alibabacloud_dm20151123 import models as dm_models

            payload = build_create_domain_payload(**kwargs)
            request = dm_models.CreateDomainRequest(**payload)
            return _unwrap_body(self._client.create_domain(request))
        except Exception as exc:  # pragma: no cover - SDK typing is broad.
            if isinstance(exc, (ValueError, ImportError)):
                raise
            raise AliDirectMailError(_stringify_exception(exc)) from exc

    def query_domains(self, **kwargs) -> dict[str, Any]:
        try:
            from alibabacloud_dm20151123 import models as dm_models

            payload = build_query_domain_payload(**kwargs)
            request = dm_models.QueryDomainByParamRequest(**payload)
            return _unwrap_body(self._client.query_domain_by_param(request))
        except Exception as exc:  # pragma: no cover - SDK typing is broad.
            if isinstance(exc, (ValueError, ImportError)):
                raise
            raise AliDirectMailError(_stringify_exception(exc)) from exc

    def query_mail_addresses(self, **kwargs) -> dict[str, Any]:
        try:
            from alibabacloud_dm20151123 import models as dm_models

            payload = build_query_mail_address_payload(**kwargs)
            request = dm_models.QueryMailAddressByParamRequest(**payload)
            return _unwrap_body(self._client.query_mail_address_by_param(request))
        except Exception as exc:  # pragma: no cover - SDK typing is broad.
            if isinstance(exc, (ValueError, ImportError)):
                raise
            raise AliDirectMailError(_stringify_exception(exc)) from exc

    def desc_domain(self, *, domain_id: str | int) -> dict[str, Any]:
        try:
            from alibabacloud_dm20151123 import models as dm_models

            request = dm_models.DescDomainRequest(domain_id=int(domain_id))
            return _unwrap_body(self._client.desc_domain(request))
        except Exception as exc:  # pragma: no cover - SDK typing is broad.
            if isinstance(exc, (ValueError, ImportError)):
                raise
            raise AliDirectMailError(_stringify_exception(exc)) from exc

    def check_domain(self, *, domain_id: str | int) -> dict[str, Any]:
        try:
            from alibabacloud_dm20151123 import models as dm_models

            request = dm_models.CheckDomainRequest(domain_id=int(domain_id))
            return _unwrap_body(self._client.check_domain(request))
        except Exception as exc:  # pragma: no cover - SDK typing is broad.
            if isinstance(exc, (ValueError, ImportError)):
                raise
            raise AliDirectMailError(_stringify_exception(exc)) from exc
