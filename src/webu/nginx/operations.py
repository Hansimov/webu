from __future__ import annotations

import shlex
import tempfile

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from webu.ssh.operations import copy_to as ssh_copy_to
from webu.ssh.operations import exec_host as ssh_exec_host


DEFAULT_REMOTE_CONF_DIR = "/etc/nginx/conf.d"
DEFAULT_NGINX_TEST_COMMAND = "nginx -t"
DEFAULT_NGINX_RELOAD_COMMAND = "nginx -s reload"
DEFAULT_ACME_ROOT = "/usr/share/nginx/html"
DEFAULT_STATIC_CACHE_PATH = "/tmp/webu-nginx-cache"
DEFAULT_STATIC_CACHE_MAX_SIZE = "512m"
DEFAULT_STATIC_CACHE_INACTIVE = "7d"
DEFAULT_STATIC_CACHE_VALID = "30d"
DEFAULT_STATIC_BROWSER_CACHE = "31536000"


def _require_text(value: object, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


def _safe_file_token(value: str) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch in {"-", "_", "."} else "-"
        for ch in str(value or "").strip().lower()
    )
    return cleaned.strip("-.") or "default"


def _normalize_server_names(server_names: list[str]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for item in server_names:
        cleaned = str(item or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        items.append(cleaned)
    if not items:
        raise ValueError("at least one server name is required")
    return items


def _safe_nginx_token(value: str) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch == "_" else "_"
        for ch in str(value or "").strip().lower()
    )
    cleaned = cleaned.strip("_")
    if not cleaned:
        return "default"
    if cleaned[0].isdigit():
        return f"z_{cleaned}"
    return cleaned


def _require_nginx_simple_value(value: object, label: str) -> str:
    normalized = _require_text(value, label)
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./:-")
    if any(ch not in allowed for ch in normalized):
        raise ValueError(f"{label} contains unsupported nginx directive characters")
    return normalized


def _require_browser_max_age(value: object) -> str:
    normalized = _require_text(value, "static_cache_browser_max_age")
    if not normalized.isdigit():
        raise ValueError("static_cache_browser_max_age must be an integer second value")
    return normalized


def _render_proxy_common(upstream_url: str) -> list[str]:
    parsed = urlparse(_require_text(upstream_url, "upstream_url"))
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("upstream_url must start with http:// or https://")
    lines = [
        f"        proxy_pass {upstream_url};",
        "        proxy_http_version 1.1;",
        "        proxy_set_header Host $host;",
        "        proxy_set_header X-Real-IP $remote_addr;",
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
        "        proxy_set_header X-Forwarded-Proto $scheme;",
        '        proxy_set_header Connection "";',
    ]
    if parsed.scheme == "https":
        lines.extend(
            [
                "        proxy_ssl_server_name on;",
                "        proxy_ssl_verify off;",
            ]
        )
    lines.extend(
        [
            "        proxy_read_timeout 60s;",
            "        proxy_send_timeout 60s;",
        ]
    )
    return lines


def _render_proxy_location(upstream_url: str) -> list[str]:
    return [
        "    location / {",
        *_render_proxy_common(upstream_url),
        "    }",
    ]


def _render_static_cache_locations(
    upstream_url: str,
    *,
    cache_zone: str,
    browser_max_age_seconds: str,
) -> list[str]:
    safe_zone = _safe_nginx_token(cache_zone)
    max_age = _require_browser_max_age(
        browser_max_age_seconds or DEFAULT_STATIC_BROWSER_CACHE
    )
    return [
        "    location ^~ /assets/ {",
        f"        proxy_cache {safe_zone};",
        "        proxy_cache_lock on;",
        f"        proxy_cache_valid 200 301 302 {DEFAULT_STATIC_CACHE_VALID};",
        "        proxy_cache_valid 404 1m;",
        "        proxy_ignore_headers Set-Cookie;",
        "        proxy_hide_header Set-Cookie;",
        f'        add_header Cache-Control "public, max-age={max_age}, immutable" always;',
        '        add_header X-WebU-Relay-Cache "$upstream_cache_status" always;',
        *_render_proxy_common(upstream_url),
        "    }",
        "",
        "    location ^~ /icons/ {",
        f"        proxy_cache {safe_zone};",
        "        proxy_cache_lock on;",
        f"        proxy_cache_valid 200 301 302 {DEFAULT_STATIC_CACHE_VALID};",
        "        proxy_cache_valid 404 1m;",
        "        proxy_ignore_headers Set-Cookie;",
        "        proxy_hide_header Set-Cookie;",
        f'        add_header Cache-Control "public, max-age={max_age}, immutable" always;',
        '        add_header X-WebU-Relay-Cache "$upstream_cache_status" always;',
        *_render_proxy_common(upstream_url),
        "    }",
    ]


def _render_static_cache_path(
    *,
    enabled: bool,
    cache_zone: str,
    cache_path: str,
    max_size: str,
    inactive: str,
) -> list[str]:
    if not enabled:
        return []
    safe_zone = _safe_nginx_token(cache_zone)
    safe_path = _require_nginx_simple_value(cache_path, "static_cache_path")
    safe_max_size = _require_nginx_simple_value(
        max_size or DEFAULT_STATIC_CACHE_MAX_SIZE,
        "static_cache_max_size",
    )
    safe_inactive = _require_nginx_simple_value(
        inactive or DEFAULT_STATIC_CACHE_INACTIVE,
        "static_cache_inactive",
    )
    return [
        f"proxy_cache_path {safe_path} levels=1:2 keys_zone={safe_zone}:20m "
        f"max_size={safe_max_size} inactive={safe_inactive} use_temp_path=off;",
        "",
    ]


def _render_access_by_lua_override(disable_access_by_lua: bool) -> list[str]:
    if not disable_access_by_lua:
        return []
    return [
        "    access_by_lua_block {",
        "    }",
    ]


def render_reverse_proxy_site(
    *,
    server_names: list[str],
    upstream_url: str,
    listen_http: bool = True,
    listen_https: bool = False,
    redirect_https: bool = False,
    disable_access_by_lua: bool = False,
    ssl_certificate: str = "",
    ssl_certificate_key: str = "",
    acme_root: str = DEFAULT_ACME_ROOT,
    enable_static_cache: bool = False,
    static_cache_zone: str = "",
    static_cache_path: str = DEFAULT_STATIC_CACHE_PATH,
    static_cache_max_size: str = DEFAULT_STATIC_CACHE_MAX_SIZE,
    static_cache_inactive: str = DEFAULT_STATIC_CACHE_INACTIVE,
    static_cache_browser_max_age: str = DEFAULT_STATIC_BROWSER_CACHE,
) -> str:
    normalized_names = _normalize_server_names(server_names)
    if listen_https and (not ssl_certificate or not ssl_certificate_key):
        raise ValueError(
            "ssl_certificate and ssl_certificate_key are required when listen_https=true"
        )

    cache_zone = static_cache_zone or normalized_names[0]
    static_cache_locations = (
        _render_static_cache_locations(
            upstream_url,
            cache_zone=cache_zone,
            browser_max_age_seconds=static_cache_browser_max_age,
        )
        if enable_static_cache
        else []
    )
    blocks: list[str] = _render_static_cache_path(
        enabled=enable_static_cache,
        cache_zone=cache_zone,
        cache_path=static_cache_path,
        max_size=static_cache_max_size,
        inactive=static_cache_inactive,
    )
    server_name_line = f"    server_name {' '.join(normalized_names)};"
    access_by_lua_override = _render_access_by_lua_override(disable_access_by_lua)
    acme_block = [
        "    location ^~ /.well-known/acme-challenge/ {",
        f"        root {acme_root};",
        "        allow all;",
        "    }",
    ]

    if listen_http:
        http_lines = [
            "server {",
            "    listen 80;",
            server_name_line,
            *access_by_lua_override,
            *acme_block,
        ]
        if redirect_https and listen_https:
            http_lines.extend(
                [
                    "    location / {",
                    "        return 301 https://$host$request_uri;",
                    "    }",
                ]
            )
        else:
            http_lines.extend(static_cache_locations)
            http_lines.extend(_render_proxy_location(upstream_url))
        http_lines.append("}")
        blocks.append("\n".join(http_lines))

    if listen_https:
        https_lines = [
            "server {",
            "    listen 443 ssl http2;",
            server_name_line,
            *access_by_lua_override,
            f"    ssl_certificate {ssl_certificate};",
            f"    ssl_certificate_key {ssl_certificate_key};",
            "    ssl_protocols TLSv1.2 TLSv1.3;",
            *acme_block,
            *static_cache_locations,
            *_render_proxy_location(upstream_url),
            "}",
        ]
        blocks.append("\n".join(https_lines))

    return "\n\n".join(blocks).rstrip() + "\n"


def remote_site_apply(
    *,
    host_name: str,
    site_name: str,
    server_names: list[str],
    upstream_url: str,
    remote_conf_dir: str = DEFAULT_REMOTE_CONF_DIR,
    test_command: str = DEFAULT_NGINX_TEST_COMMAND,
    reload_command: str = DEFAULT_NGINX_RELOAD_COMMAND,
    listen_http: bool = True,
    listen_https: bool = False,
    redirect_https: bool = False,
    disable_access_by_lua: bool = False,
    ssl_certificate: str = "",
    ssl_certificate_key: str = "",
    acme_root: str = DEFAULT_ACME_ROOT,
    enable_static_cache: bool = False,
    static_cache_zone: str = "",
    static_cache_path: str = DEFAULT_STATIC_CACHE_PATH,
    static_cache_max_size: str = DEFAULT_STATIC_CACHE_MAX_SIZE,
    static_cache_inactive: str = DEFAULT_STATIC_CACHE_INACTIVE,
    static_cache_browser_max_age: str = DEFAULT_STATIC_BROWSER_CACHE,
) -> dict[str, Any]:
    rendered = render_reverse_proxy_site(
        server_names=server_names,
        upstream_url=upstream_url,
        listen_http=listen_http,
        listen_https=listen_https,
        redirect_https=redirect_https,
        disable_access_by_lua=disable_access_by_lua,
        ssl_certificate=ssl_certificate,
        ssl_certificate_key=ssl_certificate_key,
        acme_root=acme_root,
        enable_static_cache=enable_static_cache,
        static_cache_zone=static_cache_zone or site_name,
        static_cache_path=static_cache_path,
        static_cache_max_size=static_cache_max_size,
        static_cache_inactive=static_cache_inactive,
        static_cache_browser_max_age=static_cache_browser_max_age,
    )
    file_name = f"{_safe_file_token(site_name)}.conf"
    remote_conf_path = f"{remote_conf_dir.rstrip('/')}/{file_name}"
    remote_tmp_path = f"/tmp/{file_name}.webu.tmp"

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp_file:
        tmp_file.write(rendered)
        tmp_path = Path(tmp_file.name)

    try:
        upload_result = ssh_copy_to(
            name=host_name,
            local_path=str(tmp_path),
            remote_path=remote_tmp_path,
        )
        remote_script = "\n".join(
            [
                "set -e",
                f"conf={shlex.quote(remote_conf_path)}",
                f"tmp={shlex.quote(remote_tmp_path)}",
                'bak="${conf}.webu.bak"',
                "had_conf=0",
                f"mkdir -p {shlex.quote(remote_conf_dir)}",
                'if [ -f "$conf" ]; then cp "$conf" "$bak"; had_conf=1; fi',
                'mv "$tmp" "$conf"',
                f"if ! {test_command}; then",
                '  if [ "$had_conf" = "1" ]; then mv "$bak" "$conf"; else rm -f "$conf"; fi',
                f"  {test_command} || true",
                "  exit 1",
                "fi",
                'rm -f "$bak"',
                f"{reload_command}",
            ]
        )
        apply_result = ssh_exec_host(
            name=host_name, command=remote_script, timeout_seconds=120
        )
        if apply_result["returncode"] != 0:
            raise RuntimeError(
                apply_result["stderr"]
                or apply_result["stdout"]
                or "remote nginx apply failed"
            )
        return {
            "host_name": host_name,
            "site_name": site_name,
            "server_names": _normalize_server_names(server_names),
            "upstream_url": upstream_url,
            "remote_conf_path": remote_conf_path,
            "config_upload": upload_result,
            "apply": apply_result,
            "content": rendered,
        }
    finally:
        tmp_path.unlink(missing_ok=True)


def remote_site_show(
    *,
    host_name: str,
    site_name: str,
    remote_conf_dir: str = DEFAULT_REMOTE_CONF_DIR,
) -> dict[str, Any]:
    file_name = f"{_safe_file_token(site_name)}.conf"
    remote_conf_path = f"{remote_conf_dir.rstrip('/')}/{file_name}"
    result = ssh_exec_host(
        name=host_name,
        command=f"cat {shlex.quote(remote_conf_path)}",
        timeout_seconds=30,
    )
    return {
        "host_name": host_name,
        "site_name": site_name,
        "remote_conf_path": remote_conf_path,
        **result,
    }


def remote_site_disable(
    *,
    host_name: str,
    site_name: str,
    remote_conf_dir: str = DEFAULT_REMOTE_CONF_DIR,
    test_command: str = DEFAULT_NGINX_TEST_COMMAND,
    reload_command: str = DEFAULT_NGINX_RELOAD_COMMAND,
) -> dict[str, Any]:
    file_name = f"{_safe_file_token(site_name)}.conf"
    remote_conf_path = f"{remote_conf_dir.rstrip('/')}/{file_name}"
    remote_script = " && ".join(
        [
            f"rm -f {shlex.quote(remote_conf_path)}",
            f"{test_command}",
            f"{reload_command}",
        ]
    )
    result = ssh_exec_host(name=host_name, command=remote_script, timeout_seconds=120)
    return {
        "host_name": host_name,
        "site_name": site_name,
        "remote_conf_path": remote_conf_path,
        **result,
    }
