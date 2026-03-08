from __future__ import annotations

from webu.fastapis.dashboard_ui import (
    THEME,
    format_ms,
    format_rate,
    instance_card,
    metric_card,
    metric_card_with_meta,
    status_bar_strip_card,
)


def _normalize_height(value: float, peak: float) -> float:
    value = max(0.0, float(value))
    peak = max(0.0, float(peak))
    if peak <= 0:
        return 0.22
    if value <= 0:
        return 0.12
    if peak <= value:
        return 1.0
    if peak <= 1e-6:
        return 0.62
    ratio = value / peak
    return 0.12 + ratio * 0.88


def _request_color(rate: float, accepted: float) -> str:
    if accepted <= 0:
        return THEME["border_light"]
    if rate >= 97:
        return THEME["accent"]
    if rate >= 85:
        return THEME["info"]
    if rate >= 70:
        return THEME["warn"]
    return THEME["danger"]


def _latency_color(latency_ms: float) -> str:
    if latency_ms >= 6000:
        return THEME["danger"]
    if latency_ms >= 3000:
        return THEME["warn"]
    if latency_ms > 0:
        return THEME["info"]
    return THEME["border_light"]


def build_time_metric_cards(snapshot: dict) -> list:
    return [
        metric_card_with_meta(
            "UPTIME",
            str(snapshot.get("uptime_human", "0s")),
            str(snapshot.get("current_time_human", "")),
            "accent",
            value_props={
                "data-uptime-value": "1",
                "data-uptime-started-ts": str(snapshot.get("started_ts", 0.0) or 0.0),
            },
            note_props={
                "data-uptime-note": "1",
                "data-uptime-started-ts": str(snapshot.get("started_ts", 0.0) or 0.0),
            },
        )
    ]


def build_request_metric_cards(requests: dict) -> list:
    accepted = int(requests.get("accepted_requests", 0))
    successful = int(requests.get("successful_requests", 0))
    failed = int(requests.get("failed_requests", 0))
    success_rate = float(requests.get("success_rate", 0.0))
    recent_latency_ms = float(
        requests.get("recent_latency_ms", requests.get("last_latency_ms", 0.0))
    )
    median_latency_ms = float(
        requests.get("median_latency_ms", requests.get("avg_latency_ms", 0.0))
    )
    return [
        metric_card(
            "Requests",
            str(accepted),
            f"{successful} success / {failed} failed",
            "info",
        ),
        metric_card(
            "SuccessRate",
            format_rate(success_rate),
            f"of {accepted} total requests",
            "accent" if success_rate >= 90 else "warn",
        ),
        metric_card(
            "Latency",
            f"{format_ms(recent_latency_ms)} / {format_ms(median_latency_ms)}",
            "recent / mid",
            _latency_tone(max(recent_latency_ms, median_latency_ms)),
        ),
    ]


def _latency_tone(latency_ms: float) -> str:
    if latency_ms >= 6000:
        return "danger"
    if latency_ms >= 3000:
        return "warn"
    return "info"


def build_node_metric_card(node: dict, note: str = ""):
    return metric_card(
        str(node.get("label", "Node")),
        str(node.get("value", "unknown")),
        note,
        "info",
    )


def build_instances_metric_card(snapshot: dict):
    health = snapshot.get("health", {})
    healthy_count = int(health.get("healthy_backends", 0))
    total_count = int(health.get("backend_count", 0))
    enabled_count = int(health.get("enabled_backends", total_count))
    tone = (
        "accent"
        if healthy_count == enabled_count and enabled_count > 0
        else ("warn" if healthy_count > 0 else "danger")
    )
    return metric_card(
        "Instances",
        f"{healthy_count}/{enabled_count if enabled_count > 0 else 0}",
        "",
        tone,
    )


def build_request_trend_cards(requests: dict, *, history_limit: int = 60) -> list:
    history = list(requests.get("history", []))[-history_limit:]
    request_bars = build_request_trend_bars(history)
    latency_bars = build_latency_trend_bars(history)
    request_values = [
        int(float(item.get("accepted_requests", 0.0))) for item in history
    ]
    latency_values = [
        max(
            float(item.get("recent_latency_ms", item.get("last_latency_ms", 0.0))),
            float(item.get("median_latency_ms", item.get("avg_latency_ms", 0.0))),
        )
        for item in history
    ]
    request_peak = max(request_values) if request_values else 0
    latency_peak = max(latency_values) if latency_values else 0.0
    return [
        status_bar_strip_card(
            title="Request trend",
            bars=request_bars,
            summary=(
                f"1m windows · {int(requests.get('accepted_requests', 0))} total requests"
                f" · drag to pan"
            ),
            footer_left=f"{len(history)} windows loaded",
            footer_right=f"Peak {request_peak} req/min",
        ),
        status_bar_strip_card(
            title="Latency trend",
            bars=latency_bars,
            summary=(
                f"recent {format_ms(float(requests.get('recent_latency_ms', requests.get('last_latency_ms', 0.0))))}"
                f" / mid {format_ms(float(requests.get('median_latency_ms', requests.get('avg_latency_ms', 0.0))))}"
                f" · drag to pan"
            ),
            footer_left=f"{len(history)} windows loaded",
            footer_right=f"Peak {format_ms(latency_peak)}",
        ),
    ]


def build_request_trend_bars(history: list[dict]) -> list[dict]:
    values = [float(item.get("accepted_requests", 0.0)) for item in history]
    peak = max(values) if values else 0.0
    bars: list[dict] = []
    for item in history:
        accepted = float(item.get("accepted_requests", 0.0))
        successful = float(item.get("successful_requests", 0.0))
        failed = float(item.get("failed_requests", 0.0))
        rate = float(item.get("success_rate", 0.0))
        bars.append(
            {
                "label": str(item.get("label", "")),
                "height": _normalize_height(accepted, peak),
                "color": _request_color(rate, accepted),
                "title": (
                    f"{item.get('label', '')}: {int(accepted)} req/min, "
                    f"{int(successful)} ok, {int(failed)} fail, {rate:.1f}%"
                ),
            }
        )
    return bars


def build_latency_trend_bars(history: list[dict]) -> list[dict]:
    values = [
        max(
            float(item.get("recent_latency_ms", item.get("last_latency_ms", 0.0))),
            float(item.get("median_latency_ms", item.get("avg_latency_ms", 0.0))),
        )
        for item in history
    ]
    peak = max(values) if values else 0.0
    bars: list[dict] = []
    for item in history:
        recent_latency_ms = float(
            item.get("recent_latency_ms", item.get("last_latency_ms", 0.0))
        )
        median_latency_ms = float(
            item.get("median_latency_ms", item.get("avg_latency_ms", 0.0))
        )
        display_latency_ms = max(recent_latency_ms, median_latency_ms)
        bars.append(
            {
                "label": str(item.get("label", "")),
                "height": _normalize_height(display_latency_ms, peak),
                "color": _latency_color(display_latency_ms),
                "title": (
                    f"{item.get('label', '')}: recent {format_ms(recent_latency_ms)}, "
                    f"mid {format_ms(median_latency_ms)}"
                ),
            }
        )
    return bars


def build_backend_instance_cards(instances: list[dict]) -> list:
    cards = []
    ordered_instances = sorted(
        instances,
        key=lambda item: (
            not bool(item.get("enabled", True)),
            not bool(item.get("healthy", False)),
            str(item.get("name", "")),
        ),
    )
    for item in ordered_instances:
        enabled = bool(item.get("enabled", True))
        healthy = bool(item.get("healthy")) and enabled
        if not enabled:
            status_label = "disabled"
            status_tone = "neutral"
        else:
            status_label = "healthy" if healthy else "unhealthy"
            status_tone = "accent" if healthy else "danger"
        cards.append(
            instance_card(
                name=item.get("name", "instance"),
                caption=item.get("space_name") or item.get("kind", ""),
                healthy=healthy,
                status_label=status_label,
                status_tone=status_tone,
                note=str(item.get("disabled_reason", "")).strip(),
                style={"opacity": 0.58} if not enabled else None,
                stats=[
                    ("Requests", str(item.get("request_count", 0))),
                    (
                        "Recent",
                        format_ms(
                            float(
                                item.get(
                                    "last_request_latency_ms",
                                    item.get("avg_request_latency_ms", 0.0),
                                )
                            )
                        ),
                    ),
                    ("Success", format_rate(float(item.get("success_rate", 0.0)))),
                ],
            )
        )
    return cards
