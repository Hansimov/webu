#!/usr/bin/env python3
"""全面代理诊断脚本 — 采集、测试、分析并生成报告。

功能：
  1. 从所有代理源采集 IP
  2. 对数据库中所有 IP 进行 Level-1 快速检测
  3. 对 Level-1 通过的 IP 进行 Level-2 搜索检测
  4. 按协议、来源分类统计通过率
  5. 分析失败原因分布
  6. 生成 REPORT.md 报告

运行: python tests/google_api/run_full_diagnosis.py
"""

import asyncio
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tclogger import logger, logstr

from webu.google_api.constants import PROXY_SOURCES
from webu.proxy_api.mongo import MongoProxyStore
from webu.proxy_api.collector import ProxyCollector
from webu.proxy_api.checker import (
    check_level1_batch,
    _build_proxy_url,
    LEVEL1_ENDPOINTS,
)
from webu.google_api.checker import check_level2_batch


REPORT_PATH = Path(__file__).resolve().parents[2] / "docs" / "google-api" / "REPORT.md"


async def run_full_diagnosis():
    """运行完整诊断流程。"""
    store = MongoProxyStore(verbose=True)
    collector = ProxyCollector(store=store, verbose=True)

    report = {}
    report["timestamp"] = datetime.now(timezone.utc).isoformat()

    # ══════════════════════════════════════════════════════════
    # 阶段 1: 采集
    # ══════════════════════════════════════════════════════════
    logger.note("=" * 60)
    logger.note("> Phase 1: Collecting proxies from all sources ...")
    logger.note("=" * 60)

    collect_result = collector.collect_all()
    report["collect"] = collect_result
    logger.okay(f"  ✓ Collected: {collect_result}")

    # 统计各源采集数量
    source_stats = defaultdict(lambda: {"count": 0, "protocols": Counter()})
    all_ips = store.get_all_ips(limit=0)
    for ip in all_ips:
        src = ip.get("source", "unknown")
        source_stats[src]["count"] += 1
        source_stats[src]["protocols"][ip["protocol"]] += 1

    report["source_stats"] = {
        src: {"count": s["count"], "protocols": dict(s["protocols"])}
        for src, s in source_stats.items()
    }

    total_ips = len(all_ips)
    logger.note(f"> Total IPs in database: {logstr.mesg(total_ips)}")
    for src, s in sorted(source_stats.items(), key=lambda x: -x[1]["count"]):
        logger.mesg(f"  {src}: {s['count']} ({dict(s['protocols'])})")

    # 按协议统计
    proto_counts = Counter(ip["protocol"] for ip in all_ips)
    report["protocol_counts"] = dict(proto_counts)
    logger.note(f"> Protocol distribution:")
    for proto, cnt in proto_counts.most_common():
        logger.mesg(f"  {proto}: {cnt} ({cnt/total_ips*100:.1f}%)")

    # ══════════════════════════════════════════════════════════
    # 阶段 2: Level-1 快速检测（全量）
    # ══════════════════════════════════════════════════════════
    logger.note("=" * 60)
    logger.note(f"> Phase 2: Level-1 check ALL {total_ips} proxies ...")
    logger.note("=" * 60)

    start_time = time.time()
    level1_results = await check_level1_batch(
        all_ips,
        timeout_s=12,
        concurrency=80,
        verbose=True,
    )
    level1_elapsed = time.time() - start_time

    # Level-1 结果分析
    l1_passed = [r for r in level1_results if r.get("is_valid")]
    l1_failed = [r for r in level1_results if not r.get("is_valid")]

    report["level1"] = {
        "total": len(level1_results),
        "passed": len(l1_passed),
        "failed": len(l1_failed),
        "pass_rate": f"{len(l1_passed)/len(level1_results)*100:.1f}%" if level1_results else "N/A",
        "elapsed_s": round(level1_elapsed, 1),
    }

    logger.okay(
        f"  ✓ Level-1: {len(l1_passed)}/{len(level1_results)} passed "
        f"({len(l1_passed)/len(level1_results)*100:.1f}%) in {level1_elapsed:.1f}s"
    )

    # Level-1 按协议统计通过率
    l1_by_proto = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in level1_results:
        proto = r["protocol"]
        l1_by_proto[proto]["total"] += 1
        if r.get("is_valid"):
            l1_by_proto[proto]["passed"] += 1

    report["level1_by_protocol"] = {}
    logger.note("> Level-1 pass rate by protocol:")
    for proto, s in sorted(l1_by_proto.items()):
        rate = s["passed"] / s["total"] * 100 if s["total"] > 0 else 0
        report["level1_by_protocol"][proto] = {
            "total": s["total"],
            "passed": s["passed"],
            "pass_rate": f"{rate:.1f}%",
        }
        logger.mesg(f"  {proto}: {s['passed']}/{s['total']} ({rate:.1f}%)")

    # Level-1 按来源统计通过率
    l1_by_source = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in level1_results:
        src = r.get("source", "unknown")
        l1_by_source[src]["total"] += 1
        if r.get("is_valid"):
            l1_by_source[src]["passed"] += 1

    report["level1_by_source"] = {}
    logger.note("> Level-1 pass rate by source:")
    for src, s in sorted(l1_by_source.items(), key=lambda x: -(x[1]["passed"]/max(1,x[1]["total"]))):
        rate = s["passed"] / s["total"] * 100 if s["total"] > 0 else 0
        report["level1_by_source"][src] = {
            "total": s["total"],
            "passed": s["passed"],
            "pass_rate": f"{rate:.1f}%",
        }
        logger.mesg(f"  {src}: {s['passed']}/{s['total']} ({rate:.1f}%)")

    # Level-1 错误原因分析
    error_counter = Counter()
    for r in l1_failed:
        err = r.get("last_error", "unknown")
        # 归类错误
        if "timeout" in err.lower():
            error_counter["timeout"] += 1
        elif "connect" in err.lower() or "connection" in err.lower():
            error_counter["connection_error"] += 1
        elif "refused" in err.lower():
            error_counter["connection_refused"] += 1
        elif "reset" in err.lower():
            error_counter["connection_reset"] += 1
        elif "ssl" in err.lower() or "tls" in err.lower():
            error_counter["ssl_error"] += 1
        elif "proxy" in err.lower():
            error_counter["proxy_error"] += 1
        elif "status=" in err.lower():
            error_counter["wrong_status"] += 1
        elif "dns" in err.lower() or "resolve" in err.lower():
            error_counter["dns_error"] += 1
        else:
            error_counter["other"] += 1

    report["level1_errors"] = dict(error_counter.most_common())
    logger.note("> Level-1 failure reasons:")
    for err, cnt in error_counter.most_common():
        logger.mesg(f"  {err}: {cnt} ({cnt/len(l1_failed)*100:.1f}%)" if l1_failed else f"  {err}: {cnt}")

    # Level-1 延迟分布
    latencies = [r["latency_ms"] for r in l1_passed if r["latency_ms"] > 0]
    if latencies:
        latencies.sort()
        report["level1_latency"] = {
            "min_ms": latencies[0],
            "max_ms": latencies[-1],
            "median_ms": latencies[len(latencies)//2],
            "p90_ms": latencies[int(len(latencies)*0.9)],
            "p95_ms": latencies[int(len(latencies)*0.95)],
            "avg_ms": round(sum(latencies)/len(latencies)),
        }
        logger.note("> Level-1 latency (passed proxies):")
        for k, v in report["level1_latency"].items():
            logger.mesg(f"  {k}: {v}")

    # 存储 Level-1 结果到 MongoDB
    logger.note("> Saving Level-1 results to MongoDB ...")
    store.upsert_check_results(level1_results)

    # ══════════════════════════════════════════════════════════
    # 阶段 3: Level-2 搜索检测（对 Level-1 通过的 IP）
    # ══════════════════════════════════════════════════════════
    l2_candidates = l1_passed
    if len(l2_candidates) > 200:
        # 如果 Level-1 通过太多，按延迟排序取 top 200
        l2_candidates.sort(key=lambda r: r.get("latency_ms", 99999))
        l2_candidates = l2_candidates[:200]

    if l2_candidates:
        logger.note("=" * 60)
        logger.note(f"> Phase 3: Level-2 check {len(l2_candidates)} proxies ...")
        logger.note("=" * 60)

        start_time = time.time()
        level2_results = await check_level2_batch(
            l2_candidates,
            timeout_s=20,
            concurrency=10,
            verbose=True,
        )
        level2_elapsed = time.time() - start_time

        l2_passed = [r for r in level2_results if r.get("is_valid")]
        l2_failed = [r for r in level2_results if not r.get("is_valid")]

        report["level2"] = {
            "total": len(level2_results),
            "passed": len(l2_passed),
            "failed": len(l2_failed),
            "pass_rate": f"{len(l2_passed)/len(level2_results)*100:.1f}%" if level2_results else "N/A",
            "elapsed_s": round(level2_elapsed, 1),
        }

        # Level-2 按协议
        l2_by_proto = defaultdict(lambda: {"total": 0, "passed": 0})
        for r in level2_results:
            proto = r["protocol"]
            l2_by_proto[proto]["total"] += 1
            if r.get("is_valid"):
                l2_by_proto[proto]["passed"] += 1

        report["level2_by_protocol"] = {}
        logger.note("> Level-2 pass rate by protocol:")
        for proto, s in sorted(l2_by_proto.items()):
            rate = s["passed"] / s["total"] * 100 if s["total"] > 0 else 0
            report["level2_by_protocol"][proto] = {
                "total": s["total"],
                "passed": s["passed"],
                "pass_rate": f"{rate:.1f}%",
            }
            logger.mesg(f"  {proto}: {s['passed']}/{s['total']} ({rate:.1f}%)")

        # Level-2 错误原因
        l2_error_counter = Counter()
        for r in l2_failed:
            err = r.get("last_error", "unknown")
            if "captcha" in err.lower():
                l2_error_counter["CAPTCHA"] += 1
            elif "timeout" in err.lower():
                l2_error_counter["timeout"] += 1
            elif "no search results" in err.lower():
                l2_error_counter["no_results"] += 1
            elif "page too small" in err.lower():
                l2_error_counter["page_too_small"] += 1
            elif "net::" in err.lower() or "err_" in err.lower():
                l2_error_counter["network_error"] += 1
            else:
                l2_error_counter["other"] += 1

        report["level2_errors"] = dict(l2_error_counter.most_common())
        logger.note("> Level-2 failure reasons:")
        for err, cnt in l2_error_counter.most_common():
            pct = cnt / len(l2_failed) * 100 if l2_failed else 0
            logger.mesg(f"  {err}: {cnt} ({pct:.1f}%)")

        # Level-2 延迟
        l2_latencies = [r["latency_ms"] for r in l2_passed if r["latency_ms"] > 0]
        if l2_latencies:
            l2_latencies.sort()
            report["level2_latency"] = {
                "min_ms": l2_latencies[0],
                "max_ms": l2_latencies[-1],
                "median_ms": l2_latencies[len(l2_latencies)//2],
                "avg_ms": round(sum(l2_latencies)/len(l2_latencies)),
            }

        # 存储 Level-2 结果
        store.upsert_check_results(level2_results)

        # 列出可用代理
        if l2_passed:
            logger.note("> Valid Google proxies (Level-2 passed):")
            for r in sorted(l2_passed, key=lambda x: x.get("latency_ms", 99999)):
                logger.okay(
                    f"  ✓ {r['proxy_url']} "
                    f"({r['protocol']}, {r['latency_ms']}ms, src={r.get('source','')})"
                )
    else:
        report["level2"] = {"total": 0, "passed": 0, "failed": 0, "pass_rate": "N/A"}
        logger.warn("> No Level-1 passed proxies to test in Level-2")

    # ══════════════════════════════════════════════════════════
    # 阶段 4: 生成报告
    # ══════════════════════════════════════════════════════════
    logger.note("=" * 60)
    logger.note("> Phase 4: Generating report ...")
    logger.note("=" * 60)

    generate_report(report)
    logger.okay(f"  ✓ Report written to: {REPORT_PATH}")

    # 最终统计
    final_stats = store.get_stats()
    logger.note("> Final proxy pool stats:")
    for k, v in final_stats.items():
        logger.mesg(f"  {k}: {v}")

    return report


def generate_report(report: dict):
    """生成 Markdown 格式报告。"""
    ts = report.get("timestamp", datetime.now(timezone.utc).isoformat())
    lines = []
    lines.append("# ggsc — 代理池测试报告")
    lines.append("")
    lines.append(f"> 报告生成时间: {ts}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 1. 采集总览 ──
    lines.append("## 1. 采集总览")
    lines.append("")
    collect = report.get("collect", {})
    lines.append(f"- 本次采集: **{collect.get('total_fetched', 0)}** 个代理")
    lines.append(f"- 新增: **{collect.get('inserted', 0)}**")
    lines.append(f"- 更新: **{collect.get('updated', 0)}**")
    lines.append(f"- 数据库总量: **{collect.get('total', 0)}**")
    lines.append("")

    # 协议分布
    proto_counts = report.get("protocol_counts", {})
    if proto_counts:
        total = sum(proto_counts.values())
        lines.append("### 1.1 协议分布")
        lines.append("")
        lines.append("| 协议 | 数量 | 占比 |")
        lines.append("|------|------|------|")
        for proto, cnt in sorted(proto_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {proto} | {cnt} | {cnt/total*100:.1f}% |")
        lines.append("")

    # 来源分布
    source_stats = report.get("source_stats", {})
    if source_stats:
        lines.append("### 1.2 来源分布")
        lines.append("")
        lines.append("| 来源 | 总数 | 协议构成 |")
        lines.append("|------|------|---------|")
        for src, s in sorted(source_stats.items(), key=lambda x: -x[1]["count"]):
            protos = ", ".join(f"{p}:{c}" for p, c in sorted(s["protocols"].items()))
            lines.append(f"| {src} | {s['count']} | {protos} |")
        lines.append("")

    # ── 2. Level-1 检测 ──
    lines.append("## 2. Level-1 快速检测（aiohttp）")
    lines.append("")
    l1 = report.get("level1", {})
    lines.append(f"- 检测总数: **{l1.get('total', 0)}**")
    lines.append(f"- 通过: **{l1.get('passed', 0)}**")
    lines.append(f"- 失败: **{l1.get('failed', 0)}**")
    lines.append(f"- 通过率: **{l1.get('pass_rate', 'N/A')}**")
    lines.append(f"- 耗时: **{l1.get('elapsed_s', 0)}** 秒")
    lines.append("")

    # Level-1 按协议
    l1_proto = report.get("level1_by_protocol", {})
    if l1_proto:
        lines.append("### 2.1 按协议统计")
        lines.append("")
        lines.append("| 协议 | 检测数 | 通过数 | 通过率 |")
        lines.append("|------|--------|--------|--------|")
        for proto, s in sorted(l1_proto.items()):
            lines.append(f"| {proto} | {s['total']} | {s['passed']} | {s['pass_rate']} |")
        lines.append("")

    # Level-1 按来源
    l1_source = report.get("level1_by_source", {})
    if l1_source:
        lines.append("### 2.2 按来源统计")
        lines.append("")
        lines.append("| 来源 | 检测数 | 通过数 | 通过率 |")
        lines.append("|------|--------|--------|--------|")
        for src, s in sorted(l1_source.items(), key=lambda x: -float(x[1]["pass_rate"].rstrip("%")) if x[1]["pass_rate"] != "N/A" else 0):
            lines.append(f"| {src} | {s['total']} | {s['passed']} | {s['pass_rate']} |")
        lines.append("")

    # Level-1 错误原因
    l1_errs = report.get("level1_errors", {})
    if l1_errs:
        total_errs = sum(l1_errs.values())
        lines.append("### 2.3 失败原因分析")
        lines.append("")
        lines.append("| 原因 | 数量 | 占比 |")
        lines.append("|------|------|------|")
        for err, cnt in sorted(l1_errs.items(), key=lambda x: -x[1]):
            lines.append(f"| {err} | {cnt} | {cnt/total_errs*100:.1f}% |")
        lines.append("")

    # Level-1 延迟
    l1_lat = report.get("level1_latency", {})
    if l1_lat:
        lines.append("### 2.4 延迟分布（通过的代理）")
        lines.append("")
        lines.append("| 指标 | 延迟 (ms) |")
        lines.append("|------|-----------|")
        for k, v in l1_lat.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    # ── 3. Level-2 检测 ──
    lines.append("## 3. Level-2 搜索检测（Playwright）")
    lines.append("")
    l2 = report.get("level2", {})
    lines.append(f"- 检测总数: **{l2.get('total', 0)}**")
    lines.append(f"- 通过: **{l2.get('passed', 0)}**")
    lines.append(f"- 失败: **{l2.get('failed', 0)}**")
    lines.append(f"- 通过率: **{l2.get('pass_rate', 'N/A')}**")
    if l2.get("elapsed_s"):
        lines.append(f"- 耗时: **{l2['elapsed_s']}** 秒")
    lines.append("")

    # Level-2 按协议
    l2_proto = report.get("level2_by_protocol", {})
    if l2_proto:
        lines.append("### 3.1 按协议统计")
        lines.append("")
        lines.append("| 协议 | 检测数 | 通过数 | 通过率 |")
        lines.append("|------|--------|--------|--------|")
        for proto, s in sorted(l2_proto.items()):
            lines.append(f"| {proto} | {s['total']} | {s['passed']} | {s['pass_rate']} |")
        lines.append("")

    # Level-2 错误原因
    l2_errs = report.get("level2_errors", {})
    if l2_errs:
        total_errs = sum(l2_errs.values())
        lines.append("### 3.2 失败原因分析")
        lines.append("")
        lines.append("| 原因 | 数量 | 占比 |")
        lines.append("|------|------|------|")
        for err, cnt in sorted(l2_errs.items(), key=lambda x: -x[1]):
            lines.append(f"| {err} | {cnt} | {cnt/total_errs*100:.1f}% |")
        lines.append("")

    # Level-2 延迟
    l2_lat = report.get("level2_latency", {})
    if l2_lat:
        lines.append("### 3.3 延迟分布（通过的代理）")
        lines.append("")
        lines.append("| 指标 | 延迟 (ms) |")
        lines.append("|------|-----------|")
        for k, v in l2_lat.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    # ── 4. 诊断结论 ──
    lines.append("## 4. 诊断结论")
    lines.append("")

    l1_pass = l1.get("passed", 0)
    l1_total_val = l1.get("total", 1)
    l2_pass = l2.get("passed", 0)
    l2_total_val = l2.get("total", 1)

    lines.append("### 4.1 HTTP 代理可用性低的原因")
    lines.append("")

    http_stats = l1_proto.get("http", {})
    https_stats = l1_proto.get("https", {})
    socks5_stats = l1_proto.get("socks5", {})

    if http_stats or https_stats:
        http_rate = float(http_stats.get("pass_rate", "0%").rstrip("%")) if http_stats else 0
        https_rate = float(https_stats.get("pass_rate", "0%").rstrip("%")) if https_stats else 0
        socks5_rate = float(socks5_stats.get("pass_rate", "0%").rstrip("%")) if socks5_stats else 0

        lines.append("**分析：**")
        lines.append("")
        lines.append(f"- HTTP 代理 Level-1 通过率: {http_rate:.1f}%")
        lines.append(f"- HTTPS 代理 Level-1 通过率: {https_rate:.1f}%")
        lines.append(f"- SOCKS5 代理 Level-1 通过率: {socks5_rate:.1f}%")
        lines.append("")

        if http_rate < 15:
            lines.append("HTTP 代理可用性极低，主要原因：")
            lines.append("")
            lines.append("1. **代理质量差**：免费 HTTP 代理的平均存活时间很短（通常几分钟到几小时）")
            lines.append("2. **端口被封**：很多 HTTP 代理端口被目标网站（Google）屏蔽")
            lines.append("3. **透明代理**：很多 HTTP 代理是透明代理，会暴露真实 IP，被 Google 拒绝")
            lines.append("4. **过期代理**：代理列表更新有延迟，很多 IP 在获取时已经失效")
            lines.append("")

        lines.append("**建议：**")
        lines.append("")
        lines.append("1. 优先使用 SOCKS5 代理（通过率通常更高，且支持 UDP）")
        lines.append("2. 增加检测频率，及时淘汰失效代理")
        lines.append("3. 使用多端点检测（generate_204 + robots.txt + clients3_204）提高准确性")
        lines.append("4. 考虑购买少量高质量代理作为补充")
        lines.append("")

    # ── 5. 可用代理列表 ──
    lines.append("## 5. 当前可用代理")
    lines.append("")
    lines.append(f"- Level-1 通过: **{l1_pass}** 个")
    lines.append(f"- Level-2 通过（Google 搜索可用）: **{l2_pass}** 个")
    lines.append("")
    if l2_pass > 0:
        lines.append("Level-2 通过的代理可直接用于 Google 搜索服务。")
    elif l1_pass > 0:
        lines.append("虽然 Level-2 通过率低，但 Level-1 通过的代理可用于其他 HTTP 场景（非 Google 搜索）。")
    else:
        lines.append("⚠️ 当前无可用代理，建议：增加代理源、调整超时、检查网络环境。")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"*报告生成时间: {ts}*")
    lines.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(run_full_diagnosis())
