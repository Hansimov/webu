"""Google 搜索模块 — 基于 ProxyManager + undetected chromedriver。

本地代理列表从 configs/proxies.json 读取，
包含 round-robin 负载均衡、健康检查、自动故障转移和 CAPTCHA 绕过。
"""

from .proxy_manager import ProxyManager, ProxyState, DEFAULT_PROXIES
from .scraper import GoogleScraper
from .parser import GoogleResultParser, GoogleSearchResult, GoogleSearchResponse
