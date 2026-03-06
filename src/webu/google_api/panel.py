from __future__ import annotations

from collections.abc import Callable

from a2wsgi import WSGIMiddleware
from dash import Input, Output, dcc, html

from webu.fastapis.dashboard_ui import (
    THEME,
    create_dash_app,
    format_ms,
    format_rate,
    graph_card,
    line_figure,
    metric_card,
    page_shell,
    request_table,
    section,
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
    history_labels = _history_labels(history)

    status_label = service.get("status_label", "starting")
    badge_tone = "accent" if status_label == "healthy" else "warn"

    subtitle_parts = [
        f"Updated {snapshot.get('updated_at_human', '')}",
        f"Runtime {snapshot.get('runtime_env', 'unknown')}",
        f"Node {node.get('value', 'unknown')}",
    ]

    cards = [
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
        graph_card(
            "Request trend",
            line_figure(
                labels=history_labels,
                series=[
                    {
                        "name": "Accepted",
                        "values": _history_values(history, "accepted_requests"),
                        "color": THEME["info"],
                    },
                    {
                        "name": "Success",
                        "values": _history_values(history, "successful_requests"),
                        "color": THEME["accent"],
                    },
                ],
                axis_title="Requests",
            ),
        ),
        graph_card(
            "Latency trend",
            line_figure(
                labels=history_labels,
                series=[
                    {
                        "name": "Avg",
                        "values": _history_values(history, "avg_latency_ms"),
                        "color": THEME["warn"],
                    },
                    {
                        "name": "Last",
                        "values": _history_values(history, "last_latency_ms"),
                        "color": THEME["info"],
                    },
                ],
                axis_title="ms",
            ),
        ),
    ]

    return page_shell(
        title="GOOGLE INSTANCE",
        subtitle=" · ".join(subtitle_parts),
        badge=status_label.upper(),
        badge_tone=badge_tone,
        body=[
            section("Overview", cards, kind="metric"),
            section("Trends", charts, kind="chart"),
            section("Request history", [request_table(request_log)], kind="chart"),
        ],
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
