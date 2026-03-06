"""warp_api 模块单元测试。"""

import pytest
import subprocess

from webu.warp_api.constants import (
    WARP_INTERFACE,
    WARP_PROXY_HOST,
    WARP_PROXY_PORT,
    WARP_API_HOST,
    WARP_API_PORT,
    DATA_DIR,
    IP_CHECK_URLS,
)
from webu.warp_api.warp import WarpClient


# ═══════════════════════════════════════════════════════════════
# 常量测试
# ═══════════════════════════════════════════════════════════════


class TestConstants:
    def test_interface_name(self):
        assert WARP_INTERFACE == "CloudflareWARP"

    def test_proxy_port(self):
        assert WARP_PROXY_PORT == 11000

    def test_api_port(self):
        assert WARP_API_PORT == 11001

    def test_ip_check_urls(self):
        assert len(IP_CHECK_URLS) >= 2
        for url in IP_CHECK_URLS:
            assert url.startswith("https://")


# ═══════════════════════════════════════════════════════════════
# WarpClient 测试
# ═══════════════════════════════════════════════════════════════


class TestWarpClient:
    def setup_method(self):
        self.client = WarpClient()

    def test_status_returns_dict(self):
        info = self.client.status()
        assert isinstance(info, dict)
        assert "connected" in info
        assert "status" in info
        assert "raw" in info

    def test_is_connected_returns_bool(self):
        result = self.client.is_connected()
        assert isinstance(result, bool)

    def test_get_warp_ip_format(self):
        ip = self.client.get_warp_ip()
        if ip is not None:
            # 应该是 100.96.x.x 格式
            parts = ip.split(".")
            assert len(parts) == 4
            assert parts[0] == "100"
            assert int(parts[1]) >= 96

    def test_registration_info(self):
        info = self.client.registration_info()
        assert isinstance(info, dict)
        assert "raw" in info

    def test_organization(self):
        org = self.client.organization()
        assert isinstance(org, str)


# ═══════════════════════════════════════════════════════════════
# 网络修复测试
# ═══════════════════════════════════════════════════════════════


class TestNetfix:
    def test_check_tailscale_compat(self):
        from webu.warp_api.netfix import check_tailscale_compat

        result = check_tailscale_compat()
        assert isinstance(result, dict)
        assert "nft_table_exists" in result
        assert "nft_input_ok" in result
        assert "nft_output_ok" in result
        assert "ip_rule_ok" in result


# ═══════════════════════════════════════════════════════════════
# 集成测试（需要 WARP 连接 + root 权限）
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestWarpIntegration:
    """需要 WARP 已连接且代理已运行。"""

    def test_warp_connected(self):
        """验证 WARP 已连接。"""
        client = WarpClient()
        assert client.is_connected(), "WARP must be connected for integration tests"

    def test_warp_ip_assigned(self):
        """验证 WARP 接口有 IP。"""
        client = WarpClient()
        ip = client.get_warp_ip()
        assert ip is not None, "WARP interface must have an IPv4 address"
        assert ip.startswith("100.96."), f"Expected 100.96.x.x, got {ip}"

    def test_ip_check(self):
        """检测出口 IP 不同于直连。"""
        client = WarpClient()
        if not client.is_connected():
            pytest.skip("WARP not connected")
        result = client.check_ip()
        assert result["warp_interface_ip"] is not None

    def test_proxy_reachable(self):
        """验证代理端口可达。"""
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        try:
            result = sock.connect_ex(("127.0.0.1", WARP_PROXY_PORT))
            if result != 0:
                pytest.skip("Proxy not running")
        finally:
            sock.close()

    def test_proxy_socks5_ip_check(self):
        """通过 SOCKS5 代理检测出口 IP。"""
        result = subprocess.run(
            [
                "curl",
                "-s",
                "--max-time",
                "15",
                "--socks5-hostname",
                f"127.0.0.1:{WARP_PROXY_PORT}",
                "https://api.ipify.org",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            pytest.skip(f"Proxy not available: {result.stderr}")
        exit_ip = result.stdout.strip()
        assert exit_ip, "Should return an IP address"
        # 确认不是直连 IP
        direct = subprocess.run(
            ["curl", "-4", "-s", "--max-time", "10", "https://api.ipify.org"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        direct_ip = direct.stdout.strip()
        assert (
            exit_ip != direct_ip
        ), f"Proxy exit IP ({exit_ip}) should differ from direct IP ({direct_ip})"

    def test_proxy_http_forward_ip_check(self):
        """通过 HTTP Forward Proxy 检测出口 IP (curl --proxy http://...)。"""
        result = subprocess.run(
            [
                "curl",
                "-s",
                "--max-time",
                "15",
                "--proxy",
                f"http://127.0.0.1:{WARP_PROXY_PORT}",
                "http://ifconfig.me/ip",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            pytest.skip(f"HTTP forward proxy not available: {result.stderr}")
        exit_ip = result.stdout.strip()
        assert exit_ip, "Should return an IP address"
        # 确认不是直连 IP
        direct = subprocess.run(
            ["curl", "-4", "-s", "--max-time", "10", "http://ifconfig.me/ip"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        direct_ip = direct.stdout.strip()
        assert (
            exit_ip != direct_ip
        ), f"HTTP forward proxy exit IP ({exit_ip}) should differ from direct IP ({direct_ip})"

    def test_api_health(self):
        """验证管理 API 健康检查。"""
        result = subprocess.run(
            [
                "curl",
                "-s",
                "--max-time",
                "5",
                f"http://{WARP_API_HOST}:{WARP_API_PORT}/health",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            pytest.skip("API not running")
        import json

        data = json.loads(result.stdout)
        assert data["status"] == "ok"
