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
    4. abandon() — 标记失效代理为废弃
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
        """一键刷新：采集 + 标记废弃 + 检测未检测的 IP。

        Returns:
            {"collect": dict, "check_results": list}
        """
        logger.note("> Proxy pool refresh ...")
        # 1. 采集新代理
        collect_result = self.collect()
        # 2. 扫描并标记废弃代理
        abandoned_count = self.scan_abandoned()
        # 3. 检测未检测的 IP
        check_results = await self.checker.check_unchecked(limit=check_limit)
        stats = self.stats()
        logger.okay(f"  ✓ Refresh done: {logstr.mesg(stats)}")
        return {
            "collect": collect_result,
            "check_count": len(check_results),
            "abandoned_marked": abandoned_count,
            "stats": stats,
        }

    async def search_parse_test(
        self,
        query: str = "python programming",
        limit: int = 5,
    ) -> list[dict]:
        """用 Level-2 有效代理测试 Google 搜索结果解析 (Playwright)。

        Google 搜索页面仅返回 JS SPA（客户端渲染），纯 HTTP 请求无法获取
        可解析的 HTML。因此使用 Playwright 浏览器渲染页面后解析搜索结果。

        流程：启动 Playwright → 逐个代理搜索 → Parser 解析 → 返回结果

        Args:
            query: 搜索查询词
            limit: 测试的代理数量

        Returns:
            测试结果列表
        """
        import time
        from .proxy_checker import _build_proxy_url

        # Lazy import 避免循环依赖（scraper → proxy_pool → scraper）
        from .scraper import GoogleScraper

        # 获取有效代理（优先 L2，不足则补充 L1）
        proxies = self.store.get_valid_proxies(limit=limit * 5, max_latency_ms=15000)
        l2_list = [p for p in proxies if p.get("check_level") == 2]
        l1_list = [p for p in proxies if p.get("check_level") != 2]
        # L2 优先，L1 补充
        test_proxies = l2_list[:limit]
        if len(test_proxies) < limit:
            test_proxies.extend(l1_list[: limit - len(test_proxies)])

        if not test_proxies:
            logger.warn("  × No valid proxies for search_parse_test")
            return []

        logger.note(
            f"> Testing Google search parsing (Playwright) with "
            f"{logstr.mesg(len(test_proxies))} proxies, query={logstr.mesg(query)}"
        )

        # 创建 scraper（不使用 self 作为 proxy_pool，避免自动选代理）
        scraper = GoogleScraper(
            proxy_pool=self,
            headless=True,
            verbose=self.verbose,
        )

        results = []
        try:
            await scraper.start()

            for i, proxy in enumerate(test_proxies):
                proxy_url = proxy.get("proxy_url") or _build_proxy_url(
                    proxy["ip"], proxy["port"], proxy["protocol"]
                )
                test_result = {
                    "proxy_url": proxy_url,
                    "ip": proxy["ip"],
                    "port": proxy["port"],
                    "protocol": proxy["protocol"],
                    "success": False,
                    "result_count": 0,
                    "total_results_text": "",
                    "has_captcha": False,
                    "error": "",
                    "results": [],
                    "latency_ms": 0,
                }

                try:
                    start = time.time()
                    # 使用 Playwright 搜索（指定代理）
                    parsed = await scraper.search(
                        query=query,
                        num=10,
                        lang="en",
                        proxy_url=proxy_url,
                        retry_count=0,  # 不重试，只测一次
                    )
                    elapsed_ms = int((time.time() - start) * 1000)
                    test_result["latency_ms"] = elapsed_ms
                    test_result["has_captcha"] = parsed.has_captcha
                    test_result["total_results_text"] = parsed.total_results_text
                    test_result["result_count"] = len(parsed.results)
                    test_result["results"] = [r.to_dict() for r in parsed.results]

                    if parsed.has_captcha:
                        test_result["error"] = "CAPTCHA detected"
                    elif parsed.results:
                        test_result["success"] = True
                    else:
                        test_result["error"] = parsed.error or "No results parsed"

                except Exception as e:
                    test_result["error"] = str(e)[:200]

                results.append(test_result)
                status = "✓" if test_result["success"] else "×"
                logger.mesg(
                    f"  [{i+1}/{len(test_proxies)}] {status} {proxy_url} → "
                    f"{test_result['result_count']} results ({test_result['latency_ms']}ms)"
                )

        finally:
            await scraper.stop()

        success_count = sum(1 for r in results if r["success"])
        logger.okay(
            f"  ✓ Parse test: {logstr.mesg(success_count)}/{len(results)} "
            f"proxies produced parseable results"
        )
        return results
