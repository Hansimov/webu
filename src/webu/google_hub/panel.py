from __future__ import annotations

from collections.abc import Callable
import os

from urllib.parse import urlsplit

from a2wsgi import WSGIMiddleware
from dash import Input, Output, State, callback_context, dcc, html
from dash.exceptions import PreventUpdate

from webu.fastapis.dashboard_ui import (
    SHARED_ACCESS_STATE_ID,
    create_dash_app,
    meta_row,
    mask_private_value,
    page_shell,
    privacy_gate_popup,
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
    resolve_google_docker_settings,
)

from .manager import sanitize_hub_search_error


SnapshotProvider = Callable[[], dict]
SearchProvider = Callable[[str, int, str, str], dict]


def _accepted_admin_tokens(admin_token: str) -> set[str]:
    docker_admin_token = ""
    try:
        docker_admin_token = str(resolve_google_docker_settings().admin_token).strip()
    except Exception:
        docker_admin_token = ""
    candidates = {
        str(admin_token or "").strip(),
        docker_admin_token,
        str(os.getenv("WEBU_HUB_ADMIN_TOKEN", "")).strip(),
        str(os.getenv("WEBU_ADMIN_TOKEN", "")).strip(),
    }
    return {token for token in candidates if token}


def _panel_ids(prefix: str) -> dict[str, str]:
    return {
        "access_state": SHARED_ACCESS_STATE_ID,
        "access_message": f"{prefix}-access-message",
        "access_modal": f"{prefix}-access-modal",
        "access_open": f"{prefix}-access-open",
        "access_close": f"{prefix}-access-close",
        "auth_token": f"{prefix}-auth-token",
        "auth_submit": f"{prefix}-auth-submit",
        "page_state": f"{prefix}-history-page-state",
        "page_size_state": f"{prefix}-history-page-size-state",
        "page": f"{prefix}-history-page",
        "page_size": f"{prefix}-history-page-size",
        "page_prev": f"{prefix}-history-prev",
        "page_next": f"{prefix}-history-next",
        "refresh": f"{prefix}-refresh",
        "search_state": f"{prefix}-search-state",
        "search_query": f"{prefix}-search-query",
        "search_backend": f"{prefix}-search-backend",
        "search_submit": f"{prefix}-search-submit",
        "root": f"{prefix}-root",
    }


def _search_route_options(snapshot: dict) -> list[dict[str, str]]:
    options = [{"label": "Auto select best healthy instance", "value": ""}]
    healthy_backends = sorted(
        [
            item
            for item in list(snapshot.get("backends", []))
            if bool(item.get("enabled", True)) and bool(item.get("healthy", False))
        ],
        key=lambda item: str(item.get("name", "")),
    )
    for item in healthy_backends:
        parsed = urlsplit(str(item.get("base_url", "")).strip())
        route_suffix = ""
        if parsed.hostname:
            route_suffix = f" · {parsed.hostname}"
            if parsed.port:
                route_suffix = f"{route_suffix}:{parsed.port}"
        options.append(
            {
                "label": f"{item.get('name', 'instance')}{route_suffix}",
                "value": str(item.get("name", "")).strip(),
            }
        )
    return options


def _build_search_card(ids: dict[str, str], snapshot: dict, search_state: dict):
    route_options = _search_route_options(snapshot)
    route_values = {item["value"] for item in route_options}
    query_value = str(search_state.get("query", ""))
    selected_backend = str(search_state.get("backend", "")).strip()
    if selected_backend not in route_values:
        selected_backend = ""

    status = str(search_state.get("status", "idle")).strip().lower() or "idle"
    error_text = sanitize_hub_search_error(str(search_state.get("error", "")).strip())
    result_payload = dict(search_state.get("result", {}) or {})
    result_query = str(
        result_payload.get("query", search_state.get("query", ""))
    ).strip()
    selected_backend_name = str(result_payload.get("backend", "")).strip()
    selection_mode = str(result_payload.get("selection_mode", "auto")).strip() or "auto"

    status_class = "dash-search-status"
    status_text = (
        "Search any query and let the hub route it to the best healthy instance."
    )
    if status == "ok":
        status_class += " ok"
        status_text = (
            f"Resolved via {selected_backend_name or 'hub routing'}"
            f" · {result_payload.get('result_count', 0)} results"
        )
    elif status == "error" and error_text:
        status_class += " fail"
        status_text = error_text

    result_children = [
        html.Div(
            "Search results will appear here. Use auto routing or pin a specific healthy instance.",
            className="dash-search-empty",
        )
    ]
    if status == "ok":
        chips = [
            f"Query {result_query or query_value}",
            f"Mode {selection_mode}",
            f"Instance {selected_backend_name or 'unknown'}",
            f"Results {result_payload.get('result_count', 0)}",
        ]
        total_results_text = str(result_payload.get("total_results_text", "")).strip()
        if total_results_text:
            chips.append(total_results_text)
        if bool(result_payload.get("has_captcha", False)):
            chips.append("Captcha detected")
        result_items = []
        for index, item in enumerate(list(result_payload.get("results", [])), start=1):
            title = str(item.get("title", "")).strip() or f"Result {index}"
            url = str(item.get("url", "")).strip()
            displayed_url = str(item.get("displayed_url", "")).strip() or url
            snippet = str(item.get("snippet", "")).strip()
            position = int(item.get("position", index) or index)
            result_type = str(item.get("result_type", "organic")).strip() or "organic"
            result_items.append(
                html.Div(
                    [
                        meta_row([f"#{position}", result_type]),
                        (
                            html.A(
                                title,
                                href=url or displayed_url or None,
                                target="_blank",
                                rel="noreferrer noopener",
                                className="dash-search-result-title",
                            )
                            if (url or displayed_url)
                            else html.Div(title, className="dash-search-result-title")
                        ),
                        (
                            html.A(
                                displayed_url,
                                href=url or displayed_url,
                                target="_blank",
                                rel="noreferrer noopener",
                                className="dash-search-result-link",
                            )
                            if (url or displayed_url)
                            else None
                        ),
                        (
                            html.Div(snippet, className="dash-search-result-snippet")
                            if snippet
                            else None
                        ),
                    ],
                    className="dash-search-result",
                )
            )
        result_children = [
            meta_row(chips),
            html.Div(
                result_items
                or [
                    html.Div(
                        "No organic results returned", className="dash-search-empty"
                    )
                ],
                className="dash-search-results",
            ),
        ]

    return html.Div(
        [
            html.Div(
                "Use auto routing for the best healthy instance, or pin one healthy instance when you need deterministic execution.",
                className="dash-search-copy",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            dcc.Textarea(
                                id=ids["search_query"],
                                value=query_value,
                                placeholder="Search Google via the hub...",
                                rows=2,
                                className="dash-search-input",
                                persistence=True,
                                persistence_type="session",
                            ),
                            html.Button(
                                "Search",
                                id=ids["search_submit"],
                                n_clicks=0,
                                className="dash-button",
                            ),
                        ],
                        className="dash-search-row",
                    ),
                    html.Div(
                        [
                            html.Div("Route", className="dash-controls-label"),
                            dcc.RadioItems(
                                id=ids["search_backend"],
                                options=route_options,
                                value=selected_backend,
                                inline=True,
                                persistence=True,
                                persistence_type="session",
                                className="dash-radioitems",
                                inputClassName="dash-radioinput",
                                labelClassName="dash-radiolabel",
                            ),
                        ],
                        className="dash-search-route",
                    ),
                ],
                className="dash-search-form",
            ),
            html.Div(status_text, className=status_class),
            *result_children,
        ],
        className="dash-card dash-search-card",
    )


def _resolve_search_state(
    search_clicks: int | None,
    query_value: str | None,
    backend_name: str | None,
    search_provider: SearchProvider,
) -> dict[str, object]:
    if int(search_clicks or 0) <= 0:
        raise PreventUpdate

    query = str(query_value or "").strip()
    backend_name = str(backend_name or "").strip()
    if not query:
        raise PreventUpdate
    try:
        result = search_provider(query, 5, "en", backend_name)
        return {
            "status": "ok",
            "query": query,
            "backend": backend_name,
            "result": result,
            "error": "",
        }
    except Exception as exc:
        return {
            "status": "error",
            "query": query,
            "backend": backend_name,
            "result": {},
            "error": sanitize_hub_search_error(str(exc)),
        }


def _build_body(
    snapshot: dict,
    *,
    auth_unlocked: bool,
    admin_token_configured: bool,
    page: int,
    page_size: int,
    ids: dict[str, str] | None = None,
    search_state: dict | None = None,
):
    ids = ids or _panel_ids("google-hub-panel")
    requests = snapshot.get("requests", {})
    health = snapshot.get("health", {})
    instances = list(snapshot.get("backends", []))
    node = dict(snapshot.get("node", {}))
    request_log = list(requests.get("request_log", []))

    node["value"] = mask_private_value(
        str(node.get("label", "")),
        str(node.get("value", "unknown")),
        auth_unlocked,
    )

    healthy_count = int(health.get("healthy_backends", 0))
    total_count = int(health.get("enabled_backends", len(instances)))
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
        build_node_metric_card(node, ""),
    ]

    body = [section("Overview", cards, kind="metric")]
    body.extend(
        [
            section(
                "Search",
                [
                    _build_search_card(
                        ids,
                        snapshot,
                        dict(search_state or {}),
                    )
                ],
                kind="search",
            ),
            section("Trends", build_request_trend_cards(requests), kind="chart"),
            section(
                "Instances", build_backend_instance_cards(instances), kind="instance"
            ),
        ]
    )
    if auth_unlocked or not admin_token_configured:
        body.append(
            section(
                "Request history",
                [
                    request_table(
                        request_log,
                        show_backend=True,
                        page=page,
                        page_size=page_size,
                        component_prefix="google-hub-panel",
                    )
                ],
                kind="chart",
            )
        )

    return page_shell(
        title="GOOGLE HUB",
        subtitle=subtitle,
        badge=f"{healthy_count}/{total_count} HEALTHY",
        badge_tone=badge_tone,
        body=body,
    )


def mount_google_hub_panel(
    app,
    snapshot_provider: SnapshotProvider,
    search_provider: SearchProvider,
    *,
    admin_token: str = "",
):
    ids = _panel_ids("google-hub-panel")
    default_access_state = {
        "unlocked": not bool(admin_token),
        "hint_dismissed": not bool(admin_token),
    }
    dash_app = create_dash_app(
        name=__name__,
        title="Google Hub Panel",
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
                id=ids["access_state"],
                storage_type="local",
                data=default_access_state,
            ),
            dcc.Store(id=ids["access_message"], storage_type="memory", data=""),
            dcc.Store(
                id=ids["access_modal"], storage_type="memory", data={"open": False}
            ),
            dcc.Store(id=ids["page_state"], storage_type="session", data=1),
            dcc.Store(id=ids["page_size_state"], storage_type="session", data=10),
            dcc.Store(
                id=ids["search_state"],
                storage_type="session",
                data={
                    "status": "idle",
                    "query": "",
                    "backend": "",
                    "result": {},
                    "error": "",
                },
            ),
            html.Div(id="google-hub-panel-access-layer"),
            html.Div(id=ids["root"]),
        ]
    )

    @dash_app.callback(
        Output("google-hub-panel-access-layer", "children"),
        Input(ids["access_state"], "data"),
        Input(ids["access_message"], "data"),
        Input(ids["access_modal"], "data"),
    )
    def render_access_popup(
        access_state: dict | None,
        access_message: str | None,
        access_modal: dict | None,
    ):
        state = dict(access_state or default_access_state)
        modal_state = dict(access_modal or {})
        unlocked = bool(state.get("unlocked")) or not bool(admin_token)
        open_modal = False
        if bool(admin_token):
            open_modal = bool(modal_state.get("open")) or (
                not unlocked and not bool(state.get("hint_dismissed"))
            )
        return privacy_gate_popup(
            component_prefix="google-hub-panel",
            unlocked=unlocked,
            open_modal=open_modal,
            message=str(access_message or "").strip(),
            token_configured=bool(admin_token),
        )

    @dash_app.callback(
        Output(ids["access_state"], "data"),
        Output(ids["access_message"], "data"),
        Output(ids["access_modal"], "data"),
        Input(ids["access_open"], "n_clicks"),
        Input(ids["access_close"], "n_clicks"),
        Input(ids["auth_submit"], "n_clicks"),
        Input(ids["auth_token"], "n_submit"),
        State(ids["auth_token"], "value"),
        State(ids["access_state"], "data"),
        State(ids["access_modal"], "data"),
    )
    def update_access_state(
        open_clicks: int,
        close_clicks: int,
        submit_clicks: int,
        submit_enter: int,
        entered_token: str | None,
        current_state: dict | None,
        current_modal: dict | None,
    ):
        del open_clicks, close_clicks, submit_clicks, submit_enter
        state = dict(current_state or default_access_state)
        state.setdefault("unlocked", not bool(admin_token))
        state.setdefault("hint_dismissed", not bool(admin_token))
        modal_state = dict(current_modal or {"open": False})
        modal_state.setdefault("open", False)
        trigger = (
            callback_context.triggered[0]["prop_id"].split(".")[0]
            if callback_context.triggered
            else ""
        )
        if not admin_token:
            return (
                {
                    "unlocked": True,
                    "hint_dismissed": True,
                },
                "",
                {"open": False},
            )
        if trigger == ids["access_open"]:
            state["hint_dismissed"] = True
            return state, "", {"open": True}
        if trigger == ids["access_close"]:
            state["hint_dismissed"] = True
            return state, "", {"open": False}
        if trigger in {ids["auth_submit"], ids["auth_token"]}:
            if str(entered_token or "").strip() in _accepted_admin_tokens(admin_token):
                return (
                    {
                        "unlocked": True,
                        "hint_dismissed": True,
                    },
                    "",
                    {"open": False},
                )
            state["unlocked"] = False
            state["hint_dismissed"] = True
            return state, "Invalid admin token", {"open": True}
        return state, "", modal_state

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
        Output(ids["search_state"], "data"),
        Input(ids["search_submit"], "n_clicks"),
        State(ids["search_query"], "value"),
        State(ids["search_backend"], "value"),
        prevent_initial_call=True,
    )
    def run_search(
        search_clicks: int,
        query_value: str | None,
        backend_name: str | None,
    ):
        return _resolve_search_state(
            search_clicks,
            query_value,
            backend_name,
            search_provider,
        )

    @dash_app.callback(
        Output(ids["root"], "children"),
        Input(ids["refresh"], "n_intervals"),
        Input(ids["access_state"], "data"),
        Input(ids["page_state"], "data"),
        Input(ids["page_size_state"], "data"),
        Input(ids["search_state"], "data"),
    )
    def refresh_panel(
        _n_intervals: int,
        access_state: dict | None,
        page: int | None,
        page_size: int | None,
        search_state: dict | None,
    ):
        state = dict(access_state or default_access_state)
        return _build_body(
            snapshot_provider(),
            auth_unlocked=bool(state.get("unlocked")) or not bool(admin_token),
            admin_token_configured=bool(admin_token),
            page=max(1, int(page or 1)),
            page_size=max(1, int(page_size or 10)),
            ids=ids,
            search_state=dict(search_state or {}),
        )

    app.mount(DEFAULT_GOOGLE_API_PANEL_PATH, WSGIMiddleware(dash_app.server))
