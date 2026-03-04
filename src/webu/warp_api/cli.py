"""cfwp (CloudFlare WarP) CLI — Cloudflare WARP 代理管理工具。

命令行工具: cfwp

支持的命令：
  start      — 启动 WARP 代理 + 管理 API 服务（后台）
  stop       — 停止服务
  restart    — 重启服务
  status     — 查看服务及 WARP 状态
  logs       — 查看服务日志
  ip         — 检测直连/WARP 出口 IP
  connect    — 连接 WARP
  disconnect — 断开 WARP
  fix        — 修复 WARP 与 Tailscale 的网络冲突
"""

import argparse
import asyncio
import os
import signal
import subprocess
import sys
import threading
import time

from pathlib import Path
from tclogger import logger, logstr

from .constants import (
    DATA_DIR,
    PID_FILE,
    LOG_FILE,
    WARP_PROXY_HOST,
    WARP_PROXY_PORT,
    WARP_API_HOST,
    WARP_API_PORT,
    WARP_INTERFACE,
)


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
    """启动 WARP 代理 + 管理 API 服务（后台运行）。"""
    pid = _read_pid()
    if pid and _is_process_running(pid):
        logger.warn(f"  × Server already running (PID: {pid})")
        return

    # 自动修复 Tailscale 兼容性
    try:
        from .netfix import fix_tailscale_compat

        logger.note("> Checking WARP/Tailscale compatibility ...")
        fix_tailscale_compat()
    except Exception as e:
        logger.warn(f"  × Tailscale compat fix failed: {e}")

    proxy_host = getattr(args, "proxy_host", WARP_PROXY_HOST)
    proxy_port = getattr(args, "proxy_port", WARP_PROXY_PORT)
    api_host = getattr(args, "api_host", WARP_API_HOST)
    api_port = getattr(args, "api_port", WARP_API_PORT)

    _ensure_data_dir()

    # 后台启动 — 需要 root 权限以使用 SO_BINDTODEVICE
    python_exe = sys.executable
    serve_args = [
        "-m", "webu.warp_api",
        "_serve",
        "--proxy-host", proxy_host,
        "--proxy-port", str(proxy_port),
        "--api-host", api_host,
        "--api-port", str(api_port),
    ]

    if os.geteuid() == 0:
        cmd = [python_exe] + serve_args
    else:
        sudopass = os.environ.get("SUDOPASS", "")
        if sudopass:
            # 使用 SUDOPASS 环境变量通过 sudo -S 提权
            cmd = [
                "sudo", "-S", "env", f"PATH={os.environ.get('PATH', '')}",
                python_exe,
            ] + serve_args
        else:
            logger.warn(
                "  × Proxy requires root (SO_BINDTODEVICE). "
                "Set SUDOPASS env or run as root."
            )
            logger.mesg("  Example: SUDOPASS=xxx cfwp start")
            return

    logger.note(
        f"> Starting WARP Proxy on {proxy_host}:{proxy_port} "
        f"+ API on {api_host}:{api_port} ..."
    )
    log_fp = open(LOG_FILE, "a")

    stdin_pipe = None
    sudopass = os.environ.get("SUDOPASS", "")
    if sudopass and os.geteuid() != 0:
        stdin_pipe = subprocess.PIPE

    proc = subprocess.Popen(
        cmd,
        stdin=stdin_pipe,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    # 通过 stdin 传递密码给 sudo -S
    if stdin_pipe and sudopass:
        try:
            proc.stdin.write((sudopass + "\n").encode())
            proc.stdin.flush()
            proc.stdin.close()
        except Exception:
            pass

    _write_pid(proc.pid)
    logger.okay(f"  ✓ Server started (PID: {proc.pid})")
    logger.mesg(f"  Log: {LOG_FILE}")
    logger.mesg(f"  SOCKS5 proxy: socks5://{proxy_host}:{proxy_port}")
    logger.mesg(f"  API docs: http://{api_host}:{api_port}/docs")


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

    def _kill(pid, sig, group=False):
        """发送信号给进程或进程组（自动提权）。"""
        target = -pid if group else pid
        try:
            os.kill(target, sig)
        except PermissionError:
            if group:
                subprocess.run(
                    ["sudo", "kill", f"-{sig}", "--", f"-{pid}"], check=False
                )
            else:
                subprocess.run(
                    ["sudo", "kill", f"-{sig}", str(pid)], check=False
                )
        except ProcessLookupError:
            pass

    try:
        # 先尝试终止整个进程组（sudo + python 子进程）
        _kill(pid, signal.SIGTERM, group=True)
        for _ in range(10):
            if not _is_process_running(pid):
                break
            time.sleep(0.5)
        else:
            logger.warn(f"  × Process didn't stop gracefully, sending SIGKILL ...")
            _kill(pid, signal.SIGKILL, group=True)
            time.sleep(0.5)
    except ProcessLookupError:
        pass

    _remove_pid()
    logger.okay(f"  ✓ Server stopped")


def cmd_restart(args):
    cmd_stop(args)
    time.sleep(1)
    cmd_start(args)


def cmd_status(args):
    """查看服务与 WARP 状态。"""
    from .warp import WarpClient

    # 服务状态
    pid = _read_pid()
    if not pid:
        logger.mesg("  Proxy server: NOT RUNNING (no PID file)")
    elif _is_process_running(pid):
        logger.okay(f"  Proxy server: RUNNING (PID: {pid})")
    else:
        logger.warn(f"  Proxy server: DEAD (PID: {pid} not found)")
        _remove_pid()

    # WARP 状态
    warp = WarpClient()
    info = warp.status()
    warp_ip = warp.get_warp_ip() or "N/A"

    if info.get("connected"):
        logger.okay(f"  WARP: {logstr.mesg('Connected')} ({warp_ip})")
    else:
        status_str = info.get("status", "Unknown")
        logger.warn(f"  WARP: {logstr.mesg(status_str)}")

    try:
        org = warp.organization()
        logger.mesg(f"  Organization: {logstr.mesg(org)}")
    except Exception:
        pass


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


def cmd_ip(args):
    """检测直连/WARP 出口 IP。"""
    from .warp import WarpClient

    warp = WarpClient()
    logger.note("> Checking IPs ...")

    result = warp.check_ip()
    logger.mesg(f"  Direct exit IP:    {logstr.mesg(result['direct_ip'] or 'N/A')}")
    logger.mesg(f"  WARP exit IP:      {logstr.mesg(result['warp_exit_ip'] or 'N/A')}")
    logger.mesg(f"  WARP interface IP: {logstr.mesg(result['warp_interface_ip'] or 'N/A')}")

    if result["warp_active"]:
        logger.okay(f"  ✓ WARP is masking your IP")
    else:
        logger.warn(f"  × WARP is NOT active or not changing exit IP")


def cmd_connect(args):
    from .warp import WarpClient

    warp = WarpClient()
    warp.connect()


def cmd_disconnect(args):
    from .warp import WarpClient

    warp = WarpClient()
    warp.disconnect()


def cmd_fix(args):
    """修复 WARP 与 Tailscale 的网络兼容性。"""
    from .netfix import fix_tailscale_compat, check_tailscale_compat

    check_only = getattr(args, "check", False)

    if check_only:
        logger.note("> Checking WARP/Tailscale compatibility ...")
        status = check_tailscale_compat()
        for key, val in status.items():
            icon = logstr.okay("✓") if val else logstr.warn("×")
            logger.mesg(f"  {icon} {key}: {val}")
    else:
        logger.note("> Fixing WARP/Tailscale compatibility ...")
        result = fix_tailscale_compat()
        fixed_count = sum(1 for v in result.values() if v)
        if fixed_count:
            logger.okay(f"  ✓ Applied {fixed_count} fix(es)")
        else:
            logger.mesg("  No fixes needed — all checks passed")


# ═══════════════════════════════════════════════════════════════
# 内部服务入口 — 同时运行代理 + API
# ═══════════════════════════════════════════════════════════════


def cmd_serve(args):
    """内部命令：实际启动代理 + API 服务（前台阻塞）。"""
    import uvicorn
    from .proxy import WarpSocksProxy
    from .server import create_warp_server, set_proxy_instance

    proxy_host = getattr(args, "proxy_host", WARP_PROXY_HOST)
    proxy_port = getattr(args, "proxy_port", WARP_PROXY_PORT)
    api_host = getattr(args, "api_host", WARP_API_HOST)
    api_port = getattr(args, "api_port", WARP_API_PORT)

    proxy = WarpSocksProxy(
        host=proxy_host,
        port=proxy_port,
    )
    set_proxy_instance(proxy)

    app = create_warp_server()

    shutdown_event = asyncio.Event()

    async def _run_all():
        # 启动代理和 API 服务
        proxy_task = asyncio.create_task(proxy.start())

        config = uvicorn.Config(
            app,
            host=api_host,
            port=api_port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        api_task = asyncio.create_task(server.serve())

        # 等待关闭信号或任一服务退出
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        done, pending = await asyncio.wait(
            [proxy_task, api_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        logger.note("> Shutting down services ...")
        # 停止 uvicorn
        server.should_exit = True
        # 停止代理
        await proxy.stop()
        # 取消剩余任务
        for task in pending:
            task.cancel()
        # 等待任务退出（最多 3 秒）
        if pending:
            await asyncio.wait(pending, timeout=3.0)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown(signum, frame):
        logger.note(f"\n> Received signal {signum}, shutting down ...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(_run_all())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        # 清理残余任务
        pending = asyncio.all_tasks(loop)
        if pending:
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
        logger.okay("  ✓ Server shutdown complete")


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        prog="cfwp",
        description="cfwp (CloudFlare WarP) — Cloudflare WARP 代理管理工具",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # start
    sp_start = subparsers.add_parser("start", help="启动 WARP 代理（后台）")
    sp_start.add_argument("--proxy-host", default=WARP_PROXY_HOST, help="代理绑定地址")
    sp_start.add_argument("--proxy-port", type=int, default=WARP_PROXY_PORT, help="代理端口")
    sp_start.add_argument("--api-host", default=WARP_API_HOST, help="API 绑定地址")
    sp_start.add_argument("--api-port", type=int, default=WARP_API_PORT, help="API 端口")
    sp_start.set_defaults(func=cmd_start)

    # stop
    sp_stop = subparsers.add_parser("stop", help="停止服务")
    sp_stop.set_defaults(func=cmd_stop)

    # restart
    sp_restart = subparsers.add_parser("restart", help="重启服务")
    sp_restart.add_argument("--proxy-host", default=WARP_PROXY_HOST, help="代理绑定地址")
    sp_restart.add_argument("--proxy-port", type=int, default=WARP_PROXY_PORT, help="代理端口")
    sp_restart.add_argument("--api-host", default=WARP_API_HOST, help="API 绑定地址")
    sp_restart.add_argument("--api-port", type=int, default=WARP_API_PORT, help="API 端口")
    sp_restart.set_defaults(func=cmd_restart)

    # status
    sp_status = subparsers.add_parser("status", help="查看服务及 WARP 状态")
    sp_status.set_defaults(func=cmd_status)

    # logs
    sp_logs = subparsers.add_parser("logs", help="查看服务日志")
    sp_logs.add_argument("-n", "--lines", type=int, default=50, help="显示行数")
    sp_logs.add_argument("-f", "--follow", action="store_true", help="实时跟踪")
    sp_logs.set_defaults(func=cmd_logs)

    # ip
    sp_ip = subparsers.add_parser("ip", help="检测直连/WARP 出口 IP")
    sp_ip.set_defaults(func=cmd_ip)

    # connect
    sp_connect = subparsers.add_parser("connect", help="连接 WARP")
    sp_connect.set_defaults(func=cmd_connect)

    # disconnect
    sp_disconnect = subparsers.add_parser("disconnect", help="断开 WARP")
    sp_disconnect.set_defaults(func=cmd_disconnect)

    # fix
    sp_fix = subparsers.add_parser("fix", help="修复 WARP 与 Tailscale 兼容性")
    sp_fix.add_argument("--check", action="store_true", help="仅检查，不修复")
    sp_fix.set_defaults(func=cmd_fix)

    # _serve (内部命令，用户不应直接调用)
    sp_serve = subparsers.add_parser("_serve", help=argparse.SUPPRESS)
    sp_serve.add_argument("--proxy-host", default=WARP_PROXY_HOST)
    sp_serve.add_argument("--proxy-port", type=int, default=WARP_PROXY_PORT)
    sp_serve.add_argument("--api-host", default=WARP_API_HOST)
    sp_serve.add_argument("--api-port", type=int, default=WARP_API_PORT)
    sp_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
