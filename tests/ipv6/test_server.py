import requests

from webu.ipv6 import session as ipv6_session_module
from webu.ipv6.constants import CHECK_URLS
from webu.ipv6.server import IPv6DBServer


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeSession:
    def __init__(self, responders: dict[str, object], calls: list[str]):
        self.responders = responders
        self.calls = calls

    def get(self, url: str, timeout: float):
        self.calls.append(url)
        result = self.responders[url]
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        return None


def make_server(check_url: str | None = None, check_urls: list[str] | None = None):
    server = object.__new__(IPv6DBServer)
    server.check_urls = IPv6DBServer._normalize_check_urls(check_url, check_urls)
    server.check_url = server.check_urls[0]
    server._preferred_check_url = server.check_url
    server.check_timeout = 5.0
    server.verbose = False
    return server


def patch_ipv6_adapter(monkeypatch):
    monkeypatch.setattr(
        ipv6_session_module.IPv6SessionAdapter,
        "save_family",
        lambda: None,
    )
    monkeypatch.setattr(
        ipv6_session_module.IPv6SessionAdapter,
        "restore_family",
        lambda saved: None,
    )
    monkeypatch.setattr(
        ipv6_session_module.IPv6SessionAdapter,
        "force_ipv6",
        lambda: None,
    )
    monkeypatch.setattr(
        ipv6_session_module.IPv6SessionAdapter,
        "adapt",
        lambda session, addr: session,
    )


def test_check_falls_back_to_next_url_when_first_url_fails(monkeypatch):
    addr = "2408:820c:685d:f1b0::1234"
    bad_url = "https://bad.example"
    good_url = "https://good.example"
    calls: list[str] = []
    responders = {
        bad_url: requests.ConnectionError("dns failure"),
        good_url: FakeResponse(addr),
    }

    patch_ipv6_adapter(monkeypatch)
    monkeypatch.setattr(requests, "Session", lambda: FakeSession(responders, calls))

    server = make_server(check_url=bad_url, check_urls=[good_url])

    assert server.check(addr) is True
    assert calls == [bad_url, good_url]
    assert server.check_url == good_url
    assert server._preferred_check_url == good_url


def test_check_continues_when_first_url_echoes_wrong_ip(monkeypatch):
    addr = "2408:820c:685d:f1b0::1234"
    wrong_url = "https://wrong.example"
    good_url = "https://good.example"
    calls: list[str] = []
    responders = {
        wrong_url: FakeResponse("2408:820c:685d:f1b0::9999"),
        good_url: FakeResponse(addr),
    }

    patch_ipv6_adapter(monkeypatch)
    monkeypatch.setattr(requests, "Session", lambda: FakeSession(responders, calls))

    server = make_server(check_url=wrong_url, check_urls=[good_url])

    assert server.check(addr) is True
    assert calls == [wrong_url, good_url]
    assert server.check_url == good_url


def test_normalize_check_urls_prefers_custom_urls_without_duplicates():
    custom_url = "https://custom.example"

    normalized = IPv6DBServer._normalize_check_urls(
        check_url=custom_url,
        check_urls=[CHECK_URLS[1], custom_url],
    )

    assert normalized[0] == custom_url
    assert normalized.count(custom_url) == 1
    assert normalized.count(CHECK_URLS[1]) == 1
    for default_url in CHECK_URLS:
        assert default_url in normalized
