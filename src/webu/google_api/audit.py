from __future__ import annotations

import json
import time

from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests


ROOT = Path(__file__).resolve().parents[3]
CONFIGS_DIR = ROOT / "configs"
GOOGLE_API_CONFIG = CONFIGS_DIR / "google_api.json"
HF_SPACES_CONFIG = CONFIGS_DIR / "hf_spaces.json"
GOOGLE_HUB_CONFIG = CONFIGS_DIR / "google_hub.json"
REQUEST_TIMEOUT_SEC = 60


@dataclass
class QueryAudit:
    query: str
    expected_hl: str
    status_code: int = 0
    inferred_hl: str = ""
    result_count: int = 0
    success: bool = False
    error: str = ""


@dataclass
class SpaceAudit:
    space: str
    base_url: str
    health_ok: bool = False
    health_status: str = ""
    search_ok: bool = False
    search_result_count: int = 0
    play_result_present: bool = False
    raw_ok: bool = False
    raw_status_code: int = 0
    raw_x_query: str = ""
    locale_audits: list[QueryAudit] | None = None
    error: str = ""

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["locale_audits"] = [asdict(item) for item in (self.locale_audits or [])]
        return payload


@dataclass
class HubAudit:
    base_url: str
    health_ok: bool = False
    health_status: str = ""
    healthy_backends: int = 0
    wikipedia_ok: bool = False
    wikipedia_result_count: int = 0
    play_result_present: bool = False
    locale_audits: list[QueryAudit] | None = None
    backends_seen: list[str] | None = None
    error: str = ""

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["locale_audits"] = [asdict(item) for item in (self.locale_audits or [])]
        return payload


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_search_api_token() -> str:
    config = load_json(GOOGLE_API_CONFIG)
    for service in config.get("services", []):
        if str(service.get("type", "")).strip() == "hf-space":
            return str(service.get("api_token", "")).strip()
    raise RuntimeError("HF search api token not found in configs/google_api.json")


def resolve_spaces() -> list[tuple[str, str]]:
    config = load_json(HF_SPACES_CONFIG)
    items: list[tuple[str, str]] = []
    for account in config.get("accounts", []):
        owner = str(account.get("account", "")).strip()
        for space in account.get("spaces", []):
            if not bool(space.get("enabled", True)):
                continue
            name = str(space.get("name", "")).strip()
            items.append((f"{owner}/{name}", f"https://{owner}-{name}.hf.space"))
    return items


def resolve_hub_url() -> str:
    config = load_json(GOOGLE_HUB_CONFIG)
    host = str(config.get("host", "127.0.0.1")).strip() or "127.0.0.1"
    port = int(config.get("port", 18100))
    if host == "0.0.0.0":
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def extract_hl(final_url: str) -> str:
    if not final_url:
        return ""
    parsed = urlparse(final_url)
    values = parse_qs(parsed.query).get("hl") or []
    return values[0] if values else ""


def _get_json(
    session: requests.Session,
    url: str,
    headers: dict,
    params: dict,
) -> tuple[int, dict]:
    response = session.get(
        url,
        headers=headers,
        params=params,
        timeout=REQUEST_TIMEOUT_SEC,
    )
    return response.status_code, response.json()


def _get_response(
    session: requests.Session,
    url: str,
    headers: dict,
    params: dict,
) -> requests.Response:
    return session.get(
        url,
        headers=headers,
        params=params,
        timeout=REQUEST_TIMEOUT_SEC,
    )


def audit_space(space: str, base_url: str, token: str) -> SpaceAudit:
    headers = {"X-Api-Token": token}
    result = SpaceAudit(space=space, base_url=base_url, locale_audits=[])
    session = requests.Session()

    try:
        health_response = session.get(f"{base_url}/health", timeout=REQUEST_TIMEOUT_SEC)
        result.health_ok = health_response.status_code == 200
        if result.health_ok:
            result.health_status = str(health_response.json().get("status", "")).strip()

        search_status, search_payload = _get_json(
            session,
            f"{base_url}/search",
            headers,
            {"q": "wikipedia", "num": 10},
        )
        result.search_ok = search_status == 200 and bool(
            search_payload.get("success", False)
        )
        result.search_result_count = int(search_payload.get("result_count", 0) or 0)
        result.play_result_present = any(
            item.get("url", "").startswith("https://play.google.com/")
            for item in search_payload.get("results", [])
        )

        raw_response = _get_response(
            session,
            f"{base_url}/search_raw",
            headers,
            {"q": "玩机器切片", "num": 10},
        )
        result.raw_status_code = raw_response.status_code
        result.raw_ok = raw_response.status_code == 200
        result.raw_x_query = raw_response.headers.get("x-query", "")

        for query, expected_hl in [
            ("玩机器切片", "zh-CN"),
            ("東京の天気予報", "ja"),
            ("bonjour paris actualites", "fr"),
        ]:
            response = _get_response(
                session,
                f"{base_url}/search_raw",
                headers,
                {"q": query, "num": 10},
            )
            final_url = response.headers.get("x-final-url", "")
            audit = QueryAudit(
                query=query,
                expected_hl=expected_hl,
                status_code=response.status_code,
                inferred_hl=extract_hl(final_url),
                success=response.status_code == 200
                and extract_hl(final_url) == expected_hl,
                error="" if response.status_code == 200 else response.text[:160],
            )
            if query == "bonjour paris actualites" and response.status_code == 200:
                try:
                    search_response = session.get(
                        f"{base_url}/search",
                        headers=headers,
                        params={"q": query, "num": 10},
                        timeout=REQUEST_TIMEOUT_SEC,
                    )
                    if search_response.status_code == 200:
                        payload = search_response.json()
                        audit.result_count = int(payload.get("result_count", 0) or 0)
                except Exception as exc:
                    audit.error = str(exc)[:160]
            result.locale_audits.append(audit)
    except Exception as exc:
        result.error = str(exc)[:200]
    finally:
        session.close()

    return result


def audit_hub(base_url: str) -> HubAudit:
    session = requests.Session()
    result = HubAudit(base_url=base_url, locale_audits=[], backends_seen=[])

    try:
        health_response = session.get(f"{base_url}/health", timeout=REQUEST_TIMEOUT_SEC)
        result.health_ok = health_response.status_code == 200
        if result.health_ok:
            payload = health_response.json()
            result.health_status = str(payload.get("status", "")).strip()
            result.healthy_backends = int(payload.get("healthy_backends", 0) or 0)

        wikipedia_response = session.get(
            f"{base_url}/search",
            params={"q": "wikipedia", "num": 10},
            timeout=REQUEST_TIMEOUT_SEC,
        )
        wikipedia_payload = (
            wikipedia_response.json() if wikipedia_response.status_code == 200 else {}
        )
        result.wikipedia_ok = wikipedia_response.status_code == 200 and bool(
            wikipedia_payload.get("success", False)
        )
        result.wikipedia_result_count = int(
            wikipedia_payload.get("result_count", 0) or 0
        )
        result.play_result_present = any(
            item.get("url", "").startswith("https://play.google.com/")
            for item in wikipedia_payload.get("results", [])
        )
        backend_name = str(wikipedia_payload.get("backend", "")).strip()
        if backend_name:
            result.backends_seen.append(backend_name)

        for query, expected_hl, min_results in [
            ("玩机器切片", "zh", 5),
            ("東京の天気予報", "ja", 5),
            ("bonjour paris actualites", "fr", 5),
        ]:
            response = session.get(
                f"{base_url}/search",
                params={"q": query, "num": 10},
                timeout=REQUEST_TIMEOUT_SEC,
            )
            payload = response.json() if response.status_code == 200 else {}
            backend_name = str(payload.get("backend", "")).strip()
            if backend_name and backend_name not in result.backends_seen:
                result.backends_seen.append(backend_name)
            result_count = int(payload.get("result_count", 0) or 0)
            result.locale_audits.append(
                QueryAudit(
                    query=query,
                    expected_hl=expected_hl,
                    status_code=response.status_code,
                    inferred_hl=(
                        expected_hl
                        if response.status_code == 200 and result_count >= min_results
                        else ""
                    ),
                    result_count=result_count,
                    success=response.status_code == 200
                    and bool(payload.get("success", False))
                    and result_count >= min_results,
                    error="" if response.status_code == 200 else response.text[:160],
                )
            )
    except Exception as exc:
        result.error = str(exc)[:200]
    finally:
        session.close()

    return result


def summarize_spaces(results: list[SpaceAudit]) -> dict:
    summary = {
        "space_count": len(results),
        "healthy_count": sum(1 for item in results if item.health_ok),
        "search_ok_count": sum(1 for item in results if item.search_ok),
        "raw_ok_count": sum(1 for item in results if item.raw_ok),
        "play_result_count": sum(1 for item in results if item.play_result_present),
        "locale_ok_counts": {"zh-CN": 0, "ja": 0, "fr": 0},
    }
    for item in results:
        for audit in item.locale_audits or []:
            if audit.success and audit.expected_hl in summary["locale_ok_counts"]:
                summary["locale_ok_counts"][audit.expected_hl] += 1
    return summary


def summarize_hub(result: HubAudit | None) -> dict:
    if result is None:
        return {}
    summary = {
        "health_ok": result.health_ok,
        "healthy_backends": result.healthy_backends,
        "wikipedia_ok": result.wikipedia_ok,
        "wikipedia_result_count": result.wikipedia_result_count,
        "play_result_present": result.play_result_present,
        "locale_ok_counts": {"zh": 0, "ja": 0, "fr": 0},
    }
    for audit in result.locale_audits or []:
        if audit.success and audit.expected_hl in summary["locale_ok_counts"]:
            summary["locale_ok_counts"][audit.expected_hl] += 1
    return summary


def format_audit_summary(payload: dict) -> str:
    lines: list[str] = []
    elapsed_sec = payload.get("elapsed_sec")
    if elapsed_sec is not None:
        lines.append(f"Audit completed in {elapsed_sec}s")
    else:
        lines.append("Audit completed")

    summary = payload.get("summary", {}) or {}
    spaces_summary = summary.get("spaces", {}) or {}
    if spaces_summary:
        space_count = int(spaces_summary.get("space_count", 0) or 0)
        locale_counts = spaces_summary.get("locale_ok_counts", {}) or {}
        locale_text = ", ".join(
            f"{name} {int(count or 0)}/{space_count}"
            for name, count in locale_counts.items()
        )
        lines.append(
            "Spaces: "
            f"healthy {int(spaces_summary.get('healthy_count', 0) or 0)}/{space_count}, "
            f"search {int(spaces_summary.get('search_ok_count', 0) or 0)}/{space_count}, "
            f"raw {int(spaces_summary.get('raw_ok_count', 0) or 0)}/{space_count}, "
            f"play-result {int(spaces_summary.get('play_result_count', 0) or 0)}/{space_count}, "
            f"locale [{locale_text}]"
        )

    hub_summary = summary.get("hub", {}) or {}
    if hub_summary:
        locale_counts = hub_summary.get("locale_ok_counts", {}) or {}
        locale_text = ", ".join(
            f"{name} {int(count or 0)}/1" for name, count in locale_counts.items()
        )
        lines.append(
            "Hub: "
            f"health {'ok' if hub_summary.get('health_ok') else 'bad'}, "
            f"healthy_backends {int(hub_summary.get('healthy_backends', 0) or 0)}, "
            f"wikipedia {'ok' if hub_summary.get('wikipedia_ok') else 'bad'} ({int(hub_summary.get('wikipedia_result_count', 0) or 0)} results), "
            f"play-result {'yes' if hub_summary.get('play_result_present') else 'no'}, "
            f"locale [{locale_text}]"
        )

    failures: list[str] = []
    for item in payload.get("spaces", []) or []:
        error = str(item.get("error", "")).strip()
        if error:
            failures.append(f"space {item.get('space', '')}: {error}")
    hub_payload = payload.get("hub") or {}
    hub_error = str(hub_payload.get("error", "")).strip()
    if hub_error:
        failures.append(f"hub: {hub_error}")

    if failures:
        lines.append("Failures:")
        lines.extend(f"- {failure}" for failure in failures)
    else:
        lines.append("Failures: none")

    backends_seen = list(hub_payload.get("backends_seen") or [])
    if backends_seen:
        lines.append(f"Hub backends seen: {', '.join(backends_seen)}")

    return "\n".join(lines)


def run_audit(*, target: str = "all", hub_url: str = "", output_path: str = "") -> dict:
    started = time.time()
    token = resolve_search_api_token()
    spaces_results: list[SpaceAudit] = []
    hub_result: HubAudit | None = None

    if target in {"spaces", "all"}:
        spaces_results = [
            audit_space(space, base_url, token) for space, base_url in resolve_spaces()
        ]

    if target in {"hub", "all"}:
        hub_result = audit_hub(hub_url.strip() or resolve_hub_url())

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - started, 2),
        "summary": {
            "spaces": summarize_spaces(spaces_results) if spaces_results else {},
            "hub": summarize_hub(hub_result),
        },
        "spaces": [item.to_dict() for item in spaces_results],
        "hub": hub_result.to_dict() if hub_result else None,
    }

    if output_path:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return payload


def audit_has_failures(payload: dict) -> bool:
    for item in payload.get("spaces", []):
        if str(item.get("error", "")).strip():
            return True
    hub_payload = payload.get("hub") or {}
    return bool(str(hub_payload.get("error", "")).strip())
