import pytest
import netifaces

from webu.ipv6.route import IPv6Prefixer


PRIMARY_INTERFACE = "primary0"
VPN_INTERFACE = "vpn0"
PRIMARY_PREFIX = "2606:4700:1234:5678"
VPN_PREFIX = "2607:f8b0:abcd:1234"


def test_prefixer_skips_link_local_and_uses_global_ipv6(monkeypatch):
    monkeypatch.setattr(netifaces, "interfaces", lambda: ["lo", PRIMARY_INTERFACE])
    monkeypatch.setattr(netifaces, "gateways", lambda: {"default": {}})

    def fake_ifaddresses(interface):
        if interface == "lo":
            return {
                netifaces.AF_INET6: [
                    {
                        "addr": "::1",
                        "netmask": "ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff/128",
                    }
                ]
            }
        return {
            netifaces.AF_INET6: [
                {
                    "addr": f"fe80::1%{PRIMARY_INTERFACE}",
                    "netmask": "ffff:ffff:ffff:ffff::/64",
                },
                {
                    "addr": f"{PRIMARY_PREFIX}::1234",
                    "netmask": "ffff:ffff:ffff:ffff::/64",
                },
            ]
        }

    monkeypatch.setattr(netifaces, "ifaddresses", fake_ifaddresses)

    prefixer = IPv6Prefixer()

    assert prefixer.netint == PRIMARY_INTERFACE
    assert prefixer.prefix == PRIMARY_PREFIX
    assert prefixer.prefix_bits == 64


def test_prefixer_raises_when_no_global_ipv6_exists(monkeypatch):
    monkeypatch.setattr(netifaces, "interfaces", lambda: [PRIMARY_INTERFACE])
    monkeypatch.setattr(netifaces, "gateways", lambda: {"default": {}})
    monkeypatch.setattr(
        netifaces,
        "ifaddresses",
        lambda interface: {
            netifaces.AF_INET6: [
                {
                    "addr": f"fe80::1%{PRIMARY_INTERFACE}",
                    "netmask": "ffff:ffff:ffff:ffff::/64",
                }
            ]
        },
    )

    with pytest.raises(RuntimeError, match="No global IPv6 interface found"):
        IPv6Prefixer()


def test_prefixer_prefers_default_route_interface_over_vpn(monkeypatch):
    monkeypatch.setattr(
        netifaces, "interfaces", lambda: [VPN_INTERFACE, PRIMARY_INTERFACE]
    )
    monkeypatch.setattr(
        netifaces,
        "gateways",
        lambda: {
            "default": {
                netifaces.AF_INET: ("192.168.1.1", PRIMARY_INTERFACE),
                netifaces.AF_INET6: ("fe80::1", PRIMARY_INTERFACE, 0),
            },
            netifaces.AF_INET: [("192.168.1.1", PRIMARY_INTERFACE, True)],
            netifaces.AF_INET6: [("fe80::1", PRIMARY_INTERFACE, True)],
        },
    )

    def fake_ifaddresses(interface):
        if interface == VPN_INTERFACE:
            return {
                netifaces.AF_INET6: [
                    {"addr": f"{VPN_PREFIX}::1", "netmask": "ffff:ffff:ffff:ffff::/64"}
                ]
            }
        return {
            netifaces.AF_INET6: [
                {
                    "addr": f"{PRIMARY_PREFIX}::1234",
                    "netmask": "ffff:ffff:ffff:ffff::/64",
                }
            ]
        }

    monkeypatch.setattr(netifaces, "ifaddresses", fake_ifaddresses)

    prefixer = IPv6Prefixer()

    assert prefixer.netint == PRIMARY_INTERFACE
    assert prefixer.prefix == PRIMARY_PREFIX


def test_prefixer_prefers_default_route_interface_without_default_key(monkeypatch):
    monkeypatch.setattr(
        netifaces, "interfaces", lambda: [VPN_INTERFACE, PRIMARY_INTERFACE]
    )
    monkeypatch.setattr(
        netifaces,
        "gateways",
        lambda: {
            netifaces.AF_INET: [("192.168.1.1", PRIMARY_INTERFACE, True)],
            netifaces.AF_INET6: [("fe80::1", PRIMARY_INTERFACE, True)],
        },
    )

    def fake_ifaddresses(interface):
        if interface == VPN_INTERFACE:
            return {
                netifaces.AF_INET6: [
                    {"addr": f"{VPN_PREFIX}::1", "netmask": "ffff:ffff:ffff:ffff::/64"}
                ]
            }
        return {
            netifaces.AF_INET6: [
                {
                    "addr": f"{PRIMARY_PREFIX}::1234",
                    "netmask": "ffff:ffff:ffff:ffff::/64",
                }
            ]
        }

    monkeypatch.setattr(netifaces, "ifaddresses", fake_ifaddresses)

    prefixer = IPv6Prefixer()

    assert prefixer.netint == PRIMARY_INTERFACE
    assert prefixer.prefix == PRIMARY_PREFIX
