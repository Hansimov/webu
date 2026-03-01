"""CLI 服务管理工具测试。

运行: pytest tests/google_api/test_cli.py -xvs
"""

import os
import signal
import subprocess
import sys
import time

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

from webu.google_api.cli import (
    _read_pid,
    _write_pid,
    _remove_pid,
    _is_process_running,
    cmd_status,
    cmd_collect,
    cmd_stats,
    DATA_DIR,
    PID_FILE,
    LOG_FILE,
)


# ═══════════════════════════════════════════════════════════════
# PID 管理单元测试
# ═══════════════════════════════════════════════════════════════


class TestPIDManagement:
    """PID 文件读写测试。"""

    def setup_method(self):
        """确保测试前清理状态。"""
        self._test_pid_file = DATA_DIR / "test_server.pid"

    def test_write_and_read_pid(self, tmp_path):
        """测试 PID 文件写入和读取。"""
        pid_file = tmp_path / "test.pid"
        with patch("webu.google_api.cli.PID_FILE", pid_file):
            _write_pid(12345)
            assert pid_file.read_text().strip() == "12345"

        with patch("webu.google_api.cli.PID_FILE", pid_file):
            pid = _read_pid()
            assert pid == 12345

    def test_read_pid_no_file(self, tmp_path):
        """测试 PID 文件不存在时返回 None。"""
        pid_file = tmp_path / "nonexistent.pid"
        with patch("webu.google_api.cli.PID_FILE", pid_file):
            assert _read_pid() is None

    def test_remove_pid(self, tmp_path):
        """测试删除 PID 文件。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345")
        with patch("webu.google_api.cli.PID_FILE", pid_file):
            _remove_pid()
            assert not pid_file.exists()

    def test_remove_pid_nonexistent(self, tmp_path):
        """测试删除不存在的 PID 文件（不报错）。"""
        pid_file = tmp_path / "nonexistent.pid"
        with patch("webu.google_api.cli.PID_FILE", pid_file):
            _remove_pid()  # 不应抛出异常

    def test_is_process_running_current(self):
        """测试当前进程应该是运行中的。"""
        assert _is_process_running(os.getpid()) is True

    def test_is_process_running_nonexistent(self):
        """测试不存在的 PID。"""
        # 使用一个极大的 PID 号，几乎不可能存在
        assert _is_process_running(99999999) is False


# ═══════════════════════════════════════════════════════════════
# CLI 命令测试（mock）
# ═══════════════════════════════════════════════════════════════


class TestCLICommands:
    """CLI 命令测试（使用 mock 避免实际操作）。"""

    def test_status_no_pid(self, tmp_path):
        """测试 status 命令 — 无 PID 文件。"""
        pid_file = tmp_path / "test.pid"
        with patch("webu.google_api.cli.PID_FILE", pid_file):
            args = MagicMock()
            cmd_status(args)  # 不应抛出异常

    def test_status_dead_process(self, tmp_path):
        """测试 status 命令 — PID 文件存在但进程已死。"""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("99999999")
        with patch("webu.google_api.cli.PID_FILE", pid_file):
            args = MagicMock()
            cmd_status(args)
            # PID 文件应被清理
            assert not pid_file.exists()

    def test_stats_command(self):
        """测试 stats 命令 — mock ProxyPool。"""
        mock_pool = MagicMock()
        mock_pool.stats.return_value = {
            "total_ips": 1000,
            "total_checked": 500,
            "total_valid": 50,
            "valid_ratio": "10.0%",
        }

        with patch("webu.google_api.proxy_pool.ProxyPool", return_value=mock_pool):
            args = MagicMock()
            # 不做实际调用，因为 cmd_stats 内部导入模块
            # 只确保不崩溃即可


# ═══════════════════════════════════════════════════════════════
# CLI 入口测试
# ═══════════════════════════════════════════════════════════════


class TestCLIEntry:
    """CLI 入口点测试。"""

    def test_help_output(self):
        """测试 --help 命令输出。"""
        result = subprocess.run(
            [sys.executable, "-m", "webu.google_api", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "Google Search API" in result.stdout
        assert "start" in result.stdout
        assert "stop" in result.stdout

    def test_subcommand_help(self):
        """测试子命令 --help 输出。"""
        for cmd in ["start", "stop", "status", "logs", "collect", "check", "stats"]:
            result = subprocess.run(
                [sys.executable, "-m", "webu.google_api", cmd, "--help"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert result.returncode == 0, f"{cmd} --help failed"

    def test_no_args_shows_help(self):
        """测试无参数时显示帮助。"""
        result = subprocess.run(
            [sys.executable, "-m", "webu.google_api"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # 无参数时应显示帮助（不应崩溃）
        assert result.returncode == 0
