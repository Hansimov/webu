"""Google 搜索模块 — 基于 proxy_api 代理池 + undetected chromedriver。"""

# 从 proxy_api 重新导出代理基础设施（向后兼容）
from webu.proxy_api.constants import (
    MONGO_CONFIGS, PROXY_SOURCES, MongoConfigsType,
    ABANDONED_FAIL_THRESHOLD, ABANDONED_STALE_HOURS, ABANDONED_COOLDOWN_HOURS,
)
from webu.proxy_api.mongo import MongoProxyStore
from webu.proxy_api.collector import ProxyCollector
from webu.proxy_api.checker import check_level1_batch, build_proxy_url
from webu.proxy_api.pool import ProxyPool

# Google 搜索特有模块
from .checker import ProxyChecker, check_level2_batch
from .pool import GoogleSearchPool
from .scraper import GoogleScraper
from .parser import GoogleResultParser, GoogleSearchResult, GoogleSearchResponse
