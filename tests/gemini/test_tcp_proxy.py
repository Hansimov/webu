"""测试 TCP 代理的 Host 头和 URL 重写。

验证：
1. Host 头在所有 HTTP 请求中被重写（不仅仅是第一个）
2. Chrome DevTools 响应中的内部地址被重写为外部地址
3. WebSocket 升级请求也被重写
4. Keep-alive 连接正确处理多个请求
5. 端到端代理与真实 Chrome 实例工作
"""

import asyncio
import socket
import subprocess

import pytest


# ── _TCPProxy 重写方法单元测试 ──────────────────────────────


class TestTCPProxyRewrite:
    """测试 _TCPProxy._rewrite_request 和 _rewrite_response 方法。"""

    def _make_proxy(self, external_port=30001, internal_port=30011):
        from webu.gemini.browser import _TCPProxy

        return _TCPProxy(external_port, internal_port)

    # ── 请求重写（Host 头）──

    def test_rewrite_host_simple_get(self):
        proxy = self._make_proxy()
        req = b"GET /json HTTP/1.1\r\nHost: <hostname>:30001\r\nAccept: */*\r\n\r\n"
        result = proxy._rewrite_request(req)
        assert b"Host: 127.0.0.1:30011" in result
        assert b"Host: <hostname>:30001" not in result

    def test_rewrite_host_case_insensitive(self):
        proxy = self._make_proxy()
        req = b"GET /json HTTP/1.1\r\nhost: <hostname>:30001\r\nAccept: */*\r\n\r\n"
        result = proxy._rewrite_request(req)
        assert b"Host: 127.0.0.1:30011" in result
        assert b"host: <hostname>:30001" not in result

    def test_rewrite_host_with_spaces(self):
        proxy = self._make_proxy()
        req = b"GET /json HTTP/1.1\r\nHost:   <hostname>:30001\r\nAccept: */*\r\n\r\n"
        result = proxy._rewrite_request(req)
        assert b"Host: 127.0.0.1:30011" in result

    def test_rewrite_host_preserves_other_headers(self):
        proxy = self._make_proxy()
        req = (
            b"GET /json HTTP/1.1\r\n"
            b"Host: <hostname>:30001\r\n"
            b"Accept: application/json\r\n"
            b"User-Agent: TestBrowser\r\n"
            b"\r\n"
        )
        result = proxy._rewrite_request(req)
        assert b"Accept: application/json" in result
        assert b"User-Agent: TestBrowser" in result
        assert b"Host: 127.0.0.1:30011" in result

    def test_rewrite_host_websocket_upgrade(self):
        proxy = self._make_proxy()
        req = (
            b"GET /devtools/page/ABC123 HTTP/1.1\r\n"
            b"Host: <hostname>:30001\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            b"\r\n"
        )
        result = proxy._rewrite_request(req)
        assert b"Host: 127.0.0.1:30011" in result
        assert b"Upgrade: websocket" in result

    def test_rewrite_host_multiple_requests_keepalive(self):
        """单个数据块中的两个流水线 HTTP 请求都必须被重写。"""
        proxy = self._make_proxy()
        # Two pipelined requests in one TCP read
        data = (
            b"GET /json/version HTTP/1.1\r\n"
            b"Host: <hostname>:30001\r\n"
            b"Connection: keep-alive\r\n"
            b"\r\n"
            b"GET /json HTTP/1.1\r\n"
            b"Host: <hostname>:30001\r\n"
            b"Connection: keep-alive\r\n"
            b"\r\n"
        )
        result = proxy._rewrite_request(data)
        # 两个 Host 头都应被重写
        assert result.count(b"Host: 127.0.0.1:30011") == 2
        assert b"Host: <hostname>:30001" not in result

    def test_rewrite_no_host_header(self):
        """没有 Host 头的数据应直接通过。"""
        proxy = self._make_proxy()
        data = b"\x00\x01\x02\x03binary data"
        assert proxy._rewrite_request(data) == data

    def test_rewrite_empty_data(self):
        proxy = self._make_proxy()
        assert proxy._rewrite_request(b"") == b""

    # ── 响应重写（内部 URL）──

    def test_rewrite_response_websocket_url(self):
        proxy = self._make_proxy()
        hostname = socket.gethostname()
        body = b'{"webSocketDebuggerUrl":"ws://127.0.0.1:30011/devtools/browser/abc"}'
        result = proxy._rewrite_response(body)
        expected = f'{{"webSocketDebuggerUrl":"ws://{hostname}:30001/devtools/browser/abc"}}'.encode()
        assert result == expected

    def test_rewrite_response_http_url(self):
        proxy = self._make_proxy()
        hostname = socket.gethostname()
        body = b'"devtoolsFrontendUrl":"http://127.0.0.1:30011/devtools/inspector.html"'
        result = proxy._rewrite_response(body)
        assert f"http://{hostname}:30001/devtools/inspector.html".encode() in result

    def test_rewrite_response_multiple_occurrences(self):
        proxy = self._make_proxy()
        hostname = socket.gethostname()
        body = (
            b'[{"webSocketDebuggerUrl":"ws://127.0.0.1:30011/devtools/page/A"},'
            b'{"webSocketDebuggerUrl":"ws://127.0.0.1:30011/devtools/page/B"}]'
        )
        result = proxy._rewrite_response(body)
        assert result.count(f"{hostname}:30001".encode()) == 2
        assert b"127.0.0.1:30011" not in result

    def test_rewrite_response_no_internal_addr(self):
        """没有内部地址的数据应直接通过。"""
        proxy = self._make_proxy()
        data = b'{"status": "ok"}'
        assert proxy._rewrite_response(data) == data

    def test_rewrite_response_content_length_adjusted(self):
        """当响应体大小变化时，Content-Length 头必须被更新。"""
        proxy = self._make_proxy()
        hostname = socket.gethostname()
        body = b'{"url":"ws://127.0.0.1:30011/devtools/browser/abc"}'
        original_response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"\r\n" + body
        )
        result = proxy._rewrite_response(original_response)

        # Parse the result
        header_end = result.find(b"\r\n\r\n")
        headers = result[:header_end].decode()
        new_body = result[header_end + 4 :]

        # Content-Length 应与实际响应体长度匹配
        import re

        cl_match = re.search(r"Content-Length:\s*(\d+)", headers, re.IGNORECASE)
        assert cl_match is not None
        assert int(cl_match.group(1)) == len(new_body)
        # 内部地址应已被替换
        assert b"127.0.0.1:30011" not in new_body
        assert f"{hostname}:30001".encode() in new_body

    def test_rewrite_response_no_content_length(self):
        """没有 Content-Length 的响应仍应重写响应体。"""
        proxy = self._make_proxy()
        hostname = socket.gethostname()
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"\r\n"
            b'{"url":"ws://127.0.0.1:30011/devtools/page/X"}'
        )
        result = proxy._rewrite_response(response)
        assert b"127.0.0.1:30011" not in result
        assert f"{hostname}:30001".encode() in result


# ── 集成测试：代理 + 模拟 HTTP 服务器 ──────────────────────


class TestTCPProxyIntegration:
    """使用模拟 Chrome DevTools 服务器测试完整的 TCP 代理。"""

    @pytest.fixture
    async def proxy_with_mock_server(self):
        """在内部端口启动模拟 DevTools 服务器，在外部端口启动代理。"""
        from webu.gemini.browser import _TCPProxy

        internal_port = 39011
        external_port = 39001
        hostname = socket.gethostname()

        # Mock Chrome DevTools HTTP server
        async def mock_handler(reader, writer):
            data = await reader.read(4096)
            request = data.decode("utf-8", errors="replace")

            # 检查 Host 头是否被重写
            if f"Host: 127.0.0.1:{internal_port}" not in request:
                body = b"FAIL: Host header not rewritten"
                response = (
                    b"HTTP/1.1 400 Bad Request\r\n"
                    b"Content-Type: text/plain\r\n"
                    b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                    b"\r\n" + body
                )
            elif "/json/version" in request:
                body = (
                    b'{"Browser":"Chrome/138","Protocol-Version":"1.3",'
                    b'"webSocketDebuggerUrl":"ws://127.0.0.1:'
                    + str(internal_port).encode()
                    + b'/devtools/browser/test-id"}'
                )
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                    b"\r\n" + body
                )
            else:
                body = b'[{"id":"page1","url":"about:blank",'
                body += (
                    b'"webSocketDebuggerUrl":"ws://127.0.0.1:'
                    + str(internal_port).encode()
                    + b'/devtools/page/page1"}]'
                )
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                    b"\r\n" + body
                )

            writer.write(response)
            await writer.drain()
            writer.close()

        mock_server = await asyncio.start_server(
            mock_handler, "127.0.0.1", internal_port
        )

        proxy = _TCPProxy(external_port, internal_port)
        proxy.start()
        await asyncio.sleep(0.3)  # Let proxy start

        yield {
            "proxy": proxy,
            "mock_server": mock_server,
            "internal_port": internal_port,
            "external_port": external_port,
            "hostname": hostname,
        }

        proxy.stop()
        mock_server.close()
        await mock_server.wait_closed()

    @pytest.mark.asyncio
    async def test_proxy_rewrites_host_and_response(self, proxy_with_mock_server):
        """端到端：通过代理的请求重写 Host，响应重写 URL。"""
        ctx = proxy_with_mock_server
        hostname = ctx["hostname"]
        external_port = ctx["external_port"]

        reader, writer = await asyncio.open_connection("127.0.0.1", external_port)
        request = (
            f"GET /json/version HTTP/1.1\r\n"
            f"Host: {hostname}:{external_port}\r\n"
            f"Accept: application/json\r\n"
            f"\r\n"
        ).encode()
        writer.write(request)
        await writer.drain()

        response = await asyncio.wait_for(reader.read(4096), timeout=5)
        writer.close()

        response_str = response.decode("utf-8")
        # 响应中不应出现内部地址
        assert f"127.0.0.1:{ctx['internal_port']}" not in response_str
        # 响应中应出现外部地址
        assert f"{hostname}:{external_port}" in response_str
        # 应为成功响应（Host 已正确重写）
        assert "200 OK" in response_str
        assert "Chrome/138" in response_str

    @pytest.mark.asyncio
    async def test_proxy_json_list_rewrite(self, proxy_with_mock_server):
        """端到端：/json 接口的 URL 被重写。"""
        ctx = proxy_with_mock_server
        hostname = ctx["hostname"]
        external_port = ctx["external_port"]

        reader, writer = await asyncio.open_connection("127.0.0.1", external_port)
        request = (
            f"GET /json HTTP/1.1\r\n" f"Host: {hostname}:{external_port}\r\n" f"\r\n"
        ).encode()
        writer.write(request)
        await writer.drain()

        response = await asyncio.wait_for(reader.read(4096), timeout=5)
        writer.close()

        response_str = response.decode("utf-8")
        assert "200 OK" in response_str
        assert f"ws://{hostname}:{external_port}/devtools/page/page1" in response_str
        assert f"127.0.0.1:{ctx['internal_port']}" not in response_str

    @pytest.mark.asyncio
    async def test_proxy_rejects_bad_host(self, proxy_with_mock_server):
        """验证没有代理时，主机名 Host 会被拒绝。"""
        ctx = proxy_with_mock_server
        # 直接连接模拟服务器，使用主机名 Host 头
        # （模拟服务器检查重写后的 Host，未重写则返回 400）
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", ctx["internal_port"]
        )
        request = (
            f"GET /json/version HTTP/1.1\r\n"
            f"Host: <hostname>:{ctx['internal_port']}\r\n"
            f"\r\n"
        ).encode()
        writer.write(request)
        await writer.drain()

        response = await asyncio.wait_for(reader.read(4096), timeout=5)
        writer.close()

        response_str = response.decode("utf-8")
        assert "400" in response_str
        assert "Host header not rewritten" in response_str


# ── 集成测试：真实 Chrome CDP ──────────────────────────────


@pytest.mark.integration
class TestChromeCDPProxy:
    """使用真实 Chrome 实例测试代理（需要 Chrome + 显示器）。"""

    @pytest.mark.asyncio
    async def test_real_chrome_devtools_accessible(self):
        """启动 Chrome，验证 DevTools JSON API 可通过代理访问。"""
        from webu.gemini.browser import GeminiBrowser
        from webu.gemini.config import GeminiConfig

        config = GeminiConfig()
        browser = GeminiBrowser(config=config)
        try:
            await browser.start()
            external_port = config.browser_port
            hostname = socket.gethostname()

            # 通过代理使用主机名访问 /json/version
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

            response_str = response.decode("utf-8")
            assert "200" in response_str or "Chrome" in response_str
            # 内部地址应被重写
            internal_port = external_port + 10
            assert f"127.0.0.1:{internal_port}" not in response_str

        finally:
            await browser.stop()
