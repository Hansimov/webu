from __future__ import annotations

from collections.abc import Callable

from a2wsgi import WSGIMiddleware
from dash import Input, Output, dcc, html

from webu.fastapis.dashboard_ui import (
    THEME,
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


def _proxy_charts(proxy_stats: dict):
    proxy_items = list(proxy_stats.get("proxies", []))
    healthy = int(proxy_stats.get("healthy_proxies", 0))
    total = int(proxy_stats.get("total_proxies", 0))
    latencies = [float(item.get("latency_ms", 0.0)) for item in proxy_items]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    cards = [
        metric_card("Proxy pool", f"{healthy}/{max(total, 1)}", "Healthy proxies in rotation", "accent" if healthy else "danger"),
        metric_card("Proxy latency", format_ms(avg_latency), f"Across {total} configured proxies", "warn"),
    ]
    charts = [
        graph_card(
            "Proxy health",
            gauge_figure(value=healthy, maximum=max(total, 1), color=THEME["accent"] if healthy else THEME["danger"]),
        ),
        graph_card(
            "Proxy RTT",
            bar_figure(
                labels=[item.get("name") or item.get("url", "proxy") for item in proxy_items],
                values=latencies,
                colors=[THEME["accent"] if item.get("healthy") else THEME["danger"] for item in proxy_items] or [THEME["accent"]],
                axis_title="Latency (ms)",
            ),
        ),
    ]
    return cards, charts


def _build_body(snapshot: dict):
    requests = snapshot.get("requests", {})
    service = snapshot.get("service", {})
    node = snapshot.get("node", {})
    proxy_stats = snapshot.get("proxy_stats", {})
    has_proxies = bool(snapshot.get("has_proxies"))

    accepted_requests = int(requests.get("accepted_requests", 0))
    successful_requests = int(requests.get("successful_requests", 0))
    failed_requests = int(requests.get("failed_requests", 0))

    cards = [
        metric_card("Service", service.get("status_label", "starting"), service.get("status_note", "Search pipeline status"), service.get("tone", "warn")),
        metric_card("Accepted requests", str(accepted_requests), "Search requests admitted", "info"),
        metric_card("Successful requests", str(successful_requests), f"{format_rate(float(requests.get('success_rate', 0.0)))} success", "accent"),
        metric_card("Avg latency", format_ms(float(requests.get("avg_latency_ms", 0.0))), f"min {format_ms(float(requests.get('min_latency_ms', 0.0)))} / max {format_ms(float(requests.get('max_latency_ms', 0.0)))}", "warn"),
        metric_card(node.get("label", "Server IP"), node.get("value", "unknown"), "Current node", "info"),
    ]

    charts = [
        graph_card(
            "Request outcomes",
            donut_figure(
                labels=["Success", "Other"],
                values=[successful_requests, max(0, accepted_requests - successful_requests)],
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
            "Latency profile",
            bar_figure(
                labels=["avg", "min", "max", "last"],
                values=[
                    float(requests.get("avg_latency_ms", 0.0)),
                    float(requests.get("min_latency_ms", 0.0)),
                    float(requests.get("max_latency_ms", 0.0)),
                    float(requests.get("last_latency_ms", 0.0)),
                ],
                colors=[THEME["warn"], THEME["accent"], THEME["danger"], THEME["info"]],
                axis_title="Latency (ms)",
            ),
        ),
    ]

    chips = [
        chip(f"Updated {snapshot.get('updated_at_human', '')}"),
        chip(f"Runtime {snapshot.get('runtime_env', 'unknown')}"),
        chip(f"Requests {accepted_requests}"),
        chip(f"Failures {failed_requests}"),
    ]

    sections = [
        section("Service overview", cards, kind="cards"),
        section("Request dashboards", charts, kind="charts"),
    ]
    if has_proxies:
        proxy_cards, proxy_charts = _proxy_charts(proxy_stats)
        sections.append(section("Proxy dashboards", proxy_cards, kind="cards"))
        sections.append(section("Proxy health and latency", proxy_charts, kind="charts"))

    return page_shell(
        title="Search Control Deck",
        kicker="Google API",
        subtitle="Unified dark-mode dashboard for service health, accepted request traffic, latency distribution, and proxy pool quality when proxies are enabled.",
        chips=chips,
        body=sections,
    )


def mount_google_api_panel(app, snapshot_provider: SnapshotProvider):
    dash_app = create_dash_app(name=__name__, title="Google API Panel", panel_path=DEFAULT_GOOGLE_API_PANEL_PATH)
    dash_app.layout = html.Div(
        [
            dcc.Interval(id="panel-refresh", interval=DEFAULT_GOOGLE_API_PANEL_REFRESH_MS, n_intervals=0),
            html.Div(id="panel-root"),
        ]
    )

    @dash_app.callback(Output("panel-root", "children"), Input("panel-refresh", "n_intervals"))
    def refresh_panel(_n_intervals: int):
        return _build_body(snapshot_provider())

    app.mount(DEFAULT_GOOGLE_API_PANEL_PATH, WSGIMiddleware(dash_app.server))