# IPv6 Module Constants

from pathlib import Path

# ========== Database ========== #
DB_ROOT = Path(__file__).parent
DBNAME = "default"
GLOBAL_DB_FILE = "ipv6_global_addrs.json"
MIRROR_DB_DIR = "ipv6_mirrors"

# ========== Server ========== #
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 16000
SERVER_URL = f"http://localhost:{SERVER_PORT}"
USABLE_NUM = 20

# Use multiple IPv6-capable echo endpoints so address checks keep working even
# if a single public host loses its AAAA record or becomes temporarily unstable.
CHECK_URLS = [
    "https://api64.ipify.org",
    "https://v6.ident.me",
    "https://icanhazip.com",
    "https://ifconfig.me/ip",
]
CHECK_URL = CHECK_URLS[0]
CHECK_TIMEOUT = 5.0

ROUTE_CHECK_INTERVAL = 1800.0  # 30min

SPAWN_MAX_RETRIES = 3
SPAWN_MAX_ADDRS = 3

# ========== Client ========== #
CLIENT_TIMEOUT = 10.0

# ========== Session ========== #
ADAPT_RETRY_INTERVAL = 5.0
ADAPT_MAX_RETRIES = 15

REQUESTS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}
