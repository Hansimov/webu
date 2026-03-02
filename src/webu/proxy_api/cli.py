"""pxsc (ProXy-SearCh) CLI — 代理池管理工具。

命令行工具: pxsc

支持的命令：
  start      — 启动代理管理 API 服务（后台）
  stop       — 停止服务
  restart    — 重启服务
  status     — 查看服务状态
  logs       — 查看服务日志
  collect    — 采集代理 IP
  check      — 检测代理 IP 连通性 (Level-1)
  stats      — 查看代理池统计
  refresh    — 一键刷新（采集 + 检测）
  abandon    — 扫描并标记废弃代理
"""

import argparse
import asyncio
import os
import signal
import subprocess
import sys
import time

from pathlib import Path
from tclogger import logger, logstr

# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

DATA_DIR = Path("data/proxy_api")
PID_FILE = DATA_DIR / "server.pid"
LOG_FILE = DATA_DIR / "server.log"

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 18001

# ═══════════════════════════════════════════════════════════════
# PID 管理
# ═══════════════════════════════════════════════════════════════


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_pid() -> int | None:
    try:
        if PID_FILE.exists():
            return int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        pass
    return None


def _write_pid(pid: int):
    _ensure_data_dir()
    PID_FILE.write_text(str(pid))


def _remove_pid():
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


# ═══════════════════════════════════════════════════════════════
# CLI 命令实现
# ═══════════════════════════════════════════════════════════════


def cmd_start(args):
    """启动服务（后台运行）。"""
    pid = _read_pid()
    if pid and _is_process_running(pid):
        logger.warn(f"  × Server already running (PID: {pid})")
        return

    host = getattr(args, "host", DEFAULT_HOST)
    port = getattr(args, "port", DEFAULT_PORT)

    _ensure_data_dir()

    cmd = [
        sys.executable, "-m", "uvicorn",
        "webu.proxy_api.server:app_instance",
        "--host", host,
        "--port", str(port),
        "--factory",
    ]

    logger.note(f"> Starting Proxy API Server on {host}:{port} ...")
    log_fp = open(LOG_FILE, "a")
    proc = subprocess.Popen(
        cmd,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _write_pid(proc.pid)
    logger.okay(f"  ✓ Server started (PID: {proc.pid})")
    logger.mesg(f"  Log: {LOG_FILE}")


def cmd_stop(args):
    """停止服务。"""
    pid = _read_pid()
    if not pid:
        logger.warn("  × No PID file found — server not running?")
        return

    if not _is_process_running(pid):
        logger.warn(f"  × Process {pid} not found — cleaning up PID file")
        _remove_pid()
        return

    logger.note(f"> Stopping server (PID: {pid}) ...")
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            if not _is_process_running(pid):
                break
            time.sleep(0.5)
        else:
            logger.warn(f"  × Process didn't stop gracefully, sending SIGKILL ...")
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    _remove_pid()
    logger.okay(f"  ✓ Server stopped")


def cmd_restart(args):
    cmd_stop(args)
    time.sleep(1)
    cmd_start(args)


def cmd_status(args):
    pid = _read_pid()
    if not pid:
        logger.mesg("  Server: NOT RUNNING (no PID file)")
        return

    if _is_process_running(pid):
        logger.okay(f"  Server: RUNNING (PID: {pid})")
    else:
        logger.warn(f"  Server: DEAD (PID: {pid} not found)")
        _remove_pid()
        logger.mesg("  Cleaned up stale PID file")


def cmd_logs(args):
    if not LOG_FILE.exists():
        logger.warn("  × No log file found")
        return

    lines = getattr(args, "lines", 50)
    follow = getattr(args, "follow", False)

    if follow:
        os.execvp("tail", ["tail", "-f", str(LOG_FILE)])
    else:
        try:
            with open(LOG_FILE, "r") as f:
                all_lines = f.readlines()
                for line in all_lines[-lines:]:
                    print(line, end="")
        except Exception as e:
            logger.err(f"  × Failed to read logs: {e}")


def cmd_collect(args):
    from .pool import ProxyPool

    source = getattr(args, "source", None)
    pool = ProxyPool(verbose=True)

    if source:
        logger.note(f"> Collecting from source: {logstr.mesg(source)}")
        result = pool.collect_source(source)
    else:
        result = pool.collect()

    logger.okay(f"  ✓ Collect result: {logstr.mesg(result)}")


def cmd_check(args):
    from .pool import ProxyPool

    limit = getattr(args, "limit", 200)
    mode = getattr(args, "mode", "unchecked")
    pool = ProxyPool(verbose=True)

    async def _run():
        if mode == "unchecked":
            return await pool.check_unchecked(limit=limit)
        elif mode == "stale":
            return await pool.check_stale(limit=limit)
        elif mode == "all":
            return await pool.check_all(limit=limit)
        else:
            logger.err(f"  × Unknown mode: {mode}")
            return []

    results = asyncio.run(_run())
    valid = sum(1 for r in results if r.get("is_valid"))
    logger.okay(
        f"  ✓ Checked {logstr.mesg(len(results))}: "
        f"{logstr.mesg(valid)} valid, "
        f"{logstr.mesg(len(results) - valid)} invalid"
    )


def cmd_stats(args):
    from .pool import ProxyPool

    pool = ProxyPool(verbose=False)
    stats = pool.stats()
    logger.note("> Proxy Pool Stats:")
    for key, val in stats.items():
        logger.mesg(f"  {key}: {logstr.mesg(val)}")


def cmd_refresh(args):
    from .pool import ProxyPool

    limit = getattr(args, "limit", 200)
    pool = ProxyPool(verbose=True)

    async def _run():
        return await pool.refresh(check_limit=limit)

    result = asyncio.run(_run())
    logger.okay(f"  ✓ Refresh done: {logstr.mesg(result.get('stats', {}))}")


def cmd_abandon(args):
    from .pool import ProxyPool

    pool = ProxyPool(verbose=True)
    count = pool.scan_abandoned()
    stats = pool.get_abandoned_stats()
    logger.okay(
        f"  ✓ Newly abandoned: {logstr.mesg(count)}, "
        f"total abandoned: {logstr.mesg(stats['total_abandoned'])}"
    )


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        prog="pxsc",
        description="pxsc (ProXy-SearCh) — 代理池管理工具",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # start
    sp_start = subparsers.add_parser("start", help="启动代理管理服务（后台）")
    sp_start.add_argument("--host", default=DEFAULT_HOST, help="绑定地址")
    sp_start.add_argument("--port", type=int, default=DEFAULT_PORT, help="绑定端口")
    sp_start.set_defaults(func=cmd_start)

    # stop
    sp_stop = subparsers.add_parser("stop", help="停止服务")
    sp_stop.set_defaults(func=cmd_stop)

    # restart
    sp_restart = subparsers.add_parser("restart", help="重启服务")
    sp_restart.add_argument("--host", default=DEFAULT_HOST, help="绑定地址")
    sp_restart.add_argument("--port", type=int, default=DEFAULT_PORT, help="绑定端口")
    sp_restart.set_defaults(func=cmd_restart)

    # status
    sp_status = subparsers.add_parser("status", help="查看服务状态")
    sp_status.set_defaults(func=cmd_status)

    # logs
    sp_logs = subparsers.add_parser("logs", help="查看服务日志")
    sp_logs.add_argument("-n", "--lines", type=int, default=50, help="显示行数")
    sp_logs.add_argument("-f", "--follow", action="store_true", help="实时跟踪日志")
    sp_logs.set_defaults(func=cmd_logs)

    # collect
    sp_collect = subparsers.add_parser("collect", help="采集代理 IP")
    sp_collect.add_argument("--source", help="指定代理源名称")
    sp_collect.set_defaults(func=cmd_collect)

    # check
    sp_check = subparsers.add_parser("check", help="检测代理连通性 (Level-1)")
    sp_check.add_argument("--limit", type=int, default=200, help="最大检测数量")
    sp_check.add_argument(
        "--mode", choices=["unchecked", "stale", "all"], default="unchecked",
        help="检测模式",
    )
    sp_check.set_defaults(func=cmd_check)

    # stats
    sp_stats = subparsers.add_parser("stats", help="查看代理池统计")
    sp_stats.set_defaults(func=cmd_stats)

    # refresh
    sp_refresh = subparsers.add_parser("refresh", help="一键刷新：采集 + 检测")
    sp_refresh.add_argument("--limit", type=int, default=200, help="检测数量上限")
    sp_refresh.set_defaults(func=cmd_refresh)

    # abandon
    sp_abandon = subparsers.add_parser("abandon", help="扫描并标记废弃代理")
    sp_abandon.set_defaults(func=cmd_abandon)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
