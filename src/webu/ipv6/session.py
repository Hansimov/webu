import requests
import requests.packages.urllib3.util.connection as urllib3_cn
import socket
import time

from requests import Session
from requests.adapters import HTTPAdapter
from tclogger import TCLogger, logstr

from .constants import (
    SERVER_URL,
    DBNAME,
    SESSION_RETRY_INTERVAL,
)
from .server import AddrStatus, AddrReportInfo

logger = TCLogger(name="IPv6Session")


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

    @staticmethod
    def adapt(session: requests.Session, ip: str):
        """Adapt session to use specified IPv6 address."""
        try:
            socket.inet_pton(socket.AF_INET6, ip)
        except Exception as e:
            raise ValueError(f"× Invalid IPv6 format: [{ip}]")

        adapter = IPv6Adapter((ip, 0))
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session


class IPv6Session(Session):
    """
    Inherits from requests.Session, and supports force ipv6 connection,
    and auto use new ipv6 addr from db.
    """

    def __init__(
        self,
        dbname: str = DBNAME,
        server_url: str = SERVER_URL,
        retry_interval: float = SESSION_RETRY_INTERVAL,
        verbose: bool = False,
    ):
        super().__init__()
        self.dbname = dbname
        self.server_url = server_url
        self.retry_interval = retry_interval
        self.verbose = verbose
        self.current_ip: str = None
        self._client = None

        # Force IPv6 connection
        IPv6SessionAdapter.force_ipv6()

    def _get_client(self):
        """Get or create IPv6DBClient instance."""
        if self._client is None:
            from .client import IPv6DBClient

            self._client = IPv6DBClient(
                dbname=self.dbname,
                server_url=self.server_url,
                verbose=self.verbose,
            )
        return self._client

    def adapt(self) -> str:
        """
        Pick ip from db, and adapt session to use that ip.
        If db is empty, would hang and wait for new addrs spawned and usable in server side.
        """
        client = self._get_client()

        while True:
            ip = client.pick()
            if ip:
                IPv6SessionAdapter.adapt(self, ip)
                self.current_ip = ip
                if self.verbose:
                    ip_str = logstr.okay(f"[{ip}]")
                    logger.note(f"> Adapted [{self.dbname}] to IPv6: {ip_str}")
                return ip
            else:
                if self.verbose:
                    logger.warn(
                        f"× No usable IPv6 addr for [{self.dbname}], retry in {self.retry_interval}s ..."
                    )
                time.sleep(self.retry_interval)

    def report(self, status: AddrStatus):
        """Report current addr status to server."""
        if self.current_ip:
            client = self._get_client()
            report_info = AddrReportInfo(addr=self.current_ip, status=status)
            client.report(report_info)
            if self.verbose:
                status_str = logstr.okay(status.value)
                logger.note(
                    f"> Reported [{self.dbname}] [{self.current_ip}]: {status_str}"
                )
