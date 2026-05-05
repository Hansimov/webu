from __future__ import annotations

import argparse
import os

from pathlib import Path

from webu.clis import print_json

from .operations import (
    DEFAULT_ACME_ROOT,
    DEFAULT_STATIC_BROWSER_CACHE,
    DEFAULT_STATIC_CACHE_INACTIVE,
    DEFAULT_STATIC_CACHE_MAX_SIZE,
    DEFAULT_STATIC_CACHE_PATH,
    DEFAULT_NGINX_RELOAD_COMMAND,
    DEFAULT_NGINX_TEST_COMMAND,
    DEFAULT_REMOTE_CONF_DIR,
    remote_cert_install,
    remote_site_apply,
    remote_site_disable,
    remote_site_show,
    render_reverse_proxy_site,
)


def _add_runtime_path_options(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--project-root",
        default="",
        help="Explicit webu project root used to resolve relative paths and project-local outputs.",
    )
    parser.add_argument(
        "--config-dir",
        default="",
        help="Explicit directory containing webu JSON configs such as configs/ssh.json.",
    )


def _apply_runtime_path_overrides(args) -> None:
    project_root = str(getattr(args, "project_root", "") or "").strip()
    config_dir = str(getattr(args, "config_dir", "") or "").strip()

    if project_root:
        os.environ["WEBU_PROJECT_ROOT"] = str(Path(project_root).expanduser().resolve())
    if config_dir:
        os.environ["WEBU_CONFIG_DIR"] = str(Path(config_dir).expanduser().resolve())


def _server_names(args) -> list[str]:
    return list(args.server_name or [])


def cmd_render_reverse_proxy(args):
    print_json(
        {
            "content": render_reverse_proxy_site(
                server_names=_server_names(args),
                upstream_url=args.upstream_url,
                listen_http=args.listen_http,
                listen_https=args.listen_https,
                redirect_https=args.redirect_https,
                disable_access_by_lua=args.disable_access_by_lua,
                ssl_certificate=args.ssl_certificate,
                ssl_certificate_key=args.ssl_certificate_key,
                acme_root=args.acme_root,
                enable_static_cache=args.enable_static_cache,
                static_cache_zone=args.static_cache_zone,
                static_cache_path=args.static_cache_path,
                static_cache_max_size=args.static_cache_max_size,
                static_cache_inactive=args.static_cache_inactive,
                static_cache_browser_max_age=args.static_cache_browser_max_age,
            )
        }
    )


def cmd_remote_site_apply(args):
    print_json(
        remote_site_apply(
            host_name=args.host_name,
            site_name=args.site_name,
            server_names=_server_names(args),
            upstream_url=args.upstream_url,
            remote_conf_dir=args.remote_conf_dir,
            test_command=args.test_command,
            reload_command=args.reload_command,
            listen_http=args.listen_http,
            listen_https=args.listen_https,
            redirect_https=args.redirect_https,
            disable_access_by_lua=args.disable_access_by_lua,
            ssl_certificate=args.ssl_certificate,
            ssl_certificate_key=args.ssl_certificate_key,
            acme_root=args.acme_root,
            enable_static_cache=args.enable_static_cache,
            static_cache_zone=args.static_cache_zone,
            static_cache_path=args.static_cache_path,
            static_cache_max_size=args.static_cache_max_size,
            static_cache_inactive=args.static_cache_inactive,
            static_cache_browser_max_age=args.static_cache_browser_max_age,
        )
    )


def cmd_remote_cert_install(args):
    print_json(
        remote_cert_install(
            host_name=args.host_name,
            local_fullchain=args.local_fullchain,
            local_privkey=args.local_privkey,
            remote_cert_dir=args.remote_cert_dir,
            fullchain_name=args.fullchain_name,
            privkey_name=args.privkey_name,
            test_command=args.test_command,
            reload_command=args.reload_command,
        )
    )


def cmd_remote_site_show(args):
    print_json(
        remote_site_show(
            host_name=args.host_name,
            site_name=args.site_name,
            remote_conf_dir=args.remote_conf_dir,
        )
    )


def cmd_remote_site_disable(args):
    print_json(
        remote_site_disable(
            host_name=args.host_name,
            site_name=args.site_name,
            remote_conf_dir=args.remote_conf_dir,
            test_command=args.test_command,
            reload_command=args.reload_command,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wngx",
        description="Render and apply nginx/openresty reverse-proxy site configs for webu.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    render_parser = subparsers.add_parser(
        "render-reverse-proxy",
        help="Render a reverse-proxy nginx site config.",
    )
    render_parser.add_argument("--server-name", action="append", required=True)
    render_parser.add_argument("--upstream-url", required=True)
    render_parser.add_argument("--listen-http", action="store_true", default=False)
    render_parser.add_argument("--listen-https", action="store_true", default=False)
    render_parser.add_argument("--redirect-https", action="store_true")
    render_parser.add_argument("--disable-access-by-lua", action="store_true")
    render_parser.add_argument("--ssl-certificate", default="")
    render_parser.add_argument("--ssl-certificate-key", default="")
    render_parser.add_argument("--acme-root", default=DEFAULT_ACME_ROOT)
    render_parser.add_argument("--enable-static-cache", action="store_true")
    render_parser.add_argument("--static-cache-zone", default="")
    render_parser.add_argument("--static-cache-path", default=DEFAULT_STATIC_CACHE_PATH)
    render_parser.add_argument(
        "--static-cache-max-size", default=DEFAULT_STATIC_CACHE_MAX_SIZE
    )
    render_parser.add_argument(
        "--static-cache-inactive", default=DEFAULT_STATIC_CACHE_INACTIVE
    )
    render_parser.add_argument(
        "--static-cache-browser-max-age", default=DEFAULT_STATIC_BROWSER_CACHE
    )
    _add_runtime_path_options(render_parser)
    render_parser.set_defaults(func=cmd_render_reverse_proxy)

    apply_parser = subparsers.add_parser(
        "remote-site-apply",
        help="Upload and apply a rendered nginx site config on a remote host over SSH.",
    )
    apply_parser.add_argument("--host-name", required=True)
    apply_parser.add_argument("--site-name", required=True)
    apply_parser.add_argument("--server-name", action="append", required=True)
    apply_parser.add_argument("--upstream-url", required=True)
    apply_parser.add_argument("--remote-conf-dir", default=DEFAULT_REMOTE_CONF_DIR)
    apply_parser.add_argument("--test-command", default=DEFAULT_NGINX_TEST_COMMAND)
    apply_parser.add_argument("--reload-command", default=DEFAULT_NGINX_RELOAD_COMMAND)
    apply_parser.add_argument("--listen-http", action="store_true", default=False)
    apply_parser.add_argument("--listen-https", action="store_true", default=False)
    apply_parser.add_argument("--redirect-https", action="store_true")
    apply_parser.add_argument("--disable-access-by-lua", action="store_true")
    apply_parser.add_argument("--ssl-certificate", default="")
    apply_parser.add_argument("--ssl-certificate-key", default="")
    apply_parser.add_argument("--acme-root", default=DEFAULT_ACME_ROOT)
    apply_parser.add_argument("--enable-static-cache", action="store_true")
    apply_parser.add_argument("--static-cache-zone", default="")
    apply_parser.add_argument("--static-cache-path", default=DEFAULT_STATIC_CACHE_PATH)
    apply_parser.add_argument(
        "--static-cache-max-size", default=DEFAULT_STATIC_CACHE_MAX_SIZE
    )
    apply_parser.add_argument(
        "--static-cache-inactive", default=DEFAULT_STATIC_CACHE_INACTIVE
    )
    apply_parser.add_argument(
        "--static-cache-browser-max-age", default=DEFAULT_STATIC_BROWSER_CACHE
    )
    _add_runtime_path_options(apply_parser)
    apply_parser.set_defaults(func=cmd_remote_site_apply)

    cert_parser = subparsers.add_parser(
        "remote-cert-install",
        help="Copy a local TLS certificate pair to a remote nginx/openresty cert directory.",
    )
    cert_parser.add_argument("--host-name", required=True)
    cert_parser.add_argument("--local-fullchain", required=True)
    cert_parser.add_argument("--local-privkey", required=True)
    cert_parser.add_argument("--remote-cert-dir", required=True)
    cert_parser.add_argument("--fullchain-name", default="fullchain.pem")
    cert_parser.add_argument("--privkey-name", default="privkey.pem")
    cert_parser.add_argument("--test-command", default="")
    cert_parser.add_argument("--reload-command", default="")
    _add_runtime_path_options(cert_parser)
    cert_parser.set_defaults(func=cmd_remote_cert_install)

    show_parser = subparsers.add_parser(
        "remote-site-show",
        help="Show a remote nginx site config over SSH.",
    )
    show_parser.add_argument("--host-name", required=True)
    show_parser.add_argument("--site-name", required=True)
    show_parser.add_argument("--remote-conf-dir", default=DEFAULT_REMOTE_CONF_DIR)
    _add_runtime_path_options(show_parser)
    show_parser.set_defaults(func=cmd_remote_site_show)

    disable_parser = subparsers.add_parser(
        "remote-site-disable",
        help="Remove a remote nginx site config over SSH and reload nginx.",
    )
    disable_parser.add_argument("--host-name", required=True)
    disable_parser.add_argument("--site-name", required=True)
    disable_parser.add_argument("--remote-conf-dir", default=DEFAULT_REMOTE_CONF_DIR)
    disable_parser.add_argument("--test-command", default=DEFAULT_NGINX_TEST_COMMAND)
    disable_parser.add_argument(
        "--reload-command", default=DEFAULT_NGINX_RELOAD_COMMAND
    )
    _add_runtime_path_options(disable_parser)
    disable_parser.set_defaults(func=cmd_remote_site_disable)

    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    _apply_runtime_path_overrides(args)
    args.func(args)


if __name__ == "__main__":
    main()
