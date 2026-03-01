"""常量定义：MongoDB 配置、代理源 URL、User-Agent 列表等。"""

from typing import TypedDict, Optional

# ═══════════════════════════════════════════════════════════════
# MongoDB 配置
# ═══════════════════════════════════════════════════════════════


class MongoConfigsType(TypedDict):
    host: str
    port: int
    dbname: str


MONGO_CONFIGS: MongoConfigsType = {
    "host": "localhost",
    "port": 27017,
    "dbname": "webu",
}

# Collection 名称
COLLECTION_IPS = "ips"
COLLECTION_GOOGLE_IPS = "google_ips"

# ═══════════════════════════════════════════════════════════════
# 代理源 URL 配置
# ═══════════════════════════════════════════════════════════════


class ProxySourceType(TypedDict):
    url: str
    protocol: str  # http / https / socks5
    source: str  # 来源标识


PROXY_SOURCES: list[ProxySourceType] = [
    # proxifly — 每 5 分钟更新
    {
        "url": "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/https/data.txt",
        "protocol": "https",
        "source": "proxifly",
    },
    {
        "url": "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt",
        "protocol": "socks5",
        "source": "proxifly",
    },
    # TheSpeedX — 每日更新，量大
    {
        "url": "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
        "protocol": "http",
        "source": "thespeedx",
    },
    {
        "url": "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
        "protocol": "socks5",
        "source": "thespeedx",
    },
    # zloi-user — 每 10 分钟更新
    {
        "url": "https://github.com/zloi-user/hideip.me/raw/refs/heads/master/https.txt",
        "protocol": "https",
        "source": "zloi-user",
    },
    {
        "url": "https://github.com/zloi-user/hideip.me/raw/refs/heads/master/socks5.txt",
        "protocol": "socks5",
        "source": "zloi-user",
    },
]

# ═══════════════════════════════════════════════════════════════
# Google 搜索相关常量
# ═══════════════════════════════════════════════════════════════

GOOGLE_SEARCH_URL = "https://www.google.com/search"
GOOGLE_HOME_URL = "https://www.google.com"

# Google 可用性检测用的测试查询
GOOGLE_CHECK_QUERY = "test"

# 检测超时（秒）
PROXY_CHECK_TIMEOUT = 15

# 搜索超时（秒）
SEARCH_TIMEOUT = 30

# 并发检测数量
CHECK_CONCURRENCY = 20

# ═══════════════════════════════════════════════════════════════
# User-Agent 列表
# ═══════════════════════════════════════════════════════════════

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:134.0) Gecko/20100101 Firefox/134.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

# ═══════════════════════════════════════════════════════════════
# 浏览器视口尺寸列表（随机选择）
# ═══════════════════════════════════════════════════════════════

VIEWPORT_SIZES = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 720},
    {"width": 1600, "height": 900},
]

# ═══════════════════════════════════════════════════════════════
# 语言/地区列表（随机选择）
# ═══════════════════════════════════════════════════════════════

LOCALES = ["en-US", "en-GB", "en-CA", "en-AU"]
