from __future__ import annotations

from typing import Iterable

from dash import Dash, dcc, html
from plotly import graph_objects as go


THEME = {
    "bg": "#07111f",
    "bg_alt": "#0b1728",
    "surface": "#111c2d",
    "surface_alt": "#16243a",
    "surface_soft": "#1a2a43",
    "border": "#263850",
    "text": "#f3f7fb",
    "muted": "#8ea3bd",
    "accent": "#3dd9b8",
    "accent_soft": "rgba(61, 217, 184, 0.12)",
    "warn": "#ffb84d",
    "warn_soft": "rgba(255, 184, 77, 0.14)",
    "danger": "#ff6b7a",
    "danger_soft": "rgba(255, 107, 122, 0.14)",
    "info": "#52a8ff",
    "info_soft": "rgba(82, 168, 255, 0.14)",
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
                --bg-alt: {THEME['bg_alt']};
                --surface: {THEME['surface']};
                --surface-alt: {THEME['surface_alt']};
                --surface-soft: {THEME['surface_soft']};
                --border: {THEME['border']};
                --text: {THEME['text']};
                --muted: {THEME['muted']};
                --accent: {THEME['accent']};
                --warn: {THEME['warn']};
                --danger: {THEME['danger']};
            }}
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0;
                min-height: 100vh;
                background:
                    radial-gradient(circle at top left, rgba(61, 217, 184, 0.12), transparent 28%),
                    radial-gradient(circle at top right, rgba(82, 168, 255, 0.10), transparent 24%),
                    linear-gradient(180deg, var(--bg) 0%, var(--bg-alt) 100%);
                color: var(--text);
                font-family: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
            }}
            a {{ color: var(--accent); text-decoration: none; }}
            .dashboard-shell {{ padding: 28px; }}
            .dashboard-header {{ margin-bottom: 24px; }}
            .dashboard-kicker {{ color: var(--muted); font-size: 12px; letter-spacing: 0.18em; text-transform: uppercase; }}
            .dashboard-title {{ margin: 10px 0 8px; font-size: clamp(30px, 5vw, 46px); line-height: 1.02; }}
            .dashboard-subtitle {{ margin: 0; max-width: 760px; color: var(--muted); font-size: 15px; line-height: 1.7; }}
            .dashboard-chip-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
            .dashboard-chip {{ padding: 8px 12px; border-radius: 999px; border: 1px solid var(--border); background: rgba(255,255,255,0.03); color: var(--muted); font-size: 12px; }}
            .dashboard-grid {{ display: grid; gap: 16px; }}
            .dashboard-grid.cards {{ grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }}
            .dashboard-grid.charts {{ grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }}
            .dashboard-grid.backends {{ grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}
            .dashboard-card {{
                padding: 18px 18px 16px;
                border-radius: 20px;
                background: linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.02));
                border: 1px solid var(--border);
                box-shadow: 0 20px 60px rgba(0, 0, 0, 0.22);
            }}
            .dashboard-card-label {{ color: var(--muted); font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase; }}
            .dashboard-card-value {{ margin-top: 10px; font-size: clamp(24px, 3vw, 34px); font-weight: 700; line-height: 1.05; }}
            .dashboard-card-note {{ margin-top: 8px; color: var(--muted); font-size: 13px; line-height: 1.5; }}
            .dashboard-section {{ margin-top: 22px; }}
            .dashboard-section-title {{ margin: 0 0 14px; font-size: 18px; letter-spacing: 0.02em; }}
            .dashboard-backend-card {{
                padding: 18px;
                border-radius: 20px;
                border: 1px solid var(--border);
                background: linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.015));
            }}
            .dashboard-backend-top {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
            .dashboard-backend-name {{ font-size: 16px; font-weight: 600; }}
            .dashboard-backend-meta {{ margin-top: 6px; color: var(--muted); font-size: 13px; }}
            .dashboard-pill {{ padding: 6px 10px; border-radius: 999px; font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; }}
            .dashboard-stat-pair {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }}
            .dashboard-stat-box {{ padding: 12px; border-radius: 14px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.04); }}
            .dashboard-stat-label {{ color: var(--muted); font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; }}
            .dashboard-stat-value {{ margin-top: 8px; font-size: 20px; font-weight: 700; }}
            @media (max-width: 720px) {{
                .dashboard-shell {{ padding: 18px; }}
                .dashboard-card, .dashboard-backend-card {{ border-radius: 18px; }}
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


def page_shell(*, title: str, kicker: str, subtitle: str, chips: Iterable, body: Iterable):
    return html.Div(
        [
            html.Header(
                [
                    html.Div(kicker, className="dashboard-kicker"),
                    html.H1(title, className="dashboard-title"),
                    html.P(subtitle, className="dashboard-subtitle"),
                    html.Div(list(chips), className="dashboard-chip-row"),
                ],
                className="dashboard-header",
            ),
            *list(body),
        ],
        className="dashboard-shell",
    )


def chip(text: str):
    return html.Div(text, className="dashboard-chip")


def metric_card(label: str, value: str, note: str = "", tone: str = "accent"):
    tone_map = {
        "accent": (THEME["accent"], THEME["accent_soft"]),
        "warn": (THEME["warn"], THEME["warn_soft"]),
        "danger": (THEME["danger"], THEME["danger_soft"]),
        "info": (THEME["info"], THEME["info_soft"]),
    }
    ink, bg = tone_map.get(tone, tone_map["accent"])
    return html.Div(
        [
            html.Div(label, className="dashboard-card-label"),
            html.Div(value, className="dashboard-card-value", style={"color": ink}),
            html.Div(note, className="dashboard-card-note"),
        ],
        className="dashboard-card",
        style={"background": f"linear-gradient(180deg, {bg}, rgba(255,255,255,0.02))"},
    )


def section(title: str, children, kind: str = "charts"):
    return html.Section(
        [
            html.H2(title, className="dashboard-section-title"),
            html.Div(list(children), className=f"dashboard-grid {kind}"),
        ],
        className="dashboard-section",
    )


def graph_card(title: str, figure: go.Figure):
    return html.Div(
        [
            html.Div(title, className="dashboard-card-label"),
            dcc.Graph(figure=figure, config={"displayModeBar": False}, style={"height": "290px", "marginTop": "8px"}),
        ],
        className="dashboard-card",
    )


def backend_card(*, name: str, caption: str, healthy: bool, request_value: str, success_value: str, latency_value: str, note: str = ""):
    pill_style = {
        "background": THEME["accent_soft"] if healthy else THEME["danger_soft"],
        "color": THEME["accent"] if healthy else THEME["danger"],
    }
    return html.Div(
        [
            html.Div(
                [
                    html.Div(name, className="dashboard-backend-name"),
                    html.Div("healthy" if healthy else "degraded", className="dashboard-pill", style=pill_style),
                ],
                className="dashboard-backend-top",
            ),
            html.Div(caption, className="dashboard-backend-meta"),
            html.Div(
                [
                    html.Div(
                        [html.Div("Requests", className="dashboard-stat-label"), html.Div(request_value, className="dashboard-stat-value")],
                        className="dashboard-stat-box",
                    ),
                    html.Div(
                        [html.Div("Success", className="dashboard-stat-label"), html.Div(success_value, className="dashboard-stat-value")],
                        className="dashboard-stat-box",
                    ),
                    html.Div(
                        [html.Div("Avg Latency", className="dashboard-stat-label"), html.Div(latency_value, className="dashboard-stat-value")],
                        className="dashboard-stat-box",
                    ),
                    html.Div(
                        [html.Div("Health", className="dashboard-stat-label"), html.Div(note or ("ready" if healthy else "retrying"), className="dashboard-stat-value")],
                        className="dashboard-stat-box",
                    ),
                ],
                className="dashboard-stat-pair",
            ),
        ],
        className="dashboard-backend-card",
    )


def base_figure() -> go.Figure:
    figure = go.Figure()
    figure.update_layout(
        margin={"l": 12, "r": 12, "t": 12, "b": 12},
        paper_bgcolor=THEME["surface"],
        plot_bgcolor=THEME["surface_alt"],
        font={"family": '"IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif', "color": THEME["text"]},
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
                "steps": [{"range": [0, max(1.0, float(maximum))], "color": THEME["surface_soft"]}],
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


def format_ms(value: float) -> str:
    if value <= 0:
        return "0 ms"
    if value >= 1000:
        return f"{value / 1000:.2f} s"
    return f"{value:.0f} ms"


def format_rate(value: float) -> str:
    return f"{value:.1f}%"