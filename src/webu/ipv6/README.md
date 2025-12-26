# Ipv6 Module

IPv6 route, proxy, pool, and manager.

## `route.py`

### `class IPv6Prefixer`

Helper class of `class IPv6RouteUpdater`.

Auto init `netint` and `prefix`, used by :
- `self.netint`
- `self.prefix`
- `def addr_to_segs()`

### `class IPv6RouteUpdater`

Update IPv6 routes using `ndppd` and `ip route add`:

- `def add_route`
- `def is_ndppd_conf_latest`
- `def modify_ndppd_conf`

## `session.py`

### `class IPv6SessionAdapter`

Helper class of `class IPv6Session`.

Adapter to force connect via IPv6 in requests sessions. 
- `def force_ipv4()`
- `def force_ipv6()`
- `def adapt(session, ip)`


### `class IPv6Session`

Inherits from `requests.Session`, and supports force ipv6 connection, and auto use new ipv6 addr from pool.

Could be used directly by outside scraper.

- `def adapt()`: pick ip from pool, and adapt session to use that ip.

## `pool.py`

### `class IPv6Checker`

Helper class of `IPv6Spawner`.

Check ipv6 addr usability.

- `def check(addr)`
- `def checks(addrs)`

### `class IPv6Spawner`

- `def spawn(num:int=1)`: Spawn random IPv6 address not in pool.


### `class IPv6Picker`

Used by `class IPv6Session`.

Pick IPv6 address from pool.

### `class IPv6Database`

- `def exists(addr)`
- `def push(addr)`
- `def pop(addr)`
- `def len()`

### `class IPv6Pool`


## How to use in scraper

### scraper side
- `IPv6Session` could be instantiated as `session` in scraper
- if current ipv6 addr is unusable, call `session.adapt()` to switch to use a new addr from pool
- if pool is empty, `adapt()` would hang, and wait for new addrs spawned and available

### pool side
- `IPv6Pool` is used by `IPv6Session`, and pool is consited of `IPv6Database`, `IPv6Picker` and `IPv6Spawner`
- `IPv6Database` manages the ipv6 addrs cache, storage and flush
- `IPv6Picker` picks good and not-using addrs from database
- `IPv6Spawner` spawns new random addrs, and it would use `IPv6Checker` to check addr usability

### database side

- `IPv6Database` uses `json` as persistent storage, and `IPv6Cacher` as in-memory cache
- it contains `IPv6Cacher` and `IPv6Storage`
- `IPv6Cacher` manages in-memory cache of addrs, and has methods like `push()`, `pop()`, `exists()`, `len()`
- `IPv6Storage` manages persistent storage of addrs, and has methods like `load()`, `save()`, `flush()`
- should run as a service