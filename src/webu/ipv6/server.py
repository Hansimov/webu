import argparse
import asyncio
import json
import random
import requests
import threading

from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from fastapi import FastAPI, Query
from pathlib import Path
from pydantic import BaseModel
from tclogger import TCLogger, logstr
from typing import Optional

from .constants import (
    DB_ROOT,
    SERVER_HOST,
    SERVER_PORT,
    DBNAME,
    GLOBAL_DB_FILE,
    MIRROR_DB_DIR,
    USABLE_NUM,
    CHECK_URL,
    CHECK_TIMEOUT,
    ROUTE_CHECK_INTERVAL,
    MAINTAIN_INTERVAL,
    SPAWN_MAX_RETRIES,
    SPAWN_MAX_ADDRS,
)
from .route import IPv6Prefixer, IPv6RouteUpdater

logger = TCLogger(name="IPv6DBServer")


class AddrStatus(str, Enum):
    """Status of IPv6 address in a mirror."""

    IDLE = "idle"  # usable and not in use
    USING = "using"  # currently in use
    UNUSABLE = "unusable"  # marked as unusable


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
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GlobalAddrInfo":
        return cls(
            addr=data["addr"],
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if data.get("created_at")
                else None
            ),
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
            "last_used_at": (
                self.last_used_at.isoformat() if self.last_used_at else None
            ),
            "use_count": self.use_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MirrorAddrInfo":
        return cls(
            addr=data["addr"],
            status=AddrStatus(data.get("status", "idle")),
            last_used_at=(
                datetime.fromisoformat(data["last_used_at"])
                if data.get("last_used_at")
                else None
            ),
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
            "report_at": self.report_at.isoformat() if self.report_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AddrReportInfo":
        return cls(
            addr=data["addr"],
            status=AddrStatus(data.get("status", "unusable")),
            report_at=(
                datetime.fromisoformat(data["report_at"])
                if data.get("report_at")
                else None
            ),
        )


class GlobalAddrsDB:
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


class MirrorDB:
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

    def get_idle_addr(self) -> Optional[str]:
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
            unusable = sum(
                1 for info in self.addrs.values() if info.status == AddrStatus.UNUSABLE
            )
        return {
            "dbname": self.dbname,
            "total": total,
            "idle": idle,
            "using": using,
            "unusable": unusable,
        }


class IPv6DBServer:
    """
    FastAPI server for IPv6 address management.

    Architecture:
    - GlobalAddrsDB: Server-maintained, stores all spawned addrs (verified usable)
    - MirrorDB: Per-dbname, mirrors global addrs with its own status

    APIs:
    - spawn/spawns: Create new addrs to global db
    - pick/picks: Get idle addrs from specific dbname's mirror
    - check/checks: Check addr usability
    - report/reports: Report addr status to specific dbname's mirror
    - save/load/flush: Sync databases
    - monitor_route/update_route: Monitor IPv6 prefix change and update routes
    """

    def __init__(
        self,
        db_root: Path = None,
        usable_num: int = USABLE_NUM,
        check_url: str = CHECK_URL,
        check_timeout: float = CHECK_TIMEOUT,
        route_check_interval: float = ROUTE_CHECK_INTERVAL,
        verbose: bool = False,
    ):
        self.db_root = Path(db_root or DB_ROOT)
        self.usable_num = usable_num
        self.check_url = check_url
        self.check_timeout = check_timeout
        self.route_check_interval = route_check_interval
        self.verbose = verbose

        # Global database (server-maintained)
        self.global_db = GlobalAddrsDB(db_root=self.db_root, verbose=verbose)

        # Mirror databases (per dbname)
        self.mirror_db_dir = self.db_root / MIRROR_DB_DIR
        self.mirrors: dict[str, MirrorDB] = {}
        self._mirrors_lock = threading.Lock()

        # IPv6 prefix management
        self.prefixer = IPv6Prefixer(verbose=verbose)
        self.prefix = self.prefixer.prefix
        self.route_updater = IPv6RouteUpdater(verbose=verbose)

        # Update global db prefix
        self.global_db.set_prefix(self.prefix)

        # Background tasks
        self._route_monitor_task: asyncio.Task = None
        self._spawn_task: asyncio.Task = None

        # Load existing mirrors
        self._load_existing_mirrors()

    def _load_existing_mirrors(self):
        """Load existing mirror databases from disk."""
        if self.mirror_db_dir.exists():
            for db_file in self.mirror_db_dir.glob("*.json"):
                dbname = db_file.stem
                self.get_mirror(dbname)

    def get_mirror(self, dbname: str) -> MirrorDB:
        """Get or create a mirror for the given dbname."""
        with self._mirrors_lock:
            if dbname not in self.mirrors:
                mirror = MirrorDB(
                    dbname=dbname,
                    db_root=self.db_root,
                    verbose=self.verbose,
                )
                # Sync from global db
                mirror.sync_from_global(self.global_db.get_all_addrs())
                self.mirrors[dbname] = mirror
                if self.verbose:
                    logger.note(f"> Created mirror for [{dbname}]")
            return self.mirrors[dbname]

    def _generate_random_suffix(self) -> str:
        """Generate random 64-bit suffix for IPv6 addr."""
        groups = []
        for _ in range(4):
            group = "".join(random.choices("0123456789abcdef", k=4))
            group = group.lstrip("0") or "0"
            groups.append(group)
        return ":".join(groups)

    def _generate_random_addr(self) -> str:
        """Generate a random IPv6 addr with current prefix."""
        suffix = self._generate_random_suffix()
        return f"{self.prefix}:{suffix}"

    def _addr_suffix(self, addr: str) -> str:
        """Extract suffix part of addr for shorter logging."""
        if self.prefix and addr.startswith(self.prefix):
            return addr[len(self.prefix) :]
        return addr

    def check(self, addr: str) -> bool:
        """Check usability of addr by making a request."""
        from .session import IPv6SessionAdapter

        try:
            session = requests.Session()
            IPv6SessionAdapter.force_ipv6()
            IPv6SessionAdapter.adapt(session, addr)
            response = session.get(self.check_url, timeout=self.check_timeout)
            result_ip = response.text.strip()
            is_good = result_ip == addr
            if self.verbose:
                if is_good:
                    mark = "✓"
                    logfunc = logger.okay
                else:
                    mark = "×"
                    logfunc = logger.warn
                logfunc(f"{mark} [{result_ip}]")
            return is_good
        except Exception as e:
            if self.verbose:
                logger.warn(f"  × Failed : [{self._addr_suffix(addr)}]")
            return False

    def checks(self, addrs: list[str]) -> list[bool]:
        """Check usability of multiple addrs."""
        return [self.check(addr) for addr in addrs]

    def spawn(self) -> str:
        """
        Spawn random IPv6 addr, verify usability, add to global db.

        Generate a random address, then check it up to SPAWN_MAX_RETRIES times.
        If check succeeds, return the address.
        If all checks fail (network issue), return None to signal spawns() to stop.

        Returns:
            str: The spawned addr if successful, None if all check attempts failed.
        """
        addr = self._generate_random_addr()
        suffix = self._addr_suffix(addr)
        for retry in range(SPAWN_MAX_RETRIES):
            if self.verbose:
                if retry >= 1:
                    retry_str = logstr.mesg(f" ({retry + 1}/{SPAWN_MAX_RETRIES})")
                else:
                    retry_str = ""
                logger.note(f"  > Checking [{suffix}]{retry_str}")
            is_good = self.check(addr)
            if is_good:
                self.global_db.add_addr(addr)
                # Sync to all mirrors
                self._sync_all_mirrors()
                if self.verbose:
                    addr_str = logstr.okay(f"[{suffix}]")
                    logger.note(f"> Spawned IPv6: {addr_str}")
                return addr
        if self.verbose:
            logger.warn(f"× Spawn failed after {SPAWN_MAX_RETRIES} retries: [{suffix}]")
        return None

    def spawns(self, num: int = 1) -> list[str]:
        """
        Spawn multiple random IPv6 addrs.

        Tolerates up to SPAWN_MAX_ADDRS consecutive failures before stopping.
        Returns tuple of (addrs, should_stop) where should_stop indicates
        if we hit the consecutive failure limit.

        Returns:
            tuple[list[str], bool]: (spawned addrs, whether to stop due to network issues)
        """
        addrs = []
        fails = 0
        for _ in range(num):
            addr = self.spawn()
            if addr:
                addrs.append(addr)
                fails = 0  # Reset on success
            else:
                fails += 1
                if fails >= SPAWN_MAX_ADDRS:
                    if self.verbose:
                        logger.warn(f"× Spawns stopped: {fails} failures reached limit")
                    break
        return addrs, fails >= SPAWN_MAX_ADDRS

    def _sync_all_mirrors(self):
        """Sync all mirrors from global db."""
        global_addrs = self.global_db.get_all_addrs()
        with self._mirrors_lock:
            for mirror in self.mirrors.values():
                mirror.sync_from_global(global_addrs)

    def pick(self, dbname: str = DBNAME) -> str:
        """Pick idle addr from specific dbname's mirror."""
        mirror = self.get_mirror(dbname)
        addr = mirror.get_idle_addr()
        if self.verbose and addr:
            addr_str = logstr.okay(f"[{self._addr_suffix(addr)}]")
            logger.note(f"> Picked [{dbname}]: {addr_str}")
        return addr

    def picks(self, dbname: str = DBNAME, num: int = 1) -> list[str]:
        """Pick multiple idle addrs from specific dbname's mirror."""
        addrs = []
        for _ in range(num):
            addr = self.pick(dbname)
            if addr:
                addrs.append(addr)
            else:
                break
        return addrs

    def report(self, dbname: str, report_info: AddrReportInfo) -> bool:
        """Report addr status to specific dbname's mirror."""
        mirror = self.get_mirror(dbname)
        mirror.release_addr(report_info)
        if self.verbose:
            status_str = logstr.okay(report_info.status.value)
            logger.note(
                f"> Reported [{dbname}] [{self._addr_suffix(report_info.addr)}]: {status_str}"
            )
        return True

    def reports(self, dbname: str, report_infos: list[AddrReportInfo]) -> bool:
        """Report multiple addrs status to specific dbname's mirror."""
        for report_info in report_infos:
            self.report(dbname, report_info)
        return True

    def save(self):
        """Save global db and all mirrors to persistent storage."""
        self.global_db.save()
        with self._mirrors_lock:
            for mirror in self.mirrors.values():
                mirror.save()

    def load(self):
        """Load global db and all mirrors from persistent storage."""
        self.global_db.load()
        with self._mirrors_lock:
            for mirror in self.mirrors.values():
                mirror.load()

    def flush(self, dbname: str = None):
        """
        Flush database.
        If dbname is None, flush global db and all mirrors.
        Otherwise, flush only the specified mirror.
        """
        if dbname is None:
            self.global_db.flush()
            with self._mirrors_lock:
                for mirror in self.mirrors.values():
                    mirror.flush()
        else:
            mirror = self.get_mirror(dbname)
            mirror.flush()
            # Re-sync from global
            mirror.sync_from_global(self.global_db.get_all_addrs())

    def update_route(self):
        """Update routes via IPv6RouteUpdater if prefix changed."""
        old_prefix = self.prefix
        self.prefixer = IPv6Prefixer(verbose=self.verbose)
        new_prefix = self.prefixer.prefix

        if old_prefix == new_prefix:
            return

        if self.verbose:
            old_str = logstr.file(old_prefix)
            new_str = logstr.okay(new_prefix)
            logger.note(f"> IPv6 prefix changed: {old_str} -> {new_str}")

        self.prefix = new_prefix
        self.global_db.set_prefix(new_prefix)
        self.route_updater = IPv6RouteUpdater(verbose=self.verbose)
        self.route_updater.run()

        # Flush all databases since old addrs are invalid
        self.flush()
        if self.verbose:
            logger.okay("✓ Flushed all dbs due to prefix change")

    async def monitor_route(self):
        """Monitor ipv6 prefix change of local network periodically."""
        try:
            while True:
                try:
                    self.update_route()
                except Exception as e:
                    if self.verbose:
                        logger.warn(f"× Route monitor error: {e}")
                await asyncio.sleep(self.route_check_interval)
        except asyncio.CancelledError:
            if self.verbose:
                logger.note("> Route monitor task cancelled")
            raise

    async def maintain_usable_addrs(self):
        """Background task to maintain usable_num of addrs in global db."""
        try:
            while True:
                try:
                    exist_count = len(self.global_db.get_all_addrs())
                    if exist_count < self.usable_num:
                        remain_count = self.usable_num - exist_count
                        if self.verbose:
                            count_str = logstr.mesg(
                                f"[{exist_count}/{self.usable_num}]"
                            )
                            logger.note(
                                f"> Global addrs: {count_str}; "
                                f"need to spawn {remain_count} new addrs..."
                            )
                        # Run blocking spawns() in thread pool to allow cancellation
                        spawned_addrs, should_stop = await asyncio.to_thread(
                            self.spawns, remain_count
                        )
                        self.save()
                        # If spawns() hit consecutive failure limit, stop task completely
                        if should_stop:
                            if self.verbose:
                                logger.warn(
                                    f"× Spawn stopped: got {len(spawned_addrs)}/{remain_count}, {SPAWN_MAX_ADDRS} failures. Task terminated."
                                )
                            return  # Exit the task completely
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    if self.verbose:
                        logger.warn(f"× Maintain addrs error: {e}")
                await asyncio.sleep(MAINTAIN_INTERVAL)
        except asyncio.CancelledError:
            if self.verbose:
                logger.note("> Maintain addrs task cancelled")
            raise

    def start_background_tasks(self):
        """Start background tasks for route monitoring and addr maintenance."""
        loop = asyncio.get_event_loop()
        self._route_monitor_task = loop.create_task(self.monitor_route())
        self._spawn_task = loop.create_task(self.maintain_usable_addrs())

    def stop_background_tasks(self):
        """Stop background tasks."""
        if self._route_monitor_task:
            self._route_monitor_task.cancel()
        if self._spawn_task:
            self._spawn_task.cancel()

    def get_global_stats(self) -> dict:
        """Get global database statistics."""
        return {
            "prefix": self.prefix,
            "total_addrs": len(self.global_db.get_all_addrs()),
            "usable_num_target": self.usable_num,
            "mirrors": list(self.mirrors.keys()),
        }

    def get_mirror_stats(self, dbname: str) -> dict:
        """Get statistics for a specific mirror."""
        mirror = self.get_mirror(dbname)
        return mirror.get_stats()


# ========== FastAPI Application ==========


class ReportRequestItem(BaseModel):
    addr: str
    status: str  # AddrStatus value


class ReportRequest(BaseModel):
    dbname: str = DBNAME
    report_info: ReportRequestItem


class ReportsRequest(BaseModel):
    dbname: str = DBNAME
    report_infos: list[ReportRequestItem]


def create_app(
    db_root: Path = None,
    usable_num: int = USABLE_NUM,
    verbose: bool = False,
) -> FastAPI:
    """Create FastAPI application with IPv6DBServer."""

    server = IPv6DBServer(
        db_root=db_root,
        usable_num=usable_num,
        verbose=verbose,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        server.start_background_tasks()
        if verbose:
            logger.okay("✓ IPv6DBServer started")
        yield
        # Shutdown
        server.stop_background_tasks()
        server.save()
        if verbose:
            logger.okay("✓ IPv6DBServer stopped")

    app = FastAPI(title="IPv6DBServer", lifespan=lifespan)

    @app.get("/spawn")
    async def spawn():
        """Spawn a new random IPv6 addr to global db."""
        addr = server.spawn()
        return {"success": addr is not None, "addr": addr}

    @app.get("/spawns")
    async def spawns(num: int = Query(default=1, ge=1, le=100)):
        """Spawn multiple new random IPv6 addrs to global db."""
        addrs = server.spawns(num)
        return {"success": len(addrs) > 0, "addrs": addrs}

    @app.get("/pick")
    async def pick(dbname: str = Query(default=DBNAME)):
        """Pick an idle addr from specific dbname's mirror."""
        addr = server.pick(dbname)
        return {"success": addr is not None, "addr": addr, "dbname": dbname}

    @app.get("/picks")
    async def picks(
        dbname: str = Query(default=DBNAME),
        num: int = Query(default=1, ge=1, le=100),
    ):
        """Pick multiple idle addrs from specific dbname's mirror."""
        addrs = server.picks(dbname, num)
        return {"success": len(addrs) > 0, "addrs": addrs, "dbname": dbname}

    @app.get("/check")
    async def check(addr: str):
        """Check usability of an addr."""
        usable = server.check(addr)
        return {"success": True, "addr": addr, "usable": usable}

    @app.get("/checks")
    async def checks(addrs: str):
        """Check usability of multiple addrs (comma-separated)."""
        addr_list = [a.strip() for a in addrs.split(",")]
        usables = server.checks(addr_list)
        return {"success": True, "results": dict(zip(addr_list, usables))}

    @app.post("/report")
    async def report(req: ReportRequest):
        """Report addr status to specific dbname's mirror."""
        report_info = AddrReportInfo(
            addr=req.report_info.addr,
            status=AddrStatus(req.report_info.status),
        )
        success = server.report(req.dbname, report_info)
        return {"success": success, "dbname": req.dbname}

    @app.post("/reports")
    async def reports(req: ReportsRequest):
        """Report multiple addrs status to specific dbname's mirror."""
        report_infos = [
            AddrReportInfo(addr=item.addr, status=AddrStatus(item.status))
            for item in req.report_infos
        ]
        success = server.reports(req.dbname, report_infos)
        return {"success": success, "dbname": req.dbname}

    @app.get("/stats")
    async def stats(dbname: str = Query(default=None)):
        """
        Get statistics.
        If dbname is None, return global stats.
        Otherwise, return stats for specific mirror.
        """
        if dbname is None:
            return server.get_global_stats()
        else:
            return server.get_mirror_stats(dbname)

    @app.post("/save")
    async def save():
        """Save all databases to persistent storage."""
        server.save()
        return {"success": True}

    @app.post("/flush")
    async def flush(dbname: str = Query(default=None)):
        """
        Flush database.
        If dbname is None, flush global and all mirrors.
        Otherwise, flush only the specified mirror.
        """
        server.flush(dbname)
        return {"success": True, "dbname": dbname}

    return app


class IPv6ServerArgparser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_argument(
            "-p",
            "--port",
            type=int,
            default=SERVER_PORT,
            help=f"Server port (default: {SERVER_PORT})",
        )
        self.add_argument(
            "-n",
            "--usable-num",
            type=int,
            default=USABLE_NUM,
            help=f"Number of usable addrs to maintain (default: {USABLE_NUM})",
        )
        self.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="Enable verbose logging",
        )

        self.args = self.parse_args()


def main():
    import uvicorn

    args = IPv6ServerArgparser().args
    app = create_app(
        usable_num=args.usable_num,
        verbose=args.verbose,
    )
    uvicorn.run(app, host=SERVER_HOST, port=args.port)


if __name__ == "__main__":
    main()

    # python -m webu.ipv6.server -p 16000 -n 100 -v
