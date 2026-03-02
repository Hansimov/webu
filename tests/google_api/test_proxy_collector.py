"""代理采集 + 存储测试。

运行: pytest tests/google_api/test_proxy_collector.py -xvs
"""

import pytest
from unittest.mock import patch, MagicMock

from webu.google_api.constants import PROXY_SOURCES
from webu.proxy_api.mongo import MongoProxyStore
from webu.proxy_api.collector import ProxyCollector


# ═══════════════════════════════════════════════════════════════
# ProxyCollector 单元测试（不需要网络和 MongoDB）
# ═══════════════════════════════════════════════════════════════


class TestProxyCollectorParsing:
    """测试代理列表解析逻辑。"""

    def setup_method(self):
        self.store = MagicMock(spec=MongoProxyStore)
        self.collector = ProxyCollector(store=self.store, verbose=False)

    def test_parse_ip_port(self):
        """测试 ip:port 格式。"""
        result = self.collector._parse_proxy_line("1.2.3.4:8080", "http")
        assert result == {"protocol": "http", "ip": "1.2.3.4", "port": 8080}

    def test_parse_with_protocol_http(self):
        """测试 http://ip:port 格式。"""
        result = self.collector._parse_proxy_line("http://1.2.3.4:3128", "https")
        assert result == {"protocol": "http", "ip": "1.2.3.4", "port": 3128}

    def test_parse_with_protocol_socks5(self):
        """测试 socks5://ip:port 格式。"""
        result = self.collector._parse_proxy_line("socks5://10.0.0.1:1080", "http")
        assert result == {"protocol": "socks5", "ip": "10.0.0.1", "port": 1080}

    def test_parse_empty_line(self):
        """测试空行。"""
        assert self.collector._parse_proxy_line("", "http") is None
        assert self.collector._parse_proxy_line("   ", "http") is None

    def test_parse_invalid_line(self):
        """测试无效格式。"""
        assert self.collector._parse_proxy_line("not a proxy", "http") is None
        assert self.collector._parse_proxy_line("abc:xyz", "http") is None

    def test_fetch_source_mock(self):
        """测试从 URL 拉取（mock HTTP 请求）。"""
        mock_response = MagicMock()
        mock_response.text = "1.2.3.4:8080\n5.6.7.8:3128\n\n"
        mock_response.raise_for_status = MagicMock()

        with patch("webu.proxy_api.collector.requests.get", return_value=mock_response):
            source = {
                "url": "http://test.example.com/proxies.txt",
                "protocol": "http",
                "source": "test",
            }
            result = self.collector.fetch_source(source)

        assert len(result) == 2
        assert result[0]["ip"] == "1.2.3.4"
        assert result[0]["port"] == 8080
        assert result[0]["source"] == "test"
        assert result[1]["ip"] == "5.6.7.8"

    def test_collect_all_mock(self):
        """测试从所有源采集（mock）。"""
        mock_response = MagicMock()
        mock_response.text = "1.2.3.4:8080\n"
        mock_response.raise_for_status = MagicMock()

        self.store.upsert_ips.return_value = {
            "inserted": 6,
            "updated": 0,
            "total": 6,
        }

        with patch("webu.proxy_api.collector.requests.get", return_value=mock_response):
            result = self.collector.collect_all()

        assert result["total_fetched"] == len(PROXY_SOURCES)  # 每个源 1 个 IP
        assert self.store.upsert_ips.called


class TestProxySources:
    """验证代理源 URL 配置。"""

    def test_sources_not_empty(self):
        assert len(PROXY_SOURCES) > 0

    def test_sources_have_required_fields(self):
        for source in PROXY_SOURCES:
            assert "url" in source
            assert "protocol" in source
            assert "source" in source
            assert source["url"].startswith("http")
            assert source["protocol"] in ("http", "https", "socks4", "socks5")


# ═══════════════════════════════════════════════════════════════
# 集成测试（需要网络，可选 MongoDB）
# ═══════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestProxyCollectorIntegration:
    """集成测试：实际从 URL 拉取代理列表。

    运行: pytest tests/google_api/test_proxy_collector.py -xvs -m integration
    """

    def test_fetch_single_source(self):
        """测试从单个源实际拉取。"""
        store = MagicMock(spec=MongoProxyStore)
        collector = ProxyCollector(store=store, verbose=True)

        source = PROXY_SOURCES[0]  # proxifly https
        ips = collector.fetch_source(source)
        print(f"\nFetched {len(ips)} proxies from {source['source']}")
        assert len(ips) > 0
        # 验证格式
        for ip in ips[:3]:
            assert "ip" in ip
            assert "port" in ip
            assert "protocol" in ip
            print(f"  {ip['protocol']}://{ip['ip']}:{ip['port']}")
