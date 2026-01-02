# IPv6 Module

IPv6 address pool management system with FastAPI server and client support.

## Architecture

### Database Structure

**Global Database** (`GlobalIPv6DB`)
- Server-maintained, stores all spawned addresses (verified usable)
- File: `ipv6_global_addrs.json`
- Only contains addresses that passed usability check during spawn

**Mirror Databases** (`MirrorIPv6DB`)
- Per-dbname databases that mirror global addresses
- Directory: `ipv6_mirrors/`
- Each mirror maintains its own status for addresses: `idle`, `using`, `bad`
- Allows different tasks/groups to track address usage independently

### Address Status

`AddrStatus` enum in `database.py`:
- `idle`: Usable and not in use
- `using`: Currently in use
- `bad`: Marked as bad (failed checks)

## Components

### `route.py`

**`class IPv6Prefixer`**
- Detects IPv6 prefix from network interfaces
- Properties: `netint` (network interface), `prefix` (IPv6 prefix), `prefix_bits`

**`class IPv6RouteUpdater`**
- Updates IPv6 routes using `ndppd` and `ip route add`
- Methods:
  - `add_route()`: Add IP route for IPv6 prefix
  - `del_route()`: Delete IP route
  - `is_ndppd_conf_latest()`: Check if ndppd.conf is up-to-date
  - `modify_ndppd_conf()`: Update ndppd.conf with current prefix
  - `restart_ndppd()`: Restart ndppd service
  - `run()`: Full setup (add route, update config, restart service)

### `database.py`

**`class GlobalIPv6DB`**
- Manages global address pool
- Methods:
  - `add_addr(addr: str) -> bool`: Add new address
  - `has_addr(addr: str) -> bool`: Check if address exists
  - `get_all_addrs() -> list[str]`: Get all addresses
  - `set_prefix(prefix: str)`: Set current prefix
  - `save()`: Sync to persistent storage
  - `load()`: Load from persistent storage
  - `flush()`: Clear cache and sync

**`class MirrorIPv6DB`**
- Per-dbname mirror of global addresses
- Methods:
  - `sync_from_global(global_addrs: list[str])`: Sync from global DB
  - `get_idle_count() -> int`: Count idle addresses
  - `get_idle_addr() -> str | None`: Get idle address and mark as using
  - `release_addr(report_info: AddrReportInfo)`: Release address with status
  - `get_stats() -> dict`: Get statistics (total, idle, using, bad)
  - `save()`, `load()`, `flush()`: Storage operations

### `server.py`

**`class IPv6DBServer`**
- FastAPI server for IPv6 address management
- Initialization parameters:
  - `db_root`: Database directory (default: module directory)
  - `usable_num`: Target number of usable addresses (default: 20)
  - `check_url`: URL for usability check (default: "https://test.ipw.cn")
  - `check_timeout`: Timeout for checks (default: 5.0s)
  - `route_check_interval`: Route monitoring interval (default: 1800s)

**Core Methods:**
- `spawn() -> str`: Generate one random usable address
- `spawns(num: int) -> tuple[list[str], bool]`: Generate multiple addresses
- `check(addr: str) -> bool`: Check address usability
- `checks(addrs: list[str]) -> list[bool]`: Check multiple addresses
- `pick(dbname: str) -> str`: Pick idle address from mirror
- `picks(dbname: str, num: int) -> list[str]`: Pick multiple addresses
- `report(dbname: str, report_info: AddrReportInfo) -> bool`: Report address status
- `reports(dbname: str, report_infos: list[AddrReportInfo]) -> bool`: Report multiple
- `save()`, `load()`, `flush()`: Database operations
- `update_route()`: Update routes if prefix changed
- `monitor_route()`: Background task to monitor prefix changes

**FastAPI Endpoints:**
- `GET /stats?dbname=`: Global stats (no dbname) or mirror stats
- `GET /spawn`: Spawn single address
- `GET /spawns?num=`: Spawn multiple addresses
- `GET /pick?dbname=`: Pick address from mirror
- `GET /picks?dbname=&num=`: Pick multiple addresses
- `POST /check`: Check single address usability
- `POST /checks`: Check multiple addresses
- `POST /report`: Report address status
- `POST /reports`: Report multiple addresses
- `POST /save`: Save all databases
- `POST /flush?dbname=`: Flush database(s)

All endpoints include Pydantic Response models with examples in Swagger UI.

**Running the server:**
```bash
python -m webu.ipv6.server -p 16000 -n 100 -v
# -p: port (default: 16000)
# -n: usable_num (default: 20)
# -v: verbose mode
```

### `client.py`

**`class IPv6DBClient`**
- Client for communicating with IPv6DBServer
- Initialization parameters:
  - `dbname`: Database name (default: "default")
  - `server_url`: Server URL (default: "http://localhost:16000")
  - `timeout`: Request timeout (default: 10.0s)

**Methods:**
- `pick() -> str`: Pick idle address from server
- `picks(num: int) -> list[str]`: Pick multiple addresses
- `report(report_info: AddrReportInfo) -> bool`: Report address status
- `reports(report_infos: list[AddrReportInfo]) -> bool`: Report multiple

Note: Client uses IPv4 to communicate with server.

### `session.py`

**`class IPv6SessionAdapter`**
- Helper for adapting requests.Session to IPv6
- Static methods:
  - `force_ipv4()`: Force IPv4 connections
  - `force_ipv6()`: Force IPv6 connections
  - `adapt(session: Session, ip: str)`: Bind session to specific IPv6 address

**`class IPv6Session`**
- Inherits from `requests.Session`
- Auto-manages IPv6 addresses from database
- Initialization parameters:
  - `dbname`: Database name (default: "default")
  - `server_url`: Server URL (default: "http://localhost:16000")
  - `adapt_retry_interval`: Retry interval when no addresses (default: 5.0s)
  - `adapt_max_retries`: Max retries (default: 15)

**Methods:**
- `adapt() -> bool`: Pick new address and bind to session
  - Automatically waits if database is empty
  - Retries with configurable interval and max attempts
- `report(status: AddrStatus)`: Report current address status

**Usage:**
```python
from webu.ipv6.session import IPv6Session
from webu.ipv6.database import AddrStatus

session = IPv6Session(dbname="scraper1", verbose=True)
# Auto-adapts to IPv6 address on initialization

try:
    response = session.get("https://example.com")
    session.report(AddrStatus.IDLE)  # Success
except Exception as e:
    session.report(AddrStatus.BAD)   # Failed
    session.adapt()  # Get new address
```

## Workflow

### Server Side

1. **Start Server**: `IPv6DBServer` initializes with route updater
2. **Route Setup**: Monitors IPv6 prefix and updates routes automatically
3. **Address Spawning**: Background task maintains `usable_num` addresses
4. **Mirror Management**: Creates per-dbname mirrors on first request
5. **Address Distribution**: Serves pick requests from mirror pools

### Client Side (Scraper)

1. **Create Session**: `IPv6Session(dbname="task1")` 
2. **Auto-Adapt**: Session picks address from server on init
3. **Make Requests**: Use session for HTTP requests via bound IPv6
4. **Report Status**: Call `session.report(AddrStatus.IDLE/BAD)` after use
5. **Handle Failures**: Call `session.adapt()` to get new address

### Data Flow

```
Scraper (IPv6Session)
    ↓ pick
IPv6DBClient
    ↓ HTTP GET /pick?dbname=task1
IPv6DBServer (FastAPI)
    ↓ get_idle_addr()
MirrorIPv6DB[task1]  ← sync_from_global ← GlobalIPv6DB
    ↑ release_addr()           ↑
    ↑                          ↑ add_addr()
IPv6DBServer                   ↑
    ↑ HTTP POST /report    spawn() → check()
IPv6DBClient
    ↑ report
Scraper (IPv6Session)
```

## Configuration

Default constants in `constants.py`:
- `DB_ROOT`: Module directory
- `DBNAME`: "default"
- `SERVER_PORT`: 16000
- `USABLE_NUM`: 20 addresses
- `CHECK_URL`: "https://test.ipw.cn"
- `CHECK_TIMEOUT`: 5.0s
- `ROUTE_CHECK_INTERVAL`: 1800s (30min)
- `CLIENT_TIMEOUT`: 10.0s
- `ADAPT_RETRY_INTERVAL`: 5.0s
- `ADAPT_MAX_RETRIES`: 15