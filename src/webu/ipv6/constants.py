# IPv6 Module Constants

from pathlib import Path

# ========== Database ==========
DB_ROOT = Path(__file__).parent
DBNAME = "default"
GLOBAL_DB_FILE = "ipv6_global_addrs.json"
MIRROR_DB_DIR = "ipv6_mirrors"
USABLE_NUM = 10

# ========== Server ==========
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 16000
SERVER_URL = f"http://localhost:{SERVER_PORT}"

# ========== Check ==========
CHECK_URL = "https://ipv6.icanhazip.com"
CHECK_TIMEOUT = 10.0

# ========== Timeouts and Intervals ==========
CLIENT_TIMEOUT = 10.0
ADAPT_RETRY_INTERVAL = 5.0
ROUTE_CHECK_INTERVAL = 60.0
MAINTAIN_INTERVAL = 10.0

# ========== Spawn ==========
MAX_SPAWN_ATTEMPTS = 100
