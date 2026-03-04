# ggsc (GooGle-SearCh) — 测试指南

> 测试用例组织、运行方式和测试策略说明。

---

## 1. 测试分类

测试分为两类：

| 类型 | 标记 | 依赖 | 目的 |
|------|------|------|------|
| **单元测试** | 无标记 | 无（mock 外部依赖）| 验证逻辑正确性 |
| **集成测试** | `@pytest.mark.integration` | MongoDB + 网络 + Playwright | 验证真实环境可用性 |

---

## 2. 运行测试

### 2.1 运行所有单元测试

```bash
python -m pytest tests/google_api/ -xvs -m "not integration"
```

### 2.2 运行所有集成测试

```bash
# 需要 MongoDB 运行 + 网络连接
python -m pytest tests/google_api/ -xvs -m integration
```

### 2.3 运行特定模块测试

```bash
# HTML 解析器
python -m pytest tests/google_api/test_parser.py -xvs

# MongoDB 操作
python -m pytest tests/google_api/test_mongo.py -xvs -m integration

# 代理采集
python -m pytest tests/google_api/test_proxy_collector.py -xvs

# 代理检测
python -m pytest tests/google_api/test_proxy_checker.py -xvs

# Scraper
python -m pytest tests/google_api/test_scraper.py -xvs

# CLI
python -m pytest tests/google_api/test_cli.py -xvs

# CLI E2E（含 ggsc entry_point 测试）
python -m pytest tests/google_api/test_cli_e2e.py -xvs
python -m pytest tests/google_api/test_cli_e2e.py -xvs -m integration  # 含真实操作

# FastAPI 服务
python -m pytest tests/google_api/test_server.py -xvs -m integration

# 服务运行时（启动 uvicorn 测试 API）
python -m pytest tests/google_api/test_live_server.py -xvs -m integration

# 实时环境
python -m pytest tests/google_api/test_live.py -xvs -m integration

# 全流程搜索
python -m pytest tests/google_api/test_search.py -xvs -m integration
```

---

## 3. 测试文件组织

```
tests/google_api/
├── test_parser.py            # HTML 解析器 — 9 个测试
│   ├── 标准搜索结果解析
│   ├── CAPTCHA 检测
│   ├── 空页面处理
│   ├── 重定向 URL 解码
│   ├── HTML 纯化
│   └── 序列化（to_dict）
│
├── test_proxy_collector.py   # 代理采集 — 9 个测试
│   ├── 行格式解析（ip:port, protocol://ip:port, ip:port:country）
│   ├── 空行/无效行处理
│   ├── HTTP 请求 mock
│   ├── 代理源配置验证
│   └── [集成] 实际 URL 拉取
│
├── test_proxy_checker.py     # 代理检测 — 13 个测试
│   ├── 代理 URL 构建（http/https/socks5/socks4/unknown）
│   ├── 随机化辅助函数（UA/viewport/locale）
│   ├── Level-1 端点配置验证（gstatic_204 优先）
│   ├── Level-1 空列表边界情况
│   ├── ProxyChecker 初始化 + 批量级别选择
│   └── [集成] Level-1 真实代理检测
│
│   注: test_level2_http.py 已删除（L2 HTTP 对 SOCKS 代理 0% 通过，无效）
│
├── test_scraper.py           # Scraper — 8 个测试
│   ├── 初始化参数
│   ├── 浏览器启动/停止
│   ├── 重复启动处理
│   └── [集成] 直连搜索 + 自动重启
│
├── test_mongo.py             # MongoDB — 7 个测试 [全部集成]
│   ├── IP upsert + 去重
│   ├── 检测结果读写
│   ├── 排序/过滤查询
│   └── 统计信息
│
├── test_cli.py               # CLI — 14 个测试
│   ├── PID 文件读写删除
│   ├── 进程状态检测
│   ├── 命令行 --help 输出（ggsc）
│   ├── 子命令帮助（含 diag）
│   ├── collect 命令 mock
│   ├── stats 命令 mock
│   └── check --level 参数验证
│
├── test_abandoned.py          # 废弃机制 — 23 个测试
│   ├── TestAbandonedMechanism (12 个)
│   │   ├── 标记废弃 (mark/scan)
│   │   ├── 复活代理 (revive)
│   │   ├── 排除废弃代理（查询过滤）
│   │   └── 自动复活
│   ├── TestTimestamp (4 个)
│   │   ├── 格式验证、时区、无后缀、空格分隔
│   ├── TestProxyPoolAbandoned (3 个)
│   │   ├── Pool 层 scan/stats/排除
│   └── TestAbandonedConstants (4 个)
│       └── 常量验证
│
├── test_cli_e2e.py           # CLI E2E — 13 个测试
│   ├── ggsc --help 输出验证
│   ├── 所有 10 个子命令 --help
│   ├── check --level / --mode 参数
│   ├── start --port / logs --follow 参数
│   ├── ggsc entry_point 验证
│   └── [集成] stats/status/check --level 1 真实操作
│
├── test_server.py            # FastAPI — 5 个测试 [全部集成]
│   ├── 健康检查
│   ├── 代理统计/采集
│   └── 搜索 GET/POST
│
├── test_live_server.py       # 服务运行时 — 18 个测试 [全部集成]
│   ├── CLI 服务管理（status/stop/stats/collect）
│   ├── HTTP API（health/docs/schema/stats）
│   ├── API 代理操作（valid/get/collect/check）
│   ├── API 搜索（GET/POST）
│   ├── 生产数据库操作（stats/valid/distribution）
│   └── Level-1 快速检测验证
│
├── test_live.py              # 实时环境 — 19+ 个测试
│   ├── MongoDB 连接/索引/读写
│   ├── 代理源可访问性（参数化 19 源）
│   ├── 全链路采集+存储
│   ├── 代理池刷新流程
│   ├── Playwright 浏览器启动
│   ├── Google 可达性
│   ├── Parser 健壮性（各种边界 HTML）
│   ├── 两级检测：Level-1 过滤死亡 IP
│   ├── 两级检测：HTTP 代理低通过率验证
│   ├── 两级检测：完整流水线
│   └── Playwright 代理集成验证（IP 路由）
│
├── test_search.py            # 全流程搜索 — 5 个测试 [全部集成]
│   ├── 采集代理
│   ├── 代理池统计
│   ├── 可用性检测
│   ├── 完整搜索流程
│   └── 直连搜索
│
├── run_check_proxies.py      # 辅助脚本：批量代理检测
├── run_full_diagnosis.py     # 辅助脚本：全面诊断 + 报告
├── run_diagnose_proxies.py   # 辅助脚本：网络连通性诊断
├── run_search_test.py        # 辅助脚本：本地代理 + DB 代理搜索测试
├── run_proxy_search_test.py  # 辅助脚本：采集→L1→浏览器搜索端到端流程
└── run_socks_browser_test.py # 辅助脚本：SOCKS 代理浏览器搜索测试（直接测试 L1 代理）
```

---

## 4. 测试策略

### 4.1 Mock 策略

- `MongoProxyStore` — 用 `MagicMock(spec=MongoProxyStore)` 模拟
- `requests.get` — 用 `patch` 模拟 HTTP 响应
- `Playwright` — 单元测试不启动浏览器，集成测试启动真实浏览器

### 4.2 集成测试数据库

集成测试使用独立数据库 `webu_test`，避免影响生产数据：

```python
TEST_CONFIGS = {
    "host": "localhost",
    "port": 27017,
    "dbname": "webu_test",  # 测试专用数据库
}
```

### 4.3 pytest 配置

`pytest.ini`：

```ini
[pytest]
markers =
    integration: marks tests that require browser and network access
asyncio_mode = auto
```

---

## 5. 当前测试统计

| 类别 | 单元测试 | 集成测试 | 总计 |
|------|---------|---------|------|
| parser | 9 | 0 | 9 |
| proxy_collector | 7 | 2 | 9 |
| proxy_checker | 8 | 3 | 11 |
| scraper | 6 | 2 | 8 |
| mongo | 0 | 7 | 7 |
| cli | 14 | 0 | 14 |
| abandoned | 23 | 0 | 23 |
| cli_e2e | 10 | 3 | 13 |
| server | 0 | 5 | 5 |
| live_server | 0 | 18 | 18 |
| live | 5 | 14+ | 19+ |
| search | 0 | 5 | 5 |
| **合计** | **~82** | **~59** | **~141** |

---

*文档更新日期：2026-03-04*
