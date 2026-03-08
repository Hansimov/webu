from __future__ import annotations

from typing import Iterable

from dash import Dash, dcc, html


SHARED_ACCESS_STATE_ID = "webu-panel-access-state"
SHARED_ACCESS_COOKIE = "webu_panel_access_state"


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
        <script>
            (function () {{
                const accessKey = {SHARED_ACCESS_STATE_ID!r};
                const cookieKey = {SHARED_ACCESS_COOKIE!r};
                function readCookie() {{
                    const prefix = cookieKey + "=";
                    const parts = document.cookie ? document.cookie.split("; ") : [];
                    for (const part of parts) {{
                        if (part.startsWith(prefix)) {{
                            return decodeURIComponent(part.slice(prefix.length));
                        }}
                    }}
                    return "";
                }}
                function canShareAcrossSpaces() {{
                    return window.location.protocol === "https:" && window.location.hostname.endsWith(".hf.space");
                }}
                function writeCookie(value) {{
                    if (!canShareAcrossSpaces() || !value) {{
                        return;
                    }}
                    document.cookie =
                        cookieKey +
                        "=" +
                        encodeURIComponent(value) +
                        "; path=/; domain=.hf.space; max-age=2592000; SameSite=Lax; Secure";
                }}
                try {{
                    const localValue = window.localStorage.getItem(accessKey) || "";
                    const cookieValue = readCookie();
                    if (cookieValue && cookieValue !== localValue) {{
                        window.localStorage.setItem(accessKey, cookieValue);
                    }} else if (!cookieValue && localValue) {{
                        writeCookie(localValue);
                    }}
                    window.__webuAccessBridge = {{
                        accessKey,
                        cookieKey,
                        readCookie,
                        writeCookie,
                        canShareAcrossSpaces,
                    }};
                }} catch (_err) {{}}
            }})();
        </script>
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
            .dash-shell {{ max-width: 1200px; margin: 0 auto; padding: 28px 24px; overflow-x: clip; }}
            .dash-header {{ margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border-light); }}
            .dash-title-row {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
            .dash-title {{ font-size: 24px; font-weight: 700; letter-spacing: -0.01em; line-height: 1.2; }}
            .dash-badge {{ display: inline-block; padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }}
            .dash-subtitle {{ margin-top: 8px; font-size: 13px; color: var(--muted); line-height: 1.5; }}
            .dash-grid {{ display: grid; gap: 14px; }}
            .dash-grid > * {{ min-width: 0; }}
            .dash-grid.metric {{ grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }}
            .dash-grid.chart {{ grid-template-columns: repeat(2, 1fr); }}
            .dash-grid.instance {{ grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }}
            .dash-card {{
                min-width: 0;
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
            .dash-controls {{ display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }}
            .dash-controls-group {{ display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }}
            .dash-controls-label {{ font-size: 11px; color: var(--muted); letter-spacing: 0.05em; text-transform: uppercase; font-weight: 600; }}
            .dash-page-size .dash-radioitems {{ display: flex; flex-wrap: wrap; gap: 6px; }}
            .dash-page-size label {{ display: inline-flex; align-items: center; gap: 6px; margin: 0; padding: 6px 10px; border-radius: 999px; border: 1px solid var(--border-light); background: rgba(255,255,255,0.03); color: var(--muted); font-size: 12px; cursor: pointer; }}
            .dash-page-size input {{ margin: 0; accent-color: var(--accent); }}
            .dash-page-input {{ width: 72px; padding: 7px 9px; border-radius: 10px; border: 1px solid var(--border-light); background: rgba(15,23,42,0.72); color: var(--text); font-size: 13px; }}
            .dash-button {{ padding: 7px 12px; border-radius: 10px; border: 1px solid var(--border-light); background: rgba(255,255,255,0.03); color: var(--text); font-size: 12px; font-weight: 600; cursor: pointer; }}
            .dash-button:hover {{ border-color: rgba(52,211,153,0.45); background: rgba(52,211,153,0.08); }}
            .dash-button:disabled {{ opacity: 0.45; cursor: default; }}
            .dash-auth-card {{ display: flex; flex-direction: column; gap: 14px; }}
            .dash-auth-form {{ display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }}
            .dash-auth-input {{ flex: 1 1 240px; min-width: 200px; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--border-light); background: rgba(15,23,42,0.72); color: var(--text); font-size: 13px; }}
            .dash-auth-note {{ font-size: 12px; color: var(--muted); line-height: 1.5; }}
            .dash-auth-status {{ font-size: 12px; color: var(--muted); }}
            .dash-auth-status.ok {{ color: var(--accent); }}
            .dash-auth-status.fail {{ color: var(--danger); }}
            .dash-access-fab {{
                position: fixed;
                right: 24px;
                bottom: 24px;
                z-index: 1200;
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 11px 14px;
                border-radius: 999px;
                border: 1px solid var(--border-light);
                background: rgba(15,23,42,0.88);
                color: var(--text);
                box-shadow: 0 16px 32px rgba(2,6,23,0.38);
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 0.04em;
                text-transform: uppercase;
                cursor: pointer;
                backdrop-filter: blur(12px);
            }}
            .dash-access-fab:hover {{ border-color: rgba(96,165,250,0.42); background: rgba(15,23,42,0.96); }}
            .dash-access-fab-state {{ width: 9px; height: 9px; border-radius: 999px; }}
            .dash-access-overlay {{
                position: fixed;
                inset: 0;
                z-index: 1250;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 24px;
                background: rgba(2,6,23,0.56);
                backdrop-filter: blur(10px);
            }}
            .dash-access-modal {{
                width: min(440px, 100%);
                padding: 18px;
                border-radius: 20px;
                border: 1px solid rgba(148,163,184,0.18);
                background: linear-gradient(180deg, rgba(15,23,42,0.98), rgba(15,23,42,0.92));
                box-shadow: 0 30px 60px rgba(2,6,23,0.48);
            }}
            .dash-access-head {{ display: flex; align-items: start; justify-content: space-between; gap: 14px; }}
            .dash-access-title {{ font-size: 18px; font-weight: 700; letter-spacing: -0.01em; }}
            .dash-access-kicker {{ margin-top: 6px; font-size: 11px; color: var(--muted); letter-spacing: 0.08em; text-transform: uppercase; font-weight: 700; }}
            .dash-access-close {{
                padding: 7px 10px;
                border-radius: 999px;
                border: 1px solid var(--border-light);
                background: rgba(255,255,255,0.03);
                color: var(--muted);
                font-size: 12px;
                font-weight: 700;
                cursor: pointer;
            }}
            .dash-access-copy {{ margin-top: 14px; color: var(--muted); font-size: 13px; line-height: 1.6; }}
            .dash-access-points {{ margin-top: 14px; display: grid; gap: 10px; }}
            .dash-access-point {{ padding: 10px 12px; border-radius: 14px; border: 1px solid rgba(148,163,184,0.14); background: rgba(255,255,255,0.03); }}
            .dash-access-point-title {{ font-size: 11px; color: var(--muted); letter-spacing: 0.08em; text-transform: uppercase; font-weight: 700; }}
            .dash-access-point-copy {{ margin-top: 5px; font-size: 13px; line-height: 1.5; color: var(--text); }}
            .dash-access-actions {{ margin-top: 16px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }}
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
            .dash-table-wrap {{ width: 100%; overflow-x: auto; overflow-y: hidden; border-radius: 12px; border: 1px solid var(--border); background: var(--surface); }}
            .dash-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
            .dash-table th {{ position: sticky; top: 0; z-index: 1; background: var(--surface-alt); color: var(--muted); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border-light); }}
            .dash-table td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); color: var(--text); white-space: nowrap; }}
            .dash-table tr:last-child td {{ border-bottom: none; }}
            .dash-table tr:hover td {{ background: rgba(255,255,255,0.02); }}
            .dash-table .col-query {{ max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
            .dash-table .col-result {{ min-width: 280px; max-width: 420px; white-space: normal; }}
            .dash-empty {{ padding: 24px; text-align: center; color: var(--muted); font-size: 13px; }}
            .dash-strip-card {{ display: flex; flex-direction: column; gap: 14px; min-height: 230px; min-width: 0; overflow: hidden; }}
            .dash-strip-head {{ display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }}
            .dash-strip-summary {{ font-size: 12px; color: var(--muted); }}
            .dash-strip-scroll {{ width: 100%; max-width: 100%; overflow-x: auto; overflow-y: hidden; cursor: grab; padding-bottom: 4px; scrollbar-width: thin; }}
            .dash-strip-scroll.is-dragging {{ cursor: grabbing; }}
            .dash-strip-wrap {{
                display: flex;
                align-items: end;
                gap: 8px;
                min-height: 150px;
                min-width: max-content;
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
                .dash-strip-col {{ display: flex; flex: 0 0 32px; flex-direction: column; align-items: stretch; justify-content: flex-end; gap: 8px; min-width: 32px; }}
                .dash-strip-bar-slot {{ display: flex; align-items: end; height: 132px; }}
                .dash-strip-bar {{ width: 100%; min-height: 14px; border-radius: 10px 10px 4px 4px; background: var(--info); box-shadow: 0 10px 24px rgba(15,23,42,0.32), inset 0 -1px 0 rgba(255,255,255,0.12); }}
            .dash-strip-label {{ font-size: 10px; color: var(--muted); line-height: 1; letter-spacing: 0.03em; text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
            .dash-strip-foot {{ display: flex; justify-content: space-between; gap: 12px; color: var(--muted); font-size: 11px; }}
                .dash-result-toggle {{ border: 1px solid var(--border-light); border-radius: 10px; background: rgba(255,255,255,0.02); overflow: hidden; }}
                .dash-result-summary {{ list-style: none; cursor: pointer; padding: 8px 10px; color: var(--text); font-size: 12px; line-height: 1.45; }}
                .dash-result-summary::-webkit-details-marker {{ display: none; }}
                .dash-result-detail {{ margin: 0; padding: 10px; border-top: 1px solid var(--border); background: rgba(15,23,42,0.45); color: var(--muted); font-size: 11px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; max-height: 240px; overflow: auto; }}
            @media (max-width: 768px) {{
                .dash-shell {{ padding: 16px; }}
                .dash-grid.chart {{ grid-template-columns: 1fr; }}
                .dash-access-overlay {{ padding: 16px; align-items: end; }}
                .dash-access-modal {{ width: 100%; }}
                .dash-access-fab {{ right: 16px; bottom: 16px; }}
                .dash-controls {{ align-items: stretch; }}
                .dash-controls-group {{ width: 100%; }}
                .dash-auth-form {{ align-items: stretch; }}
                .dash-auth-input {{ width: 100%; }}
                .dash-inst-stats {{ grid-template-columns: repeat(2, 1fr); }}
                .dash-strip-wrap {{ gap: 6px; padding-left: 8px; padding-right: 8px; }}
                    .dash-table .col-result {{ min-width: 240px; max-width: 320px; }}
            }}
        </style>
    </head>
    <body>
        {{%app_entry%}}
        <footer>
            {{%config%}}
            {{%scripts%}}
            {{%renderer%}}
            <script>
                function formatWebuUptime(startedTs) {{
                    const startedMs = Number(startedTs || 0) * 1000;
                    if (!startedMs || Number.isNaN(startedMs)) {{
                        return "0s";
                    }}
                    const elapsedSec = Math.max(0, Math.floor((Date.now() - startedMs) / 1000));
                    const days = Math.floor(elapsedSec / 86400);
                    const hours = Math.floor((elapsedSec % 86400) / 3600);
                    const minutes = Math.floor((elapsedSec % 3600) / 60);
                    const seconds = elapsedSec % 60;
                    const parts = [];
                    if (days) parts.push(days + "d");
                    if (hours || parts.length) parts.push(hours + "h");
                    if (minutes || parts.length) parts.push(minutes + "m");
                    parts.push(seconds + "s");
                    return parts.join(" ");
                }}
                function formatWebuShanghaiNow() {{
                    try {{
                        const dtf = new Intl.DateTimeFormat("sv-SE", {{
                            timeZone: "Asia/Shanghai",
                            hour12: false,
                            year: "numeric",
                            month: "2-digit",
                            day: "2-digit",
                            hour: "2-digit",
                            minute: "2-digit",
                            second: "2-digit",
                        }});
                        return dtf.format(new Date()).replace("T", " ");
                    }} catch (_err) {{
                        return new Date().toISOString().slice(0, 19).replace("T", " ");
                    }}
                }}
                function refreshWebuLiveUptime() {{
                    document.querySelectorAll("[data-uptime-value='1']").forEach(function (node) {{
                        node.textContent = formatWebuUptime(node.dataset.uptimeStartedTs || "0");
                    }});
                    document.querySelectorAll("[data-uptime-note='1']").forEach(function (node) {{
                        node.textContent = formatWebuShanghaiNow();
                    }});
                }}
                document.addEventListener("DOMContentLoaded", function () {{
                    let lastSharedAccessState = null;
                    window.setInterval(function () {{
                        try {{
                            const bridge = window.__webuAccessBridge;
                            if (!bridge) {{
                                return;
                            }}
                            const current = window.localStorage.getItem(bridge.accessKey) || "";
                            if (current && current !== lastSharedAccessState) {{
                                bridge.writeCookie(current);
                                lastSharedAccessState = current;
                            }}
                        }} catch (_err) {{}}
                    }}, 1000);
                    refreshWebuLiveUptime();
                    window.setInterval(refreshWebuLiveUptime, 1000);
                    document.querySelectorAll(".dash-strip-scroll").forEach(function (node) {{
                        let dragging = false;
                        let startX = 0;
                        let startScroll = 0;
                        node.addEventListener("pointerdown", function (event) {{
                            dragging = true;
                            startX = event.clientX;
                            startScroll = node.scrollLeft;
                            node.classList.add("is-dragging");
                            node.setPointerCapture(event.pointerId);
                        }});
                        node.addEventListener("pointermove", function (event) {{
                            if (!dragging) return;
                            node.scrollLeft = startScroll - (event.clientX - startX);
                        }});
                        function stopDrag(event) {{
                            if (!dragging) return;
                            dragging = false;
                            node.classList.remove("is-dragging");
                            if (event && event.pointerId !== undefined) {{
                                try {{ node.releasePointerCapture(event.pointerId); }} catch (_err) {{}}
                            }}
                        }}
                        node.addEventListener("pointerup", stopDrag);
                        node.addEventListener("pointercancel", stopDrag);
                        node.addEventListener("pointerleave", stopDrag);
                    }});
                }});
            </script>
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
    return metric_card_with_meta(label, value, note, tone)


def metric_card_with_meta(
    label: str,
    value: str,
    note: str = "",
    tone: str = "accent",
    *,
    value_props: dict | None = None,
    note_props: dict | None = None,
):
    color = THEME.get(tone, THEME["accent"])
    children = [
        html.Div(label, className="dash-card-label"),
        html.Div(
            value,
            className="dash-card-value",
            style={"color": color},
            **(value_props or {}),
        ),
    ]
    if note:
        children.append(
            html.Div(note, className="dash-card-note", **(note_props or {}))
        )
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
    for item in bars:
        height_ratio = max(0.12, min(1.0, float(item.get("height", 0.0))))
        columns.append(
            html.Div(
                [
                    html.Div(
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
                        className="dash-strip-bar-slot",
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
            html.Div(
                html.Div(columns, className="dash-strip-wrap"),
                className="dash-strip-scroll",
            ),
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
    *,
    name: str,
    caption: str,
    healthy: bool,
    stats: list[tuple[str, str]],
    status_label: str | None = None,
    status_tone: str | None = None,
    note: str = "",
    style: dict | None = None,
):
    tone = status_tone or ("accent" if healthy else "danger")
    soft_map = {
        "accent": THEME["accent_soft"],
        "warn": THEME["warn_soft"],
        "danger": THEME["danger_soft"],
        "info": THEME["info_soft"],
        "neutral": "rgba(148,163,184,0.12)",
    }
    color_map = {
        "accent": THEME["accent"],
        "warn": THEME["warn"],
        "danger": THEME["danger"],
        "info": THEME["info"],
        "neutral": THEME["muted"],
    }
    border_map = {
        "accent": "rgba(52,211,153,0.32)",
        "warn": "rgba(251,191,36,0.28)",
        "danger": "rgba(248,113,113,0.30)",
        "info": "rgba(96,165,250,0.28)",
        "neutral": "rgba(148,163,184,0.22)",
    }
    glow_map = {
        "accent": "0 14px 28px rgba(16,185,129,0.10)",
        "warn": "0 14px 28px rgba(245,158,11,0.10)",
        "danger": "0 14px 28px rgba(239,68,68,0.12)",
        "info": "0 14px 28px rgba(59,130,246,0.10)",
        "neutral": "0 14px 28px rgba(15,23,42,0.22)",
    }
    tag_style = {
        "background": soft_map.get(tone, THEME["accent_soft"]),
        "color": color_map.get(tone, THEME["accent"]),
    }
    card_style = {
        "border": f"1px solid {border_map.get(tone, THEME['border'])}",
        "background": (
            f"linear-gradient(180deg, {soft_map.get(tone, THEME['accent_soft'])}, rgba(15,23,42,0.94))"
        ),
        "boxShadow": glow_map.get(tone, glow_map["accent"]),
    }
    if style:
        card_style.update(style)
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
                        status_label or ("healthy" if healthy else "unhealthy"),
                        className="dash-tag",
                        style=tag_style,
                    ),
                ],
                className="dash-inst-hd",
            ),
            html.Div(caption, className="dash-inst-meta"),
            html.Div(stat_items, className="dash-inst-stats"),
            html.Div(note, className="dash-inst-meta") if note else None,
        ],
        className="dash-inst",
        style=card_style,
    )


def _request_result_cell(record: dict):
    preview = str(record.get("result_preview", "")).strip()
    detail = str(record.get("result_detail", "")).strip()
    if not preview and not detail:
        return html.Td("\u2014", className="col-result")

    summary_text = preview or "View response"
    children = [html.Summary(summary_text, className="dash-result-summary")]
    if detail:
        children.append(html.Pre(detail, className="dash-result-detail"))
    return html.Td(
        html.Details(children, className="dash-result-toggle"), className="col-result"
    )


def mask_private_value(label: str, value: str, unlocked: bool) -> str:
    if unlocked:
        return value
    if str(label).strip().lower() != "server ip":
        return value
    return "**.**.**.**"


def privacy_gate_card(
    *,
    component_prefix: str,
    unlocked: bool,
    message: str = "",
    token_configured: bool = True,
) -> html.Div:
    status_class = "dash-auth-status"
    if unlocked:
        status_text = "Admin access unlocked for this browser session."
        status_class += " ok"
    elif message:
        status_text = message
        status_class += " fail"
    elif token_configured:
        status_text = "Server IP and request history stay hidden until a valid admin token is entered."
    else:
        status_text = (
            "No admin token configured. Private sections are already available."
        )

    controls = []
    if token_configured:
        controls.append(
            html.Div(
                [
                    dcc.Input(
                        id=f"{component_prefix}-auth-token",
                        type="password",
                        placeholder="Enter admin token",
                        className="dash-auth-input",
                    ),
                    html.Button(
                        "Unlock",
                        id=f"{component_prefix}-auth-submit",
                        n_clicks=0,
                        className="dash-button",
                    ),
                ],
                className="dash-auth-form",
            )
        )

    return html.Div(
        [
            html.Div("Access", className="dash-card-label"),
            html.Div(
                "Use the same admin token as the management APIs. The unlock only applies to the current browser session.",
                className="dash-auth-note",
            ),
            *controls,
            html.Div(status_text, className=status_class),
        ],
        className="dash-card dash-auth-card",
    )


def privacy_gate_popup(
    *,
    component_prefix: str,
    unlocked: bool,
    open_modal: bool,
    message: str = "",
    token_configured: bool = True,
):
    dot_color = (
        THEME["accent"]
        if unlocked or not token_configured
        else (THEME["danger"] if message else THEME["warn"])
    )
    fab_label = (
        "Access open"
        if not token_configured
        else ("Access unlocked" if unlocked else "Unlock access")
    )
    launcher = html.Button(
        [
            html.Span(
                className="dash-access-fab-state",
                style={"background": dot_color},
            ),
            html.Span(fab_label),
        ],
        id=f"{component_prefix}-access-open",
        n_clicks=0,
        className="dash-access-fab",
        title="Open access controls",
    )

    status_class = "dash-auth-status"
    if unlocked or not token_configured:
        status_text = "Private sections are available in this browser."
        status_class += " ok"
    elif message:
        status_text = message
        status_class += " fail"
    else:
        status_text = "Server IP and request history stay hidden until a valid admin token is entered."

    controls = html.Div(
        [
            dcc.Input(
                id=f"{component_prefix}-auth-token",
                type="password",
                placeholder="Enter admin token",
                className="dash-auth-input",
            ),
            html.Button(
                "Unlock",
                id=f"{component_prefix}-auth-submit",
                n_clicks=0,
                className="dash-button",
                disabled=not token_configured,
                style=None if token_configured else {"display": "none"},
            ),
        ],
        className="dash-auth-form",
        style=None if token_configured else {"display": "none"},
    )

    overlay = html.Div(
        html.Div(
            [
                html.Div(
                    [
                        html.Div(
                            [
                                html.Div("Panel access", className="dash-access-title"),
                                html.Div("Hints", className="dash-access-kicker"),
                            ]
                        ),
                        html.Button(
                            "Hide",
                            id=f"{component_prefix}-access-close",
                            n_clicks=0,
                            className="dash-access-close",
                        ),
                    ],
                    className="dash-access-head",
                ),
                html.Div(
                    "Unlock is now a popup so the dashboard itself stays focused. You can reopen it any time from the floating button.",
                    className="dash-access-copy",
                ),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Div(
                                    "Protected areas",
                                    className="dash-access-point-title",
                                ),
                                html.Div(
                                    "Server IP and request history remain hidden until access is unlocked.",
                                    className="dash-access-point-copy",
                                ),
                            ],
                            className="dash-access-point",
                        ),
                        html.Div(
                            [
                                html.Div(
                                    "Browser memory",
                                    className="dash-access-point-title",
                                ),
                                html.Div(
                                    "This browser remembers the state for later visits. On Hugging Face Spaces it is also mirrored across hf.space subdomains.",
                                    className="dash-access-point-copy",
                                ),
                            ],
                            className="dash-access-point",
                        ),
                    ],
                    className="dash-access-points",
                ),
                html.Div(status_text, className=status_class),
                html.Div(controls, className="dash-access-actions"),
            ],
            className="dash-access-modal",
        ),
        className="dash-access-overlay",
        style=None if open_modal else {"display": "none"},
    )

    return html.Div([launcher, overlay])


def request_table(
    records: list[dict],
    show_backend: bool = False,
    *,
    page: int = 1,
    page_size: int = 10,
    component_prefix: str = "",
) -> html.Div:
    if not records:
        return html.Div(
            html.Div("No requests recorded yet", className="dash-empty"),
            className="dash-table-wrap",
        )

    page_size = max(1, int(page_size or 10))
    total_records = len(records)
    total_pages = max(1, (total_records + page_size - 1) // page_size)
    page = max(1, min(int(page or 1), total_pages))

    ordered_records = list(reversed(records))
    start = (page - 1) * page_size
    end = start + page_size
    current_records = ordered_records[start:end]

    headers = ["Time", "Query", "Status", "Latency", "Top result"]
    if show_backend:
        headers.insert(2, "Instance")
    headers.append("Error")

    rows = []
    for record in current_records:
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
                _request_result_cell(record),
                html.Td(
                    record.get("error", "") or "\u2014",
                    style={"color": THEME["muted"], "fontSize": "12px"},
                ),
            ]
        )
        rows.append(html.Tr(cells))

    controls = None
    if component_prefix:
        controls = (
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("Items per page", className="dash-controls-label"),
                            dcc.RadioItems(
                                id=f"{component_prefix}-history-page-size",
                                options=[
                                    {"label": str(value), "value": value}
                                    for value in [5, 10, 20, 50, 100]
                                ],
                                value=page_size,
                                inline=True,
                                className="dash-radioitems",
                                inputClassName="dash-radioinput",
                                labelClassName="dash-radiolabel",
                            ),
                        ],
                        className="dash-controls-group dash-page-size",
                    ),
                    html.Div(
                        [
                            html.Button(
                                "Previous",
                                id=f"{component_prefix}-history-prev",
                                n_clicks=0,
                                className="dash-button",
                                disabled=page <= 1,
                            ),
                            html.Button(
                                "Next",
                                id=f"{component_prefix}-history-next",
                                n_clicks=0,
                                className="dash-button",
                                disabled=page >= total_pages,
                            ),
                            html.Div("Page", className="dash-controls-label"),
                            dcc.Input(
                                id=f"{component_prefix}-history-page",
                                type="number",
                                min=1,
                                max=total_pages,
                                step=1,
                                value=page,
                                className="dash-page-input",
                            ),
                            html.Div(
                                f"of {total_pages} · {total_records} items",
                                className="dash-auth-status",
                            ),
                        ],
                        className="dash-controls-group",
                    ),
                ],
                className="dash-controls",
            ),
        )

    return html.Div(
        [
            controls,
            html.Div(
                html.Table(
                    [
                        html.Thead(html.Tr([html.Th(h) for h in headers])),
                        html.Tbody(rows),
                    ],
                    className="dash-table",
                ),
                className="dash-table-wrap",
            ),
        ]
    )


def format_ms(value: float) -> str:
    if value <= 0:
        return "0 ms"
    if value >= 1000:
        return f"{value / 1000:.2f} s"
    return f"{value:.0f} ms"


def format_rate(value: float) -> str:
    return f"{value:.1f}%"
