"""端到端测试：CDP 浏览器启动 + TCP 代理 + noVNC。

测试内容：
1. Chrome 使用 Xvnc 虚拟显示器启动（而非 Xvfb）
2. TCP 代理绑定到 0.0.0.0
3. DevTools JSON API 可通过代理以主机名 Host 头访问
4. 响应中的内部 URL 被重写为外部主机名
5. noVNC Web 查看器可访问以进行可视化浏览器交互
"""

import asyncio
import json
import socket
import subprocess
import urllib.request

from webu.gemini.browser import GeminiBrowser
from webu.gemini.config import GeminiConfig


async def test_gemini_browser():
    print("=" * 60)
    print("测试 GeminiBrowser + CDP 代理 + noVNC")
    print("=" * 60)

    config = GeminiConfig()
    browser = GeminiBrowser(config=config)
    hostname = socket.gethostname()
    external_port = config.browser_port
    internal_port = external_port + 10
    novnc_port = config.novnc_port

    try:
        await browser.start()

        # 验证端口绑定
        r = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
        print("\n端口绑定:")
        for line in r.stdout.splitlines():
            for port in [external_port, internal_port, config.vnc_port, novnc_port]:
                if str(port) in line:
                    print(f"  {line}")
                    break

        # 测试 1：通过代理以主机名 Host 头访问 /json/version
        print(f"\n--- 测试 1: GET /json/version 通过 {hostname}:{external_port} ---")
        reader, writer = await asyncio.open_connection("127.0.0.1", external_port)
        request = (
            f"GET /json/version HTTP/1.1\r\n"
            f"Host: {hostname}:{external_port}\r\n"
            f"Accept: application/json\r\n"
            f"\r\n"
        ).encode()
        writer.write(request)
        await writer.drain()
        response = await asyncio.wait_for(reader.read(4096), timeout=10)
        writer.close()
        resp_str = response.decode("utf-8")
        print(f"  响应状态: {resp_str.splitlines()[0]}")

        # 解析 JSON 响应体
        body_start = resp_str.find("\r\n\r\n") + 4
        body = resp_str[body_start:]
        try:
            data = json.loads(body)
            print(f"  Browser: {data.get('Browser', 'N/A')}")
            ws_url = data.get("webSocketDebuggerUrl", "")
            print(f"  webSocketDebuggerUrl: {ws_url}")
            if f"127.0.0.1:{internal_port}" in ws_url:
                print("  ✗ 失败: 内部地址未被重写！")
            elif f"{hostname}:{external_port}" in ws_url:
                print("  ✓ 通过: URL 已正确重写为外部地址")
            else:
                print(f"  ? URL: {ws_url}")
        except json.JSONDecodeError:
            print(f"  Body: {body[:200]}")

        # 测试 2：通过代理访问 /json（页面列表）
        print(f"\n--- 测试 2: GET /json 通过 {hostname}:{external_port} ---")
        reader, writer = await asyncio.open_connection("127.0.0.1", external_port)
        request = (
            f"GET /json HTTP/1.1\r\n" f"Host: {hostname}:{external_port}\r\n" f"\r\n"
        ).encode()
        writer.write(request)
        await writer.drain()
        response = await asyncio.wait_for(reader.read(8192), timeout=10)
        writer.close()
        resp_str = response.decode("utf-8")
        print(f"  响应状态: {resp_str.splitlines()[0]}")

        body_start = resp_str.find("\r\n\r\n") + 4
        body = resp_str[body_start:]
        if f"127.0.0.1:{internal_port}" in body:
            print("  ✗ 失败: 页面列表中内部地址未被重写！")
        else:
            print("  ✓ 通过: 无内部地址泄露")
        print(f"  响应体预览: {body[:200]}")

        # 测试 3：验证 noVNC Web 查看器可访问
        print(f"\n--- 测试 3: noVNC Web 查看器，端口 {novnc_port} ---")
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{novnc_port}/vnc.html", timeout=5
            )
            content = resp.read()
            if b"noVNC" in content or b"vnc" in content.lower():
                print("  ✓ 通过: noVNC 页面已提供")
            else:
                print("  ? noVNC 页面内容不正确")
            print(f"  Content-Length: {len(content)} 字节")
        except Exception as e:
            print(f"  ✗ 失败: 无法访问 noVNC: {e}")

        # 为用户打印访问 URL
        print(f"\n{'=' * 60}")
        print(f"浏览器已运行！访问方式:")
        print(
            f"  可视化 (noVNC): http://{hostname}:{novnc_port}/vnc.html"
            f"?autoconnect=true&resize=remote"
        )
        print(f"  DevTools JSON:  http://{hostname}:{external_port}/json")
        print(f"  VNC (直连):   vnc://{hostname}:{config.vnc_port}")
        print(f"{'=' * 60}")
        print("按 Enter 停止浏览器...")
        await asyncio.get_event_loop().run_in_executor(None, input)

    finally:
        await browser.stop()


if __name__ == "__main__":
    asyncio.run(test_gemini_browser())
