from __future__ import annotations

import argparse
import json

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from webu.schema import find_project_root, get_config_path

from .operations import client_canary_bundle, client_override_plan, edge_trace
from .schema import CF_TUNNEL_CONFIG


DEFAULT_OUTPUT_DIR = Path("debugs/cf-tunnel-snapshots")
THIRD_PARTY_GUIDANCE = {
    "itdog": {
        "note": "Free China-facing browser checks with ping, tcping, HTTP, and traceroute. Public pages often require JS or CAPTCHA, so treat them as manual validation rather than a stable machine interface.",
    },
    "boce": {
        "guest_quota_note": "Guests currently get 20 free checks per tool per day.",
        "note": "Free browser checks with HTTP, ping, traceroute, IPv6, and domestic operator filters. API access exists, but the free workflow is primarily manual.",
    },
    "chinaz": {
        "note": "Free browser checks with domestic ping, domestic and overseas HTTP speed pages, traceroute, and DNS pollution views. Suitable for quick spot checks, not long-running automation.",
    },
    "check_host": {
        "api_docs_url": "https://check-host.net/about/api",
        "note": "Free global web and API checks for HTTP, ping, TCP, DNS, and UDP. Good for automation, but it is not mainland-China focused.",
    },
    "ping_pe": {
        "note": "Free global ping/TCP/traceroute style page, but the site is JS-driven and best treated as browser-only.",
    },
    "cloudflare_speed_test": {
        "repo_url": "https://github.com/XIU2/CloudflareSpeedTest",
        "license": "GPL-3.0",
        "note": "Free/open-source CloudflareST utility that measures TCPing, HTTPing, and download speed to rank candidate Cloudflare IPs. Use it only for client-side hosts or lab probes, not for publishing fixed A/AAAA records on Tunnel hostnames.",
    },
    "openwrt_cdnspeedtest": {
        "repo_url": "https://github.com/immortalwrt-collections/openwrt-cdnspeedtest",
        "license": "GPL-3.0-only",
        "note": "OpenWrt package around CloudflareST for running the same candidate-IP measurements on routers or home probes.",
    },
    "rejected": [
        {
            "name": "17CE API",
            "reason": "Programmatic use requires an account and paid credits, so it is intentionally excluded from the default workflow.",
        },
        {
            "name": "cf2dns / hostmonit style feeds",
            "reason": "Depends on paid optimization-IP feeds and authoritative DNS rewrites, which do not fit Cloudflare Tunnel hostnames.",
        },
    ],
}


def _snapshot_label(override: str | None = None) -> str:
    text = str(override or "").strip()
    if text:
        return text
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _resolve_output_dir(output_dir: Path) -> Path:
    expanded = output_dir.expanduser()
    if expanded.is_absolute():
        return expanded
    return find_project_root() / expanded


def _external_tool_urls(hostname: str) -> dict[str, Any]:
    quoted_https = quote(f"https://{hostname}", safe="")
    quoted_host = quote(hostname, safe="")
    return {
        "itdog": {
            "http_url": f"https://www.itdog.cn/http/{quoted_https}",
            "ping_url": f"https://www.itdog.cn/ping/{hostname}",
            "tcping_url": f"https://www.itdog.cn/tcping/{hostname}:443",
            "traceroute_url": f"https://www.itdog.cn/traceroute/{hostname}",
            "note": THIRD_PARTY_GUIDANCE["itdog"]["note"],
        },
        "boce": {
            "http_url": f"https://www.boce.com/http/{quoted_host}",
            "ping_url": f"https://www.boce.com/ping/{quoted_host}",
            "traceroute_url": f"https://www.boce.com/traceroute/{quoted_host}",
            "tcping_entry_url": "https://www.boce.com/tcping",
            "note": THIRD_PARTY_GUIDANCE["boce"]["note"],
            "guest_quota_note": THIRD_PARTY_GUIDANCE["boce"]["guest_quota_note"],
        },
        "chinaz": {
            "ping_url": f"https://ping.chinaz.com/{quoted_host}",
            "domestic_http_url": f"https://tool.chinaz.com/speedtest/{quoted_host}",
            "overseas_http_url": f"https://tool.chinaz.com/speedworld/{quoted_host}",
            "traceroute_url": f"https://tool.chinaz.com/tracert/{quoted_host}",
            "dns_pollution_url": f"https://tool.chinaz.com/dnsce/{quoted_host}",
            "note": THIRD_PARTY_GUIDANCE["chinaz"]["note"],
        },
        "check_host": {
            "http_entry_url": "https://check-host.net/check-http",
            "ping_entry_url": "https://check-host.net/check-ping",
            "tcp_entry_url": "https://check-host.net/check-tcp",
            "api_docs_url": THIRD_PARTY_GUIDANCE["check_host"]["api_docs_url"],
            "target": hostname,
            "note": THIRD_PARTY_GUIDANCE["check_host"]["note"],
        },
        "ping_pe": {
            "entry_url": "https://ping.pe/",
            "target": hostname,
            "note": THIRD_PARTY_GUIDANCE["ping_pe"]["note"],
        },
        "opensource": {
            "cloudflare_speed_test_repo_url": THIRD_PARTY_GUIDANCE[
                "cloudflare_speed_test"
            ]["repo_url"],
            "openwrt_cdnspeedtest_repo_url": THIRD_PARTY_GUIDANCE[
                "openwrt_cdnspeedtest"
            ]["repo_url"],
            "note": "Open-source candidate-IP testing tools are useful on real client networks or routers, but still belong to client-side canary workflows for Tunnel hostnames.",
        },
    }


def _pick_primary_candidate(plan: dict[str, Any]) -> dict[str, Any] | None:
    candidates = plan.get("candidates", []) if isinstance(plan, dict) else []
    if not isinstance(candidates, list) or not candidates:
        return None
    recommended = str(plan.get("recommended_prefer_family", "any")).strip()
    if recommended in {"ipv4", "ipv6"}:
        for item in candidates:
            if isinstance(item, dict) and item.get("family") == recommended:
                return item
    return candidates[0] if isinstance(candidates[0], dict) else None


def _pick_backup_candidate(
    plan: dict[str, Any], primary_candidate: dict[str, Any] | None
) -> dict[str, Any] | None:
    if primary_candidate is None:
        return None
    candidates = plan.get("candidates", []) if isinstance(plan, dict) else []
    if not isinstance(candidates, list):
        return None
    recommended = str(plan.get("recommended_prefer_family", "any")).strip()
    primary_ip = str(primary_candidate.get("ip", "")).strip()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        if str(item.get("ip", "")).strip() == primary_ip:
            continue
        if recommended in {"ipv4", "ipv6"} and item.get("family") != recommended:
            continue
        return item
    for item in candidates:
        if not isinstance(item, dict):
            continue
        if str(item.get("ip", "")).strip() != primary_ip:
            return item
    return None


def _default_rollout_template(plan: dict[str, Any]) -> dict[str, Any]:
    hostname = str(plan.get("hostname", "")).strip()
    primary_candidate = _pick_primary_candidate(plan)
    backup_candidate = _pick_backup_candidate(plan, primary_candidate)
    candidate_ip = (
        str(primary_candidate.get("ip", "")).strip() if primary_candidate else ""
    )
    candidate_family = (
        str(primary_candidate.get("family", "")).strip() if primary_candidate else ""
    )
    cohorts: list[dict[str, Any]] = []
    for isp in ("ctcc", "cucc", "cmcc"):
        for platform in ("desktop", "mobile"):
            cohorts.append(
                {
                    "cohort_id": f"{hostname}-{isp}-{platform}",
                    "isp": isp,
                    "platform": platform,
                    "sample_size": "3-5",
                    "control_group_size": "1-2",
                    "candidate_ip": candidate_ip,
                    "candidate_family": candidate_family,
                    "delivery_method": (
                        "hosts-file" if platform == "desktop" else "local-dns-override"
                    ),
                }
            )
    return {
        "primary_candidate_ip": candidate_ip,
        "primary_candidate_family": candidate_family,
        "backup_candidate_ip": (
            str(backup_candidate.get("ip", "")).strip() if backup_candidate else ""
        ),
        "verify_urls": (
            [
                f"https://{hostname}",
                f"https://{hostname}/cdn-cgi/trace",
            ]
            if hostname
            else []
        ),
        "cohorts": cohorts,
        "notes": [
            "Run one candidate IP at a time per ISP and platform cohort.",
            "Keep one normal-DNS control cohort for regression comparison.",
            "Do not mix IPv4 and IPv6 candidates in the same first-round cohort.",
        ],
    }


def _operator_shortcuts(
    hostname: str,
    *,
    external_tools: dict[str, Any],
    recommended_prefer_family: str,
) -> dict[str, Any]:
    first_round_strategy = (
        f"{recommended_prefer_family}-first"
        if recommended_prefer_family in {"ipv4", "ipv6"}
        else "mixed-family-discovery"
    )
    return {
        "first_round_strategy": first_round_strategy,
        "manual_checks": [
            {
                "label": "ITDog HTTP",
                "url": external_tools["itdog"]["http_url"],
                "focus": "mainland-http",
                "mode": "manual",
            },
            {
                "label": "Boce HTTP",
                "url": external_tools["boce"]["http_url"],
                "focus": "mainland-http",
                "mode": "manual",
            },
            {
                "label": "Chinaz Domestic Speed",
                "url": external_tools["chinaz"]["domestic_http_url"],
                "focus": "mainland-http",
                "mode": "manual",
            },
            {
                "label": "Check-Host HTTP",
                "url": external_tools["check_host"]["http_entry_url"],
                "focus": hostname,
                "mode": "manual-or-api",
            },
        ],
        "automation_ready": [
            {
                "label": "Check-Host API",
                "url": external_tools["check_host"]["api_docs_url"],
            },
            {
                "label": "CloudflareST repo",
                "url": external_tools["opensource"]["cloudflare_speed_test_repo_url"],
            },
            {
                "label": "OpenWrt cdnspeedtest repo",
                "url": external_tools["opensource"]["openwrt_cdnspeedtest_repo_url"],
            },
        ],
        "excluded_workflows": THIRD_PARTY_GUIDANCE["rejected"],
    }


def _unique_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _render_markdown_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# cf_tunnel Canary Snapshot",
        "",
        f"- generated_at: {summary['generated_at']}",
        f"- snapshot_label: {summary['snapshot_label']}",
        f"- prefer_family: {summary['prefer_family']}",
        f"- max_candidates: {summary['max_candidates']}",
        "",
        "## Current Findings",
        "",
    ]

    for item in summary.get("snapshots", []):
        lines.extend(
            [
                f"### {item['hostname']}",
                "",
                f"- recommended_prefer_family: {item['recommended_prefer_family']}",
                f"- family_summary: {item['family_summary']}",
                f"- observed_colos: {', '.join(item['observed_colos']) or 'none'}",
                f"- reason_codes: {', '.join(item['reason_codes']) or 'none'}",
                f"- primary_candidate_ip: {item['rollout_template']['primary_candidate_ip'] or 'none'}",
                f"- backup_candidate_ip: {item['rollout_template']['backup_candidate_ip'] or 'none'}",
                f"- first_round_strategy: {item['operator_shortcuts']['first_round_strategy']}",
                "- first_round_cohorts:",
            ]
        )
        for cohort in item["rollout_template"].get("cohorts", []):
            lines.append(
                "  - "
                f"{cohort['isp']} {cohort['platform']} sample_size={cohort['sample_size']} "
                f"control={cohort['control_group_size']} candidate={cohort['candidate_ip'] or 'none'}"
            )
        lines.append("- operator_shortcuts:")
        for manual_check in item["operator_shortcuts"]["manual_checks"]:
            lines.append(
                f"  - {manual_check['label']}: {manual_check['url']} ({manual_check['mode']})"
            )
        for automation_ready in item["operator_shortcuts"]["automation_ready"]:
            lines.append(f"  - {automation_ready['label']}: {automation_ready['url']}")
        lines.extend(
            [
                "- external_tools:",
                f"  - ITDog HTTP: {item['external_tools']['itdog']['http_url']}",
                f"  - Boce HTTP: {item['external_tools']['boce']['http_url']}",
                f"  - Chinaz Domestic Speed: {item['external_tools']['chinaz']['domestic_http_url']}",
                f"  - Check-Host HTTP: {item['external_tools']['check_host']['http_entry_url']} target={item['external_tools']['check_host']['target']}",
                f"  - CloudflareST repo: {item['external_tools']['opensource']['cloudflare_speed_test_repo_url']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Third-party Measurement Notes",
            "",
            "- ITDog, Boce, and Chinaz are free browser-oriented tools with useful China-facing views, but public pages can be JS-heavy, ad-heavy, rate-limited, or human-verified.",
            "- Check-Host provides free HTTP, Ping, TCP, DNS, and UDP checks plus API docs, but its node distribution is global rather than mainland focused.",
            "- CloudflareST and its OpenWrt wrapper are free/open-source ways to test candidate Cloudflare IPs on real client networks; for Tunnel hostnames, keep the results client-side and do not publish fixed A/AAAA records.",
            "- Paid or mismatched workflows such as 17CE API and cf2dns-style DNS rewriting are intentionally excluded from this snapshot output.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _write_summary_files(snapshot_root: Path, summary: dict[str, Any]) -> None:
    _write_json(snapshot_root / "summary.json", summary)
    (snapshot_root / "SUMMARY.md").write_text(
        _render_markdown_summary(summary), encoding="utf-8"
    )


def capture_canary_snapshot(
    *,
    names: list[str],
    prefer_family: str,
    max_candidates: int,
    output_dir: Path,
    stamp: str | None = None,
) -> dict[str, Any]:
    requested_names = [str(item).strip() for item in names if str(item).strip()]
    if not requested_names:
        raise ValueError("at least one --name is required")

    snapshot_label = _snapshot_label(stamp)
    snapshot_root = _resolve_output_dir(output_dir) / snapshot_label
    snapshot_root.mkdir(parents=True, exist_ok=True)

    config_path = get_config_path(CF_TUNNEL_CONFIG).expanduser().resolve()
    snapshots: list[dict[str, Any]] = []
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "snapshot_label": snapshot_label,
        "prefer_family": prefer_family,
        "max_candidates": max_candidates,
        "config_path": str(config_path),
        "output_dir": str(snapshot_root.resolve()),
        "snapshots": snapshots,
        "third_party_measurement": THIRD_PARTY_GUIDANCE,
        "notes": [
            "Use the generated client-override-plan and client-canary-bundle files as the source of truth for current candidates.",
            "These snapshot directories are local measurement artifacts and should stay out of git history.",
            "Prefer free external tools such as ITDog, Boce, Chinaz, Check-Host, and CloudflareST on real client networks.",
            "Avoid paid or policy-mismatched workflows such as 17CE API or cf2dns-style authoritative DNS rewrites for Tunnel hostnames.",
            "Do not treat IPs found in docs, tests, or old snapshots as production defaults.",
        ],
    }

    for name in requested_names:
        item_root = snapshot_root / name
        item_root.mkdir(parents=True, exist_ok=True)

        edge_trace_payload = edge_trace(tunnel_name=name, hostname=None)
        override_plan_payload = client_override_plan(
            tunnel_name=name,
            hostname=None,
            prefer_family=prefer_family,
            max_candidates=max_candidates,
        )
        canary_bundle_payload = client_canary_bundle(
            tunnel_name=name,
            hostname=None,
            prefer_family=prefer_family,
            max_candidates=max_candidates,
        )

        _write_json(item_root / "edge-trace.json", edge_trace_payload)
        _write_json(item_root / "client-override-plan.json", override_plan_payload)
        _write_json(item_root / "client-canary-bundle.json", canary_bundle_payload)

        rollout_template = _default_rollout_template(override_plan_payload)
        hostname = str(override_plan_payload.get("hostname", name)).strip() or name
        external_tools = _external_tool_urls(hostname)
        recommended_prefer_family = str(
            override_plan_payload.get("recommended_prefer_family", "any")
        )
        snapshots.append(
            {
                "requested_name": name,
                "hostname": hostname,
                "recommended_prefer_family": recommended_prefer_family,
                "family_summary": override_plan_payload.get(
                    "family_assessment", {}
                ).get("summary", ""),
                "reason_codes": override_plan_payload.get("family_assessment", {}).get(
                    "reason_codes", []
                ),
                "observed_colos": _unique_strings(
                    [
                        str(candidate.get("colo", "")).strip()
                        for candidate in edge_trace_payload.get(
                            "unique_edge_results", []
                        )
                        if isinstance(candidate, dict)
                        and str(candidate.get("colo", "")).strip()
                    ]
                ),
                "top_candidates": [
                    {
                        "ip": candidate.get("ip", ""),
                        "family": candidate.get("family", ""),
                        "colo": candidate.get("colo", ""),
                    }
                    for candidate in override_plan_payload.get("candidates", [])[
                        :max_candidates
                    ]
                    if isinstance(candidate, dict)
                ],
                "files": {
                    "edge_trace": str(item_root / "edge-trace.json"),
                    "client_override_plan": str(
                        item_root / "client-override-plan.json"
                    ),
                    "client_canary_bundle": str(
                        item_root / "client-canary-bundle.json"
                    ),
                },
                "external_tools": external_tools,
                "operator_shortcuts": _operator_shortcuts(
                    hostname,
                    external_tools=external_tools,
                    recommended_prefer_family=recommended_prefer_family,
                ),
                "rollout_template": rollout_template,
            }
        )
        summary["generated_at"] = datetime.now(UTC).isoformat()
        _write_summary_files(snapshot_root, summary)

    summary["generated_at"] = datetime.now(UTC).isoformat()
    _write_summary_files(snapshot_root, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture a cf_tunnel canary snapshot and save current plans to disk"
    )
    parser.add_argument("--name", dest="names", action="append", required=True)
    parser.add_argument(
        "--prefer-family",
        default="any",
        choices=["any", "ipv4", "ipv6"],
    )
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where snapshot files will be written.",
    )
    parser.add_argument(
        "--stamp",
        default="",
        help="Optional fixed snapshot label for deterministic output paths.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = capture_canary_snapshot(
        names=list(args.names or []),
        prefer_family=str(args.prefer_family),
        max_candidates=max(1, int(args.max_candidates)),
        output_dir=Path(args.output_dir),
        stamp=str(args.stamp or "").strip() or None,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
