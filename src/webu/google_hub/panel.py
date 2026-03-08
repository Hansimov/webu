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
    build_backend_instance_cards,
    build_instances_metric_card,
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
    health = snapshot.get("health", {})
    instances = list(snapshot.get("backends", []))
    node = snapshot.get("node", {})
    request_log = list(requests.get("request_log", []))

    healthy_count = int(health.get("healthy_backends", 0))
    total_count = int(health.get("backend_count", len(instances)))
    badge_tone = (
        "accent"
        if healthy_count == total_count and total_count > 0
        else ("warn" if healthy_count > 0 else "danger")
    )

    subtitle = (
        f"Run at {snapshot.get('started_at_human', '')}"
        f" · {snapshot.get('timezone_human', 'UTC+08 Shanghai')}"
    )

    cards = [
        *build_time_metric_cards(snapshot),
        build_instances_metric_card(snapshot),
        *build_request_metric_cards(requests),
        build_node_metric_card(
            node, f"Strategy {snapshot.get('strategy', 'adaptive')}"
        ),
    ]

    body = [section("Overview", cards, kind="metric")]
    body.extend(
        [
            section("Trends", build_request_trend_cards(requests), kind="chart"),
            section(
                "Instances", build_backend_instance_cards(instances), kind="instance"
            ),
            section(
                "Request history",
                [request_table(request_log, show_backend=True)],
                kind="chart",
            ),
        ]
    )

    return page_shell(
        title="GOOGLE HUB",
        subtitle=subtitle,
        badge=f"{healthy_count}/{total_count} HEALTHY",
        badge_tone=badge_tone,
        body=body,
    )


def mount_google_hub_panel(app, snapshot_provider: SnapshotProvider):
    dash_app = create_dash_app(
        name=__name__,
        title="Google Hub Panel",
        panel_path=DEFAULT_GOOGLE_API_PANEL_PATH,
    )
    dash_app.layout = html.Div(
        [
            dcc.Interval(
                id="hub-panel-refresh",
                interval=DEFAULT_GOOGLE_API_PANEL_REFRESH_MS,
                n_intervals=0,
            ),
            html.Div(id="hub-panel-root"),
        ]
    )

    @dash_app.callback(
        Output("hub-panel-root", "children"), Input("hub-panel-refresh", "n_intervals")
    )
    def refresh_panel(_n_intervals: int):
        return _build_body(snapshot_provider())

    app.mount(DEFAULT_GOOGLE_API_PANEL_PATH, WSGIMiddleware(dash_app.server))
