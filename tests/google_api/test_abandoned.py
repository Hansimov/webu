"""废弃代理机制和搜索解析的集成测试。

测试覆盖:
1. 废弃标记/扫描/复活
2. 废弃代理排除（unchecked/stale/valid 查询）
3. 自动复活（检测通过后）
4. 代理池编排（ProxyPool 的废弃相关方法）
5. 时间戳格式验证

运行: pytest tests/google_api/test_abandoned.py -xvs
"""

import re
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from webu.google_api.mongo import MongoProxyStore, _now_shanghai, TZ_SHANGHAI
from webu.google_api.proxy_pool import ProxyPool
from webu.google_api.constants import (
    ABANDONED_FAIL_THRESHOLD,
    ABANDONED_STALE_HOURS,
    ABANDONED_COOLDOWN_HOURS,
)


# ═══════════════════════════════════════════════════════════════
# 测试工具
# ═══════════════════════════════════════════════════════════════

TEST_CONFIGS = {
    "host": "localhost",
    "port": 27017,
    "dbname": "webu_test",
}


def _make_checked_proxy(
    ip: str,
    port: int = 8080,
    protocol: str = "http",
    is_valid: bool = True,
    latency_ms: int = 200,
    fail_count: int = 0,
    check_level: int = 1,
    checked_at: str = None,
) -> dict:
    """生成检测结果字典。"""
    return {
        "ip": ip,
        "port": port,
        "protocol": protocol,
        "proxy_url": f"{protocol}://{ip}:{port}",
        "is_valid": is_valid,
        "latency_ms": latency_ms if is_valid else 0,
        "fail_count": fail_count,
        "check_level": check_level,
        "last_error": "" if is_valid else "test failure",
        "checked_at": checked_at or _now_shanghai(),
    }


def _insert_proxy_with_fail_count(
    store: MongoProxyStore,
    ip: str,
    port: int = 8080,
    protocol: str = "http",
    fail_count: int = 0,
    checked_at: str = None,
):
    """直接在 DB 中创建带有指定 fail_count 的代理记录。

    upsert_check_result 使用 $inc 管理 fail_count，无法直接设定。
    测试需要直接插入。
    """
    now = checked_at or _now_shanghai()
    store.db["google_ips"].update_one(
        {"ip": ip, "port": port, "protocol": protocol},
        {
            "$set": {
                "ip": ip,
                "port": port,
                "protocol": protocol,
                "proxy_url": f"{protocol}://{ip}:{port}",
                "is_valid": False,
                "latency_ms": 0,
                "checked_at": now,
                "last_error": "test failure",
                "fail_count": fail_count,
                "check_level": 1,
            }
        },
        upsert=True,
    )


# ═══════════════════════════════════════════════════════════════
# 废弃机制测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestAbandonedMechanism:
    """废弃代理机制集成测试。

    需要 MongoDB 在 localhost:27017 运行。
    """

    def setup_method(self):
        self.store = MongoProxyStore(configs=TEST_CONFIGS, verbose=False)
        self.store.db["ips"].delete_many({})
        self.store.db["google_ips"].delete_many({})

    def teardown_method(self):
        self.store.db["ips"].delete_many({})
        self.store.db["google_ips"].delete_many({})

    def test_mark_abandoned(self):
        """测试手动标记代理为废弃。"""
        # 先创建一个代理检测记录
        self.store.upsert_check_result(_make_checked_proxy("1.1.1.1", is_valid=False))

        # 标记为废弃
        self.store.mark_abandoned("1.1.1.1", 8080, "http", reason="test abandon")

        # 验证状态
        doc = self.store.db["google_ips"].find_one({"ip": "1.1.1.1"})
        assert doc["is_abandoned"] is True
        assert doc["abandoned_reason"] == "test abandon"
        assert doc["is_valid"] is False
        assert "abandoned_at" in doc

    def test_mark_abandoned_timestamp_format(self):
        """测试废弃标记的时间戳格式: YYYY-MM-DD HH:MM:SS。"""
        self.store.upsert_check_result(_make_checked_proxy("1.1.1.1", is_valid=False))
        self.store.mark_abandoned("1.1.1.1", 8080, "http")

        doc = self.store.db["google_ips"].find_one({"ip": "1.1.1.1"})
        # 格式: 2025-01-01 12:30:45
        ts = doc["abandoned_at"]
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", ts), \
            f"时间戳格式不正确: {ts}"

    def test_get_abandoned_count(self):
        """测试获取废弃代理数量。"""
        for i in range(5):
            self.store.upsert_check_result(
                _make_checked_proxy(f"10.0.0.{i}", is_valid=False)
            )
            if i < 3:
                self.store.mark_abandoned(f"10.0.0.{i}", 8080, "http")

        assert self.store.get_abandoned_count() == 3

    def test_get_abandoned_ips_set(self):
        """测试获取废弃代理集合。"""
        for i in range(3):
            self.store.upsert_check_result(
                _make_checked_proxy(f"10.0.0.{i}", is_valid=False)
            )
            self.store.mark_abandoned(f"10.0.0.{i}", 8080, "http")

        abandoned_set = self.store.get_abandoned_ips_set()
        assert ("10.0.0.0", 8080, "http") in abandoned_set
        assert ("10.0.0.1", 8080, "http") in abandoned_set
        assert ("10.0.0.2", 8080, "http") in abandoned_set

    def test_revive_proxy(self):
        """测试复活废弃代理。"""
        self.store.upsert_check_result(_make_checked_proxy("1.1.1.1", is_valid=False))
        self.store.mark_abandoned("1.1.1.1", 8080, "http")

        # 验证已废弃
        assert self.store.get_abandoned_count() == 1

        # 复活
        self.store.revive_proxy("1.1.1.1", 8080, "http")

        # 验证复活
        doc = self.store.db["google_ips"].find_one({"ip": "1.1.1.1"})
        assert doc["is_abandoned"] is False
        assert self.store.get_abandoned_count() == 0

    def test_scan_and_mark_abandoned_basic(self):
        """测试自动扫描标记废弃 — 基本场景。"""
        # 创建一个符合废弃条件的代理：
        # - fail_count >= ABANDONED_FAIL_THRESHOLD
        # - checked_at 超过 ABANDONED_STALE_HOURS
        # - is_valid = False
        old_time = (
            datetime.now(TZ_SHANGHAI) - timedelta(hours=ABANDONED_STALE_HOURS + 1)
        ).strftime("%Y-%m-%d %H:%M:%S")

        # 直接设置 fail_count（upsert_check_result 用 $inc 管理，无法直接设定）
        _insert_proxy_with_fail_count(
            self.store, "10.0.0.1",
            fail_count=ABANDONED_FAIL_THRESHOLD,
            checked_at=old_time,
        )

        # 创建一个不符合条件的代理（fail_count 不够）
        _insert_proxy_with_fail_count(
            self.store, "10.0.0.2",
            fail_count=ABANDONED_FAIL_THRESHOLD - 1,
            checked_at=old_time,
        )

        count = self.store.scan_and_mark_abandoned()
        assert count == 1

        # 验证只有第一个被标记
        doc1 = self.store.db["google_ips"].find_one({"ip": "10.0.0.1"})
        doc2 = self.store.db["google_ips"].find_one({"ip": "10.0.0.2"})
        assert doc1["is_abandoned"] is True
        assert doc2.get("is_abandoned") is not True

    def test_scan_skips_recently_checked(self):
        """测试扫描跳过最近检测过的代理。"""
        # 最近检测过的代理，即使 fail_count 足够也不应被标记
        recent_time = _now_shanghai()
        _insert_proxy_with_fail_count(
            self.store, "10.0.0.1",
            fail_count=ABANDONED_FAIL_THRESHOLD + 5,
            checked_at=recent_time,
        )

        count = self.store.scan_and_mark_abandoned()
        assert count == 0

    def test_scan_skips_valid_proxies(self):
        """测试扫描跳过有效代理。"""
        old_time = (
            datetime.now(TZ_SHANGHAI) - timedelta(hours=ABANDONED_STALE_HOURS + 1)
        ).strftime("%Y-%m-%d %H:%M:%S")

        # 有效代理不应被废弃 — 直接设置 is_valid=True + 高 fail_count
        self.store.db["google_ips"].update_one(
            {"ip": "10.0.0.1", "port": 8080, "protocol": "http"},
            {
                "$set": {
                    "ip": "10.0.0.1",
                    "port": 8080,
                    "protocol": "http",
                    "proxy_url": "http://10.0.0.1:8080",
                    "is_valid": True,
                    "fail_count": ABANDONED_FAIL_THRESHOLD + 5,
                    "checked_at": old_time,
                }
            },
            upsert=True,
        )

        count = self.store.scan_and_mark_abandoned()
        assert count == 0

    def test_abandoned_excluded_from_valid_proxies(self):
        """测试废弃代理不出现在有效代理列表中。"""
        # 创建一个有效代理然后标记为废弃
        self.store.upsert_check_result(
            _make_checked_proxy("10.0.0.1", is_valid=True, latency_ms=100)
        )
        self.store.upsert_check_result(
            _make_checked_proxy("10.0.0.2", is_valid=True, latency_ms=200)
        )

        valid = self.store.get_valid_proxies()
        assert len(valid) == 2

        # 标记第一个为废弃
        self.store.mark_abandoned("10.0.0.1", 8080, "http")

        valid = self.store.get_valid_proxies()
        assert len(valid) == 1
        assert valid[0]["ip"] == "10.0.0.2"

    def test_abandoned_excluded_from_unchecked(self):
        """测试废弃代理不出现在未检测列表中。"""
        # 插入到 ips 集合
        self.store.upsert_ips([
            {"ip": "10.0.0.1", "port": 8080, "protocol": "http", "source": "test"},
            {"ip": "10.0.0.2", "port": 8080, "protocol": "http", "source": "test"},
        ])
        # 将 10.0.0.1 检测并标记废弃
        self.store.upsert_check_result(
            _make_checked_proxy("10.0.0.1", is_valid=False, fail_count=10)
        )
        self.store.mark_abandoned("10.0.0.1", 8080, "http")

        unchecked = self.store.get_unchecked_ips()
        unchecked_ips = {item["ip"] for item in unchecked}
        # 10.0.0.1 已废弃，应被排除
        assert "10.0.0.1" not in unchecked_ips
        # 10.0.0.2 未检测且未废弃
        assert "10.0.0.2" in unchecked_ips

    def test_auto_revive_on_success(self):
        """测试检测通过后自动复活废弃代理。"""
        # 标记为废弃
        self.store.upsert_check_result(
            _make_checked_proxy("10.0.0.1", is_valid=False)
        )
        self.store.mark_abandoned("10.0.0.1", 8080, "http")
        assert self.store.get_abandoned_count() == 1

        # 现在检测通过（upsert_check_result 应自动复活）
        self.store.upsert_check_result(
            _make_checked_proxy("10.0.0.1", is_valid=True, latency_ms=300)
        )

        # 验证已复活
        doc = self.store.db["google_ips"].find_one({"ip": "10.0.0.1"})
        assert doc.get("is_abandoned") is False
        assert doc["is_valid"] is True
        assert self.store.get_abandoned_count() == 0

    def test_stats_include_abandoned(self):
        """测试统计信息包含废弃数量。"""
        self.store.upsert_ips([
            {"ip": "1.1.1.1", "port": 8080, "protocol": "http", "source": "test"},
        ])
        self.store.upsert_check_result(
            _make_checked_proxy("1.1.1.1", is_valid=False)
        )
        self.store.mark_abandoned("1.1.1.1", 8080, "http")

        stats = self.store.get_stats()
        assert "total_abandoned" in stats
        assert stats["total_abandoned"] >= 1


# ═══════════════════════════════════════════════════════════════
# 时间戳格式测试
# ═══════════════════════════════════════════════════════════════


class TestTimestamp:
    """时间戳格式验证测试。"""

    def test_now_shanghai_format(self):
        """测试 _now_shanghai() 返回正确格式。"""
        ts = _now_shanghai()
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", ts), \
            f"格式不正确: {ts}"

    def test_now_shanghai_timezone(self):
        """测试 _now_shanghai() 使用 Asia/Shanghai 时区。"""
        ts = _now_shanghai()
        # 解析时间字符串
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        # 获取 UTC 当前时间 + 8 小时
        utc_now = datetime.now(timezone.utc)
        shanghai_now = utc_now + timedelta(hours=8)
        # 允许 2 秒误差
        diff = abs((dt - shanghai_now.replace(tzinfo=None)).total_seconds())
        assert diff < 2, f"时间差异过大: {diff}s"

    def test_no_timezone_suffix(self):
        """测试时间字符串不包含时区后缀。"""
        ts = _now_shanghai()
        assert "+" not in ts
        assert "Z" not in ts
        assert "T" not in ts

    def test_space_separator(self):
        """测试日期和时间之间用空格分隔。"""
        ts = _now_shanghai()
        parts = ts.split(" ")
        assert len(parts) == 2
        assert "-" in parts[0]  # 日期部分
        assert ":" in parts[1]  # 时间部分


# ═══════════════════════════════════════════════════════════════
# ProxyPool 废弃方法测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestProxyPoolAbandoned:
    """ProxyPool 废弃相关功能测试。"""

    def setup_method(self):
        self.pool = ProxyPool(configs=TEST_CONFIGS, verbose=False)
        self.pool.store.db["ips"].delete_many({})
        self.pool.store.db["google_ips"].delete_many({})

    def teardown_method(self):
        self.pool.store.db["ips"].delete_many({})
        self.pool.store.db["google_ips"].delete_many({})

    def test_scan_abandoned(self):
        """测试 ProxyPool.scan_abandoned()。"""
        old_time = (
            datetime.now(TZ_SHANGHAI) - timedelta(hours=ABANDONED_STALE_HOURS + 1)
        ).strftime("%Y-%m-%d %H:%M:%S")

        _insert_proxy_with_fail_count(
            self.pool.store, "10.0.0.1",
            fail_count=ABANDONED_FAIL_THRESHOLD,
            checked_at=old_time,
        )

        count = self.pool.scan_abandoned()
        assert count == 1

    def test_get_abandoned_stats(self):
        """测试 ProxyPool.get_abandoned_stats()。"""
        self.pool.store.upsert_check_result(
            _make_checked_proxy("10.0.0.1", is_valid=False)
        )
        self.pool.store.mark_abandoned("10.0.0.1", 8080, "http")

        stats = self.pool.get_abandoned_stats()
        assert stats["total_abandoned"] == 1

    def test_get_proxy_excludes_abandoned(self):
        """测试 ProxyPool.get_proxy() 不返回废弃代理。"""
        # 两个有效代理
        self.pool.store.upsert_check_result(
            _make_checked_proxy("10.0.0.1", is_valid=True, latency_ms=100)
        )
        self.pool.store.upsert_check_result(
            _make_checked_proxy("10.0.0.2", is_valid=True, latency_ms=200)
        )

        # 废弃第一个
        self.pool.store.mark_abandoned("10.0.0.1", 8080, "http")

        # 多次获取代理，确认不会返回废弃的
        for _ in range(10):
            proxy = self.pool.get_proxy()
            if proxy:
                assert proxy["ip"] != "10.0.0.1"


# ═══════════════════════════════════════════════════════════════
# 常量验证测试
# ═══════════════════════════════════════════════════════════════


class TestAbandonedConstants:
    """废弃机制常量验证。"""

    def test_threshold_positive(self):
        assert ABANDONED_FAIL_THRESHOLD > 0

    def test_stale_hours_positive(self):
        assert ABANDONED_STALE_HOURS > 0

    def test_cooldown_hours_positive(self):
        assert ABANDONED_COOLDOWN_HOURS > 0

    def test_cooldown_greater_than_stale(self):
        """冷却时间应 >= 过期时间。"""
        assert ABANDONED_COOLDOWN_HOURS >= ABANDONED_STALE_HOURS
