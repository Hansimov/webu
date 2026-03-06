"""Cloudflare WARP 客户端封装。

提供对 warp-cli 的 Python 封装，包括：
- 连接 / 断开
- 状态查询
- IP 检测（直连 vs WARP 出口）
"""

import re
import socket
import subprocess

from tclogger import logger, logstr

from .constants import (
    WARP_INTERFACE,
    IP_CHECK_URLS,
    IP_CHECK_TIMEOUT,
)


class WarpClient:
    """warp-cli 的 Python 封装。"""

    def __init__(self, interface: str = WARP_INTERFACE):
        self.interface = interface

    # ── warp-cli 调用 ────────────────────────────────────────

    def _run(self, *args: str, timeout: int = 15) -> str:
        """运行 warp-cli 子命令，返回 stdout。"""
        cmd = ["warp-cli", *args]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.stdout.strip()
        except FileNotFoundError:
            raise RuntimeError("warp-cli not found — is cloudflare-warp installed?")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"warp-cli {' '.join(args)} timed out")

    # ── 连接控制 ─────────────────────────────────────────────

    def connect(self) -> str:
        """连接 WARP。"""
        out = self._run("connect")
        logger.okay(f"  ✓ WARP connect: {out or 'ok'}")
        return out

    def disconnect(self) -> str:
        """断开 WARP。"""
        out = self._run("disconnect")
        logger.okay(f"  ✓ WARP disconnect: {out or 'ok'}")
        return out

    # ── 状态查询 ─────────────────────────────────────────────

    def status(self) -> dict:
        """返回 WARP 连接状态信息。"""
        out = self._run("status")
        info: dict = {"raw": out, "connected": False, "status": "Unknown"}
        for line in out.splitlines():
            if line.startswith("Status update:"):
                val = line.split(":", 1)[1].strip()
                info["status"] = val
                info["connected"] = val == "Connected"
            elif line.startswith("Network:"):
                info["network"] = line.split(":", 1)[1].strip()
        return info

    def is_connected(self) -> bool:
        return self.status().get("connected", False)

    def registration_info(self) -> dict:
        """返回注册信息。"""
        out = self._run("registration", "show")
        info: dict = {"raw": out}
        for line in out.splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                info[key.strip().lower().replace(" ", "_")] = val.strip()
        return info

    def organization(self) -> str:
        return self._run("registration", "organization")

    # ── IP 地址 ──────────────────────────────────────────────

    def get_warp_ip(self) -> str | None:
        """获取 CloudflareWARP 接口上的 IPv4 地址。"""
        out = self._run_sys(f"ip -4 -br a show dev {self.interface}")
        if not out:
            return None
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", out)
        return match.group(1) if match else None

    def _run_sys(self, cmd: str, timeout: int = 5) -> str:
        """运行系统命令。"""
        try:
            result = subprocess.run(
                cmd.split(),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def get_exit_ip(self, use_warp: bool = False) -> str | None:
        """通过 IP 检测服务获取出口 IP。

        Args:
            use_warp: 是否绑定到 WARP 接口（需要 root 权限）。
        """
        import ssl
        import urllib.request

        for url in IP_CHECK_URLS:
            try:
                host = url.split("//")[1].split("/")[0]
                path = (
                    "/" + "/".join(url.split("//")[1].split("/")[1:])
                    if "/" in url.split("//")[1]
                    else "/"
                )

                if use_warp:
                    # 使用 SO_BINDTODEVICE 绑定到 WARP 设备
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(IP_CHECK_TIMEOUT)
                    try:
                        sock.setsockopt(
                            socket.SOL_SOCKET,
                            socket.SO_BINDTODEVICE,
                            self.interface.encode() + b"\0",
                        )
                    except PermissionError:
                        sock.close()
                        logger.warn(
                            "  × SO_BINDTODEVICE requires root — "
                            "WARP exit IP detection skipped"
                        )
                        return None

                    # DNS 解析（强制 IPv4）
                    infos = socket.getaddrinfo(host, 443, socket.AF_INET)
                    if not infos:
                        sock.close()
                        continue
                    target_addr = infos[0][4]

                    sock.connect(target_addr)
                    ctx = ssl.create_default_context()
                    ssock = ctx.wrap_socket(sock, server_hostname=host)
                    ssock.sendall(
                        f"GET {path} HTTP/1.1\r\n"
                        f"Host: {host}\r\n"
                        f"User-Agent: curl/8.0\r\n"
                        f"Accept: text/plain\r\n"
                        f"Connection: close\r\n\r\n".encode()
                    )
                    data = b""
                    while True:
                        chunk = ssock.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    ssock.close()
                    body = (
                        data.decode(errors="replace").split("\r\n\r\n", 1)[-1].strip()
                    )
                else:
                    # 直连也强制 IPv4 以便与 WARP 出口 IP 对比
                    infos = socket.getaddrinfo(host, 443, socket.AF_INET)
                    if not infos:
                        continue
                    target_addr = infos[0][4]

                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(IP_CHECK_TIMEOUT)
                    sock.connect(target_addr)
                    ctx = ssl.create_default_context()
                    ssock = ctx.wrap_socket(sock, server_hostname=host)
                    ssock.sendall(
                        f"GET {path} HTTP/1.1\r\n"
                        f"Host: {host}\r\n"
                        f"User-Agent: curl/8.0\r\n"
                        f"Accept: text/plain\r\n"
                        f"Connection: close\r\n\r\n".encode()
                    )
                    data = b""
                    while True:
                        chunk = ssock.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    ssock.close()
                    body = (
                        data.decode(errors="replace").split("\r\n\r\n", 1)[-1].strip()
                    )

                # 验证返回值是有效 IP（而非 HTML 或其他内容）
                ip = body.split("\n")[0].strip()
                if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
                    return ip
            except Exception:
                continue
        return None

    def check_ip(self) -> dict:
        """检测直连 IP 和 WARP 出口 IP。"""
        direct_ip = self.get_exit_ip(use_warp=False)
        warp_ip = self.get_exit_ip(use_warp=True)
        local_warp_ip = self.get_warp_ip()

        return {
            "direct_ip": direct_ip,
            "warp_exit_ip": warp_ip,
            "warp_interface_ip": local_warp_ip,
            "warp_active": direct_ip != warp_ip and warp_ip is not None,
        }
