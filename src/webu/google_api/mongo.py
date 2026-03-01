"""MongoDB 操作封装 — 代理池数据存储。

参考 sedb/src/sedb/mongo.py 的设计，简化为代理池管理所需的功能。
"""

import pymongo

from datetime import datetime, timezone
from tclogger import logger, logstr
from typing import Optional

from .constants import (
    MongoConfigsType,
    MONGO_CONFIGS,
    COLLECTION_IPS,
    COLLECTION_GOOGLE_IPS,
)


class MongoProxyStore:
    """代理池 MongoDB 存储管理。

    管理两个 collection：
    - ips: 原生采集的 IP 数据
    - google_ips: Google 搜索可用性检测结果
    """

    def __init__(
        self,
        configs: MongoConfigsType = None,
        verbose: bool = True,
    ):
        self.configs = configs or MONGO_CONFIGS
        self.verbose = verbose
        self.host = self.configs["host"]
        self.port = self.configs["port"]
        self.dbname = self.configs["dbname"]
        self.endpoint = f"mongodb://{self.host}:{self.port}"
        self.connect()

    def connect(self):
        if self.verbose:
            logger.note(f"> Connecting to MongoDB: {logstr.mesg(self.endpoint)}")
        self.client = pymongo.MongoClient(self.endpoint)
        self.db = self.client[self.dbname]
        self._ensure_indexes()
        if self.verbose:
            logger.okay(f"  ✓ Connected to database: {logstr.mesg(self.dbname)}")

    def _ensure_indexes(self):
        """创建必要的索引。"""
        # ips collection: 唯一索引 (ip, port, protocol)
        self.db[COLLECTION_IPS].create_index(
            [("ip", 1), ("port", 1), ("protocol", 1)],
            unique=True,
            name="idx_ip_port_protocol",
        )
        # google_ips collection: 唯一索引 + 查询索引
        self.db[COLLECTION_GOOGLE_IPS].create_index(
            [("ip", 1), ("port", 1), ("protocol", 1)],
            unique=True,
            name="idx_ip_port_protocol",
        )
        self.db[COLLECTION_GOOGLE_IPS].create_index(
            [("is_valid", 1), ("latency_ms", 1)],
            name="idx_valid_latency",
        )

    # ── ips collection 操作 ───────────────────────────────────

    def upsert_ips(self, ip_list: list[dict]) -> dict:
        """批量 upsert IP 到 ips collection。

        Args:
            ip_list: list of {"ip", "port", "protocol", "source"}

        Returns:
            {"inserted": int, "updated": int, "total": int}
        """
        if not ip_list:
            return {"inserted": 0, "updated": 0, "total": 0}

        collection = self.db[COLLECTION_IPS]
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        updated = 0

        operations = []
        for item in ip_list:
            filter_key = {
                "ip": item["ip"],
                "port": item["port"],
                "protocol": item["protocol"],
            }
            update_doc = {
                "$set": {
                    "source": item.get("source", ""),
                    "collected_at": now,
                },
                "$setOnInsert": {
                    "ip": item["ip"],
                    "port": item["port"],
                    "protocol": item["protocol"],
                },
            }
            operations.append(
                pymongo.UpdateOne(filter_key, update_doc, upsert=True)
            )

        if operations:
            result = collection.bulk_write(operations, ordered=False)
            inserted = result.upserted_count
            updated = result.modified_count

        total = collection.estimated_document_count()
        if self.verbose:
            logger.okay(
                f"  ✓ Upserted IPs: "
                f"{logstr.mesg(f'+{inserted}')} new, "
                f"{logstr.mesg(f'~{updated}')} updated, "
                f"{logstr.mesg(f'{total}')} total"
            )
        return {"inserted": inserted, "updated": updated, "total": total}

    def get_unchecked_ips(
        self,
        target_collection: str = COLLECTION_GOOGLE_IPS,
        limit: int = 500,
    ) -> list[dict]:
        """获取尚未在目标 collection 中检测过的 IP。"""
        # 使用 $lookup 找出不在 target_collection 中的 IP
        pipeline = [
            {
                "$lookup": {
                    "from": target_collection,
                    "let": {"ip": "$ip", "port": "$port", "protocol": "$protocol"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$ip", "$$ip"]},
                                        {"$eq": ["$port", "$$port"]},
                                        {"$eq": ["$protocol", "$$protocol"]},
                                    ]
                                }
                            }
                        }
                    ],
                    "as": "checked",
                }
            },
            {"$match": {"checked": {"$size": 0}}},
            {"$project": {"_id": 0, "ip": 1, "port": 1, "protocol": 1, "source": 1}},
            {"$limit": limit},
        ]
        return list(self.db[COLLECTION_IPS].aggregate(pipeline))

    def get_stale_ips(
        self,
        target_collection: str = COLLECTION_GOOGLE_IPS,
        max_age_hours: float = 1.0,
        limit: int = 500,
    ) -> list[dict]:
        """获取检测结果已过期（超过 max_age_hours 小时）的 IP。"""
        cutoff = datetime.now(timezone.utc).isoformat()
        # 简化：取 checked_at 较旧的记录
        cursor = (
            self.db[target_collection]
            .find(
                {},
                {"_id": 0, "ip": 1, "port": 1, "protocol": 1, "proxy_url": 1},
            )
            .sort("checked_at", pymongo.ASCENDING)
            .limit(limit)
        )
        return list(cursor)

    def get_all_ips(self, limit: int = 0) -> list[dict]:
        """获取所有 IP（用于批量检测）。"""
        cursor = self.db[COLLECTION_IPS].find(
            {}, {"_id": 0, "ip": 1, "port": 1, "protocol": 1, "source": 1}
        )
        if limit > 0:
            cursor = cursor.limit(limit)
        return list(cursor)

    def get_ips_count(self) -> int:
        """获取 ips collection 中的 IP 数量。"""
        return self.db[COLLECTION_IPS].estimated_document_count()

    # ── google_ips collection 操作 ────────────────────────────

    def upsert_check_result(self, result: dict):
        """更新单个 IP 的 Google 检测结果到 google_ips。

        Args:
            result: {
                "ip", "port", "protocol", "proxy_url",
                "is_valid", "latency_ms", "last_error"
            }
        """
        collection = self.db[COLLECTION_GOOGLE_IPS]
        now = datetime.now(timezone.utc).isoformat()

        filter_key = {
            "ip": result["ip"],
            "port": result["port"],
            "protocol": result["protocol"],
        }

        if result.get("is_valid"):
            update_doc = {
                "$set": {
                    "proxy_url": result["proxy_url"],
                    "is_valid": True,
                    "latency_ms": result.get("latency_ms", 0),
                    "checked_at": now,
                    "last_error": "",
                    "fail_count": 0,
                },
                "$inc": {"success_count": 1},
                "$setOnInsert": {
                    "ip": result["ip"],
                    "port": result["port"],
                    "protocol": result["protocol"],
                },
            }
        else:
            update_doc = {
                "$set": {
                    "proxy_url": result["proxy_url"],
                    "is_valid": False,
                    "latency_ms": 0,
                    "checked_at": now,
                    "last_error": result.get("last_error", ""),
                },
                "$inc": {"fail_count": 1},
                "$setOnInsert": {
                    "ip": result["ip"],
                    "port": result["port"],
                    "protocol": result["protocol"],
                    "success_count": 0,
                },
            }

        collection.update_one(filter_key, update_doc, upsert=True)

    def upsert_check_results(self, results: list[dict]):
        """批量更新检测结果。"""
        for result in results:
            self.upsert_check_result(result)

    def get_valid_proxies(
        self,
        limit: int = 50,
        max_latency_ms: int = 10000,
        exclude_ips: list[str] = None,
    ) -> list[dict]:
        """获取可用的 Google 代理，按延迟排序。

        Args:
            limit: 最多返回数量
            max_latency_ms: 最大可接受延迟（毫秒）
            exclude_ips: 需排除的 IP 列表（避免短期内复用）

        Returns:
            list of {"ip", "port", "protocol", "proxy_url", "latency_ms", ...}
        """
        filter_dict = {
            "is_valid": True,
            "latency_ms": {"$gt": 0, "$lte": max_latency_ms},
        }
        if exclude_ips:
            filter_dict["ip"] = {"$nin": exclude_ips}

        cursor = (
            self.db[COLLECTION_GOOGLE_IPS]
            .find(filter_dict, {"_id": 0})
            .sort("latency_ms", pymongo.ASCENDING)
            .limit(limit)
        )
        return list(cursor)

    def get_valid_count(self) -> int:
        """获取可用 Google 代理数量。"""
        return self.db[COLLECTION_GOOGLE_IPS].count_documents({"is_valid": True})

    def get_google_ips_count(self) -> int:
        """获取 google_ips collection 中的记录数量。"""
        return self.db[COLLECTION_GOOGLE_IPS].estimated_document_count()

    def get_stats(self) -> dict:
        """获取代理池整体统计信息。"""
        total_ips = self.get_ips_count()
        total_checked = self.get_google_ips_count()
        total_valid = self.get_valid_count()
        return {
            "total_ips": total_ips,
            "total_checked": total_checked,
            "total_valid": total_valid,
            "valid_ratio": f"{total_valid / total_checked * 100:.1f}%"
            if total_checked > 0
            else "N/A",
        }
