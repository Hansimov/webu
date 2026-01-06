import argparse
import asyncio
import random
import requests
import threading

from typing import Union

from contextlib import asynccontextmanager
from fastapi import FastAPI, Query
from pathlib import Path
from pydantic import BaseModel
from tclogger import TCLogger, logstr

from .constants import (
    DB_ROOT,
    SERVER_HOST,
    SERVER_PORT,
    DBNAME,
    MIRROR_DB_DIR,
    USABLE_NUM,
    CHECK_URL,
    CHECK_TIMEOUT,
    ROUTE_CHECK_INTERVAL,
    SPAWN_MAX_RETRIES,
    SPAWN_MAX_ADDRS,
)
from .database import AddrStatus, AddrReportInfo, GlobalIPv6DB, MirrorIPv6DB
from .route import IPv6Prefixer, IPv6RouteUpdater

logger = TCLogger(name="IPv6DBServer")

_addr_suffix = IPv6Prefixer()._addr_suffix


class IPv6DBServer:
    """
    FastAPI server for IPv6 address management.

    Architecture:
    - GlobalIPv6DB: Server-maintained, stores all spawned addrs (verified usable)
    - MirrorIPv6DB: Per-dbname, mirrors global addrs with its own status

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
        self.global_db = GlobalIPv6DB(db_root=self.db_root, verbose=verbose)

        # Mirror databases (per dbname)
        self.mirror_db_dir = self.db_root / MIRROR_DB_DIR
        self.mirrors: dict[str, MirrorIPv6DB] = {}
        self._mirrors_lock = threading.Lock()

        # IPv6 prefix management
        self.prefixer = IPv6Prefixer(verbose=verbose)
        self.prefix = self.prefixer.prefix
        self.route_updater = IPv6RouteUpdater(verbose=verbose)

        # Update global db prefix
        self.global_db.set_prefix(self.prefix)

        # Background tasks
        self._route_monitor_task: asyncio.Task = None

        # Load existing mirrors
        self._load_existing_mirrors()

    def _load_existing_mirrors(self):
        """Load existing mirror databases from disk."""
        if self.mirror_db_dir.exists():
            for db_file in self.mirror_db_dir.glob("*.json"):
                dbname = db_file.stem
                self.get_mirror(dbname)

    def get_mirror(self, dbname: str) -> MirrorIPv6DB:
        """Get or create a mirror for the given dbname."""
        with self._mirrors_lock:
            if dbname not in self.mirrors:
                mirror = MirrorIPv6DB(
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
                logfunc(f"  {mark} [{_addr_suffix(result_ip)}]")
            return is_good
        except Exception as e:
            if self.verbose:
                logger.warn(f"  × Failed: [{_addr_suffix(addr)}]")
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
        suffix = _addr_suffix(addr)
        logger.note(f"> Spawn: [{suffix}]")
        for retry in range(SPAWN_MAX_RETRIES):
            if self.verbose:
                if retry >= 1:
                    retry_str = logstr.mesg(f" ({retry + 1}/{SPAWN_MAX_RETRIES})")
                else:
                    retry_str = ""
                logger.mesg(f"  * Check: [{suffix}]{retry_str}")
            is_good = self.check(addr)
            if is_good:
                self.global_db.add_addr(addr)
                # Sync to all mirrors
                self._sync_all_mirrors()
                return addr
        if self.verbose:
            logger.warn(
                f"  × Spawn failed after {SPAWN_MAX_RETRIES} retries: [{suffix}]"
            )
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
            addr_str = logstr.okay(f"[{_addr_suffix(addr)}]")
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
                f"> Reported [{dbname}] [{_addr_suffix(report_info.addr)}]: {status_str}"
            )
        return True

    def reports(self, dbname: str, report_infos: list[AddrReportInfo]) -> bool:
        """Report multiple addrs status to specific dbname's mirror."""
        for report_info in report_infos:
            self.report(dbname, report_info)
        return True

    def reset(self, dbname: str, addr: str) -> bool:
        """Reset addr status to IDLE in specific dbname's mirror."""
        mirror = self.get_mirror(dbname)
        success = mirror.reset_addr(addr)
        if self.verbose and success:
            logger.note(f"> Reset [{dbname}] [{_addr_suffix(addr)}] to IDLE")
        return success

    def resets(self, dbname: str, addrs: list[str]) -> int:
        """Reset multiple addrs status to IDLE in specific dbname's mirror."""
        mirror = self.get_mirror(dbname)
        count = mirror.reset_addrs(addrs)
        if self.verbose:
            logger.note(f"> Reset [{dbname}] {count}/{len(addrs)} addrs to IDLE")
        return count

    def reset_all(self, dbname: str) -> int:
        """Reset all addrs status to IDLE in specific dbname's mirror."""
        mirror = self.get_mirror(dbname)
        count = mirror.reset_all()
        if self.verbose:
            logger.note(f"> Reset all [{dbname}] {count} addrs to IDLE")
        return count

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

    async def init_usable_addrs(self):
        """Initialize usable_num of addrs in global db at startup."""
        try:
            exist_count = len(self.global_db.get_all_addrs())
            if exist_count < self.usable_num:
                remain_count = self.usable_num - exist_count
                if self.verbose:
                    count_str = logstr.mesg(f"[{exist_count}/{self.usable_num}]")
                    logger.note(
                        f"> Global addrs: {count_str}; "
                        f"need to spawn {remain_count} new addrs..."
                    )
                # Run blocking spawns() in thread pool
                spawned_addrs, should_stop = await asyncio.to_thread(
                    self.spawns, remain_count
                )
                self.save()
                # Log result
                if should_stop:
                    if self.verbose:
                        logger.warn(
                            f"× Spawn stopped: got {len(spawned_addrs)}/{remain_count}, {SPAWN_MAX_ADDRS} failures."
                        )
                elif self.verbose:
                    logger.okay(f"✓ Spawned {len(spawned_addrs)} new addrs")
        except Exception as e:
            if self.verbose:
                logger.warn(f"× Init addrs error: {e}")

    def start_background_tasks(self):
        """Start background tasks for route monitoring."""
        loop = asyncio.get_event_loop()
        self._route_monitor_task = loop.create_task(self.monitor_route())

    def stop_background_tasks(self):
        """Stop background tasks."""
        if self._route_monitor_task:
            self._route_monitor_task.cancel()

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

# ========== Request Models ==========


class CheckRequest(BaseModel):
    addr: str


class ChecksRequest(BaseModel):
    addrs: list[str]


class ReportRequestItem(BaseModel):
    addr: str
    status: AddrStatus


class ReportRequest(BaseModel):
    dbname: str = DBNAME
    report_info: ReportRequestItem


class ReportsRequest(BaseModel):
    dbname: str = DBNAME
    report_infos: list[ReportRequestItem]


class ResetRequest(BaseModel):
    dbname: str = DBNAME
    addr: str


class ResetsRequest(BaseModel):
    dbname: str = DBNAME
    addrs: list[str]


# ========== Response Models ==========


class GlobalStatsResponse(BaseModel):
    """Response for global statistics."""

    prefix: str
    total_addrs: int
    usable_num_target: int
    mirrors: list[str]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "prefix": "240x:xxx:xxx:xxx",
                    "total_addrs": 223,
                    "usable_num_target": 100,
                    "mirrors": ["default", "test"],
                }
            ]
        }
    }


class MirrorStatsResponse(BaseModel):
    """Response for mirror-specific statistics."""

    dbname: str
    total: int
    idle: int
    using: int
    bad: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "dbname": "default",
                    "total": 223,
                    "idle": 200,
                    "using": 15,
                    "bad": 8,
                }
            ]
        }
    }


class SpawnResponse(BaseModel):
    """Response for spawning a single IPv6 address."""

    success: bool
    addr: str | None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "addr": "240x:xxx:xxx:xxx:xxx:xxx:xxx:xxx",
                }
            ]
        }
    }


class SpawnsResponse(BaseModel):
    """Response for spawning multiple IPv6 addresses."""

    success: bool
    addrs: list[str]
    should_stop: bool
    spawned_count: int
    requested_count: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "addrs": [
                        "240x:xxx:xxx:xxx:xxx:xxx:xxx:xxx",
                        "240x:yyy:yyy:yyy:yyy:yyy:yyy:yyy",
                        "240x:zzz:zzz:zzz:zzz:zzz:zzz:zzz",
                    ],
                    "should_stop": False,
                    "spawned_count": 3,
                    "requested_count": 5,
                }
            ]
        }
    }


class PickResponse(BaseModel):
    """Response for picking a single IPv6 address."""

    success: bool
    addr: str | None
    dbname: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "addr": "240x:xxx:xxx:xxx:xxx:xxx:xxx:xxx",
                    "dbname": "default",
                }
            ]
        }
    }


class PicksResponse(BaseModel):
    """Response for picking multiple IPv6 addresses."""

    success: bool
    addrs: list[str]
    dbname: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "addrs": [
                        "240x:xxx:xxx:xxx:xxx:xxx:xxx:xxx",
                        "240x:yyy:yyy:yyy:yyy:yyy:yyy:yyy",
                    ],
                    "dbname": "default",
                }
            ]
        }
    }


class CheckResponse(BaseModel):
    """Response for checking a single IPv6 address."""

    success: bool
    addr: str
    usable: bool

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "addr": "240x:xxx:xxx:xxx:xxx:xxx:xxx:xxx",
                    "usable": True,
                }
            ]
        }
    }


class ChecksResponse(BaseModel):
    """Response for checking multiple IPv6 addresses."""

    success: bool
    results: dict[str, bool]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "results": {
                        "240x:xxx:xxx:xxx:xxx:xxx:xxx:xxx": True,
                        "240x:yyy:yyy:yyy:yyy:yyy:yyy:yyy": True,
                        "2001:db8::1": False,
                    },
                }
            ]
        }
    }


class ReportResponse(BaseModel):
    """Response for reporting a single address status."""

    success: bool
    dbname: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "dbname": "default",
                }
            ]
        }
    }


class ReportsResponse(BaseModel):
    """Response for reporting multiple address statuses."""

    success: bool
    dbname: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "dbname": "default",
                }
            ]
        }
    }


class SaveResponse(BaseModel):
    """Response for saving databases."""

    success: bool

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                }
            ]
        }
    }


class FlushResponse(BaseModel):
    """Response for flushing databases."""

    success: bool
    dbname: str | None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "dbname": None,
                }
            ]
        }
    }


class ResetResponse(BaseModel):
    """Response for resetting a single address status."""

    success: bool
    dbname: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "dbname": "default",
                }
            ]
        }
    }


class ResetsResponse(BaseModel):
    """Response for resetting multiple addresses status."""

    success: bool
    dbname: str
    reset_count: int
    total_count: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "dbname": "default",
                    "reset_count": 5,
                    "total_count": 5,
                }
            ]
        }
    }


class ResetAllResponse(BaseModel):
    """Response for resetting all addresses status."""

    success: bool
    dbname: str
    reset_count: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "dbname": "default",
                    "reset_count": 223,
                }
            ]
        }
    }


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
        await server.init_usable_addrs()
        server.start_background_tasks()
        if verbose:
            logger.okay("✓ IPv6DBServer started")
        yield
        # Shutdown
        server.stop_background_tasks()
        server.save()
        if verbose:
            logger.okay("✓ IPv6DBServer stopped")

    app = FastAPI(
        title="IPv6DBServer",
        docs_url=None,
        lifespan=lifespan,
    )

    from ..fastapis.styles import setup_swagger_ui

    setup_swagger_ui(app)

    @app.get(
        "/stats",
        response_model=Union[GlobalStatsResponse, MirrorStatsResponse],
        summary="Get statistics. If dbname is None, return global stats. Otherwise, return stats for specific mirror.",
    )
    async def stats(dbname: str = Query(default=None)):
        if dbname is None:
            return server.get_global_stats()
        else:
            return server.get_mirror_stats(dbname)

    @app.get(
        "/spawn",
        response_model=SpawnResponse,
        summary="Spawn a new random IPv6 addr to global db",
    )
    async def spawn():
        addr = await asyncio.to_thread(server.spawn)
        return {"success": addr is not None, "addr": addr}

    @app.get(
        "/spawns",
        response_model=SpawnsResponse,
        summary="Spawn multiple new random IPv6 addrs to global db",
    )
    async def spawns(num: int = Query(default=1, ge=1, le=100)):
        addrs, should_stop = await asyncio.to_thread(server.spawns, num)
        return {
            "success": len(addrs) > 0,
            "addrs": addrs,
            "should_stop": should_stop,
            "spawned_count": len(addrs),
            "requested_count": num,
        }

    @app.get(
        "/pick",
        response_model=PickResponse,
        summary="Pick an idle addr from specific dbname's mirror",
    )
    async def pick(dbname: str = Query(default=DBNAME)):
        addr = server.pick(dbname)
        return {"success": addr is not None, "addr": addr, "dbname": dbname}

    @app.get(
        "/picks",
        response_model=PicksResponse,
        summary="Pick multiple idle addrs from specific dbname's mirror",
    )
    async def picks(
        dbname: str = Query(default=DBNAME),
        num: int = Query(default=1, ge=1, le=100),
    ):
        addrs = await asyncio.to_thread(server.picks, dbname, num)
        return {"success": len(addrs) > 0, "addrs": addrs, "dbname": dbname}

    @app.post(
        "/check",
        response_model=CheckResponse,
        summary="Check usability of an addr",
    )
    async def check(req: CheckRequest):
        usable = await asyncio.to_thread(server.check, req.addr)
        return {"success": True, "addr": req.addr, "usable": usable}

    @app.post(
        "/checks",
        response_model=ChecksResponse,
        summary="Check usability of multiple addrs",
    )
    async def checks(req: ChecksRequest):
        usables = await asyncio.to_thread(server.checks, req.addrs)
        return {"success": True, "results": dict(zip(req.addrs, usables))}

    @app.post(
        "/report",
        response_model=ReportResponse,
        summary="Report addr status to specific dbname's mirror",
    )
    async def report(req: ReportRequest):
        report_info = AddrReportInfo(
            addr=req.report_info.addr,
            status=AddrStatus(req.report_info.status),
        )
        success = server.report(req.dbname, report_info)
        return {"success": success, "dbname": req.dbname}

    @app.post(
        "/reports",
        response_model=ReportsResponse,
        summary="Report multiple addrs status to specific dbname's mirror",
    )
    async def reports(req: ReportsRequest):
        report_infos = [
            AddrReportInfo(addr=item.addr, status=AddrStatus(item.status))
            for item in req.report_infos
        ]
        success = await asyncio.to_thread(server.reports, req.dbname, report_infos)
        return {"success": success, "dbname": req.dbname}

    @app.post(
        "/reset",
        response_model=ResetResponse,
        summary="Reset addr status to IDLE in specific dbname's mirror",
    )
    async def reset(req: ResetRequest):
        success = await asyncio.to_thread(server.reset, req.dbname, req.addr)
        return {"success": success, "dbname": req.dbname}

    @app.post(
        "/resets",
        response_model=ResetsResponse,
        summary="Reset multiple addrs status to IDLE in specific dbname's mirror",
    )
    async def resets(req: ResetsRequest):
        count = await asyncio.to_thread(server.resets, req.dbname, req.addrs)
        return {
            "success": count > 0,
            "dbname": req.dbname,
            "reset_count": count,
            "total_count": len(req.addrs),
        }

    @app.post(
        "/reset_all",
        response_model=ResetAllResponse,
        summary="Reset all addrs status to IDLE in specific dbname's mirror",
    )
    async def reset_all(dbname: str = Query(default=DBNAME)):
        count = await asyncio.to_thread(server.reset_all, dbname)
        return {"success": count > 0, "dbname": dbname, "reset_count": count}

    @app.post(
        "/save",
        response_model=SaveResponse,
        summary="Save all databases to persistent storage",
    )
    async def save():
        await asyncio.to_thread(server.save)
        return {"success": True}

    @app.post(
        "/flush",
        response_model=FlushResponse,
        summary="Flush database. If dbname is None, flush global and all mirrors. Otherwise, flush only the specified mirror.",
    )
    async def flush(dbname: str = Query(default=None)):
        await asyncio.to_thread(server.flush, dbname)
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

    # Case1: normal serve
    # python -m webu.ipv6.server -p 16000 -n 100 -v

    # Case2: sudo serve (for route update)
    # echo $SUDOPASS | sudo -S env "PATH=$PATH" python -m webu.ipv6.server -p 16000 -n 100 -v
