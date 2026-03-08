from __future__ import annotations

from collections.abc import Callable

from a2wsgi import WSGIMiddleware
from dash import Input, Output, State, callback_context, dcc, html

from webu.fastapis.dashboard_ui import (
    create_dash_app,
    mask_private_value,
    page_shell,
    privacy_gate_card,
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


def _panel_ids(prefix: str) -> dict[str, str]:
    return {
        "auth_state": f"{prefix}-auth-state",
        "auth_token": f"{prefix}-auth-token",
        "auth_submit": f"{prefix}-auth-submit",
        "page_state": f"{prefix}-history-page-state",
        "page_size_state": f"{prefix}-history-page-size-state",
        "page": f"{prefix}-history-page",
        "page_size": f"{prefix}-history-page-size",
        "page_prev": f"{prefix}-history-prev",
        "page_next": f"{prefix}-history-next",
        "refresh": f"{prefix}-refresh",
        "root": f"{prefix}-root",
    }


def _build_body(
    snapshot: dict,
    *,
    auth_unlocked: bool,
    auth_message: str,
    admin_token_configured: bool,
    page: int,
    page_size: int,
):
    requests = snapshot.get("requests", {})
    service = snapshot.get("service", {})
    node = dict(snapshot.get("node", {}))
    request_log = list(requests.get("request_log", []))

    node["value"] = mask_private_value(
        str(node.get("label", "")),
        str(node.get("value", "unknown")),
        auth_unlocked,
    )

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
            section(
                "Access",
                [
                    privacy_gate_card(
                        component_prefix="google-api-panel",
                        unlocked=auth_unlocked,
                        message=auth_message,
                        token_configured=admin_token_configured,
                    )
                ],
                kind="chart",
            ),
            section("Trends", build_request_trend_cards(requests), kind="chart"),
        ]
    )
    if auth_unlocked or not admin_token_configured:
        body.append(
            section(
                "Request history",
                [
                    request_table(
                        request_log,
                        page=page,
                        page_size=page_size,
                        component_prefix="google-api-panel",
                    )
                ],
                kind="chart",
            )
        )

    return page_shell(
        title="GOOGLE INSTANCE",
        subtitle=subtitle,
        badge=status_label.upper(),
        badge_tone=badge_tone,
        body=body,
    )


def mount_google_api_panel(
    app,
    snapshot_provider: SnapshotProvider,
    *,
    admin_token: str = "",
):
    ids = _panel_ids("google-api-panel")
    dash_app = create_dash_app(
        name=__name__,
        title="Google Instance Panel",
        panel_path=DEFAULT_GOOGLE_API_PANEL_PATH,
    )
    dash_app.layout = html.Div(
        [
            dcc.Interval(
                id=ids["refresh"],
                interval=DEFAULT_GOOGLE_API_PANEL_REFRESH_MS,
                n_intervals=0,
            ),
            dcc.Store(
                id=ids["auth_state"],
                storage_type="session",
                data={"unlocked": False, "message": ""},
            ),
            dcc.Store(id=ids["page_state"], storage_type="session", data=1),
            dcc.Store(id=ids["page_size_state"], storage_type="session", data=10),
            html.Div(id=ids["root"]),
        ]
    )

    @dash_app.callback(
        Output(ids["auth_state"], "data"),
        Input(ids["auth_submit"], "n_clicks"),
        State(ids["auth_token"], "value"),
        State(ids["auth_state"], "data"),
    )
    def unlock_panel(
        n_clicks: int, entered_token: str | None, current_state: dict | None
    ):
        state = dict(current_state or {"unlocked": False, "message": ""})
        if not admin_token:
            return {"unlocked": True, "message": ""}
        if not n_clicks:
            return state
        if str(entered_token or "").strip() == admin_token:
            return {"unlocked": True, "message": ""}
        return {"unlocked": False, "message": "Invalid admin token"}

    @dash_app.callback(
        Output(ids["page_state"], "data"),
        Output(ids["page_size_state"], "data"),
        Input(ids["page_prev"], "n_clicks"),
        Input(ids["page_next"], "n_clicks"),
        Input(ids["page"], "value"),
        Input(ids["page_size"], "value"),
        Input(ids["refresh"], "n_intervals"),
        State(ids["page_state"], "data"),
        State(ids["page_size_state"], "data"),
    )
    def update_page(
        prev_clicks: int,
        next_clicks: int,
        entered_page: int | None,
        page_size: int,
        _n_intervals: int,
        current_page: int | None,
        current_page_size: int | None,
    ):
        del prev_clicks, next_clicks
        request_log = list(
            snapshot_provider().get("requests", {}).get("request_log", [])
        )
        resolved_page_size = max(1, int(page_size or current_page_size or 10))
        total_pages = max(
            1, (len(request_log) + resolved_page_size - 1) // resolved_page_size
        )
        page = max(1, min(int(current_page or 1), total_pages))
        trigger = (
            callback_context.triggered[0]["prop_id"].split(".")[0]
            if callback_context.triggered
            else ""
        )
        if trigger == ids["page_prev"]:
            return max(1, page - 1), resolved_page_size
        if trigger == ids["page_next"]:
            return min(total_pages, page + 1), resolved_page_size
        if trigger == ids["page"]:
            return max(1, min(int(entered_page or 1), total_pages)), resolved_page_size
        return page, resolved_page_size

    @dash_app.callback(
        Output(ids["root"], "children"),
        Input(ids["refresh"], "n_intervals"),
        Input(ids["auth_state"], "data"),
        Input(ids["page_state"], "data"),
        Input(ids["page_size_state"], "data"),
    )
    def refresh_panel(
        _n_intervals: int,
        auth_state: dict | None,
        page: int | None,
        page_size: int | None,
    ):
        state = dict(auth_state or {})
        return _build_body(
            snapshot_provider(),
            auth_unlocked=bool(state.get("unlocked")) or not bool(admin_token),
            auth_message=str(state.get("message", "")).strip(),
            admin_token_configured=bool(admin_token),
            page=max(1, int(page or 1)),
            page_size=max(1, int(page_size or 10)),
        )

    app.mount(DEFAULT_GOOGLE_API_PANEL_PATH, WSGIMiddleware(dash_app.server))
