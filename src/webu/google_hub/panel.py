from __future__ import annotations

from collections.abc import Callable

from a2wsgi import WSGIMiddleware
from dash import Input, Output, dcc, html

from webu.fastapis.dashboard_ui import (
    THEME,
    backend_card,
    bar_figure,
    chip,
    create_dash_app,
    donut_figure,
    format_ms,
    format_rate,
    gauge_figure,
    graph_card,
    metric_card,
    page_shell,
    section,
)
from webu.runtime_settings import DEFAULT_GOOGLE_API_PANEL_PATH, DEFAULT_GOOGLE_API_PANEL_REFRESH_MS


SnapshotProvider = Callable[[], dict]


def _build_body(snapshot: dict):
    requests = snapshot.get("requests", {})
    health = snapshot.get("health", {})
    backends = list(snapshot.get("backends", []))
    node = snapshot.get("node", {})

    healthy_backends = int(health.get("healthy_backends", 0))
    backend_count = int(health.get("backend_count", len(backends)))
    accepted_requests = int(requests.get("accepted_requests", 0))
    successful_requests = int(requests.get("successful_requests", 0))
    failed_requests = int(requests.get("failed_requests", 0))

    cards = [
        metric_card("Healthy backends", f"{healthy_backends}/{max(backend_count, 1)}", "Live routing pool", "accent" if healthy_backends else "danger"),
        metric_card("Accepted requests", str(accepted_requests), "Routed through hub", "info"),
        metric_card("Successful requests", str(successful_requests), f"{format_rate(float(requests.get('success_rate', 0.0)))} success", "accent"),
        metric_card("Avg latency", format_ms(float(requests.get("avg_latency_ms", 0.0))), f"min {format_ms(float(requests.get('min_latency_ms', 0.0)))} / max {format_ms(float(requests.get('max_latency_ms', 0.0)))}", "warn"),
        metric_card(node.get("label", "Server IP"), node.get("value", "unknown"), "Current hub node", "info"),
    ]

    charts = [
        graph_card(
            "Backend health",
            donut_figure(
                labels=["Healthy", "Degraded"],
                values=[healthy_backends, max(0, backend_count - healthy_backends)],
                colors=[THEME["accent"], THEME["danger"]],
            ),
        ),
        graph_card(
            "Success rate",
            gauge_figure(
                value=float(requests.get("success_rate", 0.0)),
                maximum=100.0,
                color=THEME["info"],
                suffix="%",
            ),
        ),
        graph_card(
            "Requests by backend",
            bar_figure(
                labels=[item.get("name", "backend") for item in backends],
                values=[float(item.get("request_count", 0)) for item in backends],
                colors=[THEME["info"] for _ in backends] or [THEME["info"]],
                axis_title="Requests",
            ),
        ),
        graph_card(
            "Latency by backend",
            bar_figure(
                labels=[item.get("name", "backend") for item in backends],
                values=[float(item.get("avg_request_latency_ms", 0.0)) for item in backends],
                colors=[THEME["accent"] if item.get("healthy") else THEME["danger"] for item in backends] or [THEME["accent"]],
                axis_title="Avg latency (ms)",
            ),
        ),
    ]

    backend_cards = [
        backend_card(
            name=item.get("name", "backend"),
            caption=item.get("space_name") or item.get("kind", ""),
            healthy=bool(item.get("healthy")),
            request_value=str(item.get("request_count", 0)),
            success_value=f"{item.get('successful_requests', 0)} / {format_rate(float(item.get('success_rate', 0.0)))}",
            latency_value=format_ms(float(item.get("avg_request_latency_ms", 0.0))),
            note=f"{item.get('inflight', 0)} inflight",
        )
        for item in backends
    ]

    chips = [
        chip(f"Updated {snapshot.get('updated_at_human', '')}"),
        chip(f"Strategy {snapshot.get('strategy', 'least-inflight')}"),
        chip(f"Backends {backend_count}"),
        chip(f"Failures {failed_requests}"),
    ]

    return page_shell(
        title="Hub Routing Deck",
        kicker="Google Hub",
        subtitle="Dark control surface for backend health, routed traffic, and latency distribution across local and HF nodes.",
        chips=chips,
        body=[
            section("Hub overview", cards, kind="cards"),
            section("Traffic dashboards", charts, kind="charts"),
            section("Instance cards", backend_cards, kind="backends"),
        ],
    )


def mount_google_hub_panel(app, snapshot_provider: SnapshotProvider):
    dash_app = create_dash_app(name=__name__, title="Google Hub Panel", panel_path=DEFAULT_GOOGLE_API_PANEL_PATH)
    dash_app.layout = html.Div(
        [
            dcc.Interval(id="hub-panel-refresh", interval=DEFAULT_GOOGLE_API_PANEL_REFRESH_MS, n_intervals=0),
            html.Div(id="hub-panel-root"),
        ]
    )

    @dash_app.callback(Output("hub-panel-root", "children"), Input("hub-panel-refresh", "n_intervals"))
    def refresh_panel(_n_intervals: int):
        return _build_body(snapshot_provider())

    app.mount(DEFAULT_GOOGLE_API_PANEL_PATH, WSGIMiddleware(dash_app.server))