"""Google 搜索相关常量。

本模块只包含 google_api 模块自身需要的常量。
代理管理由 ProxyManager 负责，不再依赖 proxy_api 模块。
"""

# ═══════════════════════════════════════════════════════════════
# Google 搜索
# ═══════════════════════════════════════════════════════════════

GOOGLE_SEARCH_URL = "https://www.google.com/search"
GOOGLE_HOME_URL = "https://www.google.com"

# Google 可用性检测用的测试查询
GOOGLE_CHECK_QUERY = "test"

# 搜索超时（秒）
SEARCH_TIMEOUT = 30

# ═══════════════════════════════════════════════════════════════
# 浏览器指纹随机化
# ═══════════════════════════════════════════════════════════════

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
]

VIEWPORT_SIZES = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1280, "height": 720},
    {"width": 2560, "height": 1440},
]

LOCALES = [
    "en-US",
    "en-GB",
    "en-CA",
    "en-AU",
]
