"""临时测试脚本：验证浏览器代理连接是否正常工作。"""

import asyncio
from webu.gemini.browser import GeminiBrowser
from webu.gemini.config import GeminiConfig


async def test():
    config = GeminiConfig()
    browser = GeminiBrowser(config=config)
    try:
        await browser.start()
        print("Browser started")

        # 测试访问 google.com
        print("Navigating to google.com...")
        try:
            resp = await browser.page.goto(
                "https://www.google.com",
                timeout=30000,
                wait_until="domcontentloaded",
            )
            status = resp.status if resp else "no response"
            title = await browser.page.title()
            url = browser.page.url
            print(f"  Status: {status}")
            print(f"  Title: {title}")
            print(f"  URL: {url}")
            if resp and resp.status == 200:
                print("  SUCCESS: google.com accessible via proxy!")
            else:
                print(f"  WARNING: unexpected status {status}")
        except Exception as e:
            print(f"  FAILED navigating to google.com: {e}")

        # 测试访问 gemini.google.com
        print("\nNavigating to gemini.google.com...")
        try:
            resp = await browser.page.goto(
                "https://gemini.google.com/app",
                timeout=30000,
                wait_until="domcontentloaded",
            )
            status = resp.status if resp else "no response"
            title = await browser.page.title()
            url = browser.page.url
            print(f"  Status: {status}")
            print(f"  Title: {title}")
            print(f"  URL: {url}")
        except Exception as e:
            print(f"  FAILED navigating to gemini: {e}")
    finally:
        await browser.stop()


if __name__ == "__main__":
    asyncio.run(test())
