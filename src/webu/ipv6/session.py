import requests
import requests.packages.urllib3.util.connection as urllib3_cn
import socket

from requests import Session
from requests.adapters import HTTPAdapter


class IPv6Adapter(HTTPAdapter):
    def __init__(self, source_address, *args, **kwargs):
        self.source_address = source_address
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs["source_address"] = self.source_address
        return super().init_poolmanager(*args, **kwargs)


class IPv6SessionAdapter:
    @staticmethod
    def force_ipv4():
        urllib3_cn.allowed_gai_family = lambda: socket.AF_INET

    @staticmethod
    def force_ipv6():
        if urllib3_cn.HAS_IPV6:
            urllib3_cn.allowed_gai_family = lambda: socket.AF_INET6

    def adapt(self, session: requests.Session, ip: str):
        try:
            socket.inet_pton(socket.AF_INET6, ip)
        except Exception as e:
            raise ValueError(f"× Invalid IPv6 format: [{ip}]")

        adapter = IPv6Adapter((ip, 0))
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session


class IPv6Session(Session):
    pass
