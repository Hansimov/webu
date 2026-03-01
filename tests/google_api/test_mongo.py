"""MongoDB 代理存储测试。

运行: pytest tests/google_api/test_mongo.py -xvs
"""

import pytest
from unittest.mock import MagicMock, patch

from webu.google_api.mongo import MongoProxyStore
from webu.google_api.constants import MONGO_CONFIGS


# ═══════════════════════════════════════════════════════════════
# 集成测试（需要 MongoDB 运行）
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestMongoProxyStoreIntegration:
    """MongoDB 代理存储集成测试。

    需要 MongoDB 在 localhost:27017 运行。
    使用测试数据库 webu_test 避免影响生产数据。

    运行: pytest tests/google_api/test_mongo.py -xvs -m integration
    """

    TEST_CONFIGS = {
        "host": "localhost",
        "port": 27017,
        "dbname": "webu_test",
    }

    def setup_method(self):
        self.store = MongoProxyStore(configs=self.TEST_CONFIGS, verbose=True)
        # 清理测试数据
        self.store.db["ips"].delete_many({})
        self.store.db["google_ips"].delete_many({})

    def teardown_method(self):
        # 清理测试数据
        self.store.db["ips"].delete_many({})
        self.store.db["google_ips"].delete_many({})

    def test_upsert_ips(self):
        """测试 IP 写入和去重。"""
        ip_list = [
            {"ip": "1.2.3.4", "port": 8080, "protocol": "http", "source": "test"},
            {"ip": "5.6.7.8", "port": 3128, "protocol": "https", "source": "test"},
            {"ip": "1.2.3.4", "port": 8080, "protocol": "http", "source": "test2"},  # 重复
        ]
        result = self.store.upsert_ips(ip_list)
        assert result["inserted"] == 2  # 去重后只有 2 个
        assert result["total"] >= 2

    def test_upsert_check_result(self):
        """测试检测结果写入。"""
        # 先写入一个 IP
        self.store.upsert_ips(
            [{"ip": "1.2.3.4", "port": 8080, "protocol": "http", "source": "test"}]
        )

        # 写入检测成功结果
        self.store.upsert_check_result(
            {
                "ip": "1.2.3.4",
                "port": 8080,
                "protocol": "http",
                "proxy_url": "http://1.2.3.4:8080",
                "is_valid": True,
                "latency_ms": 500,
            }
        )

        valid = self.store.get_valid_proxies()
        assert len(valid) == 1
        assert valid[0]["ip"] == "1.2.3.4"
        assert valid[0]["latency_ms"] == 500

    def test_upsert_check_result_failure(self):
        """测试检测失败结果写入。"""
        self.store.upsert_check_result(
            {
                "ip": "9.9.9.9",
                "port": 1234,
                "protocol": "http",
                "proxy_url": "http://9.9.9.9:1234",
                "is_valid": False,
                "last_error": "Connection timeout",
            }
        )

        valid = self.store.get_valid_proxies()
        assert len(valid) == 0

    def test_get_valid_proxies_sorted(self):
        """测试可用代理按延迟排序。"""
        # 写入多个检测结果，不同延迟
        for i, (ip, latency) in enumerate(
            [("10.0.0.1", 200), ("10.0.0.2", 100), ("10.0.0.3", 500)]
        ):
            self.store.upsert_check_result(
                {
                    "ip": ip,
                    "port": 8080,
                    "protocol": "http",
                    "proxy_url": f"http://{ip}:8080",
                    "is_valid": True,
                    "latency_ms": latency,
                }
            )

        valid = self.store.get_valid_proxies()
        assert len(valid) == 3
        # 按延迟升序
        assert valid[0]["ip"] == "10.0.0.2"  # 100ms
        assert valid[1]["ip"] == "10.0.0.1"  # 200ms
        assert valid[2]["ip"] == "10.0.0.3"  # 500ms

    def test_get_valid_proxies_exclude(self):
        """测试排除特定 IP。"""
        for ip in ["10.0.0.1", "10.0.0.2", "10.0.0.3"]:
            self.store.upsert_check_result(
                {
                    "ip": ip,
                    "port": 8080,
                    "protocol": "http",
                    "proxy_url": f"http://{ip}:8080",
                    "is_valid": True,
                    "latency_ms": 200,
                }
            )

        valid = self.store.get_valid_proxies(exclude_ips=["10.0.0.1", "10.0.0.2"])
        assert len(valid) == 1
        assert valid[0]["ip"] == "10.0.0.3"

    def test_get_stats(self):
        """测试统计信息。"""
        self.store.upsert_ips(
            [
                {"ip": "1.1.1.1", "port": 80, "protocol": "http", "source": "test"},
                {"ip": "2.2.2.2", "port": 80, "protocol": "http", "source": "test"},
            ]
        )
        self.store.upsert_check_result(
            {
                "ip": "1.1.1.1",
                "port": 80,
                "protocol": "http",
                "proxy_url": "http://1.1.1.1:80",
                "is_valid": True,
                "latency_ms": 300,
            }
        )
        self.store.upsert_check_result(
            {
                "ip": "2.2.2.2",
                "port": 80,
                "protocol": "http",
                "proxy_url": "http://2.2.2.2:80",
                "is_valid": False,
                "last_error": "timeout",
            }
        )

        stats = self.store.get_stats()
        assert stats["total_ips"] >= 2
        assert stats["total_checked"] >= 2
        assert stats["total_valid"] >= 1

    def test_get_unchecked_ips(self):
        """测试获取未检测的 IP。"""
        # 写入 3 个 IP
        self.store.upsert_ips(
            [
                {"ip": "1.1.1.1", "port": 80, "protocol": "http", "source": "test"},
                {"ip": "2.2.2.2", "port": 80, "protocol": "http", "source": "test"},
                {"ip": "3.3.3.3", "port": 80, "protocol": "http", "source": "test"},
            ]
        )
        # 检测 1 个
        self.store.upsert_check_result(
            {
                "ip": "1.1.1.1",
                "port": 80,
                "protocol": "http",
                "proxy_url": "http://1.1.1.1:80",
                "is_valid": True,
                "latency_ms": 100,
            }
        )

        unchecked = self.store.get_unchecked_ips()
        unchecked_ips = {item["ip"] for item in unchecked}
        assert "1.1.1.1" not in unchecked_ips
        assert "2.2.2.2" in unchecked_ips
        assert "3.3.3.3" in unchecked_ips
