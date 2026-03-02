"""代理池管理器 — 编排 IP 采集、Level-1 检测、选取。

此模块提供纯代理基础设施能力：
- 采集代理 IP
- Level-1 快速连通性检测
- 代理选取和轮换
- 废弃代理管理

Google 搜索特有的 Level-2 检测和搜索测试请参见 webu.google_api.pool。
"""

import asyncio
import random

from tclogger import logger, logstr

from .constants import MONGO_CONFIGS, MongoConfigsType
from .mongo import MongoProxyStore
from .collector import ProxyCollector
from .checker import check_level1_batch


class ProxyPool:
    """代理池管理器。

    统一管理 IP 的采集、检测和选取流程：
    1. collect() — 从免费代理列表 URL 采集 IP 到 MongoDB
    2. check()   — 对 IP 进行 Level-1 连通性检测
    3. get()     — 从已验证可用的 IP 中选取代理
    4. abandon() — 标记失效代理为废弃
    """

    def __init__(
        self,
        configs: MongoConfigsType = None,
        check_collection: str = None,
        verbose: bool = True,
    ):
        self.store = MongoProxyStore(
            configs=configs,
            check_collection=check_collection,
            verbose=verbose,
        )
        self.collector = ProxyCollector(store=self.store, verbose=verbose)
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

    async def check_unchecked(self, limit: int = 500) -> list[dict]:
        """Level-1 检测尚未检测过的 IP。"""
        ip_list = self.store.get_unchecked_ips(limit=limit)
        if not ip_list:
            logger.mesg("  No unchecked IPs found")
            return []
        return await check_level1_batch(
            ip_list, timeout_s=10, concurrency=100,
            verbose=self.verbose, store=self.store,
        )

    async def check_stale(self, limit: int = 200) -> list[dict]:
        """Level-1 重新检测过期的 IP。"""
        ip_list = self.store.get_stale_ips(limit=limit)
        if not ip_list:
            logger.mesg("  No stale IPs found")
            return []
        return await check_level1_batch(
            ip_list, timeout_s=10, concurrency=100,
            verbose=self.verbose, store=self.store,
        )

    async def check_all(self, limit: int = 0) -> list[dict]:
        """Level-1 检测所有 IP。"""
        ip_list = self.store.get_all_ips(limit=limit)
        if not ip_list:
            logger.mesg("  No IPs found in database")
            return []
        return await check_level1_batch(
            ip_list, timeout_s=10, concurrency=100,
            verbose=self.verbose, store=self.store,
        )

    # ── 废弃管理 ──────────────────────────────────────────────

    def scan_abandoned(self) -> int:
        """扫描并标记废弃代理。"""
        return self.store.scan_and_mark_abandoned()

    def get_abandoned_stats(self) -> dict:
        """获取废弃代理统计。"""
        total = self.store.get_abandoned_count()
        return {"total_abandoned": total}

    # ── 选取 ──────────────────────────────────────────────────

    def get_proxy(self, max_latency_ms: int = 10000) -> dict | None:
        """获取一个可用代理 IP。

        优先返回低延迟、最近未使用过的代理。
        """
        proxies = self.store.get_valid_proxies(
            limit=50,
            max_latency_ms=max_latency_ms,
            exclude_ips=self._recent_ips[-self._recent_max :] if self._recent_ips else None,
        )

        if not proxies:
            proxies = self.store.get_valid_proxies(
                limit=50, max_latency_ms=max_latency_ms
            )

        if not proxies:
            if self.verbose:
                logger.warn("  × No valid proxies available")
            return None

        top_n = min(10, len(proxies))
        selected = random.choice(proxies[:top_n])

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
        """一键刷新：采集 + 标记废弃 + Level-1 检测未检测的 IP。"""
        logger.note("> Proxy pool refresh ...")
        collect_result = self.collect()
        abandoned_count = self.scan_abandoned()
        check_results = await self.check_unchecked(limit=check_limit)
        stats = self.stats()
        logger.okay(f"  ✓ Refresh done: {logstr.mesg(stats)}")
        return {
            "collect": collect_result,
            "check_count": len(check_results),
            "abandoned_marked": abandoned_count,
            "stats": stats,
        }
