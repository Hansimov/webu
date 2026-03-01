"""代理池管理器 — 编排 IP 采集、检测、选取。"""

import asyncio
import random

from tclogger import logger, logstr

from .constants import MONGO_CONFIGS, MongoConfigsType
from .mongo import MongoProxyStore
from .proxy_collector import ProxyCollector
from .proxy_checker import ProxyChecker


class ProxyPool:
    """代理池管理器。

    统一管理 IP 的采集、检测和选取流程：
    1. collect() — 从免费代理列表 URL 采集 IP 到 MongoDB
    2. check()   — 对 IP 进行 Google 可用性检测
    3. get()     — 从已验证可用的 IP 中选取代理
    """

    def __init__(
        self,
        configs: MongoConfigsType = None,
        verbose: bool = True,
    ):
        self.store = MongoProxyStore(configs=configs, verbose=verbose)
        self.collector = ProxyCollector(store=self.store, verbose=verbose)
        self.checker = ProxyChecker(store=self.store, verbose=verbose)
        self.verbose = verbose
        # 最近使用的 IP 列表（避免短期内过度复用）
        self._recent_ips: list[str] = []
        self._recent_max = 20

    # ── 采集 ──────────────────────────────────────────────────

    def collect(self) -> dict:
        """采集 IP：从所有配置的代理源拉取 IP 并存储。"""
        return self.collector.collect_all()

    def collect_source(self, source_name: str) -> dict:
        """从指定代理源采集。"""
        return self.collector.collect_source(source_name)

    # ── 检测 ──────────────────────────────────────────────────

    async def check_unchecked(self, limit: int = 500, level: str = "all") -> list[dict]:
        """检测尚未检测过的 IP。"""
        return await self.checker.check_unchecked(limit=limit, level=level)

    async def check_stale(self, limit: int = 200) -> list[dict]:
        """重新检测过期的 IP。"""
        return await self.checker.check_stale(limit=limit)

    async def check_all(self, limit: int = 0) -> list[dict]:
        """检测所有 IP。"""
        return await self.checker.check_all(limit=limit)

    # ── 选取 ──────────────────────────────────────────────────

    def get_proxy(self, max_latency_ms: int = 10000) -> dict | None:
        """获取一个可用的 Google 代理 IP。

        优先返回低延迟、最近未使用过的代理。

        Returns:
            {"ip", "port", "protocol", "proxy_url", "latency_ms"} or None
        """
        proxies = self.store.get_valid_proxies(
            limit=50,
            max_latency_ms=max_latency_ms,
            exclude_ips=self._recent_ips[-self._recent_max :] if self._recent_ips else None,
        )

        if not proxies:
            # 如果排除最近使用的 IP 后没有结果，放宽限制
            proxies = self.store.get_valid_proxies(
                limit=50, max_latency_ms=max_latency_ms
            )

        if not proxies:
            if self.verbose:
                logger.warn("  × No valid proxies available")
            return None

        # 从 top N 中随机选取（避免总是选同一个）
        top_n = min(10, len(proxies))
        selected = random.choice(proxies[:top_n])

        # 记录最近使用
        self._recent_ips.append(selected["ip"])
        if len(self._recent_ips) > self._recent_max * 2:
            self._recent_ips = self._recent_ips[-self._recent_max :]

        if self.verbose:
            logger.mesg(
                f"  → Proxy: {logstr.mesg(selected['proxy_url'])} "
                f"({selected.get('latency_ms', '?')}ms)"
            )

        return selected

    def get_proxies(self, count: int = 5, max_latency_ms: int = 10000) -> list[dict]:
        """获取多个可用代理。"""
        proxies = self.store.get_valid_proxies(
            limit=count * 3, max_latency_ms=max_latency_ms
        )
        if len(proxies) > count:
            proxies = random.sample(proxies, count)
        return proxies

    # ── 统计 ──────────────────────────────────────────────────

    def stats(self) -> dict:
        """获取代理池统计信息。"""
        return self.store.get_stats()

    # ── 一键流程 ──────────────────────────────────────────────

    async def refresh(self, check_limit: int = 200) -> dict:
        """一键刷新：采集 + 检测未检测的 IP。

        Returns:
            {"collect": dict, "check_results": list}
        """
        logger.note("> Proxy pool refresh ...")
        collect_result = self.collect()
        check_results = await self.checker.check_unchecked(limit=check_limit)
        stats = self.stats()
        logger.okay(f"  ✓ Refresh done: {logstr.mesg(stats)}")
        return {
            "collect": collect_result,
            "check_count": len(check_results),
            "stats": stats,
        }
