from __future__ import annotations

from collections.abc import Callable

from a2wsgi import WSGIMiddleware
from dash import Input, Output, dcc, html

from webu.fastapis.dashboard_ui import (
    create_dash_app,
    page_shell,
    request_table,
    section,
)
from webu.fastapis.panel_components import (
    build_node_metric_card,
    build_request_metric_cards,
    build_request_trend_cards,
    build_time_metric_cards,
)
from webu.runtime_settings import (
    DEFAULT_GOOGLE_API_PANEL_PATH,
    DEFAULT_GOOGLE_API_PANEL_REFRESH_MS,
)


SnapshotProvider = Callable[[], dict]


def _build_body(snapshot: dict):
    requests = snapshot.get("requests", {})
    service = snapshot.get("service", {})
    node = snapshot.get("node", {})
    request_log = list(requests.get("request_log", []))

    status_label = service.get("status_label", "starting")
    badge_tone = "accent" if status_label == "healthy" else "warn"

    subtitle = (
        f"Run at {snapshot.get('started_at_human', '')}"
        f" · {snapshot.get('timezone_human', 'UTC+08 Shanghai')}"
    )

    cards = [
        *build_time_metric_cards(snapshot),
        *build_request_metric_cards(requests),
        build_node_metric_card(node, service.get("status_note", "")),
    ]

    body = [section("Overview", cards, kind="metric")]
    body.extend(
        [
            section("Trends", build_request_trend_cards(requests), kind="chart"),
            section("Request history", [request_table(request_log)], kind="chart"),
        ]
    )

    return page_shell(
        title="GOOGLE INSTANCE",
        subtitle=subtitle,
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
