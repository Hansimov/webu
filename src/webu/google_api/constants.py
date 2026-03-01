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
    # ── Tier 1: 高频更新（分钟级）──────────────────────────
    # proxifly — 每 5 分钟更新
    {
        "url": "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/https/data.txt",
        "protocol": "https",
        "source": "proxifly",
    },
    {
        "url": "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks4/data.txt",
        "protocol": "socks4",
        "source": "proxifly",
    },
    {
        "url": "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt",
        "protocol": "socks5",
        "source": "proxifly",
    },
    # zloi-user — 每 10 分钟更新
    {
        "url": "https://github.com/zloi-user/hideip.me/raw/refs/heads/master/https.txt",
        "protocol": "https",
        "source": "zloi-user",
    },
    {
        "url": "https://github.com/zloi-user/hideip.me/raw/refs/heads/master/socks4.txt",
        "protocol": "socks4",
        "source": "zloi-user",
    },
    {
        "url": "https://github.com/zloi-user/hideip.me/raw/refs/heads/master/socks5.txt",
        "protocol": "socks5",
        "source": "zloi-user",
    },

    # ── Tier 2: 每日更新，量大 ──────────────────────────────
    # TheSpeedX — 每日多次更新，量最大
    {
        "url": "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
        "protocol": "http",
        "source": "thespeedx",
    },
    {
        "url": "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks4.txt",
        "protocol": "socks4",
        "source": "thespeedx",
    },
    {
        "url": "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
        "protocol": "socks5",
        "source": "thespeedx",
    },
    # monosans — 每日更新，高质量
    {
        "url": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        "protocol": "http",
        "source": "monosans",
    },
    {
        "url": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt",
        "protocol": "socks4",
        "source": "monosans",
    },
    {
        "url": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
        "protocol": "socks5",
        "source": "monosans",
    },
    # hookzof — 每 10 分钟更新
    {
        "url": "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
        "protocol": "socks5",
        "source": "hookzof",
    },
    # roosterkid — 每日更新
    {
        "url": "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt",
        "protocol": "socks5",
        "source": "roosterkid",
    },
    # MuRongPIG — ⚠️ 已废弃：数据量巨大但极度过时，通过率接近 0%，不再使用
    # {
    #     "url": "https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/socks5.txt",
    #     "protocol": "socks5",
    #     "source": "murongpig",
    # },
    # {
    #     "url": "https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/http.txt",
    #     "protocol": "http",
    #     "source": "murongpig",
    # },
    # sunny9577 — 每日更新
    {
        "url": "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/generated/socks5_proxies.txt",
        "protocol": "socks5",
        "source": "sunny9577",
    },
    {
        "url": "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/generated/http_proxies.txt",
        "protocol": "http",
        "source": "sunny9577",
    },

    # ── Tier 3: API 接口源 ──────────────────────────────────
    # proxyscrape — 实时 API
    {
        "url": "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=all",
        "protocol": "socks5",
        "source": "proxyscrape",
    },
    {
        "url": "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4&timeout=10000&country=all",
        "protocol": "socks4",
        "source": "proxyscrape",
    },
    {
        "url": "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all",
        "protocol": "http",
        "source": "proxyscrape",
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

# 采集代理列表时使用的 HTTP 代理（用于访问外网代理源 URL）
FETCH_PROXY = "http://127.0.0.1:11119"

# ═══════════════════════════════════════════════════════════════
# 废弃 (Abandoned) 机制配置
# ═══════════════════════════════════════════════════════════════

# 连续失败次数超过此阈值，标记为废弃
ABANDONED_FAIL_THRESHOLD = 5

# 最后一次成功检测距今超过此时间（小时），且连续失败 >= 阈值，标记为废弃
ABANDONED_STALE_HOURS = 24

# 废弃代理重新检测的冷却期（小时）——废弃后至少等这么久才可重新检测
ABANDONED_COOLDOWN_HOURS = 72

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
