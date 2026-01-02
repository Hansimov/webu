import json
import threading

from datetime import datetime
from enum import Enum
from pathlib import Path
from tclogger import TCLogger

from .constants import DB_ROOT, GLOBAL_DB_FILE, MIRROR_DB_DIR

logger = TCLogger(name="IPv6Database")


def _format_datetime(dt: datetime) -> str:
    """Format datetime to 'YYYY-MM-DD HH:MM:SS.mmm' format."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _parse_datetime(dt_str: str) -> datetime:
    """Parse datetime from 'YYYY-MM-DD HH:MM:SS.mmm' or ISO format."""
    if not dt_str:
        return None
    try:
        # Try new format first
        return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        # Fallback to ISO format for backward compatibility
        return datetime.fromisoformat(dt_str)


class AddrStatus(str, Enum):
    """Status of IPv6 address in a mirror."""

    IDLE = "idle"  # usable and not in use
    USING = "using"  # currently in use
    BAD = "bad"  # marked as bad


class GlobalAddrInfo:
    """Info for a single IPv6 address in global db (server-maintained)."""

    def __init__(
        self,
        addr: str,
        created_at: datetime = None,
    ):
        self.addr = addr
        self.created_at = created_at or datetime.now()

    def to_dict(self) -> dict:
        return {
            "addr": self.addr,
            "created_at": _format_datetime(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GlobalAddrInfo":
        return cls(
            addr=data["addr"],
            created_at=_parse_datetime(data.get("created_at")),
        )


class MirrorAddrInfo:
    """Info for a single IPv6 address in a mirror db (per dbname)."""

    def __init__(
        self,
        addr: str,
        status: AddrStatus = AddrStatus.IDLE,
        last_used_at: datetime = None,
        use_count: int = 0,
    ):
        self.addr = addr
        self.status = status
        self.last_used_at = last_used_at
        self.use_count = use_count

    def to_dict(self) -> dict:
        return {
            "addr": self.addr,
            "status": self.status.value,
            "last_used_at": _format_datetime(self.last_used_at),
            "use_count": self.use_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MirrorAddrInfo":
        return cls(
            addr=data["addr"],
            status=AddrStatus(data.get("status", "idle")),
            last_used_at=_parse_datetime(data.get("last_used_at")),
            use_count=data.get("use_count", 0),
        )


class AddrReportInfo:
    """Info for reporting addr status from client."""

    def __init__(
        self,
        addr: str,
        status: AddrStatus,
        report_at: datetime = None,
    ):
        self.addr = addr
        self.status = status
        self.report_at = report_at or datetime.now()

    def to_dict(self) -> dict:
        return {
            "addr": self.addr,
            "status": self.status.value,
            "report_at": _format_datetime(self.report_at),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AddrReportInfo":
        return cls(
            addr=data["addr"],
            status=AddrStatus(data.get("status", "bad")),
            report_at=_parse_datetime(data.get("report_at")),
        )


class GlobalIPv6DB:
    """
    Global database for all IPv6 addresses (server-maintained).
    Only stores addresses that passed usability check during spawn.
    """

    def __init__(
        self,
        db_root: Path = None,
        verbose: bool = False,
    ):
        self.db_root = Path(db_root or DB_ROOT)
        self.db_path = self.db_root / GLOBAL_DB_FILE
        self.verbose = verbose

        self.addrs: dict[str, GlobalAddrInfo] = {}
        self.prefix: str = None
        self._lock = threading.Lock()

        self.load()

    def save(self):
        """Sync in-memory cache to persistent storage."""
        with self._lock:
            data = {
                "prefix": self.prefix,
                "addrs": {addr: info.to_dict() for addr, info in self.addrs.items()},
            }
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.db_path, "w") as f:
                json.dump(data, f, indent=2)
            if self.verbose:
                logger.okay(f"✓ Global DB: Saved {len(self.addrs)} addrs")

    def load(self):
        """Load from persistent storage to in-memory cache."""
        if self.db_path.exists():
            try:
                with open(self.db_path, "r") as f:
                    data = json.load(f)
                self.prefix = data.get("prefix")
                self.addrs = {
                    addr: GlobalAddrInfo.from_dict(info)
                    for addr, info in data.get("addrs", {}).items()
                }
                if self.verbose:
                    logger.okay(f"✓ Global DB: Loaded {len(self.addrs)} addrs")
            except Exception as e:
                if self.verbose:
                    logger.warn(f"× Global DB: Failed to load: {e}")

    def flush(self):
        """Clear in-memory cache and sync to persistent storage."""
        with self._lock:
            self.addrs.clear()
        self.save()

    def add_addr(self, addr: str) -> bool:
        """Add a new addr to global db."""
        with self._lock:
            if addr in self.addrs:
                return False
            self.addrs[addr] = GlobalAddrInfo(addr=addr)
            return True

    def has_addr(self, addr: str) -> bool:
        """Check if addr exists in global db."""
        with self._lock:
            return addr in self.addrs

    def get_all_addrs(self) -> list[str]:
        """Get all addrs in global db."""
        with self._lock:
            return list(self.addrs.keys())

    def set_prefix(self, prefix: str):
        """Set current prefix."""
        with self._lock:
            self.prefix = prefix


class MirrorIPv6DB:
    """
    Mirror database for a specific dbname.
    Mirrors the global addrs but maintains its own status for each addr.
    """

    def __init__(
        self,
        dbname: str,
        db_root: Path = None,
        verbose: bool = False,
    ):
        self.dbname = dbname
        self.db_root = Path(db_root or DB_ROOT)
        self.db_dir = self.db_root / MIRROR_DB_DIR
        self.db_path = self.db_dir / f"{dbname}.json"
        self.verbose = verbose

        self.addrs: dict[str, MirrorAddrInfo] = {}
        self._lock = threading.Lock()

        self.load()

    def save(self):
        """Sync in-memory cache to persistent storage."""
        with self._lock:
            data = {
                "dbname": self.dbname,
                "addrs": {addr: info.to_dict() for addr, info in self.addrs.items()},
            }
            self.db_dir.mkdir(parents=True, exist_ok=True)
            with open(self.db_path, "w") as f:
                json.dump(data, f, indent=2)
            if self.verbose:
                logger.okay(f"✓ Mirror [{self.dbname}]: Saved {len(self.addrs)} addrs")

    def load(self):
        """Load from persistent storage to in-memory cache."""
        if self.db_path.exists():
            try:
                with open(self.db_path, "r") as f:
                    data = json.load(f)
                self.addrs = {
                    addr: MirrorAddrInfo.from_dict(info)
                    for addr, info in data.get("addrs", {}).items()
                }
                if self.verbose:
                    logger.okay(
                        f"✓ Mirror [{self.dbname}]: Loaded {len(self.addrs)} addrs"
                    )
            except Exception as e:
                if self.verbose:
                    logger.warn(f"× Mirror [{self.dbname}]: Failed to load: {e}")

    def flush(self):
        """Clear in-memory cache and sync to persistent storage."""
        with self._lock:
            self.addrs.clear()
        self.save()

    def sync_from_global(self, global_addrs: list[str]):
        """
        Sync addrs from global db.
        Add new addrs, keep existing status for known addrs.
        """
        with self._lock:
            # Add new addrs from global
            for addr in global_addrs:
                if addr not in self.addrs:
                    self.addrs[addr] = MirrorAddrInfo(addr=addr)

            # Remove addrs not in global (e.g., after prefix change)
            to_remove = [addr for addr in self.addrs if addr not in global_addrs]
            for addr in to_remove:
                del self.addrs[addr]

    def get_idle_count(self) -> int:
        """Get number of idle addrs."""
        with self._lock:
            return sum(
                1 for info in self.addrs.values() if info.status == AddrStatus.IDLE
            )

    def get_idle_addr(self) -> str | None:
        """Get an idle addr and mark it as using."""
        with self._lock:
            for addr, info in self.addrs.items():
                if info.status == AddrStatus.IDLE:
                    info.status = AddrStatus.USING
                    info.last_used_at = datetime.now()
                    info.use_count += 1
                    return addr
            return None

    def release_addr(self, report_info: AddrReportInfo):
        """Release addr back to pool with reported status."""
        with self._lock:
            if report_info.addr in self.addrs:
                info = self.addrs[report_info.addr]
                info.status = report_info.status

    def reset_addr(self, addr: str) -> bool:
        """Reset addr status to IDLE."""
        with self._lock:
            if addr in self.addrs:
                self.addrs[addr].status = AddrStatus.IDLE
                return True
            return False

    def reset_addrs(self, addrs: list[str]) -> int:
        """Reset multiple addrs status to IDLE. Returns count of successfully reset addrs."""
        count = 0
        with self._lock:
            for addr in addrs:
                if addr in self.addrs:
                    self.addrs[addr].status = AddrStatus.IDLE
                    count += 1
        return count

    def reset_all(self) -> int:
        """Reset all addrs status to IDLE. Returns count of reset addrs."""
        with self._lock:
            count = len(self.addrs)
            for info in self.addrs.values():
                info.status = AddrStatus.IDLE
        return count

    def get_stats(self) -> dict:
        """Get statistics for this mirror."""
        with self._lock:
            total = len(self.addrs)
            idle = sum(
                1 for info in self.addrs.values() if info.status == AddrStatus.IDLE
            )
            using = sum(
                1 for info in self.addrs.values() if info.status == AddrStatus.USING
            )
            bad = sum(
                1 for info in self.addrs.values() if info.status == AddrStatus.BAD
            )
        return {
            "dbname": self.dbname,
            "total": total,
            "idle": idle,
            "using": using,
            "bad": bad,
        }
