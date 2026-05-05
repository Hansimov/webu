from webu.nginx.operations import render_reverse_proxy_site


def test_render_reverse_proxy_site_supports_http_and_https():
    rendered = render_reverse_proxy_site(
        server_names=["public.example.com", "www.public.example.com"],
        upstream_url="http://127.0.0.1:32002",
        listen_http=True,
        listen_https=True,
        redirect_https=True,
        ssl_certificate="/etc/ssl/fullchain.pem",
        ssl_certificate_key="/etc/ssl/privkey.pem",
    )

    assert "listen 80;" in rendered
    assert "listen 443 ssl http2;" in rendered
    assert "server_name public.example.com www.public.example.com;" in rendered
    assert "return 301 https://$host$request_uri;" in rendered
    assert "proxy_pass http://127.0.0.1:32002;" in rendered
    assert "ssl_certificate /etc/ssl/fullchain.pem;" in rendered


def test_render_reverse_proxy_site_supports_static_cache():
    rendered = render_reverse_proxy_site(
        server_names=["public.example.com"],
        upstream_url="http://127.0.0.1:32002",
        listen_http=True,
        enable_static_cache=True,
        static_cache_zone="public-example",
        static_cache_path="/tmp/webu-cache-public",
    )

    assert "proxy_cache_path /tmp/webu-cache-public" in rendered
    assert "keys_zone=public_example:20m" in rendered
    assert "location ^~ /assets/" in rendered
    assert "location ^~ /icons/" in rendered
    assert 'Cache-Control "public, max-age=31536000, immutable"' in rendered
    assert 'X-WebU-Relay-Cache "$upstream_cache_status"' in rendered
    assert "proxy_ignore_headers Set-Cookie;" in rendered
    assert "proxy_hide_header Set-Cookie;" in rendered


def test_render_reverse_proxy_site_rejects_unsafe_static_cache_values():
    try:
        render_reverse_proxy_site(
            server_names=["public.example.com"],
            upstream_url="http://127.0.0.1:32002",
            listen_http=True,
            enable_static_cache=True,
            static_cache_path='/tmp/cache"; add_header X-Bad 1;',
        )
    except ValueError as exc:
        assert "static_cache_path" in str(exc)
    else:
        raise AssertionError("unsafe cache path should fail")

    try:
        render_reverse_proxy_site(
            server_names=["public.example.com"],
            upstream_url="http://127.0.0.1:32002",
            listen_http=True,
            enable_static_cache=True,
            static_cache_browser_max_age='31536000"',
        )
    except ValueError as exc:
        assert "static_cache_browser_max_age" in str(exc)
    else:
        raise AssertionError("unsafe browser cache max-age should fail")


def test_render_reverse_proxy_site_rejects_https_without_cert_paths():
    try:
        render_reverse_proxy_site(
            server_names=["public.example.com"],
            upstream_url="http://127.0.0.1:32002",
            listen_http=False,
            listen_https=True,
        )
    except ValueError as exc:
        assert "ssl_certificate" in str(exc)
    else:
        raise AssertionError("listen_https without certificate paths should fail")
