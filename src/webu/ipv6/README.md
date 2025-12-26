# Ipv6 Module

NOTE: APIs are in rapid change, refer to latest codes though.

## `route.py`

### `class IPv6RouteUpdater`

Update IPv6 routes using `ndppd` and `ip route add`:

- `def add_route`
- `def is_ndppd_conf_latest`
- `def modify_ndppd_conf`

Use helper `class IPv6Prefixer`: init `self.netint` and `self.prefix`

## `session.py`

### `class IPv6Session`

Inherits from `requests.Session`, and supports force ipv6 connection, and auto use new ipv6 addr from db.

Could be used directly by outside scraper.

- `def adapt()`: pick ip from db, and adapt session to use that ip.

Use helper `class IPv6SessionAdapter`:
- `def force_ipv4()`
- `def force_ipv6()`
- `def adapt(session, ip)`

## `server.py`

### `class IPv6DBServer`

- `def spawn()->str`: Spawn random IPv6 addr not in db
- `def pick()->str`: Pick usable and not-using addr from db
- `def check(addr:str)->bool`: check usability of addr
- `def report(addr:str, usable:bool)->bool`: report addr usability and status

For batch operations:

- `def spawns(num:int=1)->list[str]`
- `def picks(num:int=1)->list[str]`
- `def checks(addr:list[str])->list[bool]`
- `def reports(addr_usables:list[tuple[str,bool]])->bool`

## `client.py`

### `class IPv6DBClient`

- `pick()->str`: Pick usable and not-using addr from server
- `report(addr:str, usable:bool)`: report addr usability to server

For batch operations:

- `picks(num:int=1)->list[str]`
- `reports(addr_usables:list[tuple[str,bool]])->bool`

## How to use

### scraper side
- `IPv6Session` is instantiated as `session` in scraper
- if current ipv6 addr is unusable, call `session.adapt()` to use a new addr, which calls `IPv6DBClient.pick()`
- if db is empty, `adapt()` would hang, and wait for new addrs spawned and usable in server side

### database client side

- `IPv6DBClient` is used by `IPv6Session`
- communicates with `IPv6DBServer`
- `pick()` return good and not-using addrs from server
- `report(addr, usable)` report addr usability to server

### database server side

`IPv6DBServer`: (fastapi server)

- `dbname`: name of database, to maintain status and usability of addrs in different tasks or groups
- `usable_num`: number of real-time usable addrs to maintain in db

- `save()/load()/flush()`: sync between in-memory cache and persistent storage

- `check()/checks()` checks addr usability
- `spawn()/spawns()` creates new addrs, and ensures: random, not in db, usable
- `pick()/picks()` returns usable and not-using addrs

- `report()/reports()` reports addr usability and status
- `monitor_route()/update_route()`: monitor ipv6 prefix change of local network periodically, and update routes accordingly via `IPv6RouteUpdater` if change happens