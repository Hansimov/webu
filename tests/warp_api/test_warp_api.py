"""warp_api 模块单元测试。"""

import argparse
import pytest
import psutil
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
from webu.warp_api import cli as warp_cli
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

    def test_fix_dns_routing_clears_stale_interface(self, monkeypatch):
        from webu.warp_api import netfix

        primary_interface = "primary0"
        stale_interface = "vpn0"
        primary_prefix = "2606:4700:1234:5678"
        stale_prefix = "2607:f8b0:abcd:1234"

        class FakePrefixer:
            netint = primary_interface
            interfaces = [
                {
                    "interface": primary_interface,
                    "prefix": primary_prefix,
                    "prefix_bits": 64,
                },
                {
                    "interface": stale_interface,
                    "prefix": stale_prefix,
                    "prefix_bits": 64,
                },
            ]

        domains = {primary_interface: "~.", stale_interface: "~."}
        commands = []

        monkeypatch.setattr(netfix, "_get_ipv6_prefixer", lambda: FakePrefixer())
        monkeypatch.setattr(
            netfix,
            "_get_resolvectl_domain",
            lambda interface: domains.get(interface, ""),
        )

        def fake_sudo_run(cmd, check=False):
            commands.append(cmd)
            if cmd[:3] == ["resolvectl", "domain", stale_interface]:
                domains[stale_interface] = ""
            return 0, ""

        monkeypatch.setattr(netfix, "_sudo_run", fake_sudo_run)

        result = netfix.fix_dns_routing()

        assert result["stale_dns_cleared"] == 1
        assert ["resolvectl", "domain", stale_interface, ""] in commands

    def test_fix_ipv6_routing_clears_stale_prefix_rule(self, monkeypatch):
        from webu.warp_api import netfix

        primary_interface = "primary0"
        stale_interface = "vpn0"
        primary_prefix = "2606:4700:1234:5678"
        stale_prefix = "2607:f8b0:abcd:1234"

        class FakePrefixer:
            prefix = primary_prefix
            netint = primary_interface
            prefix_bits = 64
            interfaces = [
                {
                    "interface": primary_interface,
                    "prefix": primary_prefix,
                    "prefix_bits": 64,
                },
                {
                    "interface": stale_interface,
                    "prefix": stale_prefix,
                    "prefix_bits": 64,
                },
            ]

        active_rules = {f"{stale_prefix}::/64"}
        commands = []

        monkeypatch.setattr(netfix, "_get_ipv6_prefixer", lambda: FakePrefixer())
        monkeypatch.setattr(
            netfix,
            "_has_ip6_rule",
            lambda priority, keyword: keyword in active_rules,
        )

        def fake_sudo_run(cmd, check=False):
            commands.append(cmd)
            if cmd[:4] == ["ip", "-6", "rule", "del"]:
                active_rules.discard(cmd[6])
            return 0, ""

        monkeypatch.setattr(netfix, "_sudo_run", fake_sudo_run)

        result = netfix.fix_ipv6_routing()

        assert result["stale_rules_removed"] == 1
        assert [
            "ip",
            "-6",
            "rule",
            "del",
            "priority",
            str(netfix.IPV6_PROTECT_PRIORITY),
            "from",
            f"{stale_prefix}::/64",
            "lookup",
            "main",
        ] in commands


class TestCliPidRecovery:
    def test_resolve_service_pid_prefers_child_process(self, monkeypatch):
        class FakeChild:
            pid = 4321

            def cmdline(self):
                return ["python", "-m", "webu.warp_api", "_serve"]

        class FakeLauncher:
            def children(self, recursive=True):
                return [FakeChild()]

        monkeypatch.setattr(warp_cli.psutil, "Process", lambda pid: FakeLauncher())

        managed_pid = warp_cli._resolve_service_pid(1234, wait_seconds=0.01)
        assert managed_pid == 4321

    def test_recover_service_pid_updates_pid_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(warp_cli, "PID_FILE", tmp_path / "server.pid")
        monkeypatch.setattr(warp_cli, "_is_process_running", lambda pid: False)
        monkeypatch.setattr(warp_cli, "_find_running_service_pid", lambda: 5678)

        recovered_pid = warp_cli._recover_service_pid(1234)

        assert recovered_pid == 5678
        assert warp_cli.PID_FILE.read_text() == "5678"

    def test_cmd_test_runs_regression_script(self, monkeypatch, tmp_path):
        repo_root = tmp_path / "repo"
        script_path = repo_root / "debugs" / "warp_api" / "run_ipv6_warp_regression.sh"
        script_path.parent.mkdir(parents=True)
        script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

        calls = []

        monkeypatch.setattr(
            warp_cli.Path,
            "resolve",
            lambda self: repo_root / "src" / "webu" / "warp_api" / "cli.py",
        )

        def fake_run(cmd, cwd=None):
            calls.append((cmd, cwd))

            class Result:
                returncode = 0

            return Result()

        monkeypatch.setattr(warp_cli.subprocess, "run", fake_run)

        warp_cli.cmd_test(argparse.Namespace())

        assert calls == [(["bash", str(script_path)], repo_root)]


# ═══════════════════════════════════════════════════════════════
# 集成测试（需要 WARP 连接 + root 权限）
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestWarpIntegration:
    """需要 WARP 已连接且代理已运行。"""

    def test_restart_and_status_report_ports(self):
        restart = subprocess.run(
            ["cfwp", "restart"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert restart.returncode == 0, restart.stderr or restart.stdout

        status = subprocess.run(
            ["cfwp", "status"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert status.returncode == 0, status.stderr or status.stdout
        status_output = f"{status.stdout}\n{status.stderr}"
        assert (
            f"Proxy server: RUNNING (PID:" in status_output
            and f"{WARP_PROXY_HOST}:{WARP_PROXY_PORT}" in status_output
        )
        assert f"http://{WARP_API_HOST}:{WARP_API_PORT}/docs" in status_output

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
