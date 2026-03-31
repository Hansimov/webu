from __future__ import annotations

import json
import re
import shlex
import socket
import ssl
import shutil
import subprocess
import tempfile
from collections import defaultdict

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from webu.clis import prompt_choice, prompt_secret, prompt_text
from webu.schema import (
    find_project_root,
    render_config_markdown,
    render_template_json,
    validate_payload_against_schema,
)
from webu.sudo import run as sudo_run

from .clients import (
    AliyunApiError,
    AliyunDomainClient,
    CloudflareApiError,
    CloudflareClient,
)
from .helptext import CONFIGS_DOC_PATH, USAGE_DOC_PATH, render_usage_markdown
from .schema import (
    CF_TUNNEL_CONFIG,
    DomainConfig,
    TunnelConfig,
    infer_zone_name,
    list_domains,
    list_tunnels,
    load_cf_tunnel_config,
    save_cf_tunnel_config,
    upsert_domain,
    upsert_tunnel,
)


@dataclass(frozen=True)
class CloudflareCredentialResolution:
    api_token: str
    source: str
    created: bool


CLOUDFLARED_TUNNEL_SERVICE_PREFIX = "cloudflared-tunnel"


def _require_text(value: str, label: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


def _safe_systemd_token(value: str) -> str:
    safe = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return safe or "default"


def cloudflared_tunnel_service_name(tunnel_name: str) -> str:
    return f"{CLOUDFLARED_TUNNEL_SERVICE_PREFIX}-{_safe_systemd_token(tunnel_name)}.service"


def _cloudflared_tunnel_service_path(tunnel_name: str) -> Path:
    return Path("/etc/systemd/system") / cloudflared_tunnel_service_name(tunnel_name)


def _summarize_completed_process(
    completed: subprocess.CompletedProcess[bytes],
) -> dict[str, Any]:
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.decode(errors="replace").strip(),
        "stderr": completed.stderr.decode(errors="replace").strip(),
    }


def _ensure_success(
    completed: subprocess.CompletedProcess[bytes], *, label: str
) -> dict[str, Any]:
    summary = _summarize_completed_process(completed)
    if completed.returncode != 0:
        details = summary["stderr"] or summary["stdout"] or "unknown error"
        raise RuntimeError(f"{label} failed: {details}")
    return summary


def _render_cloudflared_tunnel_service_unit(
    *, tunnel_name: str, tunnel_token: str
) -> str:
    cloudflared_bin = shutil.which("cloudflared") or "/usr/bin/cloudflared"
    exec_start = shlex.join(
        [cloudflared_bin, "--no-autoupdate", "tunnel", "run", "--token", tunnel_token]
    )
    return "\n".join(
        [
            "[Unit]",
            f"Description=cloudflared tunnel for {tunnel_name}",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f"ExecStart={exec_start}",
            "Restart=always",
            "RestartSec=5s",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ]
    )


def _install_cloudflared_tunnel_service(
    *, tunnel_name: str, tunnel_token: str
) -> dict[str, Any]:
    service_name = cloudflared_tunnel_service_name(tunnel_name)
    service_path = _cloudflared_tunnel_service_path(tunnel_name)
    unit_text = _render_cloudflared_tunnel_service_unit(
        tunnel_name=tunnel_name,
        tunnel_token=tunnel_token,
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(unit_text)
        temp_path = Path(handle.name)

    try:
        write_result = _ensure_success(
            sudo_run(
                [
                    "install",
                    "-D",
                    "-m",
                    "644",
                    str(temp_path),
                    str(service_path),
                ],
                check=False,
                timeout=60,
            ),
            label=f"install systemd unit {service_name}",
        )
        daemon_reload_result = _ensure_success(
            sudo_run(["systemctl", "daemon-reload"], check=False, timeout=60),
            label="systemctl daemon-reload",
        )
        enable_result = _ensure_success(
            sudo_run(
                ["systemctl", "enable", service_name],
                check=False,
                timeout=60,
            ),
            label=f"systemctl enable {service_name}",
        )
        restart_result = _ensure_success(
            sudo_run(
                ["systemctl", "restart", service_name],
                check=False,
                timeout=60,
            ),
            label=f"systemctl restart {service_name}",
        )
        status_result = _ensure_success(
            sudo_run(
                [
                    "systemctl",
                    "show",
                    "--property",
                    "LoadState,ActiveState,SubState",
                    service_name,
                ],
                check=False,
                timeout=60,
            ),
            label=f"systemctl show {service_name}",
        )
    finally:
        temp_path.unlink(missing_ok=True)

    return {
        "service_name": service_name,
        "service_path": str(service_path),
        "write_unit": write_result,
        "daemon_reload": daemon_reload_result,
        "enable_service": enable_result,
        "restart_service": restart_result,
        "service_status": status_result,
    }


def _domain_lookup(
    payload: dict[str, Any], domain_name: str, *, zone_name: str | None = None
) -> DomainConfig:
    for item in list_domains(payload):
        if item.domain_name == domain_name or item.zone_name == (zone_name or ""):
            return item
    resolved_zone_name = zone_name or infer_zone_name(domain_name)
    return DomainConfig(
        domain_name=domain_name,
        zone_name=resolved_zone_name,
        zone_id="",
        cloudflare_nameservers=[],
        aliyun_task_no="",
        raw={},
    )


def _tunnel_lookup(
    payload: dict[str, Any], *, tunnel_name: str | None = None
) -> TunnelConfig:
    tunnels = list_tunnels(payload)
    if not tunnels:
        raise ValueError("no cf_tunnels entries found in configs/cf_tunnel.json")
    if tunnel_name:
        for item in tunnels:
            if item.tunnel_name == tunnel_name or item.domain_name == tunnel_name:
                return item
        raise ValueError(f"tunnel '{tunnel_name}' not found in configs/cf_tunnel.json")
    if len(tunnels) != 1:
        raise ValueError("multiple tunnels configured; choose one with --name")
    return tunnels[0]


def _write_payload(payload: dict[str, Any], *, save_config: bool) -> Path | None:
    if not save_config:
        return None
    return save_cf_tunnel_config(payload)


def ensure_cf_api_token(
    payload: dict[str, Any],
    *,
    account_id: str,
    zone_name: str,
    zone_id: str | None,
    token_mode: str,
    save_config: bool,
) -> CloudflareCredentialResolution:
    configured_api_token = str(payload.get("cf_api_token", "")).strip()
    if configured_api_token:
        return CloudflareCredentialResolution(configured_api_token, "config", False)

    if token_mode == "manual":
        manual_token = prompt_secret("Cloudflare API token")
        payload["cf_api_token"] = manual_token
        _write_payload(payload, save_config=save_config)
        return CloudflareCredentialResolution(manual_token, "manual", False)

    bootstrap_token = str(payload.get("cf_account_api_tokens_edit_token", "")).strip()
    if not bootstrap_token:
        if token_mode == "prompt":
            chosen = prompt_choice(
                "Cloudflare token source", ["manual", "existing"], default="manual"
            )
            if chosen == "manual":
                manual_token = prompt_secret("Cloudflare API token")
                payload["cf_api_token"] = manual_token
                _write_payload(payload, save_config=save_config)
                return CloudflareCredentialResolution(manual_token, "manual", False)
        raise ValueError(
            "cf_api_token is missing and cf_account_api_tokens_edit_token is unavailable for auto creation"
        )

    bootstrap_client = CloudflareClient(bootstrap_token)
    token_name = f"cftn-{zone_name}"
    created = bootstrap_client.create_api_token(
        name=token_name,
        account_id=account_id,
        zone_id=zone_id,
        include_zone_write=not bool(zone_id),
        expires_in_days=30,
    )
    payload["cf_api_token"] = created["value"]
    _write_payload(payload, save_config=save_config)
    return CloudflareCredentialResolution(created["value"], "auto", True)


def ensure_aliyun_client(
    payload: dict[str, Any], *, credential_mode: str
) -> AliyunDomainClient:
    access_id = str(payload.get("aliyun_access_id", "")).strip()
    access_secret = str(payload.get("aliyun_access_secret", "")).strip()
    if not access_id or not access_secret:
        if credential_mode != "manual":
            raise ValueError(
                "Aliyun credentials are missing; rerun with --aliyun-credential-mode manual or fill configs/cf_tunnel.json"
            )
        access_id = prompt_text("Aliyun AccessKey ID")
        access_secret = prompt_secret("Aliyun AccessKey Secret")
    return AliyunDomainClient(access_id, access_secret)


def ensure_domain_zone(
    payload: dict[str, Any],
    *,
    domain_name: str,
    zone_name: str | None,
    cf_token_mode: str,
    save_config: bool,
) -> tuple[dict[str, Any], DomainConfig, CloudflareCredentialResolution]:
    account_id = _require_text(str(payload.get("cf_account_id", "")), "cf_account_id")
    domain = _domain_lookup(payload, domain_name, zone_name=zone_name)
    bootstrap_or_existing = ensure_cf_api_token(
        payload,
        account_id=account_id,
        zone_name=domain.zone_name,
        zone_id=domain.zone_id or None,
        token_mode=cf_token_mode,
        save_config=save_config,
    )
    cf_client = CloudflareClient(bootstrap_or_existing.api_token)
    zone = cf_client.ensure_zone(account_id=account_id, zone_name=domain.zone_name)
    nameservers = [
        str(item).strip() for item in zone.get("name_servers", []) if str(item).strip()
    ]
    updated_domain = DomainConfig(
        domain_name=domain.domain_name,
        zone_name=domain.zone_name,
        zone_id=str(zone.get("id", "")).strip(),
        cloudflare_nameservers=nameservers,
        aliyun_task_no=domain.aliyun_task_no,
        raw=domain.raw,
    )
    payload = upsert_domain(payload, updated_domain)
    _write_payload(payload, save_config=save_config)

    if bootstrap_or_existing.created and not updated_domain.zone_id:
        return zone, updated_domain, bootstrap_or_existing

    if bootstrap_or_existing.source == "auto" and updated_domain.zone_id:
        return zone, updated_domain, bootstrap_or_existing

    if bootstrap_or_existing.source == "config" and updated_domain.zone_id:
        return zone, updated_domain, bootstrap_or_existing

    if str(payload.get("cf_api_token", "")).strip() and updated_domain.zone_id:
        return zone, updated_domain, bootstrap_or_existing

    return zone, updated_domain, bootstrap_or_existing


def migrate_dns_to_cloudflare(
    *,
    domain_name: str,
    zone_name: str | None,
    cf_token_mode: str,
    aliyun_credential_mode: str,
    save_config: bool,
) -> dict[str, Any]:
    payload = load_cf_tunnel_config()
    zone, domain, credential = ensure_domain_zone(
        payload,
        domain_name=domain_name,
        zone_name=zone_name,
        cf_token_mode=cf_token_mode,
        save_config=save_config,
    )
    nameservers = domain.cloudflare_nameservers
    if len(nameservers) < 2:
        raise CloudflareApiError(
            "Cloudflare did not return at least two assigned nameservers for the zone"
        )
    aliyun_client = ensure_aliyun_client(
        payload, credential_mode=aliyun_credential_mode
    )
    task_no = aliyun_client.modify_domain_dns(
        domain_name=domain.domain_name, nameservers=nameservers
    )
    task_details = aliyun_client.query_task_details(task_no=task_no)
    updated_domain = DomainConfig(
        domain_name=domain.domain_name,
        zone_name=domain.zone_name,
        zone_id=domain.zone_id,
        cloudflare_nameservers=nameservers,
        aliyun_task_no=task_no,
        raw=domain.raw,
    )
    payload = upsert_domain(payload, updated_domain)
    config_path = _write_payload(payload, save_config=save_config)
    return {
        "domain_name": domain.domain_name,
        "zone_name": domain.zone_name,
        "zone_id": domain.zone_id,
        "nameservers": nameservers,
        "aliyun_task_no": task_no,
        "aliyun_task_details": task_details,
        "cf_token_source": credential.source,
        "config_path": str(config_path) if config_path else "",
        "verification": {
            "precheck": [
                f"dig @{nameservers[0]} {domain.domain_name} A",
                f"dig @{nameservers[1]} {domain.domain_name} MX",
            ],
            "propagation": [
                f"dig {domain.domain_name} NS",
                f"dig +trace {domain.domain_name} A",
            ],
        },
    }


def apply_tunnel(
    *,
    tunnel_name: str | None,
    apply_all: bool,
    install_service: bool,
    cf_token_mode: str,
    save_config: bool,
) -> list[dict[str, Any]]:
    payload = load_cf_tunnel_config()
    account_id = _require_text(str(payload.get("cf_account_id", "")), "cf_account_id")
    targets = (
        list_tunnels(payload)
        if apply_all
        else [_tunnel_lookup(payload, tunnel_name=tunnel_name)]
    )
    results: list[dict[str, Any]] = []

    for item in targets:
        _, domain, credential = ensure_domain_zone(
            payload,
            domain_name=item.zone_name,
            zone_name=item.zone_name,
            cf_token_mode=cf_token_mode,
            save_config=save_config,
        )
        cf_client = CloudflareClient(credential.api_token)
        tunnel = cf_client.ensure_tunnel(
            account_id=account_id, tunnel_name=item.tunnel_name
        )
        tunnel_id = str(tunnel.get("id", item.tunnel_id)).strip()
        tunnel_token = str(
            tunnel.get("token", "")
        ).strip() or cf_client.get_tunnel_token(
            account_id=account_id, tunnel_id=tunnel_id
        )
        cf_client.put_tunnel_configuration(
            account_id=account_id,
            tunnel_id=tunnel_id,
            hostname=item.domain_name,
            service=item.local_url,
        )
        cf_client.upsert_cname_record(
            zone_id=domain.zone_id,
            hostname=item.domain_name,
            content=f"{tunnel_id}.cfargotunnel.com",
            proxied=True,
        )
        updated_tunnel = TunnelConfig(
            tunnel_name=item.tunnel_name,
            domain_name=item.domain_name,
            local_url=item.local_url,
            zone_name=item.zone_name,
            tunnel_id=tunnel_id,
            tunnel_token=tunnel_token,
            raw=item.raw,
        )
        payload = upsert_tunnel(payload, updated_tunnel)
        config_path = _write_payload(payload, save_config=save_config)
        install_result: dict[str, Any] | None = None
        if install_service:
            if not shutil.which("cloudflared"):
                raise FileNotFoundError("cloudflared is not installed or not in PATH")
            install_result = _install_cloudflared_tunnel_service(
                tunnel_name=item.tunnel_name,
                tunnel_token=tunnel_token,
            )
        results.append(
            {
                "tunnel_name": item.tunnel_name,
                "domain_name": item.domain_name,
                "local_url": item.local_url,
                "zone_name": item.zone_name,
                "tunnel_id": tunnel_id,
                "tunnel_token_saved": bool(tunnel_token),
                "install_command": (
                    f"install/update {cloudflared_tunnel_service_name(item.tunnel_name)}"
                ),
                "install_result": install_result or {},
                "cf_token_source": credential.source,
                "config_path": str(config_path) if config_path else "",
            }
        )
    return results


def tunnel_status(*, tunnel_name: str | None, cf_token_mode: str) -> dict[str, Any]:
    payload = load_cf_tunnel_config()
    account_id = _require_text(str(payload.get("cf_account_id", "")), "cf_account_id")
    target = _tunnel_lookup(payload, tunnel_name=tunnel_name)
    credential = ensure_cf_api_token(
        payload,
        account_id=account_id,
        zone_name=target.zone_name,
        zone_id=None,
        token_mode=cf_token_mode,
        save_config=False,
    )
    cf_client = CloudflareClient(credential.api_token)
    tunnel_id = target.tunnel_id
    if not tunnel_id:
        tunnel = cf_client.ensure_tunnel(
            account_id=account_id, tunnel_name=target.tunnel_name
        )
        tunnel_id = str(tunnel.get("id", "")).strip()
    result = cf_client.get_tunnel(account_id=account_id, tunnel_id=tunnel_id)
    return {
        "tunnel_name": target.tunnel_name,
        "tunnel_id": tunnel_id,
        "status": result.get("status", "unknown"),
        "connections": result.get("connections", []),
        "conns_active_at": result.get("conns_active_at"),
        "conns_inactive_at": result.get("conns_inactive_at"),
    }


def ensure_token(
    *, zone_name: str, cf_token_mode: str, save_config: bool
) -> dict[str, Any]:
    payload = load_cf_tunnel_config()
    account_id = _require_text(str(payload.get("cf_account_id", "")), "cf_account_id")
    zone_matches = [
        item for item in list_domains(payload) if item.zone_name == zone_name
    ]
    zone_id = zone_matches[0].zone_id if zone_matches else ""
    credential = ensure_cf_api_token(
        payload,
        account_id=account_id,
        zone_name=zone_name,
        zone_id=zone_id or None,
        token_mode=cf_token_mode,
        save_config=save_config,
    )
    return {
        "zone_name": zone_name,
        "source": credential.source,
        "created": credential.created,
    }


def _resolve_system_addresses(hostname: str) -> list[str]:
    addresses: list[str] = []
    seen: set[str] = set()
    for family, _, _, _, sockaddr in socket.getaddrinfo(
        hostname, 443, type=socket.SOCK_STREAM
    ):
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        address = str(sockaddr[0]).strip()
        if not address or address in seen:
            continue
        seen.add(address)
        addresses.append(address)
    return addresses


def _resolve_cloudflare_addresses(
    hostname: str, *, record_type: str = "A"
) -> list[str]:
    try:
        response = requests.get(
            "https://cloudflare-dns.com/dns-query",
            params={"name": hostname, "type": record_type},
            headers={"accept": "application/dns-json"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        answers = payload.get("Answer", [])
        resolved: list[str] = []
        seen: set[str] = set()
        for answer in answers if isinstance(answers, list) else []:
            if not isinstance(answer, dict):
                continue
            data = str(answer.get("data", "")).strip().rstrip(".")
            if not data or data in seen:
                continue
            seen.add(data)
            resolved.append(data)
        return resolved
    except Exception as primary_error:
        if shutil.which("dig"):
            completed = subprocess.run(
                ["dig", "@1.1.1.1", hostname, record_type, "+short"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if completed.returncode == 0:
                return [
                    line.strip().rstrip(".")
                    for line in completed.stdout.splitlines()
                    if line.strip()
                ]
            fallback_error = completed.stderr.strip() or completed.stdout.strip()
        else:
            fallback_error = "dig command not available"
        raise RuntimeError(
            f"Cloudflare DNS lookup failed: {primary_error}; fallback failed: {fallback_error}"
        ) from primary_error


def _flatten_certificate_name(values: Any) -> list[str]:
    flattened: list[str] = []
    for item in values if isinstance(values, (list, tuple)) else []:
        if not isinstance(item, tuple):
            continue
        if len(item) == 1 and isinstance(item[0], tuple) and len(item[0]) == 2:
            key, value = item[0]
            text = f"{str(key).strip()}={str(value).strip()}"
        elif len(item) == 2:
            text = f"{str(item[0]).strip()}={str(item[1]).strip()}"
        else:
            text = ", ".join(str(part).strip() for part in item if str(part).strip())
        if text:
            flattened.append(text)
    return flattened


def _probe_https_endpoint(hostname: str, ip_address: str) -> dict[str, Any]:
    result: dict[str, Any] = {"ip": ip_address, "success": False}
    try:
        context = ssl.create_default_context()
        with socket.create_connection((ip_address, 443), timeout=8) as raw_sock:
            with context.wrap_socket(raw_sock, server_hostname=hostname) as tls_sock:
                certificate = tls_sock.getpeercert()
                request = (
                    f"HEAD / HTTP/1.1\r\n"
                    f"Host: {hostname}\r\n"
                    "User-Agent: cftn/1.0\r\n"
                    "Accept: */*\r\n"
                    "Connection: close\r\n\r\n"
                )
                tls_sock.sendall(request.encode("ascii"))
                raw_response = b""
                while b"\r\n\r\n" not in raw_response and len(raw_response) < 8192:
                    chunk = tls_sock.recv(4096)
                    if not chunk:
                        break
                    raw_response += chunk

                header_text = raw_response.decode("iso-8859-1", errors="replace")
                header_lines = header_text.splitlines()
                status_line = header_lines[0] if header_lines else ""
                status_code = None
                parts = status_line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    status_code = int(parts[1])

                result.update(
                    {
                        "success": True,
                        "tls_version": tls_sock.version(),
                        "status_line": status_line,
                        "status_code": status_code,
                        "subject": _flatten_certificate_name(
                            certificate.get("subject", [])
                        ),
                        "issuer": _flatten_certificate_name(
                            certificate.get("issuer", [])
                        ),
                        "subject_alt_names": [
                            str(name).strip()
                            for key, name in certificate.get("subjectAltName", [])
                            if key == "DNS" and str(name).strip()
                        ],
                        "not_before": certificate.get("notBefore", ""),
                        "not_after": certificate.get("notAfter", ""),
                    }
                )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _authoritative_dns_records(
    payload: dict[str, Any], hostname: str
) -> list[dict[str, Any]]:
    account_id = _require_text(str(payload.get("cf_account_id", "")), "cf_account_id")
    matching_tunnel = None
    for item in list_tunnels(payload):
        if item.domain_name == hostname or item.tunnel_name == hostname:
            matching_tunnel = item
            break

    zone_name = (
        matching_tunnel.zone_name if matching_tunnel else infer_zone_name(hostname)
    )
    zone_matches = [
        item for item in list_domains(payload) if item.zone_name == zone_name
    ]
    zone_id = zone_matches[0].zone_id if zone_matches else ""

    credential = ensure_cf_api_token(
        payload,
        account_id=account_id,
        zone_name=zone_name,
        zone_id=zone_id or None,
        token_mode="auto",
        save_config=False,
    )
    cf_client = CloudflareClient(credential.api_token)
    if not zone_id:
        zones = cf_client.list_zones(name=zone_name, account_id=account_id)
        zone_id = str(zones[0].get("id", "")).strip() if zones else ""
    if not zone_id:
        return []

    records = cf_client.list_dns_records(zone_id, name=hostname)
    if not records:
        records = [
            item
            for item in cf_client.list_dns_records(zone_id)
            if str(item.get("name", "")).strip() == hostname
        ]
    normalized: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "id": str(item.get("id", "")).strip(),
                "type": str(item.get("type", "")).strip(),
                "name": str(item.get("name", "")).strip(),
                "content": str(item.get("content", "")).strip(),
                "proxied": bool(item.get("proxied", False)),
            }
        )
    return normalized


def _zone_context(payload: dict[str, Any], hostname: str) -> tuple[str, str, list[str]]:
    matching_tunnel = None
    for item in list_tunnels(payload):
        if item.domain_name == hostname or item.tunnel_name == hostname:
            matching_tunnel = item
            break

    zone_name = (
        matching_tunnel.zone_name if matching_tunnel else infer_zone_name(hostname)
    )
    zone_matches = [
        item for item in list_domains(payload) if item.zone_name == zone_name
    ]
    zone_id = zone_matches[0].zone_id if zone_matches else ""
    nameservers = zone_matches[0].cloudflare_nameservers if zone_matches else []
    return zone_name, zone_id, nameservers


def _resolve_authoritative_nameserver_addresses(
    payload: dict[str, Any], hostname: str, *, record_type: str = "A"
) -> list[str]:
    zone_name, zone_id, nameservers = _zone_context(payload, hostname)
    account_id = _require_text(str(payload.get("cf_account_id", "")), "cf_account_id")

    if not nameservers:
        credential = ensure_cf_api_token(
            payload,
            account_id=account_id,
            zone_name=zone_name,
            zone_id=zone_id or None,
            token_mode="auto",
            save_config=False,
        )
        cf_client = CloudflareClient(credential.api_token)
        if not zone_id:
            zones = cf_client.list_zones(name=zone_name, account_id=account_id)
            zone_id = str(zones[0].get("id", "")).strip() if zones else ""
        if zone_id:
            zone = cf_client.get_zone(zone_id)
            nameservers = [
                str(item).strip()
                for item in zone.get("name_servers", [])
                if str(item).strip()
            ]

    addresses: list[str] = []
    seen: set[str] = set()
    errors: list[str] = []
    for nameserver in nameservers[:2]:
        completed = subprocess.run(
            ["dig", f"@{nameserver}", hostname, record_type, "+short"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if completed.returncode != 0:
            errors.append(completed.stderr.strip() or completed.stdout.strip())
            continue
        for line in completed.stdout.splitlines():
            item = line.strip().rstrip(".")
            if not item or item in seen:
                continue
            seen.add(item)
            addresses.append(item)

    if addresses:
        return addresses

    detail = (
        "; ".join(item for item in errors if item)
        or "no authoritative nameserver answers"
    )
    raise RuntimeError(detail)


def _fetch_https_endpoint(
    hostname: str,
    ip_address: str,
    *,
    path: str = "/",
    method: str = "GET",
    max_body_bytes: int = 262144,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ip": ip_address,
        "path": path,
        "method": method,
        "success": False,
    }
    try:
        context = ssl.create_default_context()
        with socket.create_connection((ip_address, 443), timeout=8) as raw_sock:
            with context.wrap_socket(raw_sock, server_hostname=hostname) as tls_sock:
                request = (
                    f"{method} {path} HTTP/1.1\r\n"
                    f"Host: {hostname}\r\n"
                    "User-Agent: cftn/1.0\r\n"
                    "Accept: */*\r\n"
                    "Connection: close\r\n\r\n"
                )
                tls_sock.sendall(request.encode("ascii"))
                raw_response = b""
                while len(raw_response) < max_body_bytes:
                    chunk = tls_sock.recv(16384)
                    if not chunk:
                        break
                    raw_response += chunk

                header_bytes, _, body_bytes = raw_response.partition(b"\r\n\r\n")
                header_text = header_bytes.decode("iso-8859-1", errors="replace")
                header_lines = header_text.splitlines()
                status_line = header_lines[0] if header_lines else ""
                headers: dict[str, str] = {}
                for line in header_lines[1:]:
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()

                status_code = None
                parts = status_line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    status_code = int(parts[1])

                content_type = headers.get("content-type", "")
                body_text = body_bytes.decode("utf-8", errors="replace")
                result.update(
                    {
                        "success": True,
                        "status_line": status_line,
                        "status_code": status_code,
                        "headers": headers,
                        "content_type": content_type,
                        "body_preview": body_text[:4000],
                    }
                )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _parse_key_value_lines(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip()
        if not normalized_key:
            continue
        result[normalized_key] = value.strip()
    return result


def _ip_family(ip_address: str) -> str:
    return "ipv6" if ":" in str(ip_address) else "ipv4"


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _platform_instructions(
    hostname: str, candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    hosts_lines = [item["hosts_line"] for item in candidates]
    return {
        "windows": {
            "supported": True,
            "method": "hosts-file",
            "hosts_path": r"C:\Windows\System32\drivers\etc\hosts",
            "hosts_lines": hosts_lines,
            "flush_commands": ["ipconfig /flushdns"],
            "verify": [
                f"curl -I https://{hostname} --max-time 20",
                f"curl https://{hostname}/cdn-cgi/trace --max-time 20",
            ],
        },
        "macos": {
            "supported": True,
            "method": "hosts-file",
            "hosts_path": "/etc/hosts",
            "hosts_lines": hosts_lines,
            "flush_commands": [
                "sudo dscacheutil -flushcache",
                "sudo killall -HUP mDNSResponder",
            ],
            "verify": [
                f"curl -I https://{hostname} --max-time 20",
                f"curl https://{hostname}/cdn-cgi/trace --max-time 20",
            ],
        },
        "linux": {
            "supported": True,
            "method": "hosts-file",
            "hosts_path": "/etc/hosts",
            "hosts_lines": hosts_lines,
            "flush_commands": [
                "sudo resolvectl flush-caches",
                "sudo systemd-resolve --flush-caches",
                "sudo service nscd restart",
            ],
            "verify": [
                f"getent ahosts {hostname}",
                f"curl -I https://{hostname} --max-time 20",
                f"curl https://{hostname}/cdn-cgi/trace --max-time 20",
            ],
        },
        "android": {
            "supported": True,
            "method": "local-dns-override",
            "note": "Stock Android generally cannot edit per-host hosts mappings without root. Use a canary Wi-Fi/router DNS override or a device-local DNS tool that supports host overrides.",
            "dns_override": {"hostname": hostname, "records": hosts_lines},
            "verify": [
                f"https://{hostname}",
                f"https://{hostname}/cdn-cgi/trace",
            ],
        },
        "ios": {
            "supported": True,
            "method": "local-dns-override",
            "note": "Stock iOS generally cannot edit per-host hosts mappings directly. Use a controlled Wi-Fi/router DNS override or a device-local DNS profile/tool that supports host overrides.",
            "dns_override": {"hostname": hostname, "records": hosts_lines},
            "verify": [
                f"https://{hostname}",
                f"https://{hostname}/cdn-cgi/trace",
            ],
        },
    }


def _default_client_report(
    hostname: str,
    tunnel_name: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "hostname": hostname,
        "tunnel_name": tunnel_name,
        "report_version": 1,
        "reports": [
            {
                "region": "",
                "city": "",
                "isp": "",
                "network_type": "broadband|5g|4g|wifi",
                "platform": "windows|macos|linux|android|ios",
                "device_model": "",
                "ip_family": item["family"],
                "candidate_ip": item["ip"],
                "candidate_colo": item["colo"],
                "success": None,
                "ttfb_ms": None,
                "page_ok": None,
                "trace_colo": "",
                "trace_loc": "",
                "cf_ray": "",
                "notes": "",
            }
            for item in candidates
        ],
    }


def _normalize_asset_path(value: str) -> str:
    item = str(value).strip()
    if not item:
        return ""
    if item.startswith("//"):
        return f"https:{item}"
    return item


def _page_findings(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    scripts = [
        _normalize_asset_path(tag.get("src", "")) for tag in soup.find_all("script")
    ]
    links = [
        _normalize_asset_path(tag.get("href", "")) for tag in soup.find_all("link")
    ]
    images = [_normalize_asset_path(tag.get("src", "")) for tag in soup.find_all("img")]
    forms = [
        _normalize_asset_path(tag.get("action", "")) for tag in soup.find_all("form")
    ]
    all_refs = [item for item in [*scripts, *links, *images, *forms] if item]
    explicit_insecure = [
        item
        for item in all_refs
        if item.startswith("http://") or item.startswith("ws://")
    ]
    dev_markers: list[str] = []
    marker_candidates = [
        "/@vite/client",
        "@vite-plugin-checker-runtime",
        "/.quasar/client-entry.js",
        "__vite_ping",
    ]
    for marker in marker_candidates:
        if marker in html:
            dev_markers.append(marker)
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    return {
        "title": title,
        "scripts": [item for item in scripts if item],
        "links": [item for item in links if item],
        "images": [item for item in images if item],
        "forms": [item for item in forms if item],
        "explicit_insecure_refs": explicit_insecure,
        "development_markers": dev_markers,
    }


def _resource_checks(
    hostname: str, ip_address: str, findings: dict[str, Any]
) -> list[dict[str, Any]]:
    targets: list[str] = []
    for item in [*findings.get("scripts", []), *findings.get("links", [])]:
        text = str(item).strip()
        if not text:
            continue
        if text.startswith("/"):
            targets.append(text)
        elif text.startswith(f"https://{hostname}/"):
            targets.append(text.removeprefix(f"https://{hostname}"))
    seen: set[str] = set()
    checks: list[dict[str, Any]] = []
    for target in targets:
        if target in seen:
            continue
        seen.add(target)
        checks.append(
            _fetch_https_endpoint(hostname, ip_address, path=target, method="GET")
        )
        if len(checks) >= 6:
            break
    return checks


def page_audit(
    *,
    tunnel_name: str | None,
    hostname: str | None,
    path: str,
) -> dict[str, Any]:
    payload = load_cf_tunnel_config()
    diagnosis = access_diagnose(tunnel_name=tunnel_name, hostname=hostname)
    resolved_hostname = diagnosis["hostname"]
    resolved_tunnel_name = diagnosis["tunnel_name"]
    normalized_path = str(path or "/").strip() or "/"
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"

    system_fetches = [
        _fetch_https_endpoint(resolved_hostname, item, path=normalized_path)
        for item in diagnosis["dns"]["system_resolver"]["addresses"][:2]
    ]
    cloudflare_fetches = [
        _fetch_https_endpoint(resolved_hostname, item, path=normalized_path)
        for item in diagnosis["dns"]["cloudflare_doh"]["addresses"][:2]
    ]
    authoritative_ns_fetches = [
        _fetch_https_endpoint(resolved_hostname, item, path=normalized_path)
        for item in diagnosis["dns"]
        .get("cloudflare_authoritative_ns", {})
        .get("addresses", [])[:2]
    ]

    selected_source = ""
    selected_fetch: dict[str, Any] | None = None
    for source_name, fetches in (
        ("cloudflare_authoritative_ns", authoritative_ns_fetches),
        ("cloudflare_doh", cloudflare_fetches),
        ("system_resolver", system_fetches),
    ):
        for item in fetches:
            if item.get("success") and str(item.get("content_type", "")).startswith(
                "text/html"
            ):
                selected_source = source_name
                selected_fetch = item
                break
        if selected_fetch:
            break

    page_findings: dict[str, Any] = {}
    resource_checks: list[dict[str, Any]] = []
    diagnosis_lines: list[str] = []
    recommendations: list[str] = []

    if selected_fetch:
        page_findings = _page_findings(str(selected_fetch.get("body_preview", "")))
        resource_checks = _resource_checks(
            resolved_hostname,
            str(selected_fetch.get("ip", "")).strip(),
            page_findings,
        )

        if page_findings.get("development_markers"):
            diagnosis_lines.append(
                "The public page looks like a Vite/Quasar development entrypoint. This strongly suggests the tunnel is exposing a dev server or dev build instead of a production bundle."
            )
            recommendations.append(
                "Do not publish the dev server directly. Build the frontend for production and serve the built assets behind a production web server, or disable HMR/dev middleware on the public hostname."
            )

        if page_findings.get("explicit_insecure_refs"):
            diagnosis_lines.append(
                "The HTML contains explicit http:// or ws:// resource references, which can trigger mixed-content or insecure-connection warnings in browsers."
            )
            recommendations.append(
                "Rewrite all page resources and form actions to https:// or protocol-relative safe paths, and avoid ws:// on HTTPS pages."
            )

        broken_assets = [
            item
            for item in resource_checks
            if item.get("success") and int(item.get("status_code") or 0) >= 400
        ]
        if broken_assets:
            diagnosis_lines.append(
                "The page references frontend assets that currently return 4xx through the public hostname, so the page may render partially or fail at runtime."
            )
            recommendations.append(
                "Make sure every referenced JS/CSS asset is available on the public hostname, or replace dev-only asset paths with production build outputs."
            )
    else:
        diagnosis_lines.append(
            "No successful HTML response was obtained from the tested paths, so page-level auditing could not continue."
        )

    if not recommendations:
        recommendations.append(
            "If the page still appears insecure in a browser, inspect DevTools console and network logs for blocked mixed-content requests or failed websocket upgrades."
        )

    return {
        "hostname": resolved_hostname,
        "tunnel_name": resolved_tunnel_name,
        "path": normalized_path,
        "access_diagnose": diagnosis,
        "fetches": {
            "system_resolver": system_fetches,
            "cloudflare_doh": cloudflare_fetches,
            "cloudflare_authoritative_ns": authoritative_ns_fetches,
            "selected_source": selected_source,
        },
        "page": {
            "findings": page_findings,
            "resource_checks": resource_checks,
        },
        "diagnosis": diagnosis_lines,
        "recommendations": recommendations,
    }


def edge_trace(
    *, tunnel_name: str | None, hostname: str | None, path: str = "/cdn-cgi/trace"
) -> dict[str, Any]:
    diagnosis = access_diagnose(tunnel_name=tunnel_name, hostname=hostname)
    resolved_hostname = diagnosis["hostname"]
    resolved_tunnel_name = diagnosis["tunnel_name"]
    normalized_path = str(path or "/cdn-cgi/trace").strip() or "/cdn-cgi/trace"
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"

    sources = {
        "system_resolver": diagnosis["dns"]["system_resolver"]["addresses"],
        "cloudflare_doh": diagnosis["dns"]["cloudflare_doh"]["addresses"],
        "cloudflare_authoritative_ns": diagnosis["dns"]["cloudflare_authoritative_ns"][
            "addresses"
        ],
    }

    per_source: dict[str, list[dict[str, Any]]] = {}
    unique_results: list[dict[str, Any]] = []
    seen_ips: set[str] = set()
    all_colos: set[str] = set()
    failures: list[str] = []

    for source_name, addresses in sources.items():
        entries: list[dict[str, Any]] = []
        for ip_address in addresses[:2]:
            response = _fetch_https_endpoint(
                resolved_hostname,
                ip_address,
                path=normalized_path,
                method="GET",
                max_body_bytes=32768,
            )
            trace = _parse_key_value_lines(response.get("body_preview", ""))
            headers = response.get("headers", {}) if response.get("success") else {}
            ray_id = (
                str(headers.get("cf-ray", "")).strip()
                if isinstance(headers, dict)
                else ""
            )
            colo = str(trace.get("colo", "")).strip()
            if colo:
                all_colos.add(colo)
            if not response.get("success"):
                failures.append(f"{source_name}:{ip_address}")
            entry = {
                "ip": ip_address,
                "success": bool(response.get("success")),
                "status_code": response.get("status_code"),
                "content_type": response.get("content_type", ""),
                "server": (
                    headers.get("server", "") if isinstance(headers, dict) else ""
                ),
                "cf_ray": ray_id,
                "colo": colo,
                "trace": trace,
                "error": response.get("error", ""),
            }
            entries.append(entry)
            if ip_address not in seen_ips:
                seen_ips.add(ip_address)
                unique_results.append(entry)
        per_source[source_name] = entries

    diagnosis_lines: list[str] = []
    recommendations: list[str] = []

    if failures and len(failures) != len(seen_ips):
        diagnosis_lines.append(
            "Some pinned edge IP probes succeeded while others failed. This is compatible with resolver-path drift or network-dependent interception, not a uniformly broken tunnel."
        )
    if len(all_colos) > 1:
        diagnosis_lines.append(
            "Successful probes landed in multiple Cloudflare colos. That is expected on Anycast and is a reminder that a single 'preferred IP' is not globally stable across networks or time."
        )
    elif all_colos:
        diagnosis_lines.append(
            "The tested successful probes currently converge on the same Cloudflare colo from this network."
        )
    if not unique_results:
        diagnosis_lines.append(
            "No edge probe results were collected, so colo-level comparison is unavailable."
        )

    recommendations.append(
        "Treat these results as measurement-only for the current network. Mainland preferred-IP experiments must be run from actual mainland user networks or representative probes, not from a foreign VPS or unrelated server."
    )
    recommendations.append(
        "Do not publish hand-picked A records for a proxied tunnel hostname in Cloudflare DNS. If you experiment with preferred IPs, do it on the client side via hosts or a controlled local DNS override, and keep the authoritative zone on Cloudflare's managed proxy records."
    )
    recommendations.append(
        "If mainland performance must be contractual and stable, the Cloudflare-supported path is China Network or Global Acceleration on Enterprise with ICP-related prerequisites, not ad-hoc fixed-IP pinning."
    )

    return {
        "hostname": resolved_hostname,
        "tunnel_name": resolved_tunnel_name,
        "path": normalized_path,
        "access_diagnose": diagnosis,
        "edge_probes": per_source,
        "unique_edge_results": unique_results,
        "diagnosis": diagnosis_lines,
        "recommendations": recommendations,
    }


def client_override_plan(
    *,
    tunnel_name: str | None,
    hostname: str | None,
    prefer_family: str,
    max_candidates: int,
) -> dict[str, Any]:
    trace = edge_trace(tunnel_name=tunnel_name, hostname=hostname)
    resolved_hostname = trace["hostname"]
    resolved_tunnel_name = trace["tunnel_name"]
    allowed_families = {"ipv4", "ipv6"} if prefer_family == "any" else {prefer_family}
    max_items = max(1, int(max_candidates))

    candidates: list[dict[str, Any]] = []
    seen_ips: set[str] = set()
    for item in trace.get("unique_edge_results", []):
        if not item.get("success"):
            continue
        ip_address = str(item.get("ip", "")).strip()
        if not ip_address or ip_address in seen_ips:
            continue
        family = _ip_family(ip_address)
        if family not in allowed_families:
            continue
        seen_ips.add(ip_address)
        candidates.append(
            {
                "ip": ip_address,
                "family": family,
                "colo": str(item.get("colo", "")).strip(),
                "cf_ray": str(item.get("cf_ray", "")).strip(),
                "hosts_line": f"{ip_address} {resolved_hostname}",
                "curl_validate": f"curl --resolve {resolved_hostname}:443:{ip_address} https://{resolved_hostname}/cdn-cgi/trace --max-time 20",
                "curl_head": f"curl --resolve {resolved_hostname}:443:{ip_address} -I https://{resolved_hostname} --max-time 20",
            }
        )
        if len(candidates) >= max_items:
            break

    diagnosis: list[str] = []
    recommendations: list[str] = []
    warnings: list[str] = []

    if candidates:
        diagnosis.append(
            "The plan below is suitable for small-batch client-side hosts or local DNS override experiments. It keeps Cloudflare authoritative DNS unchanged and only changes resolution on selected clients."
        )
    else:
        diagnosis.append(
            "No successful edge candidates were found under the requested IP family filter, so there is nothing safe to export for a client-side override experiment."
        )

    if prefer_family == "any":
        recommendations.append(
            "For mainland users, start with IPv4 canaries first. Add IPv6 only if the user network has proven IPv6 quality; otherwise dual-stack overrides can make behavior less predictable."
        )
    elif prefer_family == "ipv6":
        warnings.append(
            "IPv6 overrides should only be tested on user networks with confirmed IPv6 reachability and stable routing."
        )

    recommendations.append(
        "Roll out to a very small canary group first, for example 3 to 10 users on the same ISP or region, and collect success rate, TTFB, and whether the reported colo improves."
    )
    recommendations.append(
        "Ask canary users to remove existing browser DNS cache, system DNS cache, and any previous hosts overrides before each test round."
    )
    recommendations.append(
        "Validation should use both the main page and /cdn-cgi/trace. The main page confirms application behavior, while trace confirms the actual Cloudflare colo reached by that pinned IP."
    )
    recommendations.append(
        "Do not push these overrides into the public zone. Keep them client-side only, and keep the authoritative record as the proxied Cloudflare tunnel hostname."
    )

    warnings.append(
        "Anycast edge behavior is time-dependent and network-dependent. A candidate IP that is good today for one ISP may degrade later or perform worse on another ISP."
    )
    warnings.append(
        "If a client-side preferred IP causes certificate failure, timeout, or a different unexpected hostname, remove the override immediately and fall back to normal DNS resolution."
    )

    return {
        "hostname": resolved_hostname,
        "tunnel_name": resolved_tunnel_name,
        "prefer_family": prefer_family,
        "max_candidates": max_items,
        "edge_trace": trace,
        "candidates": candidates,
        "distribution": {
            "linux_macos_hosts": [item["hosts_line"] for item in candidates],
            "windows_hosts": [item["hosts_line"] for item in candidates],
        },
        "rollback": {
            "remove_hosts_lines": [item["hosts_line"] for item in candidates],
            "verify_normal_dns": [
                f"getent ahosts {resolved_hostname}",
                f"curl -I https://{resolved_hostname} --max-time 20",
            ],
        },
        "diagnosis": diagnosis,
        "recommendations": recommendations,
        "warnings": warnings,
    }


def client_canary_bundle(
    *,
    tunnel_name: str | None,
    hostname: str | None,
    prefer_family: str,
    max_candidates: int,
) -> dict[str, Any]:
    plan = client_override_plan(
        tunnel_name=tunnel_name,
        hostname=hostname,
        prefer_family=prefer_family,
        max_candidates=max_candidates,
    )
    hostname_value = plan["hostname"]
    tunnel_name_value = plan["tunnel_name"]
    candidates = plan["candidates"]
    return {
        "hostname": hostname_value,
        "tunnel_name": tunnel_name_value,
        "prefer_family": prefer_family,
        "candidates": candidates,
        "platforms": _platform_instructions(hostname_value, candidates),
        "report_template": _default_client_report(
            hostname_value, tunnel_name_value, candidates
        ),
        "rollout": {
            "canary_group_size": "3-10 users per ISP or region",
            "stages": [
                "Run one candidate IP at a time for each ISP or region cohort.",
                "Collect success, TTFB, page rendering, and /cdn-cgi/trace colo from each client.",
                "Promote only candidates that are stable across multiple devices on the same ISP.",
                "Keep a fallback cohort on normal DNS to detect regressions quickly.",
            ],
        },
        "recommendations": [
            "Prefer ISP-specific and region-specific winners over a single nationwide preferred IP.",
            "Desktop and mobile should be validated separately because mobile often follows different DNS and transport paths.",
            "If Android or iOS canaries are required, push the override at the local DNS layer for the test Wi-Fi or test router instead of relying on per-device hosts edits.",
        ],
    }


def client_report_template(
    *,
    tunnel_name: str | None,
    hostname: str | None,
    prefer_family: str,
    max_candidates: int,
) -> dict[str, Any]:
    bundle = client_canary_bundle(
        tunnel_name=tunnel_name,
        hostname=hostname,
        prefer_family=prefer_family,
        max_candidates=max_candidates,
    )
    return bundle["report_template"]


def client_report_summary(*, report_file: str) -> dict[str, Any]:
    payload = json.loads(Path(report_file).read_text(encoding="utf-8"))
    reports = payload.get("reports", []) if isinstance(payload, dict) else payload
    if not isinstance(reports, list):
        raise ValueError(
            "report_file must contain a JSON object with a reports array or a JSON array"
        )

    by_ip: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_isp: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    by_platform: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    normalized_reports: list[dict[str, Any]] = []
    for item in reports:
        if not isinstance(item, dict):
            continue
        candidate_ip = str(item.get("candidate_ip", "")).strip()
        if not candidate_ip:
            continue
        success = bool(item.get("success"))
        ttfb_ms = _safe_float(item.get("ttfb_ms"))
        record = {
            "region": str(item.get("region", "")).strip(),
            "city": str(item.get("city", "")).strip(),
            "isp": str(item.get("isp", "")).strip() or "unknown",
            "network_type": str(item.get("network_type", "")).strip(),
            "platform": str(item.get("platform", "")).strip() or "unknown",
            "device_model": str(item.get("device_model", "")).strip(),
            "candidate_ip": candidate_ip,
            "candidate_colo": str(item.get("candidate_colo", "")).strip(),
            "success": success,
            "ttfb_ms": ttfb_ms,
            "page_ok": (
                bool(item.get("page_ok")) if item.get("page_ok") is not None else None
            ),
            "trace_colo": str(item.get("trace_colo", "")).strip(),
            "trace_loc": str(item.get("trace_loc", "")).strip(),
            "cf_ray": str(item.get("cf_ray", "")).strip(),
            "notes": str(item.get("notes", "")).strip(),
        }
        normalized_reports.append(record)
        by_ip[candidate_ip].append(record)
        by_isp[record["isp"]][candidate_ip].append(record)
        by_platform[record["platform"]][candidate_ip].append(record)

    def summarize_group(group: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for candidate_ip, items in group.items():
            total = len(items)
            success_count = sum(1 for item in items if item["success"])
            ttfb_values = [
                item["ttfb_ms"]
                for item in items
                if item["ttfb_ms"] is not None and item["success"]
            ]
            avg_ttfb = (
                _mean([float(item) for item in ttfb_values]) if ttfb_values else None
            )
            colos = sorted({item["trace_colo"] for item in items if item["trace_colo"]})
            score = (success_count / total) * 1000 if total else 0
            if avg_ttfb is not None:
                score -= avg_ttfb / 10
            rows.append(
                {
                    "candidate_ip": candidate_ip,
                    "sample_count": total,
                    "success_count": success_count,
                    "success_rate": round(success_count / total, 4) if total else 0,
                    "avg_ttfb_ms": round(avg_ttfb, 2) if avg_ttfb is not None else None,
                    "trace_colos": colos,
                    "score": round(score, 2),
                }
            )
        return sorted(
            rows,
            key=lambda item: (
                -item["score"],
                -item["success_rate"],
                item["avg_ttfb_ms"] or 1e9,
            ),
        )

    overall = summarize_group(by_ip)
    per_isp = {isp: summarize_group(group) for isp, group in by_isp.items()}
    per_platform = {
        platform: summarize_group(group) for platform, group in by_platform.items()
    }

    recommendations: list[str] = []
    if overall:
        recommendations.append(
            "Use the overall ranking only as a starting point. Prefer per-ISP winners when the leading candidate differs across carriers."
        )
    if any(
        len(rows) > 1 and rows[0]["candidate_ip"] != overall[0]["candidate_ip"]
        for rows in per_isp.values()
        if rows and overall
    ):
        recommendations.append(
            "At least one ISP has a different best candidate from the overall winner. Use ISP-specific distribution instead of a single universal preferred IP."
        )
    if any(
        len(rows) > 1 and rows[0]["candidate_ip"] != overall[0]["candidate_ip"]
        for rows in per_platform.values()
        if rows and overall
    ):
        recommendations.append(
            "Desktop and mobile winners are diverging. Keep separate rollout groups for different platforms."
        )
    recommendations.append(
        "Do not promote a candidate to a larger audience until it has successful samples from multiple users in the same ISP and at least two device categories."
    )

    return {
        "sample_count": len(normalized_reports),
        "overall": overall,
        "per_isp": per_isp,
        "per_platform": per_platform,
        "recommendations": recommendations,
    }


def access_diagnose(*, tunnel_name: str | None, hostname: str | None) -> dict[str, Any]:
    payload = load_cf_tunnel_config()
    resolved_hostname = str(hostname or "").strip()
    resolved_tunnel_name = str(tunnel_name or "").strip()

    if not resolved_hostname:
        tunnel = _tunnel_lookup(payload, tunnel_name=resolved_tunnel_name or None)
        resolved_hostname = tunnel.domain_name
        resolved_tunnel_name = tunnel.tunnel_name

    system_addresses = _resolve_system_addresses(resolved_hostname)
    cloudflare_addresses: list[str] = []
    cloudflare_cnames: list[str] = []
    cloudflare_lookup_errors: list[str] = []
    authoritative_ns_addresses: list[str] = []
    authoritative_ns_errors: list[str] = []
    authoritative_records: list[dict[str, Any]] = []
    authoritative_error = ""

    try:
        authoritative_records = _authoritative_dns_records(payload, resolved_hostname)
    except Exception as exc:
        authoritative_error = str(exc)

    try:
        cloudflare_addresses = _resolve_cloudflare_addresses(
            resolved_hostname, record_type="A"
        )
    except Exception as exc:
        cloudflare_lookup_errors.append(str(exc))

    try:
        cloudflare_cnames = _resolve_cloudflare_addresses(
            resolved_hostname, record_type="CNAME"
        )
    except Exception as exc:
        cloudflare_lookup_errors.append(str(exc))

    try:
        authoritative_ns_addresses = _resolve_authoritative_nameserver_addresses(
            payload, resolved_hostname, record_type="A"
        )
    except Exception as exc:
        authoritative_ns_errors.append(str(exc))

    system_probes = [
        _probe_https_endpoint(resolved_hostname, item) for item in system_addresses[:2]
    ]
    cloudflare_probes = [
        _probe_https_endpoint(resolved_hostname, item)
        for item in cloudflare_addresses[:2]
    ]
    authoritative_ns_probes = [
        _probe_https_endpoint(resolved_hostname, item)
        for item in authoritative_ns_addresses[:2]
    ]

    comparison_targets = authoritative_ns_addresses or cloudflare_addresses
    mismatch = bool(system_addresses and comparison_targets) and set(
        system_addresses
    ) != set(comparison_targets)
    recursive_mismatch = bool(
        cloudflare_addresses and authoritative_ns_addresses
    ) and set(cloudflare_addresses) != set(authoritative_ns_addresses)
    system_https_ok = any(item.get("success") for item in system_probes)
    cloudflare_https_ok = any(item.get("success") for item in cloudflare_probes)
    authoritative_ns_https_ok = any(
        item.get("success") for item in authoritative_ns_probes
    )
    https_ok = system_https_ok or cloudflare_https_ok or authoritative_ns_https_ok
    https_failed = any(
        not item.get("success")
        for item in [*system_probes, *cloudflare_probes, *authoritative_ns_probes]
    )
    diagnosis: list[str] = []
    recommendations: list[str] = []

    if mismatch:
        diagnosis.append(
            "System DNS answers differ from Cloudflare DoH answers. On mainland networks this usually indicates local DNS hijacking or DNS pollution on the visitor side."
        )
    if recursive_mismatch:
        diagnosis.append(
            "Recursive resolver answers differ from Cloudflare authoritative nameserver answers. This indicates that at least one public DNS resolution path is being polluted or intercepted before it reaches the zone's true records."
        )
    if authoritative_records:
        proxied_tunnel_records = [
            item
            for item in authoritative_records
            if item.get("proxied")
            and item.get("type") == "CNAME"
            and str(item.get("content", "")).endswith(".cfargotunnel.com")
        ]
        if proxied_tunnel_records:
            diagnosis.append(
                "Cloudflare authoritative DNS confirms that the hostname is a proxied CNAME pointing at a tunnel target."
            )
    if mismatch and https_ok and https_failed:
        diagnosis.append(
            "Different resolver paths are reaching different network endpoints. At least one path completes HTTPS successfully while another path fails TLS, which is consistent with DNS pollution or resolver interception rather than a broken tunnel."
        )
    if (cloudflare_https_ok or authoritative_ns_https_ok) and not system_https_ok:
        diagnosis.append(
            "HTTPS works when the hostname is forced to Cloudflare edge IPs, but fails on the system-resolved address. Tunnel and edge certificate are healthy; the current access problem is in DNS resolution, not tunnel creation."
        )
    if (
        system_https_ok
        and not (cloudflare_https_ok or authoritative_ns_https_ok)
        and mismatch
    ):
        diagnosis.append(
            "The system resolver currently reaches a valid HTTPS endpoint, but the alternate Cloudflare lookup path reaches a different address that fails TLS. This split behavior is typical of resolver poisoning or unstable preferred-IP fronting on the current network."
        )
    if authoritative_records and not system_https_ok:
        diagnosis.append(
            "Cloudflare has the expected tunnel DNS record, but the current network path still cannot complete TLS to the resolved address. This is consistent with DNS pollution, transparent interception, or an incompatible preferred-IP fronting setup."
        )
    if https_ok:
        diagnosis.append(
            "A Cloudflare edge path is presenting a valid certificate for the hostname."
        )
    elif cloudflare_addresses or system_addresses:
        diagnosis.append(
            "DNS resolution returned reachable IPs, but HTTPS probing failed on all tested paths. Check Cloudflare edge certificate issuance, tunnel configuration, and origin health."
        )
    if not mismatch and system_https_ok:
        diagnosis.append(
            "System DNS and Cloudflare authoritative nameserver answers are consistent, and HTTPS probing succeeded from the current network."
        )

    recommendations.append(
        "Do not replace a proxied Cloudflare Tunnel hostname with a manually selected 'preferred Cloudflare IP'. Community preferred-IP workflows are meant for direct CDN hostname testing or hosts overrides, not for Cloudflare Tunnel visitor routing."
    )
    recommendations.append(
        "If mainland-first low latency is mandatory, place a nearby reverse proxy or relay in Hong Kong, Japan, or Singapore, or use a mainland-compliant CDN/front door. Public Cloudflare Tunnel alone cannot guarantee stable low-latency access from mainland China."
    )
    recommendations.append(
        "Enable DNSSEC for the zone at Cloudflare and publish the DS record at the registrar to reduce spoofed DNS responses on validating resolvers."
    )
    recommendations.append(
        "If browsers still show 'connection not secure' after DNS is correct, inspect the page for mixed content such as http:// images, scripts, CSS, or form actions, and enable Automatic HTTPS Rewrites where appropriate."
    )

    return {
        "hostname": resolved_hostname,
        "tunnel_name": resolved_tunnel_name,
        "dns": {
            "system_resolver": {"addresses": system_addresses},
            "cloudflare_doh": {
                "addresses": cloudflare_addresses,
                "cnames": cloudflare_cnames,
                "errors": cloudflare_lookup_errors,
            },
            "cloudflare_authoritative_ns": {
                "addresses": authoritative_ns_addresses,
                "errors": authoritative_ns_errors,
            },
            "cloudflare_authoritative": {
                "records": authoritative_records,
                "error": authoritative_error,
            },
            "mismatch": mismatch,
            "recursive_mismatch": recursive_mismatch,
        },
        "https": {
            "system_resolver": system_probes,
            "cloudflare_doh": cloudflare_probes,
            "cloudflare_authoritative_ns": authoritative_ns_probes,
        },
        "diagnosis": diagnosis,
        "recommendations": recommendations,
    }


def config_schema_json() -> dict[str, Any]:
    return CF_TUNNEL_CONFIG.schema


def config_check() -> list[str]:
    payload = load_cf_tunnel_config()
    return validate_payload_against_schema(
        payload, CF_TUNNEL_CONFIG.schema, CF_TUNNEL_CONFIG.name
    )


def config_init(*, force: bool) -> str:
    path = find_project_root()
    config_path = Path(path / "configs" / CF_TUNNEL_CONFIG.file_name)
    if config_path.exists() and not force:
        raise FileExistsError(
            f"{config_path} already exists; rerun with --force to overwrite"
        )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(render_template_json(CF_TUNNEL_CONFIG), encoding="utf-8")
    return str(config_path)


def docs_sync() -> dict[str, str]:
    USAGE_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIGS_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    USAGE_DOC_PATH.write_text(render_usage_markdown(), encoding="utf-8")
    CONFIGS_DOC_PATH.write_text(
        render_config_markdown([CF_TUNNEL_CONFIG]), encoding="utf-8"
    )
    return {"usage": str(USAGE_DOC_PATH), "configs": str(CONFIGS_DOC_PATH)}
