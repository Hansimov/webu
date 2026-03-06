"""Debug script: fetch Google search HTML and test parser."""

import asyncio
import aiohttp
from aiohttp_socks import ProxyConnector
from pathlib import Path
from webu.proxy_api.checker import _random_ua, _build_proxy_url
from webu.google_api.checker import _LEVEL2_HEADERS
from webu.google_api.parser import GoogleResultParser
from webu.google_api.constants import GOOGLE_SEARCH_URL
from webu.proxy_api.mongo import MongoProxyStore


async def main():
    store = MongoProxyStore(verbose=True)
    proxies = store.get_valid_proxies(limit=50, max_latency_ms=15000)

    query = "python programming"
    output_dir = Path("data/debug/html")
    output_dir.mkdir(parents=True, exist_ok=True)

    parser = GoogleResultParser(verbose=True)

    for i, proxy in enumerate(proxies[:20]):
        proxy_url = proxy.get("proxy_url") or _build_proxy_url(
            proxy["ip"], proxy["port"], proxy["protocol"]
        )
        protocol = proxy["protocol"]
        print(f"\n[{i+1}] Trying {proxy_url} ...")

        try:
            timeout = aiohttp.ClientTimeout(total=20)
            headers = {**_LEVEL2_HEADERS, "User-Agent": _random_ua()}
            is_socks = protocol in ("socks4", "socks5")

            if is_socks:
                connector = ProxyConnector.from_url(proxy_url)
                session = aiohttp.ClientSession(
                    connector=connector,
                    headers=headers,
                    timeout=timeout,
                )
                kwargs = {"ssl": False}
            else:
                session = aiohttp.ClientSession(
                    headers=headers,
                    timeout=timeout,
                )
                kwargs = {"ssl": False, "proxy": proxy_url}

            url = f"{GOOGLE_SEARCH_URL}?q={query.replace(' ', '+')}&num=10&hl=en"

            async with session:
                async with session.get(url, **kwargs) as resp:
                    body = await resp.text()
                    print(f"  Status: {resp.status}, Body length: {len(body)}")

                    if len(body) > 1000:
                        # Save HTML
                        safe_ip = proxy["ip"].replace(".", "_")
                        filename = f"google_{safe_ip}_{proxy['port']}.html"
                        filepath = output_dir / filename
                        filepath.write_text(body, encoding="utf-8")
                        print(f"  Saved to: {filepath}")

                        # Parse
                        result = parser.parse(body, query=query)
                        print(f"  Results: {len(result.results)}")
                        print(f"  CAPTCHA: {result.has_captcha}")
                        print(f"  Total: {result.total_results_text}")
                        print(f"  Clean HTML: {result.clean_html_length}")

                        if result.results:
                            for r in result.results[:3]:
                                print(f"    - {r.title}")
                                print(f"      {r.url}")
                            return  # Found working proxy, stop
                        elif not result.has_captcha:
                            print("  → Parser found no results in valid HTML!")
                            # Dump a snippet for debugging
                            from bs4 import BeautifulSoup

                            soup = BeautifulSoup(body, "html.parser")
                            divg = soup.select("div.g")
                            print(f"  div.g count: {len(divg)}")
                            rso = soup.find("div", id="rso")
                            print(f"  #rso found: {rso is not None}")
                            search_div = soup.find("div", id="search")
                            print(f"  #search found: {search_div is not None}")
                            # Check links
                            links = soup.find_all("a", href=True)
                            external = [
                                a
                                for a in links
                                if a["href"].startswith("http")
                                and "google" not in a["href"]
                            ]
                            print(f"  External links: {len(external)}")
                            for a in external[:5]:
                                print(f"    → {a['href'][:80]}")
                            return  # Debug one, then stop

        except Exception as e:
            print(f"  Error: {e}")
            continue


if __name__ == "__main__":
    asyncio.run(main())
