from __future__ import annotations

from typing import Iterable

from dash import Dash, dcc, html
from plotly import graph_objects as go


THEME = {
    "bg": "#0b1120",
    "surface": "#111827",
    "surface_alt": "#1e293b",
    "border": "#1e293b",
    "border_light": "#334155",
    "text": "#f1f5f9",
    "muted": "#94a3b8",
    "accent": "#34d399",
    "accent_soft": "rgba(52,211,153,0.15)",
    "warn": "#fbbf24",
    "warn_soft": "rgba(251,191,36,0.15)",
    "danger": "#f87171",
    "danger_soft": "rgba(248,113,113,0.15)",
    "info": "#60a5fa",
    "info_soft": "rgba(96,165,250,0.15)",
}


def create_dash_app(*, name: str, title: str, panel_path: str) -> Dash:
    app = Dash(
        name,
        requests_pathname_prefix=panel_path,
        routes_pathname_prefix="/",
        suppress_callback_exceptions=True,
        title=title,
    )
    app.index_string = f"""
<!DOCTYPE html>
<html>
    <head>
        {{%metas%}}
        <title>{{%title%}}</title>
        {{%favicon%}}
        {{%css%}}
        <style>
            :root {{
                color-scheme: dark;
                --bg: {THEME['bg']};
                --surface: {THEME['surface']};
                --surface-alt: {THEME['surface_alt']};
                --border: {THEME['border']};
                --border-light: {THEME['border_light']};
                --text: {THEME['text']};
                --muted: {THEME['muted']};
                --accent: {THEME['accent']};
                --warn: {THEME['warn']};
                --danger: {THEME['danger']};
                --info: {THEME['info']};
            }}
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                min-height: 100vh;
                background: var(--bg);
                color: var(--text);
                font-family: "Inter", "SF Pro Display", -apple-system, "Segoe UI", sans-serif;
                -webkit-font-smoothing: antialiased;
            }}
            a {{ color: var(--accent); text-decoration: none; }}
            .dash-shell {{ max-width: 1200px; margin: 0 auto; padding: 28px 24px; }}
            .dash-header {{ margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border-light); }}
            .dash-title-row {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
            .dash-title {{ font-size: 24px; font-weight: 700; letter-spacing: -0.01em; line-height: 1.2; }}
            .dash-badge {{ display: inline-block; padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }}
            .dash-subtitle {{ margin-top: 8px; font-size: 13px; color: var(--muted); line-height: 1.5; }}
            .dash-grid {{ display: grid; gap: 14px; }}
            .dash-grid.metric {{ grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }}
            .dash-grid.chart {{ grid-template-columns: repeat(2, 1fr); }}
            .dash-grid.instance {{ grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }}
            .dash-card {{
                padding: 16px;
                border-radius: 12px;
                background: var(--surface);
                border: 1px solid var(--border);
            }}
            .dash-card-label {{ font-size: 11px; color: var(--muted); letter-spacing: 0.06em; text-transform: uppercase; font-weight: 500; }}
            .dash-card-value {{ margin-top: 8px; font-size: 26px; font-weight: 700; line-height: 1; }}
            .dash-card-note {{ margin-top: 6px; font-size: 12px; color: var(--muted); }}
            .dash-section {{ margin-top: 24px; }}
            .dash-section-title {{ font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); margin-bottom: 12px; font-weight: 600; }}
            .dash-inst {{ padding: 14px; border-radius: 12px; background: var(--surface); border: 1px solid var(--border); }}
            .dash-inst-hd {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; }}
            .dash-inst-name {{ font-size: 15px; font-weight: 600; }}
            .dash-inst-meta {{ margin-top: 4px; font-size: 12px; color: var(--muted); }}
            .dash-inst-stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 12px; }}
            .dash-stat {{ padding: 8px 10px; border-radius: 8px; background: var(--surface-alt); }}
            .dash-stat-label {{ font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }}
            .dash-stat-value {{ margin-top: 4px; font-size: 16px; font-weight: 600; }}
            .dash-tag {{ display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
            .dash-table-wrap {{ overflow-x: auto; border-radius: 12px; border: 1px solid var(--border); background: var(--surface); max-height: 340px; overflow-y: auto; }}
            .dash-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
            .dash-table th {{ position: sticky; top: 0; z-index: 1; background: var(--surface-alt); color: var(--muted); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border-light); }}
            .dash-table td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); color: var(--text); white-space: nowrap; }}
            .dash-table tr:last-child td {{ border-bottom: none; }}
            .dash-table tr:hover td {{ background: rgba(255,255,255,0.02); }}
            .dash-table .col-query {{ max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
            .dash-empty {{ padding: 24px; text-align: center; color: var(--muted); font-size: 13px; }}
            @media (max-width: 768px) {{
                .dash-shell {{ padding: 16px; }}
                .dash-grid.chart {{ grid-template-columns: 1fr; }}
                .dash-inst-stats {{ grid-template-columns: repeat(2, 1fr); }}
            }}
        </style>
    </head>
    <body>
        {{%app_entry%}}
        <footer>
            {{%config%}}
            {{%scripts%}}
            {{%renderer%}}
        </footer>
    </body>
</html>
"""
    return app


def page_shell(*, title: str, subtitle: str = "", badge: str = "", badge_tone: str = "accent", body: Iterable, chips: Iterable = ()):
    tone_map = {
        "accent": (THEME["accent"], THEME["accent_soft"]),
        "warn": (THEME["warn"], THEME["warn_soft"]),
        "danger": (THEME["danger"], THEME["danger_soft"]),
        "info": (THEME["info"], THEME["info_soft"]),
    }
    ink, bg = tone_map.get(badge_tone, tone_map["accent"])
    title_children = [html.H1(title, className="dash-title")]
    if badge:
        title_children.append(html.Span(badge, className="dash-badge", style={"background": bg, "color": ink}))
    header_children = [html.Div(title_children, className="dash-title-row")]
    if subtitle:
        header_children.append(html.Div(subtitle, className="dash-subtitle"))
    return html.Div(
        [
            html.Header(header_children, className="dash-header"),
            *list(body),
        ],
        className="dash-shell",
    )


def chip(text: str):
    return html.Div(text, className="dashboard-chip")


def metric_card(label: str, value: str, note: str = "", tone: str = "accent"):
    color = THEME.get(tone, THEME["accent"])
    children = [
        html.Div(label, className="dash-card-label"),
        html.Div(value, className="dash-card-value", style={"color": color}),
    ]
    if note:
        children.append(html.Div(note, className="dash-card-note"))
    return html.Div(children, className="dash-card")


def section(title: str, children, kind: str = "chart"):
    return html.Section(
        [
            html.H2(title, className="dash-section-title"),
            html.Div(list(children), className=f"dash-grid {kind}"),
        ],
        className="dash-section",
    )


def graph_card(title: str, figure: go.Figure):
    return html.Div(
        [
            html.Div(title, className="dash-card-label"),
            dcc.Graph(figure=figure, config={"displayModeBar": False}, style={"height": "200px", "marginTop": "8px"}),
        ],
        className="dash-card",
    )


def instance_card(*, name: str, caption: str, healthy: bool, stats: list[tuple[str, str]]):
    tag_style = {
        "background": THEME["accent_soft"] if healthy else THEME["danger_soft"],
        "color": THEME["accent"] if healthy else THEME["danger"],
    }
    stat_items = [
        html.Div(
            [
                html.Div(label, className="dash-stat-label"),
                html.Div(value, className="dash-stat-value"),
            ],
            className="dash-stat",
        )
        for label, value in stats
    ]
    return html.Div(
        [
            html.Div(
                [
                    html.Div(name, className="dash-inst-name"),
                    html.Span("healthy" if healthy else "unhealthy", className="dash-tag", style=tag_style),
                ],
                className="dash-inst-hd",
            ),
            html.Div(caption, className="dash-inst-meta"),
            html.Div(stat_items, className="dash-inst-stats"),
        ],
        className="dash-inst",
    )


def request_table(records: list[dict], show_backend: bool = False) -> html.Div:
    if not records:
        return html.Div(html.Div("No requests recorded yet", className="dash-empty"), className="dash-table-wrap")

    headers = ["Time", "Query", "Status", "Latency"]
    if show_backend:
        headers.insert(2, "Instance")
    headers.append("Error")

    rows = []
    for record in reversed(records[-50:]):
        success = record.get("success", False)
        tag_style = {
            "background": THEME["accent_soft"] if success else THEME["danger_soft"],
            "color": THEME["accent"] if success else THEME["danger"],
        }
        cells = [
            html.Td(record.get("ts_label", "")),
            html.Td(record.get("query", "") or "\u2014", className="col-query"),
        ]
        if show_backend:
            cells.append(html.Td(record.get("backend", "") or "\u2014"))
        cells.extend([
            html.Td(html.Span("OK" if success else "FAIL", className="dash-tag", style=tag_style)),
            html.Td(format_ms(float(record.get("latency_ms", 0)))),
            html.Td(record.get("error", "") or "\u2014", style={"color": THEME["muted"], "fontSize": "12px"}),
        ])
        rows.append(html.Tr(cells))

    return html.Div(
        html.Table(
            [html.Thead(html.Tr([html.Th(h) for h in headers])), html.Tbody(rows)],
            className="dash-table",
        ),
        className="dash-table-wrap",
    )


def base_figure() -> go.Figure:
    figure = go.Figure()
    figure.update_layout(
        margin={"l": 12, "r": 12, "t": 12, "b": 12},
        paper_bgcolor=THEME["surface"],
        plot_bgcolor=THEME["surface_alt"],
        font={"family": '"Inter", "SF Pro Display", -apple-system, "Segoe UI", sans-serif', "color": THEME["text"]},
    )
    return figure


def donut_figure(*, labels: list[str], values: list[float], colors: list[str]) -> go.Figure:
    figure = base_figure()
    figure.add_trace(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.68,
            textinfo="label+value",
            marker={"colors": colors},
            sort=False,
        )
    )
    figure.update_layout(showlegend=False)
    return figure


def gauge_figure(*, value: float, maximum: float, color: str, suffix: str = "") -> go.Figure:
    figure = base_figure()
    figure.add_trace(
        go.Indicator(
            mode="gauge+number",
            value=max(0.0, float(value)),
            number={"suffix": suffix},
            gauge={
                "axis": {"range": [0, max(1.0, float(maximum))], "tickcolor": THEME["muted"]},
                "bar": {"color": color},
                "bgcolor": THEME["surface_alt"],
                "borderwidth": 0,
                "steps": [{"range": [0, max(1.0, float(maximum))], "color": THEME["surface_alt"]}],
            },
        )
    )
    return figure


def bar_figure(*, labels: list[str], values: list[float], colors: list[str], horizontal: bool = False, axis_title: str = "") -> go.Figure:
    figure = base_figure()
    if horizontal:
        figure.add_trace(go.Bar(x=values, y=labels, orientation="h", marker={"color": colors}))
        figure.update_layout(xaxis_title=axis_title, yaxis_title="")
    else:
        figure.add_trace(go.Bar(x=labels, y=values, marker={"color": colors}))
        figure.update_layout(yaxis_title=axis_title, xaxis_title="")
    return figure


def line_figure(*, labels: list[str], series: list[dict], axis_title: str = "") -> go.Figure:
    figure = base_figure()
    for item in series:
        figure.add_trace(
            go.Scatter(
                x=labels,
                y=item.get("values", []),
                mode="lines+markers",
                name=item.get("name", "series"),
                line={"color": item.get("color", THEME["accent"]), "width": 2.5},
                marker={"size": 6},
                fill=item.get("fill", None),
            )
        )
    figure.update_layout(
        yaxis_title=axis_title,
        xaxis_title="",
        legend={"orientation": "h", "y": 1.12, "x": 0},
        margin={"l": 12, "r": 12, "t": 24, "b": 12},
    )
    return figure


def format_ms(value: float) -> str:
    if value <= 0:
        return "0 ms"
    if value >= 1000:
        return f"{value / 1000:.2f} s"
    return f"{value:.0f} ms"


def format_rate(value: float) -> str:
    return f"{value:.1f}%"