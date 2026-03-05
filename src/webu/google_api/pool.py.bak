"""Google 搜索代理池 — 在 ProxyPool 基础上增加 Level-2 检测和搜索测试。"""

import asyncio
import random
import time

from tclogger import logger, logstr

from webu.proxy_api.pool import ProxyPool
from webu.proxy_api.checker import build_proxy_url
from webu.proxy_api.constants import MongoConfigsType

from .checker import ProxyChecker


class GoogleSearchPool(ProxyPool):
    """Google 搜索专用代理池。

    继承 ProxyPool 的基础代理管理能力，增加：
    - Level-2 Google 搜索检测
    - 搜索结果解析测试
    - 两级检测流程编排
    """

    def __init__(
        self,
        configs: MongoConfigsType = None,
        verbose: bool = True,
    ):
        super().__init__(configs=configs, verbose=verbose)
        self.checker = ProxyChecker(store=self.store, verbose=verbose)

    # ── 覆写检测方法，使用两级检测 ────────────────────────────

    async def check_unchecked(self, limit: int = 500, level: str = "all") -> list[dict]:
        """两级检测尚未检测过的 IP。"""
        return await self.checker.check_unchecked(limit=limit, level=level)

    async def check_stale(self, limit: int = 200) -> list[dict]:
        """两级重新检测过期的 IP。"""
        return await self.checker.check_stale(limit=limit)

    async def check_all(self, limit: int = 0) -> list[dict]:
        """两级检测所有 IP。"""
        return await self.checker.check_all(limit=limit)

    # ── 一键流程（覆写，使用两级检测）────────────────────────

    async def refresh(self, check_limit: int = 200) -> dict:
        """一键刷新：采集 + 标记废弃 + 两级检测未检测的 IP。"""
        logger.note("> Google proxy pool refresh ...")
        collect_result = self.collect()
        abandoned_count = self.scan_abandoned()
        check_results = await self.checker.check_unchecked(limit=check_limit)
        stats = self.stats()
        logger.okay(f"  ✓ Refresh done: {logstr.mesg(stats)}")
        return {
            "collect": collect_result,
            "check_count": len(check_results),
            "abandoned_marked": abandoned_count,
            "stats": stats,
        }

    # ── Google 搜索测试 ──────────────────────────────────────

    async def search_parse_test(
        self,
        query: str = "python programming",
        limit: int = 5,
    ) -> list[dict]:
        """用 Level-2 有效代理测试 Google 搜索结果解析。

        使用 undetected chromedriver + Playwright CDP 渲染页面后解析搜索结果。
        """
        from .scraper import GoogleScraper

        # 获取有效代理（优先 L2，不足则补充 L1）
        proxies = self.store.get_valid_proxies(limit=limit * 5, max_latency_ms=15000)
        l2_list = [p for p in proxies if p.get("check_level") == 2]
        l1_list = [p for p in proxies if p.get("check_level") != 2]
        test_proxies = l2_list[:limit]
        if len(test_proxies) < limit:
            test_proxies.extend(l1_list[: limit - len(test_proxies)])

        if not test_proxies:
            logger.warn("  × No valid proxies for search_parse_test")
            return []

        logger.note(
            f"> Testing Google search parsing with "
            f"{logstr.mesg(len(test_proxies))} proxies, query={logstr.mesg(query)}"
        )

        scraper = GoogleScraper(
            proxy_pool=self,
            headless=True,
            verbose=self.verbose,
        )

        results = []
        try:
            await scraper.start()

            for i, proxy in enumerate(test_proxies):
                proxy_url = proxy.get("proxy_url") or build_proxy_url(
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
                    parsed = await scraper.search(
                        query=query,
                        num=10,
                        lang="en",
                        proxy_url=proxy_url,
                        retry_count=0,
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
