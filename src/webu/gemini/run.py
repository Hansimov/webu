"""Gemini 运行管理器。

同时运行 Browser 实例和 FastAPI 服务器，并在命令行提供监控和管理功能。

用法:
    python -m webu.gemini.run start    # 启动浏览器 + 服务器
    python -m webu.gemini.run stop     # 停止
    python -m webu.gemini.run restart  # 重启
    python -m webu.gemini.run status   # 查看状态
"""

import argparse
import asyncio
import json
import os
import signal
import socket
import sys
import threading
import time
import uvicorn

from pathlib import Path
from tclogger import logger, logstr

from .config import GeminiConfig, GeminiConfigType
from .server import create_gemini_server


# 运行状态文件（记录 PID 和配置，供 status/stop 使用）
_STATE_DIR = Path(__file__).parent.parent.parent.parent / ".chats" / "gemini"
_STATE_FILE = _STATE_DIR / "runner_state.json"


def _save_state(state: dict):
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
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
        _STATE_FILE.unlink()


class GeminiRunner:
    """Gemini Browser + Server 的一体化运行管理器。

    在一个进程中同时运行：
    1. GeminiAgency（浏览器实例 + noVNC）
    2. FastAPI 服务器（REST API）

    提供 CLI 风格的 start/stop/restart/status 管理。
    """

    def __init__(self, config: GeminiConfigType = None, config_path: str = None):
        self.gemini_config = GeminiConfig(config=config, config_path=config_path)
        self._server_thread: threading.Thread = None
        self._uvicorn_server: uvicorn.Server = None
        self._stop_event = asyncio.Event()

    async def start(self):
        """启动浏览器和服务器。"""
        hostname = socket.gethostname()
        api_port = self.gemini_config.api_port
        novnc_port = self.gemini_config.novnc_port

        logger.note("═" * 60)
        logger.note("  Gemini Runner 启动中 ...")
        logger.note("═" * 60)

        # 创建 FastAPI 应用（lifespan 会自动启动 Agency）
        app = create_gemini_server(config=self.gemini_config.config)

        # 配置 uvicorn
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=api_port,
            log_level="info",
        )
        self._uvicorn_server = uvicorn.Server(config)

        # 保存运行状态
        _save_state(
            {
                "pid": os.getpid(),
                "api_port": api_port,
                "novnc_port": novnc_port,
                "hostname": hostname,
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "running",
            }
        )

        # 设置信号处理
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: self._stop_event.set())

        logger.note("─" * 60)
        logger.note(f"  API Server: http://{hostname}:{api_port}")
        logger.note(f"  Swagger UI: http://{hostname}:{api_port}/docs")
        logger.note(
            f"  VNC Viewer: http://{hostname}:{novnc_port}"
            f"/vnc.html?autoconnect=true&resize=remote"
        )
        logger.note(f"  PID: {os.getpid()}")
        logger.note("─" * 60)
        logger.note("  按 Ctrl+C 停止")
        logger.note("═" * 60)

        # 在后台启动 uvicorn
        server_task = asyncio.create_task(self._uvicorn_server.serve())

        # 等待停止信号
        try:
            await self._stop_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            logger.note("\n> 正在关闭 Gemini Runner ...")
            self._uvicorn_server.should_exit = True
            await server_task
            _save_state({**_load_state(), "status": "stopped"})
            _clear_state()
            logger.okay("  ✓ Gemini Runner 已停止")

    async def stop(self):
        """停止运行中的 Runner（通过发送信号）。"""
        state = _load_state()
        if not state or state.get("status") != "running":
            logger.warn("  没有运行中的 Gemini Runner")
            return

        pid = state.get("pid")
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                logger.okay(f"  ✓ 已向 PID {pid} 发送停止信号")
            except ProcessLookupError:
                logger.warn(f"  进程 {pid} 不存在，清理状态文件")
                _clear_state()
            except Exception as e:
                logger.err(f"  × 停止失败: {e}")
        else:
            logger.warn("  状态文件中没有 PID 信息")

    def status(self) -> dict:
        """查看运行状态。"""
        state = _load_state()
        if not state:
            return {"status": "not_running", "message": "没有运行中的 Gemini Runner"}

        pid = state.get("pid")
        is_running = False
        if pid:
            try:
                os.kill(pid, 0)  # 检查进程是否存在
                is_running = True
            except (ProcessLookupError, PermissionError):
                is_running = False

        if not is_running:
            state["status"] = "stopped"
            _clear_state()

        return state


def _print_status(status: dict):
    """格式化打印状态信息。"""
    is_running = status.get("status") == "running"
    marker = "✓" if is_running else "×"
    color = logstr.okay if is_running else logstr.warn

    logger.note("═" * 50)
    logger.note("  Gemini Runner 状态")
    logger.note("─" * 50)
    logger.mesg(f"  状态:     {color(status.get('status', 'unknown'))}")

    if is_running:
        logger.mesg(f"  PID:      {status.get('pid', '?')}")
        logger.mesg(f"  API 端口: {status.get('api_port', '?')}")
        logger.mesg(f"  VNC 端口: {status.get('novnc_port', '?')}")
        logger.mesg(f"  主机名:   {status.get('hostname', '?')}")
        logger.mesg(f"  启动时间: {status.get('started_at', '?')}")
    else:
        logger.mesg(f"  {status.get('message', '未运行')}")

    logger.note("═" * 50)


def main():
    parser = argparse.ArgumentParser(
        description="Gemini Browser + Server 运行管理器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m webu.gemini.run start             # 启动
  python -m webu.gemini.run start -c my.json  # 使用自定义配置
  python -m webu.gemini.run status            # 查看状态
  python -m webu.gemini.run stop              # 停止
  python -m webu.gemini.run restart           # 重启
""",
    )
    parser.add_argument(
        "command",
        choices=["start", "stop", "restart", "status"],
        help="管理命令",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="配置文件路径（默认: configs/gemini.json）",
    )

    args = parser.parse_args()
    runner = GeminiRunner(config_path=args.config)

    if args.command == "start":
        asyncio.run(runner.start())
    elif args.command == "stop":
        asyncio.run(runner.stop())
    elif args.command == "restart":
        asyncio.run(runner.stop())
        time.sleep(2)
        asyncio.run(runner.start())
    elif args.command == "status":
        status = runner.status()
        _print_status(status)


if __name__ == "__main__":
    main()
