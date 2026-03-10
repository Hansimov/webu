from __future__ import annotations

import argparse
import asyncio
import json
import time

import requests

from tclogger import logger, logstr

from webu.cli_support import (
    LocalServiceSpec,
    is_process_running,
    read_pid,
    read_service_log,
    remove_pid,
    start_service,
    stop_service,
    tail_service_log,
    write_pid,
)
from webu.google_api.audit import audit_has_failures, format_audit_summary, run_audit
from webu.google_hub.benchmark import run_http_benchmark
from webu.google_hub.manager import resolve_google_hub_settings
from webu.runtime_settings import get_workspace_paths


_HUB_SETTINGS = resolve_google_hub_settings()
DATA_DIR = get_workspace_paths().data_dir / "google_hub"
PID_FILE = DATA_DIR / "server.pid"
LOG_FILE = DATA_DIR / "server.log"
DEFAULT_HOST = _HUB_SETTINGS.host
DEFAULT_PORT = _HUB_SETTINGS.port
SERVICE_SPEC = LocalServiceSpec(
    name="google_hub",
    uvicorn_target="webu.google_hub.server:app_instance",
    pid_file=PID_FILE,
    log_file=LOG_FILE,
)


def _normalize_exclude_nodes(raw_value: str | None) -> str:
    parts = [str(item).strip() for item in str(raw_value or "").split(",")]
    unique: list[str] = []
    seen: set[str] = set()
    for item in parts:
        if not item or item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return ",".join(unique)


def _hub_runtime_env(args) -> dict[str, str]:
    env: dict[str, str] = {}
    exclude_nodes = _normalize_exclude_nodes(getattr(args, "exclude_nodes", ""))
    if exclude_nodes:
        env["WEBU_HUB_EXCLUDE_NODES"] = exclude_nodes
    request_timeout = int(getattr(args, "request_timeout", 60) or 60)
    env["WEBU_HUB_REQUEST_TIMEOUT_SEC"] = str(max(1, request_timeout))
    return env


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_pid() -> int | None:
    return read_pid(PID_FILE)


def _write_pid(pid: int):
    _ensure_data_dir()
    write_pid(PID_FILE, pid)


def _remove_pid():
    remove_pid(PID_FILE)


def _is_process_running(pid: int) -> bool:
    return is_process_running(pid)


def _resolve_admin_token(explicit: str | None = None) -> str:
    return str(explicit or resolve_google_hub_settings().admin_token).strip()


def _local_hub_url(port: int | None = None) -> str:
    return f"http://127.0.0.1:{int(port or DEFAULT_PORT)}"


def _print_response(response: requests.Response):
    try:
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except ValueError:
        print(response.text)


def cmd_start(args):
    pid = _read_pid()
    if pid and _is_process_running(pid):
        logger.warn(f"  × Hub already running (PID: {pid})")
        return

    logger.note(f"> Starting Google Hub on {args.host}:{args.port} ...")
    pid = start_service(
        SERVICE_SPEC,
        host=args.host,
        port=args.port,
        extra_env=_hub_runtime_env(args),
    )
    logger.okay(f"  ✓ Hub started (PID: {pid})")
    logger.mesg(f"  Log: {logstr.file(LOG_FILE)}")


def cmd_stop(args):
    pid = _read_pid()
    if not pid:
        logger.warn("  × No PID file found — hub not running?")
        return
    if not _is_process_running(pid):
        logger.warn(f"  × Process {pid} not found — cleaning up PID file")
        _remove_pid()
        return

    logger.note(f"> Stopping hub (PID: {pid}) ...")
    stop_service(SERVICE_SPEC)
    logger.okay("  ✓ Hub stopped")


def cmd_restart(args):
    cmd_stop(args)
    time.sleep(1)
    cmd_start(args)


def cmd_status(args):
    pid = _read_pid()
    if not pid:
        logger.mesg("  Hub: NOT RUNNING (no PID file)")
        return
    if _is_process_running(pid):
        logger.okay(f"  Hub: RUNNING (PID: {pid})")
    else:
        logger.warn(f"  Hub: DEAD (PID: {pid} not found)")
        _remove_pid()
        logger.mesg("  Cleaned up stale PID file")


def cmd_logs(args):
    if not LOG_FILE.exists():
        logger.warn("  × No log file found")
        return
    if args.follow:
        tail_service_log(LOG_FILE)
    print(read_service_log(LOG_FILE, lines=args.lines), end="")


def cmd_serve(args):
    from .server import main as hub_server_main

    import sys

    for key, value in _hub_runtime_env(args).items():
        os.environ[key] = value
    sys.argv = [
        sys.argv[0],
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--exclude-nodes",
        _normalize_exclude_nodes(args.exclude_nodes),
        "--request-timeout",
        str(max(1, int(args.request_timeout))),
    ]
    hub_server_main()


def cmd_check(args):
    url = _local_hub_url(args.port)
    admin_token = _resolve_admin_token(args.admin_token)
    health = None
    backends = None
    health_error = ""
    backends_error = ""

    try:
        response = requests.get(f"{url}/health", timeout=args.timeout)
        response.raise_for_status()
        health = response.json()
    except Exception as exc:
        health_error = str(exc)

    try:
        response = requests.get(
            f"{url}/admin/backends",
            headers={"X-Admin-Token": admin_token} if admin_token else None,
            timeout=args.timeout,
        )
        response.raise_for_status()
        backends = response.json()
    except Exception as exc:
        backends_error = str(exc)

    print(
        json.dumps(
            {
                "service_url": url,
                "health": health,
                "health_error": health_error,
                "backends": backends,
                "backends_error": backends_error,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def cmd_backends(args):
    admin_token = _resolve_admin_token(args.admin_token)
    response = requests.get(
        f"{_local_hub_url(args.port)}/admin/backends",
        headers={"X-Admin-Token": admin_token} if admin_token else None,
        timeout=args.timeout,
    )
    response.raise_for_status()
    _print_response(response)


def cmd_search(args):
    response = requests.get(
        f"{_local_hub_url(args.port)}/search",
        params={"q": args.query, "num": args.num, "lang": args.lang},
        timeout=args.timeout,
    )
    response.raise_for_status()
    _print_response(response)


def cmd_benchmark(args):
    summary = asyncio.run(
        run_http_benchmark(
            base_url=_local_hub_url(args.port),
            query=args.query,
            total_requests=args.requests,
            concurrency=args.concurrency,
            num=args.num,
            lang=args.lang,
            timeout_sec=args.timeout,
        )
    )
    print(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False))


def cmd_audit(args):
    payload = run_audit(
        target=args.target,
        hub_url=args.hub_url,
        output_path=args.output,
    )
    output_format = str(args.format or "summary").strip().lower()
    if output_format == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif output_format == "both":
        print(format_audit_summary(payload))
        print()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(format_audit_summary(payload))
    return 1 if audit_has_failures(payload) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gghb",
        description="gghb (GooGle-HuB) — 管理本地 google_hub 服务并执行基准测试",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    start = subparsers.add_parser("start", help="后台启动 hub 服务")
    start.add_argument("--host", default=DEFAULT_HOST)
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.set_defaults(func=cmd_start)

    stop = subparsers.add_parser("stop", help="停止 hub 服务")
    stop.set_defaults(func=cmd_stop)

    restart = subparsers.add_parser("restart", help="重启 hub 服务")
    restart.add_argument("--host", default=DEFAULT_HOST)
    restart.add_argument("--port", type=int, default=DEFAULT_PORT)
    restart.set_defaults(func=cmd_restart)

    status = subparsers.add_parser("status", help="查看 hub 进程状态")
    status.set_defaults(func=cmd_status)

    logs = subparsers.add_parser("logs", help="查看 hub 日志")
    logs.add_argument("-n", "--lines", type=int, default=80)
    logs.add_argument("-f", "--follow", action="store_true")
    logs.set_defaults(func=cmd_logs)

    serve = subparsers.add_parser("serve", help="以前台方式启动 hub")
    serve.add_argument("--host", default=DEFAULT_HOST)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.set_defaults(func=cmd_serve)

    check = subparsers.add_parser("check", help="检查 hub 健康和后端状态")
    check.add_argument("--port", type=int, default=DEFAULT_PORT)
    check.add_argument("--admin-token", default="")
    check.add_argument("--timeout", type=int, default=15)
    check.set_defaults(func=cmd_check)

    backends = subparsers.add_parser("backends", help="列出 hub 后端状态")
    backends.add_argument("--port", type=int, default=DEFAULT_PORT)
    backends.add_argument("--admin-token", default="")
    backends.add_argument("--timeout", type=int, default=30)
    backends.set_defaults(func=cmd_backends)

    search = subparsers.add_parser("search", help="通过 hub 执行搜索")
    search.add_argument("query")
    search.add_argument("--port", type=int, default=DEFAULT_PORT)
    search.add_argument("--num", type=int, default=10)
    search.add_argument("--lang", default="en")
    search.add_argument("--timeout", type=int, default=60)
    search.set_defaults(func=cmd_search)

    audit = subparsers.add_parser(
        "audit",
        help="审计本地 hub 与远端 HF Spaces 的真实搜索可用性",
    )
    audit.add_argument(
        "--target",
        choices=["spaces", "hub", "all"],
        default="all",
        help="审计目标：只查 spaces、只查 hub，或一起查",
    )
    audit.add_argument(
        "--hub-url",
        default="",
        help="覆盖本地 hub 地址，默认读取 configs/google_hub.json",
    )
    audit.add_argument(
        "--output",
        default="",
        help="可选：将完整 JSON 报告写入指定路径",
    )
    audit.add_argument(
        "--format",
        choices=["summary", "json", "both"],
        default="summary",
        help="stdout 输出格式，默认显示人类可读摘要",
    )
    audit.set_defaults(func=cmd_audit)

    benchmark = subparsers.add_parser("benchmark", help="对本地 hub 执行并发 benchmark")
    benchmark.add_argument("--port", type=int, default=DEFAULT_PORT)
    benchmark.add_argument("--query", default="OpenAI news")
    benchmark.add_argument("--requests", type=int, default=12)
    benchmark.add_argument("--concurrency", type=int, default=4)
    benchmark.add_argument("--num", type=int, default=5)
    benchmark.add_argument("--lang", default="en")
    benchmark.add_argument("--timeout", type=int, default=60)
    benchmark.set_defaults(func=cmd_benchmark)

    for subparser in (start, restart, serve):
        subparser.add_argument("--exclude-nodes", default="local-google-api")
        subparser.add_argument("--request-timeout", type=int, default=60)

    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args) or 0


if __name__ == "__main__":
    main()
