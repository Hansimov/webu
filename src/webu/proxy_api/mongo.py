"""MongoDB 操作封装 — 代理池数据存储。"""

import pymongo

from datetime import datetime, timezone, timedelta
from tclogger import logger, logstr
from typing import Optional

# Asia/Shanghai = UTC+8
TZ_SHANGHAI = timezone(timedelta(hours=8))


def _now_shanghai() -> str:
    """返回 Asia/Shanghai 当前时间字符串。

    格式: YYYY-MM-DD HH:MM:SS
    """
    return datetime.now(TZ_SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")


from .constants import (
    MongoConfigsType,
    MONGO_CONFIGS,
    COLLECTION_IPS,
    COLLECTION_CHECKED_IPS,
    ABANDONED_FAIL_THRESHOLD,
    ABANDONED_STALE_HOURS,
)


class MongoProxyStore:
    """代理池 MongoDB 存储管理。

    管理两个 collection：
    - ips: 原生采集的 IP 数据
    - checked_ips: 代理可用性检测结果（默认使用 google_ips 保持向后兼容）
    """

    def __init__(
        self,
        configs: MongoConfigsType = None,
        check_collection: str = None,
        verbose: bool = True,
    ):
        self.configs = configs or MONGO_CONFIGS
        self.check_collection = check_collection or COLLECTION_CHECKED_IPS
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
        self._migrate_timestamps()
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
        # checked_ips collection: 唯一索引 + 查询索引
        self.db[self.check_collection].create_index(
            [("ip", 1), ("port", 1), ("protocol", 1)],
            unique=True,
            name="idx_ip_port_protocol",
        )
        self.db[self.check_collection].create_index(
            [("is_valid", 1), ("latency_ms", 1)],
            name="idx_valid_latency",
        )
        # 废弃索引
        self.db[self.check_collection].create_index(
            [("is_abandoned", 1)],
            name="idx_abandoned",
        )

    def _migrate_timestamps(self):
        """将旧时间戳格式迁移为 'YYYY-MM-DD HH:MM:SS' (Asia/Shanghai)。"""
        fields = ["checked_at", "collected_at", "abandoned_at"]
        for coll_name in [COLLECTION_IPS, self.check_collection]:
            coll = self.db[coll_name]
            for field in fields:
                # 情况 1: 含 +00:00 后缀（旧 UTC 格式）
                old_utc_docs = list(coll.find(
                    {field: {"$regex": r"\+00:00$"}},
                    {"_id": 1, field: 1},
                ).limit(50000))

                if old_utc_docs:
                    operations = []
                    for doc in old_utc_docs:
                        old_val = doc[field]
                        try:
                            dt = datetime.fromisoformat(old_val)
                            new_dt = dt.astimezone(TZ_SHANGHAI)
                            new_val = new_dt.strftime("%Y-%m-%d %H:%M:%S")
                            operations.append(
                                pymongo.UpdateOne(
                                    {"_id": doc["_id"]},
                                    {"$set": {field: new_val}},
                                )
                            )
                        except (ValueError, TypeError):
                            continue
                    if operations:
                        coll.bulk_write(operations, ordered=False)
                        if self.verbose:
                            logger.mesg(
                                f"  ♻ Migrated {len(operations)} UTC timestamps "
                                f"in {coll_name}.{field}"
                            )

                # 情况 2: 含 T 分隔符（旧 ISO 格式）
                old_t_docs = list(coll.find(
                    {field: {"$regex": r"^\d{4}-\d{2}-\d{2}T"}},
                    {"_id": 1, field: 1},
                ).limit(50000))

                if old_t_docs:
                    operations = []
                    for doc in old_t_docs:
                        old_val = doc[field]
                        new_val = old_val.replace("T", " ")
                        if len(new_val) > 19:
                            new_val = new_val[:19]
                        operations.append(
                            pymongo.UpdateOne(
                                {"_id": doc["_id"]},
                                {"$set": {field: new_val}},
                            )
                        )
                    if operations:
                        coll.bulk_write(operations, ordered=False)
                        if self.verbose:
                            logger.mesg(
                                f"  ♻ Migrated {len(operations)} T-format timestamps "
                                f"in {coll_name}.{field}"
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
        now = _now_shanghai()
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
        limit: int = 500,
        exclude_abandoned: bool = True,
    ) -> list[dict]:
        """获取尚未检测过的 IP（排除废弃代理）。"""
        pipeline = [
            {
                "$lookup": {
                    "from": self.check_collection,
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

        result = list(self.db[COLLECTION_IPS].aggregate(pipeline))

        if exclude_abandoned and result:
            abandoned_set = self.get_abandoned_ips_set()
            if abandoned_set:
                before = len(result)
                result = [
                    r for r in result
                    if (r["ip"], r["port"], r["protocol"]) not in abandoned_set
                ]
                skipped = before - len(result)
                if self.verbose and skipped > 0:
                    logger.mesg(f"  ♻ Skipped {logstr.mesg(skipped)} abandoned proxies")

        return result

    def get_stale_ips(
        self,
        max_age_hours: float = 1.0,
        limit: int = 500,
    ) -> list[dict]:
        """获取检测结果已过期的 IP（排除废弃代理）。"""
        filter_doc = {
            "$or": [{"is_abandoned": {"$ne": True}}, {"is_abandoned": {"$exists": False}}],
        }
        cursor = (
            self.db[self.check_collection]
            .find(
                filter_doc,
                {"_id": 0, "ip": 1, "port": 1, "protocol": 1, "proxy_url": 1},
            )
            .sort("checked_at", pymongo.ASCENDING)
            .limit(limit)
        )
        return list(cursor)

    def get_all_ips(self, limit: int = 0) -> list[dict]:
        """获取所有 IP。"""
        cursor = self.db[COLLECTION_IPS].find(
            {}, {"_id": 0, "ip": 1, "port": 1, "protocol": 1, "source": 1}
        )
        if limit > 0:
            cursor = cursor.limit(limit)
        return list(cursor)

    def get_ips_count(self) -> int:
        """获取 ips collection 中的 IP 数量。"""
        return self.db[COLLECTION_IPS].estimated_document_count()

    # ── checked_ips collection 操作 ───────────────────────────

    def upsert_check_result(self, result: dict):
        """更新单个 IP 的检测结果。"""
        collection = self.db[self.check_collection]
        now = _now_shanghai()

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
                    "check_level": result.get("check_level", 0),
                    "is_abandoned": False,
                    "abandoned_reason": "",
                },
                "$inc": {"success_count": 1},
                "$unset": {"abandoned_at": ""},
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
                    "check_level": result.get("check_level", 0),
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
        """获取可用代理，按延迟排序（排除废弃代理）。"""
        filter_dict = {
            "is_valid": True,
            "latency_ms": {"$gt": 0, "$lte": max_latency_ms},
            "$or": [{"is_abandoned": {"$ne": True}}, {"is_abandoned": {"$exists": False}}],
        }
        if exclude_ips:
            filter_dict["ip"] = {"$nin": exclude_ips}

        cursor = (
            self.db[self.check_collection]
            .find(filter_dict, {"_id": 0})
            .sort("latency_ms", pymongo.ASCENDING)
            .limit(limit)
        )
        return list(cursor)

    def get_valid_count(self) -> int:
        """获取可用代理数量。"""
        return self.db[self.check_collection].count_documents({"is_valid": True})

    def get_checked_count(self) -> int:
        """获取已检测的记录数量。"""
        return self.db[self.check_collection].estimated_document_count()

    # ── 废弃 (Abandoned) 机制 ───────────────────────────────

    def mark_abandoned(self, ip: str, port: int, protocol: str, reason: str = ""):
        """将代理标记为废弃。"""
        now = _now_shanghai()
        self.db[self.check_collection].update_one(
            {"ip": ip, "port": port, "protocol": protocol},
            {
                "$set": {
                    "is_abandoned": True,
                    "abandoned_at": now,
                    "abandoned_reason": reason,
                    "is_valid": False,
                }
            },
        )

    def scan_and_mark_abandoned(self) -> int:
        """扫描并标记废弃代理。"""
        cutoff = (
            datetime.now(TZ_SHANGHAI) - timedelta(hours=ABANDONED_STALE_HOURS)
        ).strftime("%Y-%m-%d %H:%M:%S")

        filter_doc = {
            "$or": [{"is_abandoned": {"$ne": True}}, {"is_abandoned": {"$exists": False}}],
            "fail_count": {"$gte": ABANDONED_FAIL_THRESHOLD},
            "checked_at": {"$lte": cutoff},
            "is_valid": False,
        }

        now = _now_shanghai()
        result = self.db[self.check_collection].update_many(
            filter_doc,
            {
                "$set": {
                    "is_abandoned": True,
                    "abandoned_at": now,
                    "abandoned_reason": "auto: fail_count >= threshold & stale",
                }
            },
        )
        count = result.modified_count
        if self.verbose and count > 0:
            logger.mesg(f"  ♬ Marked {logstr.mesg(count)} proxies as abandoned")
        return count

    def get_abandoned_count(self) -> int:
        """获取废弃代理数量。"""
        return self.db[self.check_collection].count_documents({"is_abandoned": True})

    def get_abandoned_ips_set(self) -> set:
        """获取所有废弃代理的 (ip, port, protocol) 集合。"""
        cursor = self.db[self.check_collection].find(
            {"is_abandoned": True},
            {"_id": 0, "ip": 1, "port": 1, "protocol": 1},
        )
        return {(d["ip"], d["port"], d["protocol"]) for d in cursor}

    def revive_proxy(self, ip: str, port: int, protocol: str):
        """复活废弃代理。"""
        self.db[self.check_collection].update_one(
            {"ip": ip, "port": port, "protocol": protocol},
            {
                "$set": {
                    "is_abandoned": False,
                    "abandoned_reason": "",
                },
                "$unset": {"abandoned_at": ""},
            },
        )

    # ── 统计 ─────────────────────────────────────────────

    def get_stats(self) -> dict:
        """获取代理池统计信息。"""
        total_ips = self.get_ips_count()
        total_checked = self.get_checked_count()
        total_valid = self.get_valid_count()
        total_abandoned = self.get_abandoned_count()
        level1_passed = self.db[self.check_collection].count_documents({
            "is_valid": True,
            "$or": [{"is_abandoned": {"$ne": True}}, {"is_abandoned": {"$exists": False}}],
        })
        return {
            "total_ips": total_ips,
            "total_checked": total_checked,
            "level1_passed": level1_passed,
            "total_valid": total_valid,
            "total_abandoned": total_abandoned,
            "valid_ratio": f"{total_valid / total_checked * 100:.1f}%"
            if total_checked > 0
            else "N/A",
        }
