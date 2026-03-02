"""Google 搜索相关常量。

代理池基础设施常量请参见 webu.proxy_api.constants。
"""

# ═══════════════════════════════════════════════════════════════
# Google 搜索相关常量
# ═══════════════════════════════════════════════════════════════

GOOGLE_SEARCH_URL = "https://www.google.com/search"
GOOGLE_HOME_URL = "https://www.google.com"

# Google 可用性检测用的测试查询
GOOGLE_CHECK_QUERY = "test"

# 搜索超时（秒）
SEARCH_TIMEOUT = 30

# ═══════════════════════════════════════════════════════════════
# 向后兼容 — 从 proxy_api 重新导出常用常量
# ═══════════════════════════════════════════════════════════════

from webu.proxy_api.constants import (
    MONGO_CONFIGS,
    MongoConfigsType,
    PROXY_SOURCES,
    ProxySourceType,
    COLLECTION_IPS,
    COLLECTION_CHECKED_IPS,
    PROXY_CHECK_TIMEOUT,
    CHECK_CONCURRENCY,
    FETCH_PROXY,
    ABANDONED_FAIL_THRESHOLD,
    ABANDONED_STALE_HOURS,
    ABANDONED_COOLDOWN_HOURS,
    USER_AGENTS,
    VIEWPORT_SIZES,
    LOCALES,
)

# 向后兼容别名
COLLECTION_GOOGLE_IPS = COLLECTION_CHECKED_IPS
