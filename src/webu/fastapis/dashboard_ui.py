from __future__ import annotations

from typing import Iterable

from dash import Dash, html


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
            .dash-meta-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
            .dash-meta-chip {{ padding: 6px 10px; border-radius: 999px; border: 1px solid var(--border-light); background: rgba(255,255,255,0.03); color: var(--muted); font-size: 12px; line-height: 1; }}
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
            .dash-strip-card {{ display: flex; flex-direction: column; gap: 14px; min-height: 230px; }}
            .dash-strip-head {{ display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }}
            .dash-strip-summary {{ font-size: 12px; color: var(--muted); }}
            .dash-strip-wrap {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(18px, 1fr));
                align-items: end;
                gap: 8px;
                min-height: 150px;
                padding: 14px 12px 10px;
                border-radius: 14px;
                background:
                    linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.00)),
                    repeating-linear-gradient(
                        to top,
                        rgba(148,163,184,0.08) 0,
                        rgba(148,163,184,0.08) 1px,
                        transparent 1px,
                        transparent 24%
                    );
                border: 1px solid rgba(148,163,184,0.10);
            }}
            .dash-strip-col {{ display: flex; flex-direction: column; align-items: stretch; justify-content: flex-end; gap: 8px; min-width: 0; }}
            .dash-strip-bar {{ width: 100%; min-height: 14px; border-radius: 10px 10px 4px 4px; background: var(--info); box-shadow: 0 10px 24px rgba(15,23,42,0.32), inset 0 -1px 0 rgba(255,255,255,0.12); }}
            .dash-strip-label {{ font-size: 10px; color: var(--muted); line-height: 1; letter-spacing: 0.03em; text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
            .dash-strip-foot {{ display: flex; justify-content: space-between; gap: 12px; color: var(--muted); font-size: 11px; }}
            @media (max-width: 768px) {{
                .dash-shell {{ padding: 16px; }}
                .dash-grid.chart {{ grid-template-columns: 1fr; }}
                .dash-inst-stats {{ grid-template-columns: repeat(2, 1fr); }}
                .dash-strip-wrap {{ gap: 6px; padding-left: 8px; padding-right: 8px; }}
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


def page_shell(
    *,
    title: str,
    subtitle: str = "",
    badge: str = "",
    badge_tone: str = "accent",
    body: Iterable,
    chips: Iterable = (),
):
    tone_map = {
        "accent": (THEME["accent"], THEME["accent_soft"]),
        "warn": (THEME["warn"], THEME["warn_soft"]),
        "danger": (THEME["danger"], THEME["danger_soft"]),
        "info": (THEME["info"], THEME["info_soft"]),
    }
    ink, bg = tone_map.get(badge_tone, tone_map["accent"])
    title_children = [html.H1(title, className="dash-title")]
    if badge:
        title_children.append(
            html.Span(
                badge, className="dash-badge", style={"background": bg, "color": ink}
            )
        )
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
    return html.Div(text, className="dash-meta-chip")


def meta_row(items: Iterable[str]):
    chips = [chip(text) for text in items if str(text).strip()]
    if not chips:
        return None
    return html.Div(chips, className="dash-meta-row")


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


def status_bar_strip_card(
    *,
    title: str,
    bars: list[dict],
    summary: str = "",
    footer_left: str = "",
    footer_right: str = "",
):
    if not bars:
        bars = [{"label": "00:00", "height": 0.2, "color": THEME["border_light"]}]

    columns = []
    for item in bars[-24:]:
        height_ratio = max(0.12, min(1.0, float(item.get("height", 0.0))))
        columns.append(
            html.Div(
                [
                    html.Div(
                        className="dash-strip-bar",
                        style={
                            "height": f"{int(height_ratio * 100)}%",
                            "background": item.get("color", THEME["info"]),
                            "opacity": max(
                                0.45, min(1.0, float(item.get("opacity", 1.0)))
                            ),
                        },
                        title=str(item.get("title", item.get("label", ""))),
                    ),
                    html.Div(str(item.get("label", "")), className="dash-strip-label"),
                ],
                className="dash-strip-col",
            )
        )

    return html.Div(
        [
            html.Div(
                [
                    html.Div(title, className="dash-card-label"),
                    html.Div(summary, className="dash-strip-summary"),
                ],
                className="dash-strip-head",
            ),
            html.Div(columns, className="dash-strip-wrap"),
            html.Div(
                [
                    html.Span(footer_left or "", className="dash-strip-summary"),
                    html.Span(footer_right or "", className="dash-strip-summary"),
                ],
                className="dash-strip-foot",
            ),
        ],
        className="dash-card dash-strip-card",
    )


def instance_card(
    *, name: str, caption: str, healthy: bool, stats: list[tuple[str, str]]
):
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
                    html.Span(
                        "healthy" if healthy else "unhealthy",
                        className="dash-tag",
                        style=tag_style,
                    ),
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
        return html.Div(
            html.Div("No requests recorded yet", className="dash-empty"),
            className="dash-table-wrap",
        )

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
        cells.extend(
            [
                html.Td(
                    html.Span(
                        "OK" if success else "FAIL",
                        className="dash-tag",
                        style=tag_style,
                    )
                ),
                html.Td(format_ms(float(record.get("latency_ms", 0)))),
                html.Td(
                    record.get("error", "") or "\u2014",
                    style={"color": THEME["muted"], "fontSize": "12px"},
                ),
            ]
        )
        rows.append(html.Tr(cells))

    return html.Div(
        html.Table(
            [html.Thead(html.Tr([html.Th(h) for h in headers])), html.Tbody(rows)],
            className="dash-table",
        ),
        className="dash-table-wrap",
    )


def format_ms(value: float) -> str:
    if value <= 0:
        return "0 ms"
    if value >= 1000:
        return f"{value / 1000:.2f} s"
    return f"{value:.0f} ms"


def format_rate(value: float) -> str:
    return f"{value:.1f}%"
