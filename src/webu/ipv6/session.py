import requests
import requests.packages.urllib3.util.connection as urllib3_cn
import socket
import time

from requests import Session
from requests.adapters import HTTPAdapter
from tclogger import TCLogger, logstr

from .constants import SERVER_URL, DBNAME
from .constants import ADAPT_RETRY_INTERVAL, ADAPT_MAX_RETRIES
from .constants import REQUESTS_HEADERS
from .server import AddrStatus, AddrReportInfo
from .client import IPv6DBClient

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
        adapt_retry_interval: float = ADAPT_RETRY_INTERVAL,
        adapt_max_retries: int = ADAPT_MAX_RETRIES,
        headers: dict = None,
        verbose: bool = False,
    ):
        super().__init__()
        self.dbname = dbname
        self.server_url = server_url
        self.adapt_retry_interval = adapt_retry_interval
        self.adapt_max_retries = adapt_max_retries
        self.verbose = verbose
        self.headers.update(headers or REQUESTS_HEADERS)
        self.client = IPv6DBClient(
            dbname=self.dbname,
            server_url=self.server_url,
            verbose=self.verbose,
        )
        self.ip = None
        self.adapt()

    def adapt(self) -> bool:
        """
        Pick ip from db, and adapt session to use that ip.
        If db is empty, would hang and wait for new addrs spawned and usable in server side.

        Returns:
            True if successfully adapted, False otherwise.

        Raises:
            KeyboardInterrupt: If interrupted by Ctrl+C.
        """
        retries = 0
        while self.adapt_max_retries is None or retries <= self.adapt_max_retries:
            try:
                ip = self.client.pick()
                if ip:
                    IPv6SessionAdapter.adapt(self, ip)
                    IPv6SessionAdapter.force_ipv6()
                    self.ip = ip
                    if self.verbose:
                        ip_str = logstr.okay(f"[{ip}]")
                        logger.note(f"> Adapted IPv6: {ip_str}")
                    return True
                else:
                    logger.warn(
                        f"× No usable IPv6 addr, retry in {self.adapt_retry_interval}s ..."
                    )
                    time.sleep(self.adapt_retry_interval)
                    retries += 1
            except KeyboardInterrupt:
                if self.verbose:
                    logger.warn(f"× Adapt [{self.dbname}] interrupted by user")
                raise
        return False

    def report(self, status: AddrStatus):
        """Report current addr status to server."""
        if self.ip:
            report_info = AddrReportInfo(addr=self.ip, status=status)
            self.client.report(report_info)
            if self.verbose:
                status_str = logstr.okay(status.value)
                logger.note(f"> Reported [{self.dbname}] [{self.ip}]: {status_str}")

    def report_idle(self):
        """Report current addr to server as idle"""
        self.report(AddrStatus.IDLE)

    def report_bad(self):
        """Report current addr to server as bad"""
        self.report(AddrStatus.BAD)
