"""异步 SOCKS5 代理服务器 — 通过 CloudflareWARP 接口转发流量。

支持 SOCKS5 (RFC 1928) 的 CONNECT 命令，将出站连接绑定到
CloudflareWARP 网络接口，从而让所有代理流量走 Cloudflare WARP 出口。

同时支持 HTTP CONNECT 代理，自动检测协议类型。
"""

import asyncio
import socket
import struct
import signal

from tclogger import logger, logstr

from .constants import (
    WARP_PROXY_HOST,
    WARP_PROXY_PORT,
    WARP_INTERFACE,
)
from .warp import WarpClient


# ═══════════════════════════════════════════════════════════════
# SOCKS5 协议常量
# ═══════════════════════════════════════════════════════════════

SOCKS5_VER = 0x05
SOCKS5_AUTH_NONE = 0x00
SOCKS5_CMD_CONNECT = 0x01
SOCKS5_ATYP_IPV4 = 0x01
SOCKS5_ATYP_DOMAIN = 0x03
SOCKS5_ATYP_IPV6 = 0x04
SOCKS5_REP_SUCCESS = 0x00
SOCKS5_REP_GENERAL_FAILURE = 0x01
SOCKS5_REP_CONN_REFUSED = 0x05
SOCKS5_REP_ADDR_NOT_SUPPORTED = 0x08

RELAY_BUF_SIZE = 65536


# ═══════════════════════════════════════════════════════════════
# 流量中继
# ═══════════════════════════════════════════════════════════════


async def _relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """单向数据中继。"""
    try:
        while True:
            data = await reader.read(RELAY_BUF_SIZE)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, OSError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _relay_bidirectional(
    r1: asyncio.StreamReader,
    w1: asyncio.StreamWriter,
    r2: asyncio.StreamReader,
    w2: asyncio.StreamWriter,
):
    """双向数据中继。"""
    await asyncio.gather(
        _relay(r1, w2),
        _relay(r2, w1),
        return_exceptions=True,
    )


# ═══════════════════════════════════════════════════════════════
# SOCKS5 协议处理
# ═══════════════════════════════════════════════════════════════


async def _socks5_handshake(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """完成 SOCKS5 握手 & CONNECT，返回 (target_host, target_port)。"""

    # 1. 认证协商 — VER NMETHODS METHODS
    header = await reader.readexactly(2)
    ver, nmethods = struct.unpack("!BB", header)
    if ver != SOCKS5_VER:
        raise ValueError(f"Unsupported SOCKS version: {ver}")

    methods = await reader.readexactly(nmethods)

    # 回复：无需认证
    writer.write(struct.pack("!BB", SOCKS5_VER, SOCKS5_AUTH_NONE))
    await writer.drain()

    # 2. 请求 — VER CMD RSV ATYP DST.ADDR DST.PORT
    req_header = await reader.readexactly(4)
    ver, cmd, _, atyp = struct.unpack("!BBBB", req_header)

    if cmd != SOCKS5_CMD_CONNECT:
        # 只支持 CONNECT
        writer.write(
            struct.pack("!BBBBIH", SOCKS5_VER, SOCKS5_REP_GENERAL_FAILURE, 0, SOCKS5_ATYP_IPV4, 0, 0)
        )
        await writer.drain()
        raise ValueError(f"Unsupported SOCKS5 command: {cmd}")

    # 解析目标地址
    if atyp == SOCKS5_ATYP_IPV4:
        raw_addr = await reader.readexactly(4)
        target_host = socket.inet_ntoa(raw_addr)
    elif atyp == SOCKS5_ATYP_DOMAIN:
        addr_len = (await reader.readexactly(1))[0]
        target_host = (await reader.readexactly(addr_len)).decode()
    elif atyp == SOCKS5_ATYP_IPV6:
        raw_addr = await reader.readexactly(16)
        target_host = socket.inet_ntop(socket.AF_INET6, raw_addr)
    else:
        writer.write(
            struct.pack("!BBBBIH", SOCKS5_VER, SOCKS5_REP_ADDR_NOT_SUPPORTED, 0, SOCKS5_ATYP_IPV4, 0, 0)
        )
        await writer.drain()
        raise ValueError(f"Unsupported address type: {atyp}")

    raw_port = await reader.readexactly(2)
    target_port = struct.unpack("!H", raw_port)[0]

    return target_host, target_port


def _socks5_reply(rep: int, bind_addr: str = "0.0.0.0", bind_port: int = 0) -> bytes:
    """构造 SOCKS5 回复报文。"""
    addr_bytes = socket.inet_aton(bind_addr)
    return struct.pack("!BBBB", SOCKS5_VER, rep, 0, SOCKS5_ATYP_IPV4) + addr_bytes + struct.pack("!H", bind_port)


# ═══════════════════════════════════════════════════════════════
# HTTP CONNECT 协议处理
# ═══════════════════════════════════════════════════════════════


async def _http_connect_handshake(first_line: bytes, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """处理 HTTP CONNECT 请求，返回 (target_host, target_port)。"""
    # 读取剩余请求头
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break

    # 解析 CONNECT host:port HTTP/1.x
    parts = first_line.decode("ascii", errors="replace").strip().split()
    if len(parts) < 2:
        raise ValueError(f"Malformed HTTP CONNECT: {first_line}")

    host_port = parts[1]
    if ":" in host_port:
        host, port_str = host_port.rsplit(":", 1)
        port = int(port_str)
    else:
        host = host_port
        port = 443

    return host, port


# ═══════════════════════════════════════════════════════════════
# 代理核心
# ═══════════════════════════════════════════════════════════════


class WarpSocksProxy:
    """SOCKS5 / HTTP CONNECT 代理服务，出站流量绑定 CloudflareWARP 接口。"""

    def __init__(
        self,
        host: str = WARP_PROXY_HOST,
        port: int = WARP_PROXY_PORT,
        interface: str = WARP_INTERFACE,
    ):
        self.host = host
        self.port = port
        self.interface = interface
        self._warp = WarpClient(interface=interface)
        self._server: asyncio.Server | None = None
        self._active_connections = 0
        self._total_connections = 0

    # ── 获取 WARP 接口 IP ────────────────────────────────────

    def _get_bind_ip(self) -> str | None:
        """获取 WARP 接口 IPv4 地址用于出站绑定。"""
        return self._warp.get_warp_ip()

    # ── 建立出站连接 ─────────────────────────────────────────

    async def _connect_via_warp(
        self, target_host: str, target_port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """通过 WARP 接口建立到目标的 TCP 连接。

        使用 SO_BINDTODEVICE 将出站连接绑定到 CloudflareWARP 设备，
        确保流量走 WireGuard 隧道。需要 CAP_NET_RAW 权限（通常 root）。
        """
        bind_ip = self._get_bind_ip()
        if not bind_ip:
            raise RuntimeError(
                f"WARP interface {self.interface} has no IPv4 address — is WARP connected?"
            )

        # IPv6 地址不支持 — WARP 接口只有 IPv4
        if ":" in target_host:
            raise RuntimeError(
                f"IPv6 address {target_host} not supported — "
                f"WARP interface only has IPv4. Use hostname instead."
            )

        # 解析目标地址（强制 IPv4）
        try:
            infos = await asyncio.get_event_loop().getaddrinfo(
                target_host, target_port, family=socket.AF_INET, type=socket.SOCK_STREAM
            )
        except socket.gaierror as e:
            raise RuntimeError(f"DNS resolution failed for {target_host}: {e}")

        if not infos:
            raise RuntimeError(f"Cannot resolve {target_host} to IPv4")

        target_addr = infos[0][4]  # (ip, port)

        # 创建绑定到 WARP 设备的 socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_BINDTODEVICE,
                self.interface.encode() + b"\0",
            )
        except PermissionError:
            sock.close()
            raise RuntimeError(
                f"SO_BINDTODEVICE requires CAP_NET_RAW — run proxy as root (sudo)"
            )
        sock.setblocking(False)

        # 异步连接
        loop = asyncio.get_event_loop()
        try:
            await asyncio.wait_for(loop.sock_connect(sock, target_addr), timeout=30)
        except Exception:
            sock.close()
            raise

        reader, writer = await asyncio.open_connection(sock=sock)
        return reader, writer

    # ── 客户端连接处理 ───────────────────────────────────────

    async def _handle_client(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ):
        """处理一个客户端连接（自动检测 SOCKS5 / HTTP CONNECT）。"""
        peer = client_writer.get_extra_info("peername", ("?", 0))
        self._active_connections += 1
        self._total_connections += 1

        target_host = target_port = None
        remote_reader = remote_writer = None
        protocol = "unknown"

        try:
            # 窥探第一个字节来区分 SOCKS5 和 HTTP
            first_byte = await asyncio.wait_for(client_reader.readexactly(1), timeout=30)

            if first_byte[0] == SOCKS5_VER:
                protocol = "SOCKS5"
                # 把第一个字节放回 — 使用 feed_data 不可行，
                # 改为直接将剩余握手逻辑的 header 第一字节传入
                # 重新实现：读第二字节 nmethods
                nmethods_byte = await client_reader.readexactly(1)
                nmethods = nmethods_byte[0]
                methods = await client_reader.readexactly(nmethods)

                # 回复：无需认证
                client_writer.write(struct.pack("!BB", SOCKS5_VER, SOCKS5_AUTH_NONE))
                await client_writer.drain()

                # 读取请求
                req_header = await client_reader.readexactly(4)
                ver, cmd, _, atyp = struct.unpack("!BBBB", req_header)

                if cmd != SOCKS5_CMD_CONNECT:
                    client_writer.write(_socks5_reply(SOCKS5_REP_GENERAL_FAILURE))
                    await client_writer.drain()
                    return

                # 解析目标地址
                if atyp == SOCKS5_ATYP_IPV4:
                    raw_addr = await client_reader.readexactly(4)
                    target_host = socket.inet_ntoa(raw_addr)
                elif atyp == SOCKS5_ATYP_DOMAIN:
                    addr_len = (await client_reader.readexactly(1))[0]
                    target_host = (await client_reader.readexactly(addr_len)).decode()
                elif atyp == SOCKS5_ATYP_IPV6:
                    raw_addr = await client_reader.readexactly(16)
                    target_host = socket.inet_ntop(socket.AF_INET6, raw_addr)
                else:
                    client_writer.write(_socks5_reply(SOCKS5_REP_ADDR_NOT_SUPPORTED))
                    await client_writer.drain()
                    return

                raw_port = await client_reader.readexactly(2)
                target_port = struct.unpack("!H", raw_port)[0]

                # 建立远程连接
                try:
                    remote_reader, remote_writer = await self._connect_via_warp(
                        target_host, target_port
                    )
                except Exception as e:
                    logger.warn(f"  × SOCKS5 connect to {target_host}:{target_port} failed: {e}")
                    client_writer.write(_socks5_reply(SOCKS5_REP_CONN_REFUSED))
                    await client_writer.drain()
                    return

                # 成功回复
                bind_addr = remote_writer.get_extra_info("sockname", ("0.0.0.0", 0))
                client_writer.write(_socks5_reply(SOCKS5_REP_SUCCESS, bind_addr[0], bind_addr[1]))
                await client_writer.drain()

            else:
                # 可能是 HTTP CONNECT — 读取完整首行
                rest_of_line = await client_reader.readline()
                first_line = first_byte + rest_of_line

                if not first_line.upper().startswith(b"CONNECT "):
                    logger.warn(f"  × Unknown protocol from {peer}: {first_line[:50]}")
                    return

                protocol = "HTTP-CONNECT"

                # 读取剩余的请求头
                while True:
                    header_line = await client_reader.readline()
                    if header_line in (b"\r\n", b"\n", b""):
                        break

                # 解析 host:port
                parts = first_line.decode("ascii", errors="replace").strip().split()
                if len(parts) < 2:
                    return

                host_port = parts[1]
                if ":" in host_port:
                    host, port_str = host_port.rsplit(":", 1)
                    target_host = host
                    target_port = int(port_str)
                else:
                    target_host = host_port
                    target_port = 443

                # 建立远程连接
                try:
                    remote_reader, remote_writer = await self._connect_via_warp(
                        target_host, target_port
                    )
                except Exception as e:
                    logger.warn(f"  × HTTP CONNECT to {target_host}:{target_port} failed: {e}")
                    client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                    await client_writer.drain()
                    return

                # 200 Connection Established
                client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await client_writer.drain()

            logger.mesg(
                f"  [{protocol}] {peer[0]}:{peer[1]} → "
                f"{logstr.mesg(f'{target_host}:{target_port}')}"
            )

            # 双向中继
            await _relay_bidirectional(
                client_reader, client_writer,
                remote_reader, remote_writer,
            )

        except asyncio.IncompleteReadError:
            pass
        except asyncio.TimeoutError:
            logger.warn(f"  × Timeout from {peer}")
        except Exception as e:
            logger.warn(f"  × Error from {peer}: {e}")
        finally:
            self._active_connections -= 1
            for w in (client_writer, remote_writer):
                if w:
                    try:
                        w.close()
                        await w.wait_closed()
                    except Exception:
                        pass

    # ── 服务器生命周期 ───────────────────────────────────────

    async def start(self):
        """启动代理服务器。"""
        bind_ip = self._get_bind_ip()
        if not bind_ip:
            logger.warn(
                f"  × WARP interface {self.interface} not found or has no IPv4 address."
            )
            logger.warn(f"    Please ensure WARP is connected: warp-cli connect")
            raise RuntimeError("WARP interface not available")

        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
        )

        logger.okay(
            f"  ✓ WARP proxy listening on "
            f"{logstr.mesg(f'socks5://{self.host}:{self.port}')}"
        )
        logger.mesg(
            f"    Outbound via {logstr.mesg(self.interface)} ({logstr.mesg(bind_ip)})"
        )

        async with self._server:
            await self._server.serve_forever()

    async def stop(self):
        """停止代理服务器。"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.okay("  ✓ WARP proxy stopped")

    @property
    def stats(self) -> dict:
        return {
            "active_connections": self._active_connections,
            "total_connections": self._total_connections,
        }


# ═══════════════════════════════════════════════════════════════
# 独立运行入口
# ═══════════════════════════════════════════════════════════════


def run_proxy(
    host: str = WARP_PROXY_HOST,
    port: int = WARP_PROXY_PORT,
    interface: str = WARP_INTERFACE,
):
    """以阻塞方式运行代理服务器。"""
    proxy = WarpSocksProxy(host=host, port=port, interface=interface)
    logger.note(f"> Starting WARP SOCKS5/HTTP proxy ...")

    loop = asyncio.new_event_loop()

    def _shutdown(signum, frame):
        logger.note(f"\n> Received signal {signum}, shutting down ...")
        loop.call_soon_threadsafe(loop.stop)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(proxy.start())
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(proxy.stop())
        loop.close()
