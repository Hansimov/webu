"""IP 源采集模块 — 从免费代理列表 URL 拉取 IP 并存储到 MongoDB。"""

import re
import requests

from tclogger import logger, logstr
from typing import Optional

from .constants import PROXY_SOURCES, ProxySourceType, FETCH_PROXY
from .mongo import MongoProxyStore


class ProxyCollector:
    """从免费代理列表 URL 采集 IP。"""

    def __init__(
        self,
        store: MongoProxyStore,
        sources: list[ProxySourceType] = None,
        timeout: int = 30,
        fetch_proxy: str = FETCH_PROXY,
        verbose: bool = True,
    ):
        self.store = store
        self.sources = sources or PROXY_SOURCES
        self.timeout = timeout
        self.fetch_proxy = fetch_proxy
        self.verbose = verbose

    def _parse_proxy_line(self, line: str, default_protocol: str) -> Optional[dict]:
        """解析单行代理数据。"""
        line = line.strip()
        if not line:
            return None

        # 带协议前缀：protocol://ip:port
        match = re.match(r"^(https?|socks[45])://(.+):(\d+)$", line)
        if match:
            return {
                "protocol": match.group(1),
                "ip": match.group(2),
                "port": int(match.group(3)),
            }

        # 无协议前缀：ip:port 或 ip:port:extra
        match = re.match(r"^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d+)(?::.*)?$", line)
        if match:
            return {
                "protocol": default_protocol,
                "ip": match.group(1),
                "port": int(match.group(2)),
            }

        return None

    def fetch_source(self, source: ProxySourceType) -> list[dict]:
        """从单个代理源 URL 拉取 IP 列表。"""
        url = source["url"]
        protocol = source["protocol"]
        source_name = source["source"]

        if self.verbose:
            logger.note(f"> Fetching: {logstr.mesg(source_name)} ({protocol})")
            logger.mesg(f"  URL: {url}")

        try:
            proxies = {"http": self.fetch_proxy, "https": self.fetch_proxy} if self.fetch_proxy else None
            resp = requests.get(url, timeout=self.timeout, proxies=proxies)
            resp.raise_for_status()
            text = resp.text
        except Exception as e:
            logger.warn(f"  × Failed to fetch {source_name}: {e}")
            return []

        ip_list = []
        lines = text.strip().split("\n")
        for line in lines:
            parsed = self._parse_proxy_line(line, default_protocol=protocol)
            if parsed:
                parsed["source"] = source_name
                ip_list.append(parsed)

        if self.verbose:
            logger.okay(f"  ✓ Parsed {logstr.mesg(len(ip_list))} proxies")

        return ip_list

    def collect_all(self) -> dict:
        """从所有配置的代理源采集 IP 并存储到 MongoDB。"""
        logger.note(f"> Collecting proxies from {len(self.sources)} sources ...")
        all_ips = []

        for source in self.sources:
            ips = self.fetch_source(source)
            all_ips.extend(ips)

        logger.note(f"> Total fetched: {logstr.mesg(len(all_ips))} proxies")

        # 过滤掉已废弃的代理
        abandoned_set = self.store.get_abandoned_ips_set()
        if abandoned_set:
            before_count = len(all_ips)
            all_ips = [
                ip for ip in all_ips
                if (ip["ip"], ip["port"], ip["protocol"]) not in abandoned_set
            ]
            skipped = before_count - len(all_ips)
            if skipped > 0:
                logger.mesg(f"  ♻ Skipped {logstr.mesg(skipped)} abandoned proxies")
        else:
            skipped = 0

        if all_ips:
            result = self.store.upsert_ips(all_ips)
        else:
            result = {"inserted": 0, "updated": 0, "total": 0}

        result["total_fetched"] = len(all_ips) + skipped
        result["abandoned_skipped"] = skipped
        return result

    def collect_source(self, source_name: str) -> dict:
        """从指定名称的代理源采集 IP 并存储。"""
        matched = [s for s in self.sources if s["source"] == source_name]
        if not matched:
            logger.warn(f"  × Unknown source: {source_name}")
            return {"total_fetched": 0, "inserted": 0, "updated": 0, "total": 0}

        logger.note(f"> Collecting from source: {logstr.mesg(source_name)} ...")
        all_ips = []
        for source in matched:
            ips = self.fetch_source(source)
            all_ips.extend(ips)

        if all_ips:
            result = self.store.upsert_ips(all_ips)
        else:
            result = {"inserted": 0, "updated": 0, "total": 0}

        result["total_fetched"] = len(all_ips)
        return result
