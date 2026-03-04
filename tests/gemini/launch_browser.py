"""持久化 Gemini 浏览器服务。

启动 Chrome + Xvnc + noVNC，保持运行。
测试脚本通过 CDP 连接到已运行的浏览器，无需重启。

用法:
    python -m tests.gemini.launch_browser

启动后打开 VNC 登录:
    http://<hostname>:30004/vnc.html?autoconnect=true&resize=remote

按 Ctrl+C 停止。
"""

import asyncio
import signal
import socket
import json
from pathlib import Path

from webu.gemini.browser import GeminiBrowser
from webu.gemini.config import GeminiConfig
from webu.gemini.constants import GEMINI_URL
from tclogger import logger

# 这个文件记录浏览器运行状态，供 test_interactive 检测
STATE_FILE = (
    Path(__file__).parent.parent.parent / ".chats" / "gemini" / "browser_state.json"
)


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def clear_state():
    if STATE_FILE.exists():
        STATE_FILE.unlink()


async def main():
    config = GeminiConfig()
    browser = GeminiBrowser(config=config)
    hostname = socket.gethostname()

    stop_event = asyncio.Event()

    def signal_handler():
        print("\n正在关闭...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGINT, signal_handler)
    loop.add_signal_handler(signal.SIGTERM, signal_handler)

    try:
        await browser.start()
        await browser.navigate_to_gemini()

        novnc_port = config.novnc_port
        cdp_port = config.browser_port
        internal_port = cdp_port + 10  # _INTERNAL_PORT_OFFSET

        # 保存运行状态
        save_state(
            {
                "running": True,
                "cdp_url": f"http://127.0.0.1:{internal_port}",
                "external_port": cdp_port,
                "novnc_port": novnc_port,
                "hostname": hostname,
            }
        )

        logger.note("=" * 60)
        logger.note("  Gemini 浏览器持久运行中")
        logger.note(
            f"  VNC:  http://{hostname}:{novnc_port}/vnc.html?autoconnect=true&resize=remote"
        )
        logger.note(f"  CDP:  http://127.0.0.1:{internal_port}")
        logger.note(f"  状态: {STATE_FILE}")
        logger.note("  按 Ctrl+C 停止")
        logger.note("=" * 60)

        # 轮询登录状态
        from webu.gemini.agency import GeminiAgency

        agency = GeminiAgency.__new__(GeminiAgency)
        agency.config = config
        agency.browser = browser
        agency.is_ready = True
        agency._image_mode = False
        agency._message_count = 0
        from webu.gemini.parser import GeminiResponseParser

        agency.parser = GeminiResponseParser()

        logged_in = False
        while not stop_event.is_set():
            if not logged_in:
                try:
                    status = await agency.check_login_status()
                    if status["logged_in"]:
                        logged_in = True
                        logger.okay(f"  ✓ 已登录: {status['message']}")
                        save_state(
                            {
                                "running": True,
                                "logged_in": True,
                                "cdp_url": f"http://127.0.0.1:{internal_port}",
                                "external_port": cdp_port,
                                "novnc_port": novnc_port,
                                "hostname": hostname,
                            }
                        )
                        logger.note("  浏览器保持运行中... (Ctrl+C 停止)")
                    else:
                        logger.mesg(f"  等待登录... ({status['message']})")
                except Exception as e:
                    logger.warn(f"  状态检测异常: {e}")

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=10)
                break
            except asyncio.TimeoutError:
                pass

    finally:
        clear_state()
        await browser.stop()
        logger.okay("  浏览器已停止")


if __name__ == "__main__":
    asyncio.run(main())
