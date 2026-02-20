"""Gemini 运行管理器。

将 Browser 实例和 FastAPI 服务器作为后台守护进程运行，
通过 CLI 命令进行生命周期管理和日志监控。

用法:
    python -m webu.gemini.run start       # 后台启动浏览器 + 服务器
    python -m webu.gemini.run stop        # 停止后台进程
    python -m webu.gemini.run restart     # 重启
    python -m webu.gemini.run status      # 查看运行状态
    python -m webu.gemini.run logs        # 追踪日志输出 (Ctrl+C 退出)
    python -m webu.gemini.run logs -n 50  # 追踪最后 50 行日志
    python -m webu.gemini.run fg          # 前台运行 (调试用)
"""

import argparse
import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time

from pathlib import Path
from tclogger import logger, logstr

from .config import GeminiConfig, GeminiConfigType
from .server import create_gemini_server


# ═══════════════════════════════════════════════════════════════
# 运行状态 & 日志路径
# ═══════════════════════════════════════════════════════════════

_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data" / "gemini"
_STATE_FILE = _DATA_DIR / "runner_state.json"
_LOG_FILE = _DATA_DIR / "runner.log"
_PID_FILE = _DATA_DIR / "runner.pid"


def _ensure_data_dir():
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── 状态持久化 ───────────────────────────────────────────────


def _save_state(state: dict):
    _ensure_data_dir()
    _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _clear_state():
    if _STATE_FILE.exists():
        _STATE_FILE.unlink(missing_ok=True)
    if _PID_FILE.exists():
        _PID_FILE.unlink(missing_ok=True)


def _save_pid(pid: int):
    _ensure_data_dir()
    _PID_FILE.write_text(str(pid), encoding="utf-8")


def _load_pid() -> int | None:
    if _PID_FILE.exists():
        try:
            return int(_PID_FILE.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return None
    return None


def _is_process_alive(pid: int) -> bool:
    """检查指定 PID 的进程是否仍然存活。"""
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ═══════════════════════════════════════════════════════════════
# GeminiRunner — 核心运行逻辑
# ═══════════════════════════════════════════════════════════════


class GeminiRunner:
    """Gemini Browser + Server 的一体化运行管理器。

    支持两种模式：
    - 前台模式 (fg): 直接在当前进程运行，日志输出到终端
    - 后台模式 (start): fork 守护进程，日志写入文件

    管理命令:
    - start:   后台启动
    - stop:    停止后台进程
    - restart: 先停后启
    - status:  查看状态
    - logs:    追踪日志
    - fg:      前台运行
    """

    def __init__(self, config: GeminiConfigType = None, config_path: str = None):
        self.gemini_config = GeminiConfig(config=config, config_path=config_path)

    # ── 前台运行 ─────────────────────────────────────────────

    async def run_foreground(self):
        """在前台运行（阻塞式），日志输出到终端。Ctrl+C 停止。"""
        import uvicorn

        hostname = socket.gethostname()
        api_port = self.gemini_config.api_port
        novnc_port = self.gemini_config.novnc_port
        pid = os.getpid()

        _save_state(
            {
                "pid": pid,
                "api_port": api_port,
                "novnc_port": novnc_port,
                "hostname": hostname,
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "running",
                "mode": "foreground",
            }
        )
        _save_pid(pid)

        self._print_banner(hostname, api_port, novnc_port, pid, mode="foreground")

        app = create_gemini_server(config=self.gemini_config.config)
        config = uvicorn.Config(app, host="0.0.0.0", port=api_port, log_level="info")
        server = uvicorn.Server(config)

        stop_event = asyncio.Event()
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: stop_event.set())

        server_task = asyncio.create_task(server.serve())

        try:
            await stop_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            logger.note("\n> 正在关闭 Gemini Runner ...")
            server.should_exit = True
            await server_task
            _clear_state()
            logger.okay("  ✓ Gemini Runner 已停止")

    # ── 后台启动 ─────────────────────────────────────────────

    def start_background(self) -> bool:
        """以后台守护进程方式启动。返回 True 表示成功。"""
        # 检查是否已有进程运行
        existing_pid = _load_pid()
        if existing_pid and _is_process_alive(existing_pid):
            state = _load_state()
            logger.warn(
                f"  Gemini Runner 已在后台运行 (PID: {existing_pid},"
                f" started: {state.get('started_at', '?')})"
            )
            logger.mesg("  如需重启，请先执行 stop 或使用 restart 命令")
            return False

        _ensure_data_dir()

        # 构建子进程命令 — 用 _daemon_worker 入口
        cmd = [
            sys.executable,
            "-m",
            "webu.gemini.run",
            "_daemon_worker",
        ]
        config_path = str(self.gemini_config.config_path)
        if config_path:
            cmd.extend(["-c", config_path])

        # 打开日志文件
        log_fd = open(_LOG_FILE, "a", encoding="utf-8")

        # 以子进程启动守护 worker
        proc = subprocess.Popen(
            cmd,
            stdout=log_fd,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # 脱离父进程会话
            close_fds=True,
        )
        log_fd.close()

        # 等待片刻，检查是否正常启动
        time.sleep(2)
        if proc.poll() is not None:
            logger.err(f"  × 后台进程启动失败 (exit code: {proc.returncode})")
            logger.mesg("  查看日志: python -m webu.gemini.run logs")
            return False

        # 记录 PID
        _save_pid(proc.pid)
        _save_state(
            {
                "pid": proc.pid,
                "api_port": self.gemini_config.api_port,
                "novnc_port": self.gemini_config.novnc_port,
                "hostname": socket.gethostname(),
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "running",
                "mode": "background",
            }
        )

        hostname = socket.gethostname()
        self._print_banner(
            hostname,
            self.gemini_config.api_port,
            self.gemini_config.novnc_port,
            proc.pid,
            mode="background",
        )
        logger.mesg(f"  日志文件: {logstr.file(str(_LOG_FILE))}")
        logger.mesg("  查看日志: python -m webu.gemini.run logs")
        return True

    # ── 停止 ─────────────────────────────────────────────────

    @staticmethod
    def stop_background() -> bool:
        """停止后台运行中的 Runner。返回 True 表示成功。

        使用进程组信号确保所有子进程（Chrome, Xvnc, noVNC 等）也被终止。
        """
        pid = _load_pid()
        if not pid:
            state = _load_state()
            pid = state.get("pid")

        if not pid:
            logger.warn("  没有运行中的 Gemini Runner")
            _clear_state()
            return False

        if not _is_process_alive(pid):
            logger.warn(f"  进程 {pid} 不存在，清理状态文件")
            _clear_state()
            return False

        # 获取进程组 ID（daemon 用 start_new_session=True 创建了新会话）
        try:
            pgid = os.getpgid(pid)
        except Exception:
            pgid = pid

        # 发送 SIGTERM 到整个进程组
        try:
            os.killpg(pgid, signal.SIGTERM)
            logger.mesg(f"  发送停止信号到进程组 {pgid} (PID {pid}) ...")
        except Exception:
            # 回退：仅发送给主进程
            try:
                os.kill(pid, signal.SIGTERM)
                logger.mesg(f"  发送停止信号到 PID {pid} ...")
            except Exception as e:
                logger.err(f"  × 发送停止信号失败: {e}")
                return False

        # 等待主进程退出（最多 15 秒）
        for i in range(30):
            if not _is_process_alive(pid):
                _clear_state()
                logger.okay(f"  ✓ Gemini Runner 已停止 (PID: {pid})")
                return True
            time.sleep(0.5)

        # 超时 → 强制 kill 整个进程组
        logger.warn(f"  进程 {pid} 未响应 SIGTERM，发送 SIGKILL ...")
        try:
            os.killpg(pgid, signal.SIGKILL)
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
        time.sleep(1)
        _clear_state()
        logger.okay(f"  ✓ Gemini Runner 已强制停止 (PID: {pid})")
        return True

    # ── 重启 ─────────────────────────────────────────────────

    def restart_background(self) -> bool:
        """重启后台 Runner。"""
        logger.note("> 重启 Gemini Runner ...")
        self.stop_background()
        time.sleep(2)
        return self.start_background()

    # ── 状态查询 ─────────────────────────────────────────────

    @staticmethod
    def status() -> dict:
        """查看运行状态。"""
        state = _load_state()
        if not state:
            return {"status": "stopped", "message": "没有运行中的 Gemini Runner"}

        pid = state.get("pid")
        if pid and _is_process_alive(pid):
            state["status"] = "running"
        else:
            state["status"] = "stopped"
            state["message"] = f"进程 {pid} 已退出"
            _clear_state()

        return state

    # ── 日志追踪 ─────────────────────────────────────────────

    @staticmethod
    def follow_logs(num_lines: int = 30):
        """追踪日志输出（类似 tail -f）。Ctrl+C 退出。"""
        if not _LOG_FILE.exists():
            logger.warn(f"  日志文件不存在: {_LOG_FILE}")
            logger.mesg("  请先使用 start 命令启动 Runner")
            return

        logger.note(f"  追踪日志: {logstr.file(str(_LOG_FILE))}")
        logger.mesg("  按 Ctrl+C 退出日志追踪 (Runner 继续在后台运行)")
        logger.note("─" * 60)

        try:
            # 先输出最后 num_lines 行
            _tail_file(_LOG_FILE, num_lines)

            # 然后持续追踪新内容
            with open(_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                # 移到文件末尾
                f.seek(0, 2)
                while True:
                    line = f.readline()
                    if line:
                        print(line, end="", flush=True)
                    else:
                        time.sleep(0.2)
        except KeyboardInterrupt:
            print()
            logger.note("─" * 60)
            logger.mesg("  日志追踪已停止，Runner 继续在后台运行")

    # ── 辅助方法 ─────────────────────────────────────────────

    @staticmethod
    def _print_banner(
        hostname: str,
        api_port: int,
        novnc_port: int,
        pid: int,
        mode: str = "foreground",
    ):
        mode_label = "前台" if mode == "foreground" else "后台"
        logger.note("═" * 60)
        logger.note(f"  Gemini Runner 已启动 ({mode_label}模式)")
        logger.note("─" * 60)
        logger.mesg(f"  API Server: http://{hostname}:{api_port}")
        logger.mesg(f"  Swagger UI: http://{hostname}:{api_port}/docs")
        logger.mesg(
            f"  VNC Viewer: http://{hostname}:{novnc_port}"
            f"/vnc.html?autoconnect=true&resize=remote"
        )
        logger.mesg(f"  PID:        {pid}")
        if mode == "foreground":
            logger.mesg("  按 Ctrl+C 停止")
        else:
            logger.mesg("  停止: python -m webu.gemini.run stop")
        logger.note("═" * 60)


def _tail_file(filepath: Path, num_lines: int = 30):
    """输出文件最后 num_lines 行。"""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            tail = lines[-num_lines:] if len(lines) > num_lines else lines
            for line in tail:
                print(line, end="", flush=True)
    except Exception as e:
        logger.warn(f"  × 读取日志文件失败: {e}")


def _print_status(status: dict):
    """格式化打印状态信息。"""
    is_running = status.get("status") == "running"

    logger.note("═" * 60)
    logger.note("  Gemini Runner 状态")
    logger.note("─" * 60)

    if is_running:
        logger.okay("  状态:     running ✓")
        logger.mesg(f"  PID:      {status.get('pid', '?')}")
        logger.mesg(f"  模式:     {status.get('mode', '?')}")
        logger.mesg(f"  API 端口: {status.get('api_port', '?')}")
        logger.mesg(f"  VNC 端口: {status.get('novnc_port', '?')}")
        logger.mesg(f"  主机名:   {status.get('hostname', '?')}")
        logger.mesg(f"  启动时间: {status.get('started_at', '?')}")
        if _LOG_FILE.exists():
            size = _LOG_FILE.stat().st_size
            size_str = (
                f"{size / 1024:.1f} KB"
                if size < 1024 * 1024
                else f"{size / 1024 / 1024:.1f} MB"
            )
            logger.mesg(f"  日志大小: {size_str}")
    else:
        logger.warn("  状态:     stopped ×")
        logger.mesg(f"  {status.get('message', '未运行')}")

    logger.note("═" * 60)


# ═══════════════════════════════════════════════════════════════
# 守护进程 Worker 入口
# ═══════════════════════════════════════════════════════════════


def _daemon_worker_main(config_path: str = None):
    """后台守护进程的实际运行入口。

    由 start_background() 通过子进程调用。stdout/stderr 已重定向到日志文件。
    日志输出自动去除 ANSI 颜色控制符。
    """
    import uvicorn
    from tclogger import decolored

    # 用 decolored 包装 stdout/stderr，去除颜色控制符
    class _DecoloredWriter:
        """去除 ANSI 颜色码的文件写入器。"""

        def __init__(self, stream):
            self._stream = stream

        def write(self, text):
            self._stream.write(decolored(text))

        def flush(self):
            self._stream.flush()

        def fileno(self):
            return self._stream.fileno()

        def isatty(self):
            return False

    sys.stdout = _DecoloredWriter(sys.stdout)
    sys.stderr = _DecoloredWriter(sys.stderr)

    config = GeminiConfig(config_path=config_path)
    pid = os.getpid()
    hostname = socket.gethostname()

    # 更新 PID（子进程的实际 PID）
    _save_pid(pid)
    _save_state(
        {
            "pid": pid,
            "api_port": config.api_port,
            "novnc_port": config.novnc_port,
            "hostname": hostname,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "running",
            "mode": "background",
        }
    )

    print(
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
        f"Gemini Runner daemon started (PID: {pid})"
    )
    print(
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
        f"API: http://{hostname}:{config.api_port}"
    )
    print(
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
        f"VNC: http://{hostname}:{config.novnc_port}"
        f"/vnc.html?autoconnect=true&resize=remote"
    )
    sys.stdout.flush()

    app = create_gemini_server(config=config.config)
    uvi_config = uvicorn.Config(
        app, host="0.0.0.0", port=config.api_port, log_level="info"
    )
    server = uvicorn.Server(uvi_config)

    # 信号处理
    def _handle_signal(signum, frame):
        print(
            f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
            f"Received signal {signum}, shutting down ..."
        )
        sys.stdout.flush()
        server.should_exit = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        server.run()
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ERROR: {e}")
        sys.stdout.flush()
    finally:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Gemini Runner daemon stopped")
        sys.stdout.flush()
        _clear_state()


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="Gemini Browser + Server 运行管理器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
命令说明:
  start       后台启动浏览器 + 服务器（守护进程）
  stop        停止后台运行的 Runner
  restart     重启后台 Runner
  status      查看运行状态
  logs        追踪日志输出（按 Ctrl+C 退出，Runner 继续运行）
  fg          前台运行（调试用，Ctrl+C 停止）

示例:
  python -m webu.gemini.run start             # 后台启动
  python -m webu.gemini.run start -c my.json  # 使用自定义配置
  python -m webu.gemini.run logs              # 查看日志
  python -m webu.gemini.run logs -n 100       # 查看最后100行日志
  python -m webu.gemini.run status            # 查看状态
  python -m webu.gemini.run stop              # 停止
  python -m webu.gemini.run restart           # 重启
  python -m webu.gemini.run fg                # 前台运行（调试）
""",
    )
    parser.add_argument(
        "command",
        choices=["start", "stop", "restart", "status", "logs", "fg", "_daemon_worker"],
        help="管理命令",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="配置文件路径（默认: configs/gemini.json）",
    )
    parser.add_argument(
        "-n",
        "--num-lines",
        type=int,
        default=30,
        help="日志追踪时显示的初始行数（默认: 30）",
    )

    args = parser.parse_args()

    if args.command == "_daemon_worker":
        # 内部命令 — 守护进程 worker
        _daemon_worker_main(config_path=args.config)
        return

    runner = GeminiRunner(config_path=args.config)

    if args.command == "start":
        runner.start_background()
    elif args.command == "stop":
        GeminiRunner.stop_background()
    elif args.command == "restart":
        runner.restart_background()
    elif args.command == "status":
        status = GeminiRunner.status()
        _print_status(status)
    elif args.command == "logs":
        GeminiRunner.follow_logs(num_lines=args.num_lines)
    elif args.command == "fg":
        asyncio.run(runner.run_foreground())


if __name__ == "__main__":
    main()
