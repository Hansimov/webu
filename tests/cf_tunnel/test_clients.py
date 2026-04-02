import requests

from webu.cf_tunnel.clients import (
    AliyunDomainClient,
    CloudflareApiError,
    CloudflareClient,
)


def test_cloudflare_create_api_token_uses_zone_scope(monkeypatch):
    client = CloudflareClient("bootstrap-token")
    recorded = {}

    groups = [
        {
            "id": "pg-tunnel",
            "name": "Cloudflare Tunnel Write",
            "scopes": ["com.cloudflare.api.account"],
        },
        {
            "id": "pg-dns",
            "name": "DNS Write",
            "scopes": ["com.cloudflare.api.account.zone"],
        },
    ]

    monkeypatch.setattr(client, "list_permission_groups", lambda **kwargs: groups)

    def fake_request(method, path, *, params=None, json_body=None):
        recorded["method"] = method
        recorded["path"] = path
        recorded["json_body"] = json_body
        return {"id": "token-id", "name": "cftn-zone", "value": "new-secret"}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.create_api_token(
        name="cftn-zone",
        account_id="acct-1",
        zone_id="zone-1",
        include_zone_write=False,
    )

    assert result["value"] == "new-secret"
    assert recorded["method"] == "POST"
    assert recorded["path"] == "/user/tokens"
    zone_policy = recorded["json_body"]["policies"][1]
    assert zone_policy["resources"] == {"com.cloudflare.api.account.zone.zone-1": "*"}
    assert zone_policy["permission_groups"] == [{"id": "pg-dns", "name": "DNS Write"}]


def test_cloudflare_create_api_token_falls_back_to_account_tokens(monkeypatch):
    client = CloudflareClient("bootstrap-token")
    recorded = {"paths": [], "permission_calls": []}

    groups = [
        {
            "id": "pg-tunnel",
            "name": "Cloudflare Tunnel Write",
            "scopes": ["com.cloudflare.api.account"],
        },
        {
            "id": "pg-dns",
            "name": "DNS Write",
            "scopes": ["com.cloudflare.api.account.zone"],
        },
    ]

    def fake_list_permission_groups(**kwargs):
        recorded["permission_calls"].append(kwargs)
        return groups

    def fake_request(method, path, *, params=None, json_body=None):
        recorded["paths"].append(path)
        if path == "/user/tokens":
            raise CloudflareApiError("Valid user-level authentication not found")
        assert path == "/accounts/acct-1/tokens"
        return {"id": "token-id", "name": "cftn-zone", "value": "new-secret"}

    monkeypatch.setattr(client, "list_permission_groups", fake_list_permission_groups)
    monkeypatch.setattr(client, "_request", fake_request)

    result = client.create_api_token(
        name="cftn-zone",
        account_id="acct-1",
        zone_id="zone-1",
        include_zone_write=False,
    )

    assert result["value"] == "new-secret"
    assert recorded["paths"] == ["/user/tokens", "/accounts/acct-1/tokens"]
    assert recorded["permission_calls"] == [{}, {"account_id": "acct-1"}]


def test_cloudflare_request_retries_transient_connection_errors(monkeypatch):
    attempts = {"count": 0}
    sleeps: list[float] = []

    class _Response:
        status_code = 200
        headers = {}
        text = ""

        def json(self):
            return {"success": True, "result": {"ok": True}}

    class _Session:
        def request(self, method, url, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise requests.ConnectionError("temporary reset")
            return _Response()

    monkeypatch.setattr("webu.cf_tunnel.clients.time.sleep", sleeps.append)

    client = CloudflareClient("bootstrap-token", session=_Session())

    result = client._request("GET", "/zones")

    assert result == {"ok": True}
    assert attempts["count"] == 2
    assert sleeps == [1.0]


def test_cloudflare_request_retries_rate_limit_with_retry_after(monkeypatch):
    attempts = {"count": 0}
    sleeps: list[float] = []

    class _RateLimitedResponse:
        status_code = 429
        headers = {"Retry-After": "3"}
        text = "rate limited"

        def json(self):
            return {"success": False, "errors": [{"message": "rate limited"}]}

    class _SuccessResponse:
        status_code = 200
        headers = {}
        text = ""

        def json(self):
            return {"success": True, "result": {"ok": True}}

    class _Session:
        def request(self, method, url, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                return _RateLimitedResponse()
            return _SuccessResponse()

    monkeypatch.setattr("webu.cf_tunnel.clients.time.sleep", sleeps.append)

    client = CloudflareClient("bootstrap-token", session=_Session())

    result = client._request("GET", "/zones")

    assert result == {"ok": True}
    assert attempts["count"] == 2
    assert sleeps == [3.0]


def test_aliyun_modify_domain_dns_flattens_arrays(monkeypatch):
    recorded = {}

    class _Response:
        status_code = 200

        def json(self):
            return {"TaskNo": "task-123"}

    class _Session:
        def post(self, url, data, timeout):
            recorded["url"] = url
            recorded["data"] = data
            recorded["timeout"] = timeout
            return _Response()

    client = AliyunDomainClient("ak", "sk", session=_Session())

    task_no = client.modify_domain_dns(
        domain_name="example.com",
        nameservers=["ns1.cloudflare.com", "ns2.cloudflare.com"],
    )

    assert task_no == "task-123"
    assert recorded["data"]["Action"] == "SaveBatchTaskForModifyingDomainDns"
    assert recorded["data"]["DomainName.1"] == "example.com"
    assert recorded["data"]["DomainNameServer.1"] == "ns1.cloudflare.com"
    assert recorded["data"]["DomainNameServer.2"] == "ns2.cloudflare.com"
    assert recorded["data"]["AliyunDns"] == "false"
    assert "Signature" in recorded["data"]
