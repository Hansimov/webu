from __future__ import annotations

import os
import platform
import time

from collections.abc import Callable

import psutil

from a2wsgi import WSGIMiddleware
from dash import Dash, Input, Output, dcc, html
from plotly import graph_objects as go

from webu.runtime_settings import DEFAULT_GOOGLE_API_PANEL_PATH, DEFAULT_GOOGLE_API_PANEL_REFRESH_MS


SnapshotProvider = Callable[[], dict]


PANEL_COLORS = {
    "bg": "#f4efe6",
    "surface": "#fffaf2",
    "surface_alt": "#f7f0e2",
    "ink": "#1d1d1b",
    "muted": "#6b6254",
    "accent": "#0f766e",
    "accent_soft": "#d7efe9",
    "warn": "#b45309",
    "warn_soft": "#fde7c6",
    "danger": "#b91c1c",
    "danger_soft": "#fde1e1",
    "border": "#d8cdb9",
}


def _card(title: str, value: str, tone: str = "accent"):
    tones = {
        "accent": (PANEL_COLORS["accent"], PANEL_COLORS["accent_soft"]),
        "warn": (PANEL_COLORS["warn"], PANEL_COLORS["warn_soft"]),
        "danger": (PANEL_COLORS["danger"], PANEL_COLORS["danger_soft"]),
    }
    ink, bg = tones.get(tone, tones["accent"])
    return html.Div(
        [
            html.Div(title, style={"fontSize": "12px", "letterSpacing": "0.08em", "textTransform": "uppercase", "color": PANEL_COLORS["muted"]}),
            html.Div(value, style={"fontSize": "28px", "fontWeight": "700", "color": ink, "marginTop": "6px"}),
        ],
        style={
            "padding": "18px 20px",
            "borderRadius": "18px",
            "background": bg,
            "border": f"1px solid {PANEL_COLORS['border']}",
            "boxShadow": "0 10px 30px rgba(29, 29, 27, 0.06)",
        },
    )


def _section(title: str, children):
    return html.Section(
        [
            html.H2(title, style={"margin": "0 0 14px", "fontSize": "18px", "letterSpacing": "0.02em"}),
            children,
        ],
        style={
            "padding": "22px",
            "borderRadius": "22px",
            "background": PANEL_COLORS["surface"],
            "border": f"1px solid {PANEL_COLORS['border']}",
            "boxShadow": "0 16px 40px rgba(29, 29, 27, 0.07)",
        },
    )


def _kv_table(rows: list[tuple[str, str]]):
    return html.Table(
        [
            html.Tbody(
                [
                    html.Tr(
                        [
                            html.Th(key, style={"textAlign": "left", "padding": "8px 12px 8px 0", "verticalAlign": "top", "color": PANEL_COLORS["muted"], "fontWeight": "600", "width": "220px"}),
                            html.Td(value, style={"padding": "8px 0", "color": PANEL_COLORS["ink"], "wordBreak": "break-word"}),
                        ]
                    )
                    for key, value in rows
                ]
            )
        ],
        style={"width": "100%", "borderCollapse": "collapse", "fontSize": "14px"},
    )


def _proxy_table(proxy_items: list[dict]):
    header = html.Thead(
        html.Tr(
            [
                html.Th("Proxy"),
                html.Th("Health"),
                html.Th("Latency"),
                html.Th("Failures"),
                html.Th("Success Rate"),
                html.Th("Last Check"),
            ]
        )
    )
    body = html.Tbody(
        [
            html.Tr(
                [
                    html.Td(item.get("name") or item.get("url", "")),
                    html.Td("healthy" if item.get("healthy") else "unhealthy"),
                    html.Td(f"{item.get('latency_ms', 0)} ms"),
                    html.Td(str(item.get("consecutive_failures", 0))),
                    html.Td(str(item.get("success_rate", ""))),
                    html.Td(str(item.get("last_check", ""))),
                ]
            )
            for item in proxy_items
        ]
    )
    return html.Table(
        [header, body],
        style={"width": "100%", "borderCollapse": "collapse", "fontSize": "14px"},
        className="panel-proxy-table",
    )


def _health_figure(proxy_stats: dict) -> go.Figure:
    healthy = int(proxy_stats.get("healthy_proxies", 0))
    unhealthy = int(proxy_stats.get("unhealthy_proxies", 0))
    figure = go.Figure(
        data=[
            go.Pie(
                labels=["Healthy", "Unhealthy"],
                values=[healthy, unhealthy],
                hole=0.62,
                marker={"colors": [PANEL_COLORS["accent"], PANEL_COLORS["danger"]]},
                textinfo="label+value",
            )
        ]
    )
    figure.update_layout(
        margin={"l": 16, "r": 16, "t": 16, "b": 16},
        paper_bgcolor=PANEL_COLORS["surface"],
        plot_bgcolor=PANEL_COLORS["surface"],
        font={"family": '"IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif', "color": PANEL_COLORS["ink"]},
    )
    return figure


def _latency_figure(proxy_items: list[dict]) -> go.Figure:
    labels = [item.get("name") or item.get("url", "") for item in proxy_items]
    latencies = [int(item.get("latency_ms", 0)) for item in proxy_items]
    colors = [PANEL_COLORS["accent"] if item.get("healthy") else PANEL_COLORS["danger"] for item in proxy_items]
    figure = go.Figure(data=[go.Bar(x=latencies, y=labels, orientation="h", marker={"color": colors})])
    figure.update_layout(
        margin={"l": 16, "r": 16, "t": 16, "b": 16},
        paper_bgcolor=PANEL_COLORS["surface"],
        plot_bgcolor=PANEL_COLORS["surface_alt"],
        font={"family": '"IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif', "color": PANEL_COLORS["ink"]},
        xaxis_title="Latency (ms)",
        yaxis_title="",
    )
    return figure


def mount_google_api_panel(app, snapshot_provider: SnapshotProvider):
    dash_app = Dash(
        __name__,
        requests_pathname_prefix=DEFAULT_GOOGLE_API_PANEL_PATH,
        routes_pathname_prefix="/",
        suppress_callback_exceptions=True,
        title="Google API Panel",
    )
    dash_app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            body { margin: 0; background: linear-gradient(180deg, #f7f1e7 0%, #efe6d8 100%); color: #1d1d1b; font-family: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif; }
            * { box-sizing: border-box; }
            a { color: #0f766e; }
            .panel-proxy-table th, .panel-proxy-table td { border-bottom: 1px solid #e5dac7; padding: 10px 12px; text-align: left; }
            .panel-proxy-table th { color: #6b6254; font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""
    dash_app.layout = html.Div(
        [
            dcc.Interval(id="panel-refresh", interval=DEFAULT_GOOGLE_API_PANEL_REFRESH_MS, n_intervals=0),
            html.Div(
                [
                    html.Div("Google API Operations Panel", style={"fontSize": "13px", "letterSpacing": "0.16em", "textTransform": "uppercase", "color": PANEL_COLORS["muted"]}),
                    html.H1("Runtime Control Surface", style={"margin": "8px 0 10px", "fontSize": "40px", "lineHeight": "1.0"}),
                    html.P("Live runtime status for the current Google API instance, including service settings, profile state, process health, and proxy pool telemetry.", style={"margin": 0, "maxWidth": "780px", "fontSize": "16px", "lineHeight": "1.7", "color": PANEL_COLORS["muted"]}),
                    html.Div(id="panel-updated", style={"marginTop": "16px", "fontSize": "13px", "color": PANEL_COLORS["muted"]}),
                ],
                style={"padding": "36px 36px 20px"},
            ),
            html.Div(id="panel-cards", style={"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(180px, 1fr))", "gap": "16px", "padding": "0 36px 20px"}),
            html.Div([
                _section("Service Snapshot", html.Div(id="panel-service")),
                _section("Process Snapshot", html.Div(id="panel-process")),
                _section("Profile Snapshot", html.Div(id="panel-profile")),
                _section("Useful Links", html.Div(id="panel-links")),
            ], style={"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(320px, 1fr))", "gap": "18px", "padding": "0 36px 20px"}),
            html.Div([
                _section("Proxy Health Mix", dcc.Graph(id="panel-health-figure", config={"displayModeBar": False})),
                _section("Proxy Latency", dcc.Graph(id="panel-latency-figure", config={"displayModeBar": False})),
            ], style={"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(320px, 1fr))", "gap": "18px", "padding": "0 36px 20px"}),
            html.Div([_section("Proxy Details", html.Div(id="panel-proxies"))], style={"padding": "0 36px 40px"}),
        ],
        style={"minHeight": "100vh"},
    )

    @dash_app.callback(
        Output("panel-updated", "children"),
        Output("panel-cards", "children"),
        Output("panel-service", "children"),
        Output("panel-process", "children"),
        Output("panel-profile", "children"),
        Output("panel-links", "children"),
        Output("panel-health-figure", "figure"),
        Output("panel-latency-figure", "figure"),
        Output("panel-proxies", "children"),
        Input("panel-refresh", "n_intervals"),
    )
    def refresh_panel(_n_intervals: int):
        snapshot = snapshot_provider()
        proxy_stats = snapshot.get("proxy_stats", {})
        proxy_items = list(proxy_stats.get("proxies", []))
        health = snapshot.get("health", {})
        runtime = snapshot.get("runtime", {})
        process = snapshot.get("process", {})
        profile = snapshot.get("profile", {})
        links = snapshot.get("links", {})
        cards = [
            _card("Runtime", str(runtime.get("runtime_env", ""))),
            _card("Healthy Proxies", f"{proxy_stats.get('healthy_proxies', 0)}/{proxy_stats.get('total_proxies', 0)}"),
            _card("Search API Token", "enabled" if runtime.get("api_token_configured") else "open", "warn" if not runtime.get("api_token_configured") else "accent"),
            _card("Admin Token", "enabled" if runtime.get("admin_token_configured") else "not set", "warn" if not runtime.get("admin_token_configured") else "accent"),
            _card("Profile Files", str(profile.get("file_count", 0))),
            _card("Scraper", "ready" if health.get("scraper_ready") else "starting", "accent" if health.get("scraper_ready") else "warn"),
        ]
        service_rows = _kv_table([
            ("Host", str(runtime.get("host", ""))),
            ("Port", str(runtime.get("port", ""))),
            ("Service URL", str(runtime.get("service_url", ""))),
            ("Service Type", str(runtime.get("service_type", ""))),
            ("Headless", "true" if runtime.get("headless") else "false"),
            ("Proxy Mode", str(runtime.get("proxy_mode", ""))),
            ("Proxy Count", str(runtime.get("proxy_count", 0))),
            ("Panel Root Mode", "default root" if runtime.get("panel_root_enabled") else "secondary route"),
            ("Profile Dir", str(runtime.get("profile_dir", ""))),
            ("Screenshot Dir", str(runtime.get("screenshot_dir", ""))),
            ("Data Dir", str(runtime.get("data_dir", ""))),
        ])
        process_rows = _kv_table([
            ("PID", str(process.get("pid", ""))),
            ("Hostname", str(process.get("hostname", ""))),
            ("Platform", str(process.get("platform", ""))),
            ("Uptime", str(process.get("uptime_human", ""))),
            ("Resident Memory", str(process.get("rss_mb", ""))),
            ("CPU Percent", str(process.get("cpu_percent", ""))),
        ])
        profile_rows = _kv_table([
            ("Profile Exists", "true" if profile.get("exists") else "false"),
            ("Archive Available", "true" if profile.get("archive_available") else "false"),
            ("Last Modified", str(profile.get("last_modified_human", ""))),
            ("Profile Dir", str(profile.get("profile_dir", ""))),
        ])
        link_children = html.Ul([html.Li(html.A(label, href=href)) for label, href in links.items()], style={"margin": 0, "paddingLeft": "20px", "lineHeight": "1.9"})
        updated_text = f"Updated at {snapshot.get('updated_at_human', '')} on {snapshot.get('process', {}).get('hostname', platform.node())}."
        return updated_text, cards, service_rows, process_rows, profile_rows, link_children, _health_figure(proxy_stats), _latency_figure(proxy_items), _proxy_table(proxy_items)

    app.mount(DEFAULT_GOOGLE_API_PANEL_PATH, WSGIMiddleware(dash_app.server))


def build_process_snapshot(started_at: float) -> dict:
    process = psutil.Process(os.getpid())
    rss_mb = process.memory_info().rss / (1024 * 1024)
    uptime_sec = max(0.0, time.time() - started_at)
    hours, remainder = divmod(int(uptime_sec), 3600)
    minutes, seconds = divmod(remainder, 60)
    return {
        "pid": process.pid,
        "hostname": platform.node(),
        "platform": platform.platform(),
        "uptime_human": f"{hours}h {minutes}m {seconds}s",
        "rss_mb": f"{rss_mb:.1f} MB",
        "cpu_percent": f"{process.cpu_percent(interval=None):.1f}%",
    }