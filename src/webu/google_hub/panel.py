from __future__ import annotations

from collections.abc import Callable
import os
import time

from urllib.parse import urlsplit

from a2wsgi import WSGIMiddleware
from dash import ALL, Input, Output, State, callback_context, dcc, html
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

from .manager import sanitize_hf_control_error, sanitize_hub_search_error


SnapshotProvider = Callable[[], dict]
SearchProvider = Callable[[str, int, str, str], dict]
ControlProvider = Callable[[str, str], dict]


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
        "page_size": f"{prefix}-history-page-size",
        "page_prev": f"{prefix}-history-prev",
        "page_next": f"{prefix}-history-next",
        "refresh": f"{prefix}-refresh",
        "search_request": f"{prefix}-search-request",
        "search_state": f"{prefix}-search-state",
        "search_query": f"{prefix}-search-query",
        "search_backend": f"{prefix}-search-backend",
        "search_submit": f"{prefix}-search-submit",
        "search_status": f"{prefix}-search-status",
        "control_request": f"{prefix}-control-request",
        "control_state": f"{prefix}-control-state",
        "control_preview": f"{prefix}-control-preview",
        "control_start_all": f"{prefix}-control-start-all",
        "control_stop_all": f"{prefix}-control-stop-all",
        "control_restart_all": f"{prefix}-control-restart-all",
        "control_rebuild_all": f"{prefix}-control-rebuild-all",
        "control_restart_bad": f"{prefix}-control-restart-bad",
        "control_rebuild_bad": f"{prefix}-control-rebuild-bad",
        "control_squash_all": f"{prefix}-control-squash-all",
        "root": f"{prefix}-root",
    }


def _backend_action_id(action: str, backend_name: str) -> dict[str, str]:
    return {
        "type": "google-hub-panel-backend-action",
        "action": str(action),
        "backend": str(backend_name),
    }


def _search_route_options(snapshot: dict) -> list[dict[str, str]]:
    options = [{"label": "Auto", "value": ""}]
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


def _build_search_card(
    ids: dict[str, str],
    snapshot: dict,
    search_state: dict,
):
    query_value = str(search_state.get("query", ""))

    status = str(search_state.get("status", "idle")).strip().lower() or "idle"
    is_searching = status == "pending"
    error_text = sanitize_hub_search_error(str(search_state.get("error", "")).strip())
    result_payload = dict(search_state.get("result", {}) or {})
    result_query = str(
        result_payload.get("query", search_state.get("query", ""))
    ).strip()
    selected_backend_name = str(result_payload.get("backend", "")).strip()
    pending_backend_name = _resolve_search_route_name(
        snapshot,
        str(search_state.get("backend", "")).strip(),
    )

    status_class = "dash-search-status"
    status_text = ""
    if is_searching:
        status_class += " pending"
        status_text = f"Searching via Route {pending_backend_name or 'hub routing'} ..."
    elif status == "ok":
        status_class += " ok"
        status_text = (
            f"Resolved via Route {selected_backend_name or 'hub routing'}"
            f" · {result_payload.get('result_count', 0)} results"
        )
    elif status == "error" and error_text:
        status_class += " fail"
        status_text = error_text

    result_children = [
        html.Div(
            "Search results will appear here.",
            className="dash-search-empty",
        )
    ]
    if is_searching:
        result_children = [
            html.Div(
                f"Searching for {query_value} via Route {pending_backend_name or 'hub routing'}...",
                className="dash-search-empty",
            )
        ]
    elif status == "ok":
        result_items = []
        for index, item in enumerate(list(result_payload.get("results", [])), start=1):
            title = str(item.get("title", "")).strip() or f"Result {index}"
            url = str(item.get("url", "")).strip()
            displayed_url = str(item.get("displayed_url", "")).strip() or url
            snippet = str(item.get("snippet", "")).strip()
            position = int(item.get("position", index) or index)
            result_items.append(
                html.Div(
                    [
                        html.Div(
                            [
                                html.Span(
                                    f"#{position}",
                                    className="dash-search-result-index",
                                ),
                                (
                                    html.A(
                                        title,
                                        href=url or displayed_url or None,
                                        target="_blank",
                                        rel="noreferrer noopener",
                                        className="dash-search-result-title",
                                    )
                                    if (url or displayed_url)
                                    else html.Div(
                                        title,
                                        className="dash-search-result-title",
                                    )
                                ),
                            ],
                            className="dash-search-result-head",
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

    results_open = is_searching or status in {"ok", "error"}

    return html.Div(
        [
            html.Details(
                [
                    html.Summary(
                        [
                            html.Span("Search", className="dash-collapse-summary-main"),
                            html.Span(
                                [
                                    (
                                        html.Span(
                                            status_text,
                                            id=ids["search_status"],
                                            className=status_class,
                                        )
                                        if status_text
                                        else html.Span(
                                            "",
                                            id=ids["search_status"],
                                            className=status_class,
                                        )
                                    ),
                                    html.Span(className="dash-collapse-icon"),
                                ],
                                className="dash-collapse-summary-side",
                            ),
                        ],
                        className="dash-collapse-summary",
                    ),
                    html.Div(
                        [
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
                                                className="dash-button dash-search-submit",
                                            ),
                                        ],
                                        className="dash-search-row",
                                    ),
                                ],
                                className="dash-search-form dash-search-form-card",
                            ),
                            html.Details(
                                [
                                    html.Summary(
                                        [
                                            html.Span(
                                                "Results",
                                                className="dash-collapse-summary-main",
                                            ),
                                            html.Span(
                                                html.Span(
                                                    className="dash-collapse-icon"
                                                ),
                                                className="dash-collapse-summary-side",
                                            ),
                                        ],
                                        className="dash-collapse-summary",
                                    ),
                                    html.Div(
                                        [
                                            html.Div(
                                                result_children,
                                                className="dash-collapse-body dash-results-body",
                                            )
                                        ],
                                        className="dash-collapse-content",
                                    ),
                                ],
                                open=results_open,
                                className="dash-collapse",
                            ),
                        ],
                        className="dash-collapse-body dash-search-body",
                    ),
                ],
                open=False,
                className="dash-collapse",
                **{
                    "data-webu-collapse-key": "google-hub-search",
                    "data-webu-collapse-open": "0",
                },
            )
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
            "request_id": int(search_clicks or 0),
            "status": "ok",
            "query": query,
            "backend": backend_name,
            "result": result,
            "error": "",
        }
    except Exception as exc:
        return {
            "request_id": int(search_clicks or 0),
            "status": "error",
            "query": query,
            "backend": backend_name,
            "result": {},
            "error": sanitize_hub_search_error(str(exc)),
        }


def _friendly_control_action(action: str) -> str:
    labels = {
        "toggle": "Toggle",
        "restart": "Restart",
        "rebuild": "Rebuild",
        "squash": "Squash",
        "start-all": "Start All",
        "stop-all": "Stop All",
        "restart-all": "Restart All",
        "rebuild-all": "Rebuild All",
        "restart-bad-all": "Restart Bad",
        "rebuild-bad-all": "Rebuild Bad",
        "squash-all": "Squash All",
        "restart-bad": "Restart Bad",
        "rebuild-bad": "Rebuild Bad",
    }
    return labels.get(str(action or "").strip().lower(), str(action or "").strip())


def _resolve_toggle_label(runtime_stage: str) -> str:
    normalized_stage = str(runtime_stage or "").strip().upper()
    return "Start" if normalized_stage in {"PAUSED", "STOPPED"} else "Stop"


def _resolve_control_state(
    request_id: int | None,
    action: str | None,
    backend_name: str | None,
    control_provider: ControlProvider,
    *,
    unlocked: bool,
) -> dict[str, object]:
    if int(request_id or 0) <= 0:
        raise PreventUpdate

    normalized_action = str(action or "").strip()
    normalized_backend = str(backend_name or "").strip()
    if not normalized_action:
        raise PreventUpdate

    if not unlocked:
        return {
            "status": "error",
            "message": "Unlock access to run HF control actions.",
            "action": normalized_action,
            "backend": normalized_backend,
            "count": 0,
            "results": [],
        }

    try:
        result = control_provider(normalized_action, normalized_backend)
        return {
            "status": "ok",
            "message": str(result.get("message", "Action requested")).strip(),
            "action": str(result.get("action", normalized_action)).strip(),
            "backend": str(result.get("backend", normalized_backend)).strip(),
            "count": int(result.get("count", 0) or 0),
            "results": list(result.get("results", [])),
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": sanitize_hf_control_error(str(exc)),
            "action": normalized_action,
            "backend": normalized_backend,
            "count": 0,
            "results": [],
        }


def _resolve_search_route_name(snapshot: dict, requested_backend: str = "") -> str:
    requested_name = str(requested_backend or "").strip()
    backends = list(snapshot.get("backends", []))
    if requested_name:
        for item in backends:
            if str(item.get("name", "")).strip() == requested_name:
                return requested_name

    now_ts = time.time()

    def _is_running(item: dict) -> bool:
        return bool(item.get("is_running", item.get("healthy", False)))

    def _not_cooling(item: dict) -> bool:
        return float(item.get("search_cooldown_until_ts", 0.0) or 0.0) <= now_ts

    def _rank(item: dict) -> tuple:
        weight = max(1, int(item.get("weight", 1) or 1))
        return (
            float(item.get("selection_score", 0.0) or 0.0),
            float(item.get("inflight", 0) or 0.0) / weight,
            int(item.get("consecutive_failures", 0) or 0),
            float(item.get("last_selected_ts", 0.0) or 0.0),
            str(item.get("name", "")),
        )

    enabled = [item for item in backends if bool(item.get("enabled", True))]
    running = [item for item in enabled if _is_running(item)]
    ready_running = [item for item in running if _not_cooling(item)]
    candidates = ready_running or running or enabled
    if not candidates:
        return ""
    return str(sorted(candidates, key=_rank)[0].get("name", "")).strip()


def _control_result_for_backend(control_state: dict, backend_name: str) -> dict | None:
    normalized_backend = str(backend_name or "").strip()
    if not normalized_backend:
        return None
    for item in list(control_state.get("results", []) or []):
        if str(item.get("backend", "")).strip() == normalized_backend:
            return dict(item)
    if str(control_state.get("backend", "")).strip() == normalized_backend:
        return dict(control_state)
    return None


def _instance_control_feedback(
    backend_name: str,
    control_state: dict | None,
    *,
    toggle_label: str,
):
    state = dict(control_state or {})
    if not backend_name:
        return None
    status = str(state.get("status", "")).strip().lower()
    action = str(state.get("action", "")).strip().lower()
    targeted_backend = str(state.get("backend", "")).strip()
    friendly_action = (
        toggle_label if action == "toggle" else _friendly_control_action(action)
    )
    matched_result = _control_result_for_backend(state, backend_name)

    feedback_text = ""
    feedback_class = "dash-action-status"
    if status == "pending":
        if targeted_backend == backend_name:
            feedback_text = f"Requesting {friendly_action}..."
            feedback_class += " pending"
    elif status == "ok":
        if matched_result:
            runtime_stage = str(matched_result.get("runtime_stage", "")).strip()
            feedback_text = f"{friendly_action} requested"
            if runtime_stage:
                feedback_text = f"{feedback_text} · {runtime_stage}"
            feedback_class += " ok"
    elif status == "error":
        if targeted_backend == backend_name or not targeted_backend:
            feedback_text = str(state.get("message", "")).strip()
            if feedback_text:
                feedback_class += " fail"

    if not feedback_text:
        return None
    return html.Div(feedback_text, className=feedback_class)


def _resolve_effective_control_state(
    control_state: dict | None,
    control_preview: dict | None,
) -> dict:
    finalized = dict(control_state or {})
    preview = dict(control_preview or {})
    if str(preview.get("status", "")).strip().lower() != "pending":
        return finalized

    preview_started_ts = float(preview.get("started_ts", 0.0) or 0.0)
    if preview_started_ts > 0 and (time.time() - preview_started_ts) > 20.0:
        return finalized

    preview_action = str(preview.get("action", "")).strip().lower()
    preview_backend = str(preview.get("backend", "")).strip()
    final_status = str(finalized.get("status", "")).strip().lower()
    final_action = str(finalized.get("action", "")).strip().lower()
    final_backend = str(finalized.get("backend", "")).strip()
    if (
        final_status in {"ok", "error"}
        and final_action == preview_action
        and final_backend == preview_backend
    ):
        return finalized
    return preview


def _summarize_control_results(control_state: dict):
    results = list(control_state.get("results", []) or [])
    chips = []
    for item in results[:4]:
        backend_name = str(item.get("space_name") or item.get("backend", "")).strip()
        runtime_stage = str(item.get("runtime_stage", "")).strip()
        if backend_name and runtime_stage:
            chips.append(f"{backend_name} -> {runtime_stage}")
        elif backend_name:
            chips.append(backend_name)
    extra_count = len(results) - len(chips)
    if extra_count > 0:
        chips.append(f"+{extra_count} more")
    summary = meta_row(chips)
    if summary is None:
        return None
    summary.className = f"{summary.className} dash-action-summary"
    return summary


def _build_history_content(
    request_log: list[dict],
    *,
    auth_unlocked: bool,
    admin_token_configured: bool,
    page: int,
    page_size: int,
):
    if auth_unlocked or not admin_token_configured:
        return request_table(
            request_log,
            show_backend=True,
            page=page,
            page_size=page_size,
            component_prefix="google-hub-panel",
        )
    return html.Div(
        "Unlock access to view request history.",
        className="dash-search-empty",
    )


def _build_global_controls_card(
    ids: dict[str, str],
    control_state: dict | None,
    snapshot: dict | None = None,
):
    control_state = dict(control_state or {})
    status = str(control_state.get("status", "idle")).strip().lower()
    message = str(control_state.get("message", "")).strip()
    pending = status == "pending"
    pending_action = str(control_state.get("action", "")).strip().lower()
    pending_backend = str(control_state.get("backend", "")).strip()
    pending_action_label = _friendly_control_action(pending_action)
    if pending_action == "toggle" and pending_backend:
        runtime_stage = ""
        for item in list((snapshot or {}).get("backends", []) or []):
            if str(item.get("name", "")).strip() == pending_backend:
                runtime_stage = str(item.get("runtime_stage", "")).strip()
                break
        pending_action_label = _resolve_toggle_label(runtime_stage)

    status_class = "dash-action-status"
    if status == "ok" and message:
        status_class += " ok"
    elif status == "error" and message:
        status_class += " fail"
    pending_message = ""
    if pending and pending_action_label:
        if pending_backend:
            pending_message = (
                f"Requesting {pending_action_label} for {pending_backend}..."
            )
        elif pending_action in {"restart-bad-all", "rebuild-bad-all"}:
            pending_message = (
                f"Requesting {pending_action_label} across matching instances..."
            )
        else:
            pending_message = f"Requesting {pending_action_label}..."
    message_node = (
        html.Div(message, className=status_class) if (message and not pending) else None
    )
    result_summary = _summarize_control_results(control_state)
    return html.Div(
        [
            html.Div(
                [
                    html.Button(
                        (
                            "Starting all..."
                            if pending
                            and str(control_state.get("action", "")) == "start-all"
                            else "Start All"
                        ),
                        id=ids["control_start_all"],
                        n_clicks=0,
                        className="dash-button",
                        disabled=pending,
                    ),
                    html.Button(
                        (
                            "Stopping all..."
                            if pending
                            and str(control_state.get("action", "")) == "stop-all"
                            else "Stop All"
                        ),
                        id=ids["control_stop_all"],
                        n_clicks=0,
                        className="dash-button",
                        disabled=pending,
                    ),
                    html.Button(
                        (
                            "Restarting..."
                            if pending
                            and str(control_state.get("action", "")) == "restart-all"
                            else "Restart All"
                        ),
                        id=ids["control_restart_all"],
                        n_clicks=0,
                        className="dash-button",
                        disabled=pending,
                    ),
                    html.Button(
                        (
                            "Rebuilding..."
                            if pending
                            and str(control_state.get("action", "")) == "rebuild-all"
                            else "Rebuild All"
                        ),
                        id=ids["control_rebuild_all"],
                        n_clicks=0,
                        className="dash-button",
                        disabled=pending,
                    ),
                    html.Button(
                        (
                            "Restarting bad..."
                            if pending
                            and str(control_state.get("action", ""))
                            == "restart-bad-all"
                            else "Restart Bad"
                        ),
                        id=ids["control_restart_bad"],
                        n_clicks=0,
                        className="dash-button",
                        disabled=pending,
                    ),
                    html.Button(
                        (
                            "Rebuilding bad..."
                            if pending
                            and str(control_state.get("action", ""))
                            == "rebuild-bad-all"
                            else "Rebuild Bad"
                        ),
                        id=ids["control_rebuild_bad"],
                        n_clicks=0,
                        className="dash-button",
                        disabled=pending,
                    ),
                    html.Button(
                        (
                            "Squashing..."
                            if pending
                            and str(control_state.get("action", "")) == "squash-all"
                            else "Squash All"
                        ),
                        id=ids["control_squash_all"],
                        n_clicks=0,
                        className="dash-button",
                        disabled=pending,
                    ),
                ],
                className="dash-action-row",
            ),
            (
                html.Div(
                    pending_message,
                    className="dash-action-status pending",
                )
                if pending_message
                else None
            ),
            message_node,
            result_summary,
        ],
        className="dash-card dash-controls-card",
    )


def _build_instance_controls(item: dict, control_state: dict | None = None):
    backend_name = str(item.get("name", "")).strip()
    if not backend_name:
        return None
    is_hf_space = str(item.get("kind", "")).strip() == "hf-space"
    runtime_stage = str(item.get("runtime_stage", "")).strip().upper()
    toggle_label = _resolve_toggle_label(runtime_stage)
    state = dict(control_state or {})
    pending = str(state.get("status", "")).strip().lower() == "pending"
    pending_action = str(state.get("action", "")).strip().lower()
    pending_backend = str(state.get("backend", "")).strip()
    disabled = (not is_hf_space) or pending
    disabled_style = {"opacity": 0.45, "cursor": "default"} if disabled else None

    def _button_label(default_label: str, action_name: str) -> str:
        if (
            pending
            and pending_backend == backend_name
            and pending_action == action_name
        ):
            return f"{default_label}..."
        return default_label

    return html.Div(
        [
            html.Div(
                [
                    html.Button(
                        _button_label(toggle_label, "toggle"),
                        id=_backend_action_id("toggle", backend_name),
                        n_clicks=0,
                        className="dash-button",
                        disabled=disabled,
                        style=disabled_style,
                    ),
                    html.Button(
                        _button_label("Restart", "restart"),
                        id=_backend_action_id("restart", backend_name),
                        n_clicks=0,
                        className="dash-button",
                        disabled=disabled,
                        style=disabled_style,
                    ),
                    html.Button(
                        _button_label("Rebuild", "rebuild"),
                        id=_backend_action_id("rebuild", backend_name),
                        n_clicks=0,
                        className="dash-button",
                        disabled=disabled,
                        style=disabled_style,
                    ),
                    html.Button(
                        _button_label("Squash", "squash"),
                        id=_backend_action_id("squash", backend_name),
                        n_clicks=0,
                        className="dash-button",
                        disabled=disabled,
                        style=disabled_style,
                    ),
                ],
                className="dash-action-row dash-action-row-compact",
            ),
            _instance_control_feedback(
                backend_name,
                state,
                toggle_label=toggle_label,
            ),
        ],
    )


def _build_body(
    snapshot: dict,
    *,
    auth_unlocked: bool,
    admin_token_configured: bool,
    page: int,
    page_size: int,
    ids: dict[str, str] | None = None,
    search_state: dict | None = None,
    control_state: dict | None = None,
    control_preview: dict | None = None,
):
    ids = ids or _panel_ids("google-hub-panel")
    requests = snapshot.get("requests", {})
    health = snapshot.get("health", {})
    instances = list(snapshot.get("backends", []))
    node = dict(snapshot.get("node", {}))
    request_log = list(requests.get("request_log", []))
    effective_search_state = dict(search_state or {})
    effective_control_state = _resolve_effective_control_state(
        control_state,
        control_preview,
    )

    if (
        str(effective_search_state.get("status", "")).strip().lower() == "pending"
        and str(effective_control_state.get("status", "")).strip().lower() == "ok"
    ):
        effective_control_state = {
            **effective_control_state,
            "message": "",
            "results": [],
        }

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
                        effective_search_state,
                    )
                ],
                kind="search",
            ),
            section(
                "Trends",
                build_request_trend_cards(requests),
                kind="chart",
                collapsible=True,
                open=True,
                collapse_key="google-hub-trends",
            ),
            section(
                "Instances",
                build_backend_instance_cards(
                    instances,
                    control_factory=lambda item: _build_instance_controls(
                        item, effective_control_state
                    ),
                ),
                kind="instance",
                collapsible=True,
                open=True,
                collapse_key="google-hub-instances",
            ),
            section(
                "Controls",
                [_build_global_controls_card(ids, effective_control_state, snapshot)],
                kind="search",
                collapsible=True,
                open=False,
                collapse_key="google-hub-controls",
            ),
            section(
                "Request history",
                [
                    _build_history_content(
                        request_log,
                        auth_unlocked=auth_unlocked,
                        admin_token_configured=admin_token_configured,
                        page=page,
                        page_size=page_size,
                    )
                ],
                kind="search",
                collapsible=True,
                open=True,
                collapse_key="google-hub-requests",
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


def mount_google_hub_panel(
    app,
    snapshot_provider: SnapshotProvider,
    search_provider: SearchProvider,
    control_provider: ControlProvider,
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
                id=ids["search_request"],
                storage_type="memory",
                data={"request_id": 0, "query": "", "backend": ""},
            ),
            dcc.Store(
                id=ids["control_request"],
                storage_type="memory",
                data={"request_id": 0, "action": "", "backend": ""},
            ),
            dcc.Store(
                id=ids["control_state"],
                storage_type="memory",
                data={"status": "idle", "message": ""},
            ),
            dcc.Store(
                id=ids["control_preview"],
                storage_type="memory",
                data={"status": "idle", "message": ""},
            ),
            dcc.Store(
                id=ids["search_state"],
                storage_type="session",
                data={
                    "request_id": 0,
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
        Input(
            {"type": "google-hub-panel-history-page-button", "page": ALL},
            "n_clicks",
        ),
        Input(ids["page_size"], "value"),
        Input(ids["refresh"], "n_intervals"),
        State(ids["page_state"], "data"),
        State(ids["page_size_state"], "data"),
    )
    def update_page(
        prev_clicks: int,
        next_clicks: int,
        page_button_clicks: list[int],
        page_size: int,
        _n_intervals: int,
        current_page: int | None,
        current_page_size: int | None,
    ):
        del prev_clicks, next_clicks, page_button_clicks
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
        if (
            isinstance(trigger, dict)
            and trigger.get("type") == "google-hub-panel-history-page-button"
        ):
            return (
                max(1, min(int(trigger.get("page", page) or page), total_pages)),
                resolved_page_size,
            )
        return page, resolved_page_size

    dash_app.clientside_callback(
        """
        function(n_clicks, query, currentRequest, currentState) {
            const clickCount = Number(n_clicks || 0);
            if (!clickCount) {
                return [window.dash_clientside.no_update, window.dash_clientside.no_update];
            }
            const normalizedQuery = String(query || '').trim();
            if (!normalizedQuery) {
                return [window.dash_clientside.no_update, window.dash_clientside.no_update];
            }
            const current = currentRequest || {};
            if (Number(current.request_id || 0) === clickCount && String(current.query || '') === normalizedQuery && String(current.backend || '') === '') {
                return [window.dash_clientside.no_update, window.dash_clientside.no_update];
            }
            const request = {
                request_id: clickCount,
                query: normalizedQuery,
                backend: '',
            };
            const pending = Object.assign({}, currentState || {}, request, {
                status: 'pending',
                result: {},
                error: '',
            });
            return [request, pending];
        }
        """,
        Output(ids["search_request"], "data"),
        Output(ids["search_state"], "data", allow_duplicate=True),
        Input(ids["search_submit"], "n_clicks"),
        State(ids["search_query"], "value"),
        State(ids["search_request"], "data"),
        State(ids["search_state"], "data"),
        prevent_initial_call=True,
    )

    dash_app.clientside_callback(
        f"""
        function(startAll, stopAll, restartAll, rebuildAll, restartBad, rebuildBad, squashAll, backendClicks, currentRequest, currentPreview) {{
            const trigger = dash_clientside.callback_context.triggered_id;
            const triggered = (dash_clientside.callback_context.triggered || [])[0] || null;
            if (!trigger) {{
                return [window.dash_clientside.no_update, window.dash_clientside.no_update];
            }}
            let action = '';
            let backend = '';
            if (typeof trigger === 'object') {{
                action = String(trigger.action || '');
                backend = String(trigger.backend || '');
            }} else if (trigger === {ids['control_start_all']!r}) {{
                action = 'start-all';
            }} else if (trigger === {ids['control_stop_all']!r}) {{
                action = 'stop-all';
            }} else if (trigger === {ids['control_restart_all']!r}) {{
                action = 'restart-all';
            }} else if (trigger === {ids['control_rebuild_all']!r}) {{
                action = 'rebuild-all';
            }} else if (trigger === {ids['control_restart_bad']!r}) {{
                action = 'restart-bad-all';
            }} else if (trigger === {ids['control_rebuild_bad']!r}) {{
                action = 'rebuild-bad-all';
            }} else if (trigger === {ids['control_squash_all']!r}) {{
                action = 'squash-all';
            }}
            if (!action) {{
                return [window.dash_clientside.no_update, window.dash_clientside.no_update];
            }}
            const clickCount = Number((triggered && triggered.value) || 0);
            if (!clickCount) {{
                return [window.dash_clientside.no_update, window.dash_clientside.no_update];
            }}
            const currentQueued = currentRequest || {{}};
            const current = currentPreview || {{}};
            if (
                Number(currentQueued.request_id || 0) === clickCount &&
                String(currentQueued.action || '') === action &&
                String(currentQueued.backend || '') === backend
            ) {{
                return [window.dash_clientside.no_update, window.dash_clientside.no_update];
            }}
            if (
                String(current.action || '') === action &&
                String(current.backend || '') === backend &&
                Number(current.click_count || 0) >= clickCount
            ) {{
                return [window.dash_clientside.no_update, window.dash_clientside.no_update];
            }}
            const labelMap = {{
                'toggle': 'Toggle',
                'restart': 'Restart',
                'rebuild': 'Rebuild',
                'squash': 'Squash',
                'start-all': 'Start All',
                'stop-all': 'Stop All',
                'restart-all': 'Restart All',
                'rebuild-all': 'Rebuild All',
                'restart-bad-all': 'Restart Bad',
                'rebuild-bad-all': 'Rebuild Bad',
                'squash-all': 'Squash All'
            }};
            const targetText = backend ? (' for ' + backend) : '';
            const request = {{
                request_id: clickCount,
                action: action,
                backend: backend,
            }};
            const pending = {{
                status: 'pending',
                action: action,
                backend: backend,
                count: 0,
                results: [],
                click_count: clickCount,
                started_ts: Date.now() / 1000,
                message: 'Requesting ' + String(labelMap[action] || action) + targetText + '...'
            }};
            return [request, pending];
        }}
        """,
        Output(ids["control_request"], "data"),
        Output(ids["control_preview"], "data"),
        Input(ids["control_start_all"], "n_clicks"),
        Input(ids["control_stop_all"], "n_clicks"),
        Input(ids["control_restart_all"], "n_clicks"),
        Input(ids["control_rebuild_all"], "n_clicks"),
        Input(ids["control_restart_bad"], "n_clicks"),
        Input(ids["control_rebuild_bad"], "n_clicks"),
        Input(ids["control_squash_all"], "n_clicks"),
        Input(
            {"type": "google-hub-panel-backend-action", "action": ALL, "backend": ALL},
            "n_clicks",
        ),
        State(ids["control_request"], "data"),
        State(ids["control_preview"], "data"),
        prevent_initial_call=True,
    )

    @dash_app.callback(
        Output(ids["search_state"], "data", allow_duplicate=True),
        Input(ids["search_request"], "data"),
        prevent_initial_call=True,
    )
    def run_search(search_request: dict | None):
        request = dict(search_request or {})
        request_id = int(request.get("request_id", 0) or 0)
        if request_id <= 0:
            raise PreventUpdate
        return _resolve_search_state(
            request_id,
            request.get("query"),
            request.get("backend"),
            search_provider,
        )

    @dash_app.callback(
        Output(ids["control_state"], "data"),
        Input(ids["control_request"], "data"),
        State(ids["access_state"], "data"),
        prevent_initial_call=True,
    )
    def run_control_action(
        control_request: dict | None,
        access_state: dict | None,
    ):
        unlocked = bool(dict(access_state or {}).get("unlocked")) or not bool(
            admin_token
        )
        try:
            request = dict(control_request or {})
            return _resolve_control_state(
                int(request.get("request_id", 0) or 0),
                request.get("action"),
                request.get("backend"),
                control_provider,
                unlocked=unlocked,
            )
        except PreventUpdate:
            raise
        except Exception as exc:
            return {
                "status": "error",
                "message": sanitize_hf_control_error(str(exc)),
                "action": "",
                "backend": "",
                "count": 0,
                "results": [],
            }

    @dash_app.callback(
        Output(ids["root"], "children"),
        Input(ids["refresh"], "n_intervals"),
        Input(ids["access_state"], "data"),
        Input(ids["page_state"], "data"),
        Input(ids["page_size_state"], "data"),
        Input(ids["search_state"], "data"),
        Input(ids["control_state"], "data"),
        Input(ids["control_preview"], "data"),
    )
    def refresh_panel(
        _n_intervals: int,
        access_state: dict | None,
        page: int | None,
        page_size: int | None,
        search_state: dict | None,
        control_state: dict | None,
        control_preview: dict | None,
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
            control_state=dict(control_state or {}),
            control_preview=dict(control_preview or {}),
        )

    app.mount(DEFAULT_GOOGLE_API_PANEL_PATH, WSGIMiddleware(dash_app.server))
