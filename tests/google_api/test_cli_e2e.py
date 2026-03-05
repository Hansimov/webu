"""ggsc CLI 端到端测试 — 验证所有 CLI 命令在真实环境中的行为。

测试 ggsc 工具的实际命令行输出和行为。

运行: pytest tests/google_api/test_cli_e2e.py -xvs -m integration
"""

import subprocess
import sys

import pytest


def _run_ggsc(*args, timeout=60):
    """运行 ggsc 命令并返回结果。"""
    cmd = [sys.executable, "-m", "webu.google_api"] + list(args)
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout
    )
    return result


# ═══════════════════════════════════════════════════════════════
# CLI 基础命令测试
# ═══════════════════════════════════════════════════════════════


class TestCLIBasicCommands:
    """测试 CLI 基础命令（不需要网络/MongoDB）。"""

    def test_help_shows_ggsc(self):
        """--help 输出包含 ggsc 标识。"""
        r = _run_ggsc("--help")
        assert r.returncode == 0
        output = r.stdout + r.stderr
        assert "ggsc" in output.lower()

    def test_help_lists_all_commands(self):
        """--help 列出所有新命令。"""
        r = _run_ggsc("--help")
        output = r.stdout
        for cmd in ["start", "stop", "restart", "status", "logs",
                     "search", "search-test", "proxy-status", "proxy-check"]:
            assert cmd in output, f"Command '{cmd}' missing from help output"

    def test_each_subcommand_help(self):
        """每个子命令都有 --help。"""
        for cmd in ["start", "stop", "restart", "status", "logs",
                     "search", "search-test", "proxy-status", "proxy-check"]:
            r = _run_ggsc(cmd, "--help")
            assert r.returncode == 0, f"{cmd} --help failed: {r.stderr}"

    def test_search_accepts_proxy_arg(self):
        """search 子命令支持 --proxy 参数。"""
        r = _run_ggsc("search", "--help")
        assert "--proxy" in r.stdout

    def test_search_accepts_num_arg(self):
        """search 子命令支持 --num 参数。"""
        r = _run_ggsc("search", "--help")
        assert "--num" in r.stdout

    def test_start_accepts_port_arg(self):
        """start 子命令支持 --port 参数。"""
        r = _run_ggsc("start", "--help")
        assert "port" in r.stdout.lower()

    def test_logs_accepts_follow_arg(self):
        """logs 子命令支持 -f/--follow 参数。"""
        r = _run_ggsc("logs", "--help")
        assert "follow" in r.stdout.lower()

    def test_invalid_command_shows_help(self):
        """无效命令不应崩溃。"""
        r = _run_ggsc()
        assert r.returncode == 0  # 显示帮助


# ═══════════════════════════════════════════════════════════════
# CLI 实际操作测试（需要代理端口）
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestCLIOperations:
    """测试 CLI 实际操作（需要代理端口活跃）。"""

    def test_status_works(self):
        """status 命令正常工作。"""
        r = _run_ggsc("status", timeout=10)
        assert r.returncode == 0

    def test_proxy_status(self):
        """proxy-status 命令正常工作。"""
        r = _run_ggsc("proxy-status", timeout=30)
        assert r.returncode == 0
        combined = r.stdout + r.stderr
        assert "proxy" in combined.lower() or "socks" in combined.lower() or "http" in combined.lower()


# ═══════════════════════════════════════════════════════════════
# ggsc 命令直接调用测试（使用 entry_point）
# ═══════════════════════════════════════════════════════════════


class TestGGSCEntryPoint:
    """测试 ggsc 作为 entry_point 安装后的命令。"""

    def test_ggsc_command_exists(self):
        """ggsc 命令已注册。"""
        r = subprocess.run(
            ["which", "ggsc"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0:
            pytest.skip("ggsc not installed (run pip install -e .)")
        assert "ggsc" in r.stdout

    def test_ggsc_help(self):
        """ggsc --help 正常工作。"""
        r = subprocess.run(
            ["ggsc", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0 and "not found" in (r.stderr or ""):
            pytest.skip("ggsc command not available")
        assert r.returncode == 0
        assert "ggsc" in r.stdout.lower()
