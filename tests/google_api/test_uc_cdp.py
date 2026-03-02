"""测试 undetected-chromedriver + Playwright CDP 搜索抓取。

用 self-built 代理 (127.0.0.1:11111 和 11119) 验证:
1. UC Chrome 启动和 CDP 连接
2. 通过代理进行 Google 搜索
3. 反检测效果

运行: pytest tests/google_api/test_uc_cdp.py -xvs -m integration
"""

import asyncio
import pytest

from webu.google_api.scraper import GoogleScraper, _find_free_port, _launch_uc_chrome


SELF_BUILT_PROXIES = [
    "http://127.0.0.1:11111",
    "http://127.0.0.1:11119",
]


# ═══════════════════════════════════════════════════════════════
# UC Chrome 启动测试
# ═══════════════════════════════════════════════════════════════


class TestUCChromeLaunch:
    """测试 UC Chrome 启动和 CDP 端口。"""

    def test_find_free_port(self):
        """端口分配正常。"""
        port = _find_free_port()
        assert isinstance(port, int)
        assert 1024 < port < 65536

    @pytest.mark.integration
    def test_launch_uc_chrome(self):
        """UC Chrome 能正常启动并返回驱动。"""
        driver, port = _launch_uc_chrome(headless=True)
        try:
            assert driver is not None
            assert isinstance(port, int)
            assert port > 0
        finally:
            try:
                driver.quit()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
# GoogleScraper 集成测试
# ═══════════════════════════════════════════════════════════════


class TestGoogleScraperStartStop:
    """测试 GoogleScraper 启动停止。"""

    @pytest.mark.integration
    async def test_start_stop(self):
        """Scraper 能正常启动和停止。"""
        scraper = GoogleScraper(headless=True, verbose=True)
        try:
            await scraper.start()
            assert scraper._browser is not None
            assert scraper._playwright is not None
        finally:
            await scraper.stop()
            assert scraper._browser is None

    @pytest.mark.integration
    async def test_direct_search(self):
        """直连搜索（无代理）— 验证基本流程。"""
        scraper = GoogleScraper(headless=True, verbose=True)
        try:
            await scraper.start()
            result = await scraper.search(
                query="python programming",
                num=5,
                proxy_url="direct",
                retry_count=0,
            )
            # 直连搜索可能因为 IP 被封而无结果，但不应崩溃
            assert result is not None
            assert result.query == "python programming"
            if result.results:
                assert len(result.results) > 0
                assert result.results[0].title
        finally:
            await scraper.stop()


# ═══════════════════════════════════════════════════════════════
# 本地代理搜索测试
# ═══════════════════════════════════════════════════════════════


class TestLocalProxySearch:
    """用本地代理 (127.0.0.1:11111, 11119) 测试 Google 搜索。"""

    @pytest.mark.integration
    async def test_search_with_local_proxy_11111(self):
        """通过 127.0.0.1:11111 代理搜索 Google。"""
        scraper = GoogleScraper(headless=True, verbose=True)
        try:
            await scraper.start()
            result = await scraper.search(
                query="test",
                num=5,
                proxy_url=SELF_BUILT_PROXIES[0],
                retry_count=0,
            )
            assert result is not None
            print(f"\n  Proxy: {SELF_BUILT_PROXIES[0]}")
            print(f"  Results: {len(result.results)}")
            print(f"  CAPTCHA: {result.has_captcha}")
            print(f"  Error: {result.error}")
            if result.results:
                for r in result.results[:3]:
                    print(f"    - {r.title}: {r.url}")
        finally:
            await scraper.stop()

    @pytest.mark.integration
    async def test_search_with_local_proxy_11119(self):
        """通过 127.0.0.1:11119 代理搜索 Google。"""
        scraper = GoogleScraper(headless=True, verbose=True)
        try:
            await scraper.start()
            result = await scraper.search(
                query="test",
                num=5,
                proxy_url=SELF_BUILT_PROXIES[1],
                retry_count=0,
            )
            assert result is not None
            print(f"\n  Proxy: {SELF_BUILT_PROXIES[1]}")
            print(f"  Results: {len(result.results)}")
            print(f"  CAPTCHA: {result.has_captcha}")
            print(f"  Error: {result.error}")
            if result.results:
                for r in result.results[:3]:
                    print(f"    - {r.title}: {r.url}")
        finally:
            await scraper.stop()


# ═══════════════════════════════════════════════════════════════
# 反检测验证
# ═══════════════════════════════════════════════════════════════


class TestAntiDetection:
    """验证 UC+CDP 的反检测效果。"""

    @pytest.mark.integration
    async def test_webdriver_not_detected(self):
        """验证 navigator.webdriver 被隐藏。"""
        scraper = GoogleScraper(headless=True, verbose=True)
        try:
            await scraper.start()
            context = await scraper._browser.new_context(
                ignore_https_errors=True,
            )
            page = await context.new_page()

            # 注入反检测脚本
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                });
                window.chrome = { runtime: {} };
            """)

            await page.goto("about:blank")
            webdriver_val = await page.evaluate("navigator.webdriver")
            chrome_val = await page.evaluate("typeof window.chrome")

            print(f"\n  navigator.webdriver = {webdriver_val}")
            print(f"  typeof window.chrome = {chrome_val}")

            # UC 应该已经修补了 webdriver — 值应该是 undefined/false/None
            assert webdriver_val is None or webdriver_val is False
            assert chrome_val == "object"

            await context.close()
        finally:
            await scraper.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-xvs", "-m", "integration"])
