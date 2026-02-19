"""Gemini 模块交互式测试脚本。

运行: python -m tests.gemini.test_interactive
"""

import asyncio
from tclogger import logger, logstr


async def test_browser_launch():
    """测试 1：浏览器启动和页面加载。"""
    from webu.gemini.browser import GeminiBrowser
    from webu.gemini.config import GeminiConfig

    logger.note("=" * 60)
    logger.note("测试 1: 浏览器启动")
    logger.note("=" * 60)

    config = GeminiConfig()
    browser = GeminiBrowser(config=config)

    try:
        await browser.start()
        logger.okay("  ✓ 浏览器启动成功")

        page = await browser.navigate_to_gemini()
        title = await page.title()
        logger.okay(f"  ✓ 页面标题: {title}")
        logger.okay(f"  ✓ 页面 URL: {page.url}")

        # 截图用于调试
        await browser.screenshot(path="data/test_screenshot_launch.png")
        logger.okay("  ✓ 截图已保存到 data/test_screenshot_launch.png")

        return browser  # 保持浏览器打开以便后续测试
    except Exception as e:
        logger.err(f"  × 浏览器启动失败: {e}")
        await browser.stop()
        raise


async def test_login_status(browser):
    """测试 2：登录状态检测。"""
    from webu.gemini.client import GeminiClient

    logger.note("=" * 60)
    logger.note("测试 2: 登录状态检测")
    logger.note("=" * 60)

    client = GeminiClient.__new__(GeminiClient)
    client.config = browser.config
    client.browser = browser
    client.parser = None
    client.is_ready = True
    client._image_mode = False

    from webu.gemini.parser import GeminiResponseParser

    client.parser = GeminiResponseParser()

    status = await client.check_login_status()
    logger.mesg(f"  登录状态: {status}")

    if not status["logged_in"]:
        import socket

        hostname = socket.gethostname()
        debug_port = browser.config.browser_port
        novnc_port = browser.config.novnc_port
        logger.warn("  ⚠ 用户未登录。")
        logger.warn("  要登录，请在你的浏览器中打开:")
        logger.warn(
            f"  Visual: http://{hostname}:{novnc_port}/vnc.html"
            f"?autoconnect=true&resize=remote"
        )
        logger.warn(
            f"  Or use chrome://inspect → Configure → '{hostname}:{debug_port}'"
        )
        logger.warn("  导航到 gemini.google.com 并登录。")
        logger.warn("  登录后按 Enter 继续...")

        # 等待用户登录
        await asyncio.get_event_loop().run_in_executor(None, input)

        # 重新检查
        # 先重新加载页面
        await browser.navigate_to_gemini()
        await asyncio.sleep(3)
        status = await client.check_login_status()
        logger.mesg(f"  手动登录后的登录状态: {status}")

    return client


async def test_send_message(client):
    """测试 3：发送消息并获取响应。"""
    logger.note("=" * 60)
    logger.note("测试 3: 发送消息")
    logger.note("=" * 60)

    try:
        # 先开始新会话
        await client.new_chat()
        await asyncio.sleep(2)

        response = await client.send_message(
            "Hello! Please respond with: 'Test successful'. Nothing else."
        )
        logger.okay(f"  ✓ 响应文本: {response.text[:200]}")
        logger.okay(f"  ✓ 响应 Markdown: {response.markdown[:200]}")
        logger.mesg(f"  图片数: {len(response.images)}")
        logger.mesg(f"  代码块数: {len(response.code_blocks)}")
        logger.mesg(f"  是否错误: {response.is_error}")

        # 截图
        await client.screenshot(path="data/test_screenshot_response.png")
        logger.okay("  ✓ 截图已保存")

        return response
    except Exception as e:
        logger.err(f"  × 发送消息失败: {e}")
        # 截图用于调试
        try:
            await client.screenshot(path="data/test_screenshot_error.png")
        except:
            pass
        raise


async def main():
    logger.note("=" * 60)
    logger.note("Gemini 模块交互式测试")
    logger.note("=" * 60)

    browser = None
    try:
        # 测试 1：浏览器启动
        browser = await test_browser_launch()

        # 测试 2：登录检查
        client = await test_login_status(browser)

        if not client:
            logger.err("未登录，无法继续")
            return

        # 测试 3：发送消息
        response = await test_send_message(client)

        logger.note("=" * 60)
        logger.okay("所有测试通过！")
        logger.note("=" * 60)

    except Exception as e:
        logger.err(f"测试失败: {e}")
        import traceback

        traceback.print_exc()
    finally:
        if browser:
            await browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
