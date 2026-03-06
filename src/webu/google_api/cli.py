"""ggsc (GooGle-SearCh) CLI — 服务管理 + 代理状态 + Google 搜索。

命令行工具: ggsc

支持的命令：
  start       — 启动 FastAPI 搜索服务（后台）
  stop        — 停止服务
  restart     — 重启服务
  status      — 查看服务状态
  logs        — 查看服务日志
  search      — 执行 Google 搜索
  search-test — 用多个代理测试搜索
  proxy-status — 查看代理健康状态
  proxy-check  — 立即执行代理健康检查
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

from webu.runtime_settings import resolve_google_api_settings

# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

_GOOGLE_API_SETTINGS = resolve_google_api_settings()

DATA_DIR = _GOOGLE_API_SETTINGS.data_dir
PID_FILE = DATA_DIR / "server.pid"
LOG_FILE = DATA_DIR / "server.log"

DEFAULT_HOST = _GOOGLE_API_SETTINGS.host
DEFAULT_PORT = _GOOGLE_API_SETTINGS.port

# ═══════════════════════════════════════════════════════════════
# PID 管理
# ═══════════════════════════════════════════════════════════════


def _ensure_data_dir():
    """确保数据目录存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_pid() -> int | None:
    """读取 PID 文件。"""
    try:
        if PID_FILE.exists():
            return int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        pass
    return None


def _write_pid(pid: int):
    """写入 PID 文件。"""
    _ensure_data_dir()
    PID_FILE.write_text(str(pid))


def _remove_pid():
    """删除 PID 文件。"""
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _is_process_running(pid: int) -> bool:
    """检查进程是否存活。"""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


# ═══════════════════════════════════════════════════════════════
# 服务管理命令
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
        sys.executable,
        "-m",
        "uvicorn",
        "webu.google_api.server:app_instance",
        "--host",
        host,
        "--port",
        str(port),
        "--factory",
    ]

    logger.note(f"> Starting Google Search Server on {host}:{port} ...")
    log_fp = open(LOG_FILE, "a")
    proc = subprocess.Popen(
        cmd,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _write_pid(proc.pid)
    logger.okay(f"  ✓ Server started (PID: {proc.pid})")
    logger.mesg(f"  Log: {logstr.file(LOG_FILE)}")


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
        # 等待进程退出
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
    """重启服务。"""
    cmd_stop(args)
    time.sleep(1)
    cmd_start(args)


def cmd_status(args):
    """查看服务状态。"""
    pid = _read_pid()
    if not pid:
        logger.mesg("  Server: NOT RUNNING (no PID file)")
        return

    if _is_process_running(pid):
        logger.okay(f"  Server: RUNNING (PID: {pid})")
        # 尝试获取代理状态
        try:
            import urllib.request
            import json

            port = getattr(args, "port", DEFAULT_PORT)
            url = f"http://127.0.0.1:{port}/proxy/status"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                logger.mesg(
                    f"  Proxies: {data['healthy_proxies']}/{data['total_proxies']} healthy"
                )
        except Exception:
            pass
    else:
        logger.warn(f"  Server: DEAD (PID: {pid} not found)")
        _remove_pid()
        logger.mesg("  Cleaned up stale PID file")


def cmd_logs(args):
    """查看服务日志。"""
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


# ═══════════════════════════════════════════════════════════════
# 代理状态命令
# ═══════════════════════════════════════════════════════════════


def cmd_proxy_status(args):
    """查看代理健康状态。"""
    from .proxy_manager import ProxyManager, DEFAULT_PROXIES

    proxies_str = getattr(args, "proxies", None)
    if proxies_str:
        proxy_list = _parse_proxy_list(proxies_str)
    else:
        proxy_list = None

    async def _run():
        manager = ProxyManager(
            proxies=proxy_list,
            verbose=True,
        )
        await manager._check_all()
        stats = manager.stats()

        logger.note("> Proxy Status:")
        for p in stats["proxies"]:
            status = "✓" if p["healthy"] else "×"
            logger.mesg(
                f"  {status} {p['name']:20s} "
                f"latency={p['latency_ms']:5d}ms "
                f"successes={p['total_successes']} "
                f"failures={p['total_failures']}"
            )
        logger.mesg(
            f"\n  Total: {stats['total_proxies']} proxies, "
            f"{stats['healthy_proxies']} healthy"
        )

    asyncio.run(_run())


def cmd_proxy_check(args):
    """立即执行代理健康检查。"""
    from .proxy_manager import ProxyManager, check_proxy_health

    proxies_str = getattr(args, "proxies", None)
    if proxies_str:
        proxy_list = _parse_proxy_list(proxies_str)
    else:
        proxy_list = None

    async def _run():
        manager = ProxyManager(
            proxies=proxy_list,
            verbose=True,
        )
        logger.note("> Running health check on all proxies ...")
        await manager._check_all()

        stats = manager.stats()
        for p in stats["proxies"]:
            status = "✓ healthy" if p["healthy"] else "× unhealthy"
            logger.mesg(f"  {logstr.file(p['url'])}: {status} ({p['latency_ms']}ms)")

    asyncio.run(_run())


# ═══════════════════════════════════════════════════════════════
# 搜索命令
# ═══════════════════════════════════════════════════════════════


def cmd_search(args):
    """执行 Google 搜索并展示结果。"""
    from .scraper import GoogleScraper
    from .proxy_manager import ProxyManager

    query = getattr(args, "query", "test")
    proxy_url = getattr(args, "proxy", None)
    num = getattr(args, "num", 10)
    profile_dir = getattr(args, "profile", None)

    async def _run():
        search_start = time.time()

        # 如果指定了代理，直接使用；否则用 ProxyManager
        if proxy_url:
            manager = None
            logger.note(
                f"> Searching: {logstr.mesg(query)} via {logstr.file(proxy_url)}"
            )
        else:
            manager = ProxyManager(verbose=True)
            await manager.start()
            logger.note(f"> Searching: {logstr.mesg(query)} via ProxyManager")

        scraper = GoogleScraper(
            proxy_manager=manager,
            headless=True,
            verbose=True,
            proxy_url=proxy_url,  # 传给 _fixed_proxy，每次搜索 context 级别使用
            profile_dir=profile_dir,
        )
        try:
            await scraper.start()
            result = await scraper.search(
                query=query,
                num=num,
                proxy_url=proxy_url,
                retry_count=2,
            )

            if result.has_captcha:
                logger.warn("  × CAPTCHA detected — try a different proxy")
                return

            if not result.results:
                logger.warn(f"  × No results — {result.error or 'unknown error'}")
                return

            logger.okay(
                f"  ✓ {len(result.results)} results" f" ({result.total_results_text})"
            )
            for i, r in enumerate(result.results):
                logger.mesg(f"\n  [{i+1}] {r.title}")
                logger.mesg(f"      {logstr.file(r.url)}")
                if r.snippet:
                    logger.mesg(f"      {r.snippet[:120]}...")

            # 总耗时统计
            total_s = time.time() - search_start
            logger.note(f"\n> Total elapsed: {total_s:.2f}s")
        finally:
            await scraper.stop()
            if manager:
                await manager.stop()

    asyncio.run(_run())


def cmd_search_test(args):
    """用多个代理测试 Google 搜索。"""
    from .scraper import GoogleScraper
    from .proxy_manager import ProxyManager, DEFAULT_PROXIES

    query = getattr(args, "query", "test")
    proxies_str = getattr(args, "proxies", None)

    # 解析代理列表
    if proxies_str:
        proxy_list = [p.strip() for p in proxies_str.split(",") if p.strip()]
    else:
        proxy_list = [p["url"] for p in DEFAULT_PROXIES]

    logger.note(f"> Search test: query={logstr.mesg(query)}, proxies={len(proxy_list)}")

    async def _run():
        scraper = GoogleScraper(headless=True, verbose=True)
        results = []
        try:
            await scraper.start()

            for i, purl in enumerate(proxy_list):
                logger.note(
                    f"\n> [{i+1}/{len(proxy_list)}] Testing {logstr.mesg(purl)}"
                )
                start = time.time()
                result = await scraper.search(
                    query=query,
                    num=5,
                    proxy_url=purl,
                    retry_count=0,
                )
                elapsed_ms = int((time.time() - start) * 1000)

                r_dict = {
                    "proxy_url": purl,
                    "success": bool(result.results and not result.has_captcha),
                    "result_count": len(result.results),
                    "has_captcha": result.has_captcha,
                    "error": result.error,
                    "latency_ms": elapsed_ms,
                }
                results.append(r_dict)

                if r_dict["success"]:
                    logger.okay(
                        f"  ✓ {logstr.file(purl)}: {r_dict['result_count']} results "
                        f"({elapsed_ms}ms)"
                    )
                    for res in result.results[:3]:
                        logger.mesg(f"    - {res.title}")
                        logger.mesg(f"      {logstr.file(res.url)}")
                else:
                    reason = "CAPTCHA" if r_dict["has_captcha"] else r_dict["error"]
                    logger.warn(f"  × {logstr.file(purl)}: {reason} ({elapsed_ms}ms)")

                if i < len(proxy_list) - 1:
                    await asyncio.sleep(2)
        finally:
            await scraper.stop()

        # Summary
        total = len(results)
        success = sum(1 for r in results if r["success"])
        captcha = sum(1 for r in results if r["has_captcha"])
        logger.note(f"\n> Summary:")
        logger.mesg(f"  Total: {total}, Success: {success}, CAPTCHA: {captcha}")
        logger.mesg(
            f"  Success rate: {success}/{total} ({success/max(1,total)*100:.0f}%)"
        )

    asyncio.run(_run())


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════


def _parse_proxy_list(proxies_str: str) -> list[dict]:
    """解析代理字符串为代理配置列表。"""
    proxy_list = []
    for i, url in enumerate(proxies_str.split(",")):
        url = url.strip()
        if not url:
            continue
        proxy_list.append(
            {
                "url": url,
                "role": "primary" if i == 0 else "backup",
                "name": url,
            }
        )
    return proxy_list


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════


def main():
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        prog="ggsc",
        description="ggsc (GooGle-SearCh) — 服务管理 + 搜索 + 代理状态",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # start
    sp_start = subparsers.add_parser("start", help="启动搜索服务（后台）")
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
    sp_status.add_argument("--port", type=int, default=DEFAULT_PORT, help="服务端口")
    sp_status.set_defaults(func=cmd_status)

    # logs
    sp_logs = subparsers.add_parser("logs", help="查看服务日志")
    sp_logs.add_argument("-n", "--lines", type=int, default=50, help="显示行数")
    sp_logs.add_argument("-f", "--follow", action="store_true", help="实时跟踪日志")
    sp_logs.set_defaults(func=cmd_logs)

    # search
    sp_search = subparsers.add_parser("search", help="执行 Google 搜索")
    sp_search.add_argument("query", help="搜索关键词")
    sp_search.add_argument(
        "--proxy",
        help="指定代理 URL（默认使用 ProxyManager 自动选择）",
    )
    sp_search.add_argument("--num", type=int, default=10, help="结果数量")
    sp_search.add_argument(
        "--profile",
        help="Chrome Profile 目录（持久化 Cookie / 验证状态）",
    )
    sp_search.set_defaults(func=cmd_search)

    # search-test
    sp_stest = subparsers.add_parser("search-test", help="用多个代理测试搜索")
    sp_stest.add_argument("--query", default="test", help="搜索查询词")
    sp_stest.add_argument(
        "--proxies",
        help="逗号分隔的代理列表（默认使用所有配置代理）",
    )
    sp_stest.set_defaults(func=cmd_search_test)

    # proxy-status
    sp_pstatus = subparsers.add_parser("proxy-status", help="查看代理健康状态")
    sp_pstatus.add_argument(
        "--proxies",
        help="逗号分隔的代理列表（默认使用配置代理）",
    )
    sp_pstatus.set_defaults(func=cmd_proxy_status)

    # proxy-check
    sp_pcheck = subparsers.add_parser("proxy-check", help="立即执行代理健康检查")
    sp_pcheck.add_argument(
        "--proxies",
        help="逗号分隔的代理列表（默认使用配置代理）",
    )
    sp_pcheck.set_defaults(func=cmd_proxy_check)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
