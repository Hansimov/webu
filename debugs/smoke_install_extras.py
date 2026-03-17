from __future__ import annotations

import sys


def check_base() -> None:
    import webu
    from webu import LLMClient

    assert webu.__name__ == "webu"
    assert LLMClient.__name__ == "LLMClient"


def check_parsing() -> None:
    from webu.google_api import GoogleResultParser
    from webu.gemini.parser import GeminiResponseParser

    assert GoogleResultParser.__name__ == "GoogleResultParser"
    assert GeminiResponseParser.__name__ == "GeminiResponseParser"


def check_browser() -> None:
    from webu.browsers.chrome import ChromeClient, ChromeClientConfigType

    client = ChromeClient()
    assert client.__class__.__name__ == "ChromeClient"
    assert ChromeClientConfigType.__name__ == "ChromeClientConfigType"


def check_captcha() -> None:
    from webu.captcha import CaptchaBypass, CaptchaSolver, GridAnnotator

    assert CaptchaBypass.__name__ == "CaptchaBypass"
    assert CaptchaSolver.__name__ == "CaptchaSolver"
    assert GridAnnotator.__name__ == "GridAnnotator"


def check_google_api() -> None:
    from fastapi import FastAPI
    from webu.google_api.server import create_google_search_server

    app = create_google_search_server()
    assert isinstance(app, FastAPI)


def check_google_api_panel() -> None:
    from fastapi import FastAPI
    from webu.google_api.server import create_google_search_server

    app = create_google_search_server(home_mode="panel")
    assert isinstance(app, FastAPI)


def check_google_hub() -> None:
    from fastapi import FastAPI
    from webu.google_hub.server import create_google_hub_server

    app = create_google_hub_server()
    assert isinstance(app, FastAPI)


def check_google_hub_panel() -> None:
    from fastapi import FastAPI
    from webu.google_hub.server import create_google_hub_server

    app = create_google_hub_server()
    assert isinstance(app, FastAPI)


def check_google_docker() -> None:
    from fastapi import FastAPI
    from webu.google_docker.server import create_google_docker_server

    app = create_google_docker_server()
    assert isinstance(app, FastAPI)


def check_google_docker_panel() -> None:
    from fastapi import FastAPI
    from webu.google_docker.server import create_google_docker_server

    app = create_google_docker_server()
    assert isinstance(app, FastAPI)


def check_proxy_api() -> None:
    from fastapi import FastAPI
    from webu.proxy_api.server import create_proxy_server

    app = create_proxy_server()
    assert isinstance(app, FastAPI)


def check_warp_api() -> None:
    from fastapi import FastAPI
    from webu.warp_api.server import create_warp_server

    app = create_warp_server()
    assert isinstance(app, FastAPI)


def check_ipv6() -> None:
    from webu.ipv6.route import IPv6Prefixer, IPv6RouteUpdater

    assert IPv6Prefixer.__name__ == "IPv6Prefixer"
    assert IPv6RouteUpdater.__name__ == "IPv6RouteUpdater"


CHECKS = {
    "base": check_base,
    "parsing": check_parsing,
    "browser": check_browser,
    "captcha": check_captcha,
    "google-api": check_google_api,
    "google-api-panel": check_google_api_panel,
    "google-hub": check_google_hub,
    "google-hub-panel": check_google_hub_panel,
    "google-docker": check_google_docker,
    "google-docker-panel": check_google_docker_panel,
    "proxy-api": check_proxy_api,
    "warp-api": check_warp_api,
    "ipv6": check_ipv6,
}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in CHECKS:
        valid = ", ".join(sorted(CHECKS))
        print(f"usage: {argv[0]} <case>\nvalid: {valid}", file=sys.stderr)
        return 2

    case = argv[1]
    CHECKS[case]()
    print(f"PASS {case}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
