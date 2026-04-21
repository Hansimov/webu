from webu.frp.operations import client_render, server_render


def test_server_render_outputs_expected_toml(monkeypatch):
    payload = {
        "servers": [
            {
                "name": "relay-frps",
                "ssh_host_name": "relay-vps",
                "bind_port": 7000,
                "proxy_bind_addr": "127.0.0.1",
                "auth_token": "secret",
                "remote_binary_path": "/root/frps",
                "remote_config_path": "/root/frps.toml",
            }
        ],
        "clients": [],
    }
    monkeypatch.setattr(
        "webu.frp.operations.load_frp_config", lambda validate=False: payload
    )

    result = server_render(name="relay-frps")

    assert "bindPort = 7000" in result["content"]
    assert 'proxyBindAddr = "127.0.0.1"' in result["content"]
    assert 'auth.token = "secret"' in result["content"]


def test_client_render_falls_back_to_ssh_host_address(monkeypatch):
    frp_payload = {
        "servers": [
            {
                "name": "relay-frps",
                "ssh_host_name": "relay-vps",
                "bind_port": 7000,
                "proxy_bind_addr": "127.0.0.1",
                "auth_token": "secret",
                "remote_binary_path": "/root/frps",
                "remote_config_path": "/root/frps.toml",
            }
        ],
        "clients": [
            {
                "name": "relay-public-web",
                "server_name": "relay-frps",
                "local_port": 20002,
                "remote_port": 32002,
            }
        ],
    }
    ssh_payload = {
        "hosts": [
            {
                "name": "relay-vps",
                "ip": "198.51.100.24",
                "username": "root",
                "password": "secret",
            }
        ],
        "tunnels": [],
    }
    monkeypatch.setattr(
        "webu.frp.operations.load_frp_config", lambda validate=False: frp_payload
    )
    monkeypatch.setattr(
        "webu.frp.operations.load_ssh_config", lambda validate=False: ssh_payload
    )

    result = client_render(name="relay-public-web")

    assert 'serverAddr = "198.51.100.24"' in result["content"]
    assert "serverPort = 7000" in result["content"]
    assert "localPort = 20002" in result["content"]
    assert "remotePort = 32002" in result["content"]
