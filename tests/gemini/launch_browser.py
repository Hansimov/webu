"""启动带 noVNC 的 Gemini 浏览器，用于远程可视化交互。

用法:
    python -m tests.gemini.launch_browser

启动 Chrome，包含:
- Xvnc 虚拟显示 (用于远程可视化访问)
- noVNC Web 查看器 (基于浏览器的 VNC，地址 http://<hostname>:30004/vnc.html)
- CDP TCP 代理 (DevTools 地址 http://<hostname>:30001/json)

通过 noVNC 可视化访问浏览器，导航到 gemini.google.com，
登录你的 Google 账号。登录会话将持久化保存在用户数据目录中。

按 Ctrl+C 停止。
"""

import asyncio
import signal
import socket

from webu.gemini.browser import GeminiBrowser
from webu.gemini.config import GeminiConfig


async def main():
    config = GeminiConfig()
    browser = GeminiBrowser(config=config)
    hostname = socket.gethostname()

    # 优雅处理 Ctrl+C
    stop_event = asyncio.Event()

    def signal_handler():
        print("\n正在关闭...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGINT, signal_handler)
    loop.add_signal_handler(signal.SIGTERM, signal_handler)

    try:
        await browser.start()

        novnc_port = config.novnc_port
        cdp_port = config.browser_port
        print(f"\n{'=' * 60}")
        print(f"浏览器已运行！在你的浏览器中打开:")
        print(
            f"  http://{hostname}:{novnc_port}/vnc.html"
            f"?autoconnect=true&resize=remote"
        )
        print(f"{'=' * 60}")
        print(f"按 Ctrl+C 停止。\n")

        # 持续运行直到收到信号
        await stop_event.wait()

    finally:
        await browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
