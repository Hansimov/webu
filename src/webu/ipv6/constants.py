# IPv6 Module Constants

from pathlib import Path

# ========== Database ==========
DB_ROOT = Path(__file__).parent
DBNAME = "default"
GLOBAL_DB_FILE = "ipv6_global_addrs.json"
MIRROR_DB_DIR = "ipv6_mirrors"
USABLE_NUM = 20

# ========== Server ==========
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 16000
SERVER_URL = f"http://localhost:{SERVER_PORT}"

# ========== Check ==========
CHECK_URL = "https://test.ipw.cn"
CHECK_TIMEOUT = 5.0

# ========== Timeouts and Intervals ==========
CLIENT_TIMEOUT = 10.0
ADAPT_RETRY_INTERVAL = 5.0
ADAPT_MAX_RETRIES = 15
ROUTE_CHECK_INTERVAL = 1800.0  # 30min

# ========== Spawn ==========
SPAWN_MAX_RETRIES = 3
SPAWN_MAX_ADDRS = 3  # Stop spawning after this many consecutive failures
