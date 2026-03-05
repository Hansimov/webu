"""Google 搜索模块 — 基于 ProxyManager + undetected chromedriver。

使用固定代理列表（warp + 备用）进行 Google 搜索，
包含自动故障转移、健康检查和 CAPTCHA 绕过功能。
"""

from .proxy_manager import ProxyManager, ProxyState, DEFAULT_PROXIES
from .scraper import GoogleScraper
from .parser import GoogleResultParser, GoogleSearchResult, GoogleSearchResponse
