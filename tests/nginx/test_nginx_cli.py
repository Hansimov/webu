import os

from pathlib import Path

from webu.nginx.cli import _apply_runtime_path_overrides, build_parser


def test_parser_supports_render_and_remote_site_commands():
    parser = build_parser()
    project_root = "/tmp/webu-project"
    config_dir = "/tmp/webu-project/configs"

    render_args = parser.parse_args(
        [
            "render-reverse-proxy",
            "--server-name",
            "public.example.com",
            "--server-name",
            "www.public.example.com",
            "--upstream-url",
            "http://127.0.0.1:32002",
            "--listen-http",
            "--listen-https",
            "--redirect-https",
            "--ssl-certificate",
            "/etc/ssl/fullchain.pem",
            "--ssl-certificate-key",
            "/etc/ssl/privkey.pem",
            "--enable-static-cache",
            "--static-cache-zone",
            "public_assets",
            "--static-cache-path",
            "/tmp/webu-cache",
            "--static-cache-max-size",
            "256m",
            "--static-cache-inactive",
            "3d",
            "--static-cache-browser-max-age",
            "604800",
        ]
    )
    apply_args = parser.parse_args(
        [
            "remote-site-apply",
            "--host-name",
            "relay-vps",
            "--site-name",
            "public-example",
            "--server-name",
            "public.example.com",
            "--upstream-url",
            "http://127.0.0.1:32002",
            "--listen-http",
            "--remote-conf-dir",
            "/opt/1panel/apps/openresty/openresty/conf/conf.d",
            "--test-command",
            "docker exec 1Panel-openresty-BDlX nginx -t",
            "--reload-command",
            "docker exec 1Panel-openresty-BDlX nginx -s reload",
            "--enable-static-cache",
            "--project-root",
            project_root,
            "--config-dir",
            config_dir,
        ]
    )
    cert_args = parser.parse_args(
        [
            "remote-cert-install",
            "--host-name",
            "relay-vps",
            "--local-fullchain",
            "/tmp/certs/fullchain.pem",
            "--local-privkey",
            "/tmp/certs/privkey.pem",
            "--remote-cert-dir",
            "/etc/openresty/certs/public.example.com",
            "--test-command",
            "nginx -t",
            "--reload-command",
            "nginx -s reload",
        ]
    )
    show_args = parser.parse_args(
        [
            "remote-site-show",
            "--host-name",
            "relay-vps",
            "--site-name",
            "public-example",
        ]
    )
    disable_args = parser.parse_args(
        [
            "remote-site-disable",
            "--host-name",
            "relay-vps",
            "--site-name",
            "public-example",
        ]
    )

    assert render_args.listen_http is True
    assert render_args.listen_https is True
    assert render_args.redirect_https is True
    assert render_args.enable_static_cache is True
    assert render_args.static_cache_zone == "public_assets"
    assert render_args.static_cache_path == "/tmp/webu-cache"
    assert render_args.static_cache_max_size == "256m"
    assert render_args.static_cache_inactive == "3d"
    assert render_args.static_cache_browser_max_age == "604800"
    assert apply_args.host_name == "relay-vps"
    assert apply_args.enable_static_cache is True
    assert apply_args.project_root == project_root
    assert apply_args.config_dir == config_dir
    assert cert_args.command == "remote-cert-install"
    assert cert_args.remote_cert_dir == "/etc/openresty/certs/public.example.com"
    assert show_args.site_name == "public-example"
    assert disable_args.site_name == "public-example"


def test_runtime_path_overrides_set_environment(monkeypatch, tmp_path):
    parser = build_parser()
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    monkeypatch.delenv("WEBU_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("WEBU_CONFIG_DIR", raising=False)

    args = parser.parse_args(
        [
            "remote-site-show",
            "--host-name",
            "relay-vps",
            "--site-name",
            "public-example",
            "--project-root",
            str(tmp_path),
            "--config-dir",
            str(config_dir),
        ]
    )

    _apply_runtime_path_overrides(args)

    assert Path(os.environ["WEBU_PROJECT_ROOT"]).resolve() == tmp_path.resolve()
    assert Path(os.environ["WEBU_CONFIG_DIR"]).resolve() == config_dir.resolve()
