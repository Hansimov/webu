import requests
import requests.packages.urllib3.util.connection as urllib3_cn
import socket

from tclogger import TCLogger, logstr

from .constants import SERVER_URL, DBNAME, CLIENT_TIMEOUT
from .server import AddrReportInfo

logger = TCLogger(name="IPv6DBClient")


class IPv6DBClient:
    """
    Client for IPv6DBServer.
    - pick(): Pick usable and not-using addr from server (for specific dbname)
    - report(): Report addr status to server (for specific dbname)
    - picks(): Pick multiple addrs
    - reports(): Report multiple addrs status
    """

    def __init__(
        self,
        dbname: str = DBNAME,
        server_url: str = SERVER_URL,
        timeout: float = CLIENT_TIMEOUT,
        verbose: bool = False,
    ):
        self.dbname = dbname
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self.verbose = verbose

    def _request(
        self, method: str, endpoint: str, params: dict = None, json: dict = None
    ) -> dict:
        """request to server (via IPv4)"""
        url = f"{self.server_url}{endpoint}"
        try:
            # force IPv4 for client-server communication
            urllib3_cn.allowed_gai_family = lambda: socket.AF_INET
            response = requests.request(
                method=method,
                url=url,
                params=params,
                json=json,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            if self.verbose:
                logger.warn(f"× Request failed: {e}")
            return None

    def pick(self) -> str:
        """Pick usable and not-using addr from server for this dbname."""
        result = self._request("GET", "/pick", params={"dbname": self.dbname})
        if result and result.get("success"):
            ip = result.get("addr")
            if self.verbose and ip:
                ip_str = logstr.okay(f"[{ip}]")
                logger.note(f"> Picked [{self.dbname}]: {ip_str}")
            return ip
        return None

    def picks(self, num: int = 1) -> list[str]:
        """Pick multiple usable and not-using addrs from server for this dbname."""
        result = self._request(
            "GET", "/picks", params={"dbname": self.dbname, "num": num}
        )
        if result and result.get("success"):
            addrs = result.get("addrs", [])
            if self.verbose and addrs:
                addrs_str = logstr.okay(f"[{len(addrs)} addrs]")
                logger.note(f"> Picked [{self.dbname}]: {addrs_str}")
            return addrs
        return []

    def report(self, report_info: AddrReportInfo) -> bool:
        """Report addr status to server for this dbname."""
        result = self._request(
            "POST",
            "/report",
            json={
                "dbname": self.dbname,
                "report_info": {
                    "addr": report_info.addr,
                    "status": report_info.status.value,
                },
            },
        )
        if result and result.get("success"):
            if self.verbose:
                status_str = logstr.okay(report_info.status.value)
                logger.note(
                    f"> Reported [{self.dbname}] [{report_info.addr}]: {status_str}"
                )
            return True
        return False

    def reports(self, report_infos: list[AddrReportInfo]) -> bool:
        """Report multiple addrs status to server for this dbname."""
        result = self._request(
            "POST",
            "/reports",
            json={
                "dbname": self.dbname,
                "report_infos": [
                    {"addr": info.addr, "status": info.status.value}
                    for info in report_infos
                ],
            },
        )
        if result and result.get("success"):
            if self.verbose:
                logger.note(f"> Reported [{self.dbname}] {len(report_infos)} addrs")
            return True
        return False

    def reset(self, addr: str) -> bool:
        """Reset addr status to IDLE in server for this dbname."""
        result = self._request(
            "POST",
            "/reset",
            json={
                "dbname": self.dbname,
                "addr": addr,
            },
        )
        if result and result.get("success"):
            if self.verbose:
                logger.note(f"> Reset [{self.dbname}] [{addr}] to IDLE")
            return True
        return False

    def resets(self, addrs: list[str]) -> int:
        """Reset multiple addrs status to IDLE in server for this dbname."""
        result = self._request(
            "POST",
            "/resets",
            json={
                "dbname": self.dbname,
                "addrs": addrs,
            },
        )
        if result and result.get("success"):
            count = result.get("reset_count", 0)
            if self.verbose:
                logger.note(
                    f"> Reset [{self.dbname}] {count}/{len(addrs)} addrs to IDLE"
                )
            return count
        return 0

    def reset_all(self) -> int:
        """Reset all addrs status to IDLE in server for this dbname."""
        result = self._request(
            "POST",
            "/reset_all",
            params={"dbname": self.dbname},
        )
        if result and result.get("success"):
            count = result.get("reset_count", 0)
            if self.verbose:
                logger.note(f"> Reset all [{self.dbname}] {count} addrs to IDLE")
            return count
        return 0
