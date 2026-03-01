"""ggsc (GooGle-SearCh) CLI — 服务管理 + 代理池操作。

命令行工具: ggsc

支持的命令：
  start      — 启动 FastAPI 搜索服务（后台）
  stop       — 停止服务
  restart    — 重启服务
  status     — 查看服务状态
  logs       — 查看服务日志
  collect    — 采集代理 IP
  check      — 检测代理 IP 可用性
  stats      — 查看代理池统计
  refresh    — 一键刷新（采集 + 检测）
  abandon    — 扫描并标记废弃代理
  parse-test — 用有效代理测试 Google 搜索结果解析
  diag       — 全面诊断 + 生成报告
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

DATA_DIR = Path("data/google_api")
PID_FILE = DATA_DIR / "server.pid"
LOG_FILE = DATA_DIR / "server.log"

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 18000

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
    headless = not getattr(args, "no_headless", False)

    _ensure_data_dir()

    cmd = [
        sys.executable, "-m", "uvicorn",
        "webu.google_api.server:app_instance",
        "--host", host,
        "--port", str(port),
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


def cmd_collect(args):
    """采集代理 IP。"""
    from .proxy_pool import ProxyPool

    source = getattr(args, "source", None)
    pool = ProxyPool(verbose=True)

    if source:
        logger.note(f"> Collecting from source: {logstr.mesg(source)}")
        result = pool.collect_source(source)
    else:
        result = pool.collect()

    logger.okay(f"  ✓ Collect result: {logstr.mesg(result)}")


def cmd_check(args):
    """检测代理 IP 可用性。"""
    from .proxy_pool import ProxyPool

    limit = getattr(args, "limit", 200)
    mode = getattr(args, "mode", "unchecked")
    level = getattr(args, "level", "all")
    pool = ProxyPool(verbose=True)

    async def _run():
        if mode == "unchecked":
            return await pool.check_unchecked(limit=limit, level=level)
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
    """查看代理池统计。"""
    from .proxy_pool import ProxyPool

    pool = ProxyPool(verbose=False)
    stats = pool.stats()
    logger.note("> Proxy Pool Stats:")
    for key, val in stats.items():
        logger.mesg(f"  {key}: {logstr.mesg(val)}")


def cmd_refresh(args):
    """一键刷新：采集 + 检测。"""
    from .proxy_pool import ProxyPool

    limit = getattr(args, "limit", 200)
    pool = ProxyPool(verbose=True)

    async def _run():
        return await pool.refresh(check_limit=limit)

    result = asyncio.run(_run())
    logger.okay(f"  ✓ Refresh done: {logstr.mesg(result.get('stats', {}))}")


def cmd_abandon(args):
    """扫描并标记废弃代理。"""
    from .proxy_pool import ProxyPool

    pool = ProxyPool(verbose=True)
    count = pool.scan_abandoned()
    stats = pool.get_abandoned_stats()
    logger.okay(
        f"  ✓ Newly abandoned: {logstr.mesg(count)}, "
        f"total abandoned: {logstr.mesg(stats['total_abandoned'])}"
    )


def cmd_parse_test(args):
    """用有效代理测试 Google 搜索结果解析。"""
    from .proxy_pool import ProxyPool

    query = getattr(args, "query", "python programming")
    limit = getattr(args, "limit", 5)
    pool = ProxyPool(verbose=True)

    async def _run():
        return await pool.search_parse_test(query=query, limit=limit)

    results = asyncio.run(_run())

    # 打印详细结果
    for i, r in enumerate(results):
        if r["success"]:
            logger.okay(f"\n  [{i+1}] ✓ {r['proxy_url']} ({r['latency_ms']}ms)")
            logger.mesg(f"      Results: {r['result_count']}")
            logger.mesg(f"      Total: {r['total_results_text']}")
            for res in r["results"][:3]:
                logger.mesg(f"      - {res['title']}")
                logger.mesg(f"        {res['url']}")
                if res.get("snippet"):
                    logger.mesg(f"        {res['snippet'][:100]}...")
        else:
            logger.warn(f"\n  [{i+1}] × {r['proxy_url']}: {r['error']}")


def cmd_diag(args):
    """全面诊断：采集 + 全量检测 + 生成报告。"""
    from .proxy_pool import ProxyPool
    from .mongo import MongoProxyStore
    from .proxy_collector import ProxyCollector
    from .proxy_checker import check_level1_batch, check_level2_batch

    import time
    from collections import Counter, defaultdict
    from datetime import datetime, timezone, timedelta

    TZ_SHANGHAI = timezone(timedelta(hours=8))

    store = MongoProxyStore(verbose=True)
    collector = ProxyCollector(store=store, verbose=True)

    report = {"timestamp": datetime.now(TZ_SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")}

    # Phase 1: Collect
    logger.note("=" * 60)
    logger.note("> Phase 1: Collecting proxies from all sources ...")
    collect_result = collector.collect_all()
    report["collect"] = collect_result

    all_ips = store.get_all_ips(limit=0)
    total_ips = len(all_ips)
    logger.okay(f"  ✓ Total IPs in database: {logstr.mesg(total_ips)}")

    # Stats by protocol & source
    proto_counts = Counter(ip["protocol"] for ip in all_ips)
    report["protocol_counts"] = dict(proto_counts)

    source_stats = defaultdict(lambda: {"count": 0, "protocols": Counter()})
    for ip in all_ips:
        src = ip.get("source", "unknown")
        source_stats[src]["count"] += 1
        source_stats[src]["protocols"][ip["protocol"]] += 1
    report["source_stats"] = {
        src: {"count": s["count"], "protocols": dict(s["protocols"])}
        for src, s in source_stats.items()
    }

    # Phase 2: Level-1 check all
    logger.note("=" * 60)
    logger.note(f"> Phase 2: Level-1 check ALL {total_ips} proxies ...")

    async def _run_diag():
        start = time.time()
        l1_results = await check_level1_batch(
            all_ips, timeout_s=12, concurrency=80, verbose=True,
            store=store,
        )
        l1_elapsed = time.time() - start

        l1_passed = [r for r in l1_results if r.get("is_valid")]
        l1_failed = [r for r in l1_results if not r.get("is_valid")]

        report["level1"] = {
            "total": len(l1_results),
            "passed": len(l1_passed),
            "failed": len(l1_failed),
            "pass_rate": f"{len(l1_passed)/max(1,len(l1_results))*100:.1f}%",
            "elapsed_s": round(l1_elapsed, 1),
        }

        # By protocol
        l1_by_proto = defaultdict(lambda: {"total": 0, "passed": 0})
        for r in l1_results:
            l1_by_proto[r["protocol"]]["total"] += 1
            if r.get("is_valid"):
                l1_by_proto[r["protocol"]]["passed"] += 1
        report["level1_by_protocol"] = {
            p: {"total": s["total"], "passed": s["passed"],
                "pass_rate": f"{s['passed']/max(1,s['total'])*100:.1f}%"}
            for p, s in l1_by_proto.items()
        }

        # By source
        l1_by_source = defaultdict(lambda: {"total": 0, "passed": 0})
        for r in l1_results:
            l1_by_source[r.get("source", "unknown")]["total"] += 1
            if r.get("is_valid"):
                l1_by_source[r.get("source", "unknown")]["passed"] += 1
        report["level1_by_source"] = {
            s: {"total": d["total"], "passed": d["passed"],
                "pass_rate": f"{d['passed']/max(1,d['total'])*100:.1f}%"}
            for s, d in l1_by_source.items()
        }

        # Errors
        error_counter = Counter()
        for r in l1_failed:
            err = r.get("last_error", "unknown").lower()
            if "timeout" in err:
                error_counter["timeout"] += 1
            elif "connect" in err or "connection" in err:
                error_counter["connection_error"] += 1
            elif "refused" in err:
                error_counter["connection_refused"] += 1
            elif "reset" in err:
                error_counter["connection_reset"] += 1
            elif "ssl" in err or "tls" in err:
                error_counter["ssl_error"] += 1
            else:
                error_counter["other"] += 1
        report["level1_errors"] = dict(error_counter.most_common())

        # Latency
        latencies = sorted(r["latency_ms"] for r in l1_passed if r["latency_ms"] > 0)
        if latencies:
            report["level1_latency"] = {
                "min_ms": latencies[0],
                "max_ms": latencies[-1],
                "median_ms": latencies[len(latencies)//2],
                "avg_ms": round(sum(latencies)/len(latencies)),
            }

        # Level-1 结果已由 check_level1_batch 实时写入数据库

        # Phase 3: Level-2
        l2_candidates = sorted(l1_passed, key=lambda r: r.get("latency_ms", 99999))[:200]
        if l2_candidates:
            logger.note("=" * 60)
            logger.note(f"> Phase 3: Level-2 check {len(l2_candidates)} proxies ...")
            start = time.time()
            l2_results = await check_level2_batch(
                l2_candidates, timeout_s=20, concurrency=10, verbose=True
            )
            l2_elapsed = time.time() - start
            l2_passed = [r for r in l2_results if r.get("is_valid")]

            report["level2"] = {
                "total": len(l2_results),
                "passed": len(l2_passed),
                "failed": len(l2_results) - len(l2_passed),
                "pass_rate": f"{len(l2_passed)/max(1,len(l2_results))*100:.1f}%",
                "elapsed_s": round(l2_elapsed, 1),
            }

            l2_by_proto = defaultdict(lambda: {"total": 0, "passed": 0})
            for r in l2_results:
                l2_by_proto[r["protocol"]]["total"] += 1
                if r.get("is_valid"):
                    l2_by_proto[r["protocol"]]["passed"] += 1
            report["level2_by_protocol"] = {
                p: {"total": s["total"], "passed": s["passed"],
                    "pass_rate": f"{s['passed']/max(1,s['total'])*100:.1f}%"}
                for p, s in l2_by_proto.items()
            }

            l2_err = Counter()
            for r in l2_results:
                if not r.get("is_valid"):
                    err = r.get("last_error", "").lower()
                    if "captcha" in err:
                        l2_err["CAPTCHA"] += 1
                    elif "timeout" in err:
                        l2_err["timeout"] += 1
                    elif "no search" in err:
                        l2_err["no_results"] += 1
                    else:
                        l2_err["other"] += 1
            report["level2_errors"] = dict(l2_err.most_common())

            store.upsert_check_results(l2_results)
        else:
            report["level2"] = {"total": 0, "passed": 0, "failed": 0, "pass_rate": "N/A"}

        return report

    report = asyncio.run(_run_diag())

    # Generate report markdown
    _generate_report_md(report)
    logger.okay(f"  ✓ Report written to docs/google-api/REPORT.md")


def _generate_report_md(report: dict):
    """生成 Markdown 格式的诊断报告。"""
    from pathlib import Path
    report_path = Path(__file__).resolve().parents[3] / "docs" / "google-api" / "REPORT.md"

    ts = report.get("timestamp", "")
    lines = [
        "# ggsc — 代理池测试报告",
        "",
        f"> 报告生成时间: {ts}",
        "",
        "---",
        "",
        "## 1. 采集总览",
        "",
    ]

    c = report.get("collect", {})
    lines += [
        f"- 本次采集: **{c.get('total_fetched', 0)}** 个代理",
        f"- 新增: **{c.get('inserted', 0)}**",
        f"- 更新: **{c.get('updated', 0)}**",
        f"- 数据库总量: **{c.get('total', 0)}**",
        "",
    ]

    proto = report.get("protocol_counts", {})
    if proto:
        total = max(1, sum(proto.values()))
        lines += ["### 1.1 协议分布", "", "| 协议 | 数量 | 占比 |", "|------|------|------|"]
        for p, cnt in sorted(proto.items(), key=lambda x: -x[1]):
            lines.append(f"| {p} | {cnt} | {cnt/total*100:.1f}% |")
        lines.append("")

    ss = report.get("source_stats", {})
    if ss:
        lines += ["### 1.2 来源分布", "", "| 来源 | 总数 | 协议构成 |", "|------|------|---------|"]
        for src, s in sorted(ss.items(), key=lambda x: -x[1]["count"]):
            protos = ", ".join(f"{k}:{v}" for k, v in sorted(s["protocols"].items()))
            lines.append(f"| {src} | {s['count']} | {protos} |")
        lines.append("")

    # Level-1
    l1 = report.get("level1", {})
    lines += [
        "## 2. Level-1 快速检测（aiohttp）", "",
        f"- 检测总数: **{l1.get('total', 0)}**",
        f"- 通过: **{l1.get('passed', 0)}**",
        f"- 失败: **{l1.get('failed', 0)}**",
        f"- 通过率: **{l1.get('pass_rate', 'N/A')}**",
        f"- 耗时: **{l1.get('elapsed_s', 0)}** 秒", "",
    ]

    l1p = report.get("level1_by_protocol", {})
    if l1p:
        lines += ["### 2.1 按协议统计", "", "| 协议 | 检测数 | 通过数 | 通过率 |", "|------|--------|--------|--------|"]
        for p, s in sorted(l1p.items()):
            lines.append(f"| {p} | {s['total']} | {s['passed']} | {s['pass_rate']} |")
        lines.append("")

    l1s = report.get("level1_by_source", {})
    if l1s:
        lines += ["### 2.2 按来源统计", "", "| 来源 | 检测数 | 通过数 | 通过率 |", "|------|--------|--------|--------|"]
        for src, s in sorted(l1s.items(), key=lambda x: -float(x[1]["pass_rate"].rstrip("%"))):
            lines.append(f"| {src} | {s['total']} | {s['passed']} | {s['pass_rate']} |")
        lines.append("")

    l1e = report.get("level1_errors", {})
    if l1e:
        te = max(1, sum(l1e.values()))
        lines += ["### 2.3 失败原因分析", "", "| 原因 | 数量 | 占比 |", "|------|------|------|"]
        for err, cnt in sorted(l1e.items(), key=lambda x: -x[1]):
            lines.append(f"| {err} | {cnt} | {cnt/te*100:.1f}% |")
        lines.append("")

    l1lat = report.get("level1_latency", {})
    if l1lat:
        lines += ["### 2.4 延迟分布", "", "| 指标 | 延迟 (ms) |", "|------|-----------|"]
        for k, v in l1lat.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    # Level-2
    l2 = report.get("level2", {})
    lines += [
        "## 3. Level-2 搜索检测（Playwright）", "",
        f"- 检测总数: **{l2.get('total', 0)}**",
        f"- 通过: **{l2.get('passed', 0)}**",
        f"- 失败: **{l2.get('failed', 0)}**",
        f"- 通过率: **{l2.get('pass_rate', 'N/A')}**",
    ]
    if l2.get("elapsed_s"):
        lines.append(f"- 耗时: **{l2['elapsed_s']}** 秒")
    lines.append("")

    l2p = report.get("level2_by_protocol", {})
    if l2p:
        lines += ["### 3.1 按协议统计", "", "| 协议 | 检测数 | 通过数 | 通过率 |", "|------|--------|--------|--------|"]
        for p, s in sorted(l2p.items()):
            lines.append(f"| {p} | {s['total']} | {s['passed']} | {s['pass_rate']} |")
        lines.append("")

    l2e = report.get("level2_errors", {})
    if l2e:
        te = max(1, sum(l2e.values()))
        lines += ["### 3.2 失败原因分析", "", "| 原因 | 数量 | 占比 |", "|------|------|------|"]
        for err, cnt in sorted(l2e.items(), key=lambda x: -x[1]):
            lines.append(f"| {err} | {cnt} | {cnt/te*100:.1f}% |")
        lines.append("")

    # Conclusions
    lines += [
        "## 4. 诊断结论", "",
        "### 4.1 HTTP 代理可用性分析", "",
    ]

    http_rate = float(l1p.get("http", {}).get("pass_rate", "0%").rstrip("%")) if l1p.get("http") else 0
    socks5_rate = float(l1p.get("socks5", {}).get("pass_rate", "0%").rstrip("%")) if l1p.get("socks5") else 0

    lines += [
        "**核心发现：**", "",
        f"- HTTP 代理 Level-1 通过率: {http_rate:.1f}%",
        f"- SOCKS5 代理 Level-1 通过率: {socks5_rate:.1f}%", "",
        "**原因分析：**", "",
        "1. 免费 HTTP 代理存活时间短（几分钟到几小时），采集到检测的延迟导致大量失效",
        "2. 很多免费 HTTP 代理是透明代理，会暴露真实 IP，被 Google 拒绝",
        "3. 数据中心 IP 段已被 Google 大量封禁",
        "4. SOCKS5 代理工作在更底层的网络协议，通过率通常高于 HTTP 代理", "",
        "**优化建议：**", "",
        "1. 优先使用 SOCKS5 代理",
        "2. 增加 Level-1 检测端点（已实现多端点回退）",
        "3. 提高采集和检测频率，缩短代理过期窗口",
        "4. 按来源选择通过率高的代理池", "",
        "---", "",
        f"*报告生成时间: {ts}*", "",
    ]

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════


def main():
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        prog="ggsc",
        description="ggsc (GooGle-SearCh) — 服务管理 + 代理池操作",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # start
    sp_start = subparsers.add_parser("start", help="启动搜索服务（后台）")
    sp_start.add_argument("--host", default=DEFAULT_HOST, help="绑定地址")
    sp_start.add_argument("--port", type=int, default=DEFAULT_PORT, help="绑定端口")
    sp_start.add_argument("--no-headless", action="store_true", help="显示浏览器窗口")
    sp_start.set_defaults(func=cmd_start)

    # stop
    sp_stop = subparsers.add_parser("stop", help="停止服务")
    sp_stop.set_defaults(func=cmd_stop)

    # restart
    sp_restart = subparsers.add_parser("restart", help="重启服务")
    sp_restart.add_argument("--host", default=DEFAULT_HOST, help="绑定地址")
    sp_restart.add_argument("--port", type=int, default=DEFAULT_PORT, help="绑定端口")
    sp_restart.add_argument("--no-headless", action="store_true", help="显示浏览器窗口")
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
    sp_check = subparsers.add_parser("check", help="检测代理可用性")
    sp_check.add_argument("--limit", type=int, default=200, help="最大检测数量")
    sp_check.add_argument(
        "--mode", choices=["unchecked", "stale", "all"], default="unchecked",
        help="检测模式",
    )
    sp_check.add_argument(
        "--level", choices=["1", "2", "all"], default="all",
        help="检测级别: 1=快速检测, 2=Google搜索, all=全部",
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

    # parse-test
    sp_parse = subparsers.add_parser("parse-test", help="用有效代理测试搜索结果解析")
    sp_parse.add_argument("--query", default="python programming", help="搜索查询词")
    sp_parse.add_argument("--limit", type=int, default=5, help="测试代理数量")
    sp_parse.set_defaults(func=cmd_parse_test)

    # diag
    sp_diag = subparsers.add_parser("diag", help="全面诊断：采集 + 全量检测 + 生成报告")
    sp_diag.set_defaults(func=cmd_diag)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
