# ggsc (GooGle-SearCh) — 测试文档

> 测试组织、运行方式和测试覆盖说明。

---

## 1. 测试文件

| 文件 | 测试类 | 说明 |
|------|--------|------|
| `test_proxy_manager.py` | TestProxyState, TestProxyManager, TestProxyManagerAsync | 代理管理器核心逻辑 |
| `test_scraper.py` | TestGoogleScraper | 搜索引擎单元测试 |
| `test_parser.py` | TestGoogleResultParser | HTML 解析器测试 |
| `test_server.py` | TestGoogleSearchServerUnit | FastAPI 端点测试 |
| `test_cli.py` | TestPIDManagement, TestCLICommands, TestCLIEntry | CLI 单元测试 |
| `test_cli_e2e.py` | TestCLIBasicCommands, TestGGSCEntryPoint | CLI E2E 测试 |
| `test_search.py` | TestGoogleSearchIntegration | 端到端搜索集成测试 |
| `test_uc_cdp.py` | TestUCCDP | UC + CDP 连接测试 |

---

## 2. 测试分类

### 2.1 单元测试（无需外部依赖）

```bash
# 运行所有单元测试（排除 integration 标记）
python -m pytest tests/google_api/ -m "not integration" --tb=short -q

# 运行特定文件
python -m pytest tests/google_api/test_proxy_manager.py -xvs
python -m pytest tests/google_api/test_parser.py -xvs
```

### 2.2 集成测试（需要代理和网络）

```bash
# 需要本地代理端口 (11111, 11119) 运行
python -m pytest tests/google_api/ -m "integration" -xvs
```

集成测试需要：
- 本地代理端口 11111, 11119 已运行
- 网络连接可用
- Chrome/Chromium 已安装

---

## 3. 运行测试

### 3.1 全部单元测试

```bash
python -m pytest tests/google_api/ -m "not integration" --tb=short -q
```

### 3.2 单个模块

```bash
# 代理管理器
python -m pytest tests/google_api/test_proxy_manager.py -xvs

# 解析器
python -m pytest tests/google_api/test_parser.py -xvs

# 服务器
python -m pytest tests/google_api/test_server.py -xvs -m "not integration"

# CLI
python -m pytest tests/google_api/test_cli.py tests/google_api/test_cli_e2e.py -xvs
```

### 3.3 仅搜索集成测试

```bash
python -m pytest tests/google_api/test_search.py -xvs -m integration
```

---

## 4. 测试覆盖

### 4.1 ProxyManager 测试 (`test_proxy_manager.py`)

- **ProxyState**：初始化默认值、成功率计算、序列化
- **代理选取**：round-robin 轮换、单代理故障切换、全部不健康降级
- **使用反馈**：成功报告、失败触发不健康标记、成功恢复代理
- **统计**：stats() 返回正确字段
- **异步**：start/stop 生命周期、check_all 全量检查、单代理失败检测

### 4.2 Parser 测试 (`test_parser.py`)

- 标准搜索结果解析
- CAPTCHA 检测（多种模式）
- 空 HTML 处理
- 重定向 URL 解析
- HTML 清理（去除 script/style）

### 4.3 Server 测试 (`test_server.py`)

- `/health` 端点
- `/proxy/status` 端点
- `/proxy/current` 端点
- `/search` 参数验证

### 4.4 CLI 测试 (`test_cli.py`, `test_cli_e2e.py`)

- PID 文件管理（写入/读取/删除）
- 进程状态检查
- Help 输出和子命令
- 入口点可用性
- 参数解析（--proxy, --num, --port, --follow）

---

## 5. 测试标记

```ini
# pytest.ini
[pytest]
markers =
    integration: 需要外部依赖（代理、网络）的集成测试
```

使用 `-m "not integration"` 排除集成测试（CI 环境）。
使用 `-m "integration"` 仅运行集成测试（本地验证）。
