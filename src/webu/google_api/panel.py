from __future__ import annotations

from collections.abc import Callable

from a2wsgi import WSGIMiddleware
from dash import Input, Output, dcc, html

from webu.fastapis.dashboard_ui import (
    THEME,
    create_dash_app,
    format_ms,
    format_rate,
    metric_card,
    meta_row,
    page_shell,
    request_table,
    section,
    status_bar_strip_card,
)
from webu.runtime_settings import (
    DEFAULT_GOOGLE_API_PANEL_PATH,
    DEFAULT_GOOGLE_API_PANEL_REFRESH_MS,
)


SnapshotProvider = Callable[[], dict]


def _history_labels(history: list[dict]) -> list[str]:
    labels = [str(item.get("label", "")) for item in history if item]
    return labels or ["00:00:00"]


def _history_values(history: list[dict], key: str) -> list[float]:
    values = [float(item.get(key, 0.0)) for item in history if item]
    return values or [0.0]


def _success_tone(rate: float) -> str:
    if rate >= 95:
        return THEME["accent"]
    if rate >= 75:
        return THEME["warn"]
    return THEME["danger"]


def _request_trend_bars(history: list[dict]) -> list[dict]:
    accepted_values = _history_values(history, "accepted_requests")
    max_requests = max(accepted_values) if accepted_values else 0.0
    bars: list[dict] = []
    for item in history[-24:]:
        accepted = float(item.get("accepted_requests", 0.0))
        success = float(item.get("successful_requests", 0.0))
        rate = float(item.get("success_rate", 0.0))
        bars.append(
            {
                "label": str(item.get("label", "")),
                "height": accepted / max_requests if max_requests > 0 else 0.2,
                "color": _success_tone(rate),
                "title": f"{item.get('label', '')}: {int(accepted)} req, {int(success)} ok, {rate:.1f}%",
            }
        )
    return bars


def _latency_trend_bars(history: list[dict]) -> list[dict]:
    latency_values = [
        max(
            float(item.get("avg_latency_ms", 0.0)),
            float(item.get("last_latency_ms", 0.0)),
        )
        for item in history[-24:]
    ]
    max_latency = max(latency_values) if latency_values else 0.0
    bars: list[dict] = []
    for item in history[-24:]:
        latency = max(
            float(item.get("avg_latency_ms", 0.0)),
            float(item.get("last_latency_ms", 0.0)),
        )
        rate = float(item.get("success_rate", 0.0))
        bars.append(
            {
                "label": str(item.get("label", "")),
                "height": latency / max_latency if max_latency > 0 else 0.2,
                "color": _success_tone(rate),
                "title": f"{item.get('label', '')}: avg {float(item.get('avg_latency_ms', 0.0)):.1f} ms, last {float(item.get('last_latency_ms', 0.0)):.1f} ms",
            }
        )
    return bars


def _build_body(snapshot: dict):
    requests = snapshot.get("requests", {})
    service = snapshot.get("service", {})
    node = snapshot.get("node", {})
    history = list(requests.get("history", []))
    request_log = list(requests.get("request_log", []))

    accepted = int(requests.get("accepted_requests", 0))
    successful = int(requests.get("successful_requests", 0))
    failed = int(requests.get("failed_requests", 0))
    success_rate = float(requests.get("success_rate", 0.0))
    avg_latency = float(requests.get("avg_latency_ms", 0.0))
    status_label = service.get("status_label", "starting")
    badge_tone = "accent" if status_label == "healthy" else "warn"

    subtitle_parts = [
        f"Updated {snapshot.get('updated_at_human', '')}",
        f"Runtime {snapshot.get('runtime_env', 'unknown')}",
        f"Node {node.get('value', 'unknown')}",
    ]
    metadata = meta_row(
        [
            f"Uptime {snapshot.get('uptime_human', '0s')}",
            f"Started {snapshot.get('started_at_human', '')}",
        ]
    )

    cards = [
        metric_card(
            "Uptime",
            snapshot.get("uptime_human", "0s"),
            snapshot.get("started_at_human", ""),
            "accent",
        ),
        metric_card(
            "Requests", str(accepted), f"{successful} success / {failed} failed", "info"
        ),
        metric_card(
            "Success rate",
            format_rate(success_rate),
            f"of {accepted} total requests",
            "accent" if success_rate >= 90 else "warn",
        ),
        metric_card(
            "Avg latency",
            format_ms(avg_latency),
            f"min {format_ms(float(requests.get('min_latency_ms', 0.0)))} · max {format_ms(float(requests.get('max_latency_ms', 0.0)))}",
            "warn",
        ),
        metric_card(
            node.get("label", "Node"),
            node.get("value", "unknown"),
            service.get("status_note", ""),
            "info",
        ),
    ]

    charts = [
        status_bar_strip_card(
            title="Request trend",
            bars=_request_trend_bars(history),
            summary=f"{accepted} total requests",
            footer_left=f"Peak {int(max(_history_values(history, 'accepted_requests')) if history else 0)} req",
            footer_right=f"Success {format_rate(success_rate)}",
        ),
        status_bar_strip_card(
            title="Latency trend",
            bars=_latency_trend_bars(history),
            summary=f"avg {format_ms(avg_latency)} / last {format_ms(float(requests.get('last_latency_ms', 0.0)))}",
            footer_left=f"Min {format_ms(float(requests.get('min_latency_ms', 0.0)))}",
            footer_right=f"Max {format_ms(float(requests.get('max_latency_ms', 0.0)))}",
        ),
    ]

    body = [section("Overview", cards, kind="metric")]
    if metadata is not None:
        body.append(section("Runtime", [metadata], kind="chart"))
    body.extend(
        [
            section("Trends", charts, kind="chart"),
            section("Request history", [request_table(request_log)], kind="chart"),
        ]
    )

    return page_shell(
        title="GOOGLE INSTANCE",
        subtitle=" · ".join(subtitle_parts),
        badge=status_label.upper(),
        badge_tone=badge_tone,
        body=body,
    )


def mount_google_api_panel(app, snapshot_provider: SnapshotProvider):
    dash_app = create_dash_app(
        name=__name__,
        title="Google Instance Panel",
        panel_path=DEFAULT_GOOGLE_API_PANEL_PATH,
    )
    dash_app.layout = html.Div(
        [
            dcc.Interval(
                id="panel-refresh",
                interval=DEFAULT_GOOGLE_API_PANEL_REFRESH_MS,
                n_intervals=0,
            ),
            html.Div(id="panel-root"),
        ]
    )

    @dash_app.callback(
        Output("panel-root", "children"), Input("panel-refresh", "n_intervals")
    )
    def refresh_panel(_n_intervals: int):
        return _build_body(snapshot_provider())

    app.mount(DEFAULT_GOOGLE_API_PANEL_PATH, WSGIMiddleware(dash_app.server))
