# ggsc (GooGle-SearCh) — 环境搭建指南

> 从零开始搭建 ggsc Google 搜索服务所需的全部依赖和环境配置。

---

## 1. 系统要求

| 项目 | 最低要求 | 推荐配置 |
|------|---------|---------|
| OS | Linux (Ubuntu 20.04+) | Ubuntu 22.04 |
| Python | 3.11+ | 3.11 |
| RAM | 4 GB | 8 GB |
| 磁盘 | 5 GB | 10 GB |
| MongoDB | 6.0+ | 7.0 |

---

## 2. 安装步骤

### 2.1 安装 Python 依赖

```bash
# 克隆仓库
git clone https://github.com/Hansimov/webu.git
cd webu

# 安装包（editable 模式）
pip install -e .
```

核心依赖列表（在 `pyproject.toml` 中定义）：

| 包 | 用途 |
|----|------|
| `playwright` | 浏览器自动化 |
| `pymongo` | MongoDB 驱动 |
| `fastapi` + `uvicorn` | HTTP API 服务 |
| `beautifulsoup4` | HTML 解析 |
| `requests` | HTTP 客户端（代理列表采集）|
| `psutil` | 进程监控 |
| `tclogger` | 日志工具 |
| `pytest` + `pytest-asyncio` | 测试框架 |

### 2.2 安装 Playwright 浏览器

```bash
# 安装 Chromium 浏览器（必须）
playwright install chromium

# 安装系统依赖（首次在新服务器上）
playwright install-deps chromium
```

### 2.3 安装 MongoDB

```bash
# Ubuntu（使用 apt）
sudo apt update
sudo apt install -y mongodb-org

# 启动 MongoDB 服务
sudo systemctl start mongod
sudo systemctl enable mongod

# 验证 MongoDB 运行
mongosh --eval 'db.runCommand({ping:1})'
```

默认配置：
- 地址：`localhost:27017`
- 数据库：`webu`
- 无密码认证

### 2.4 网络代理配置

代理列表采集需要访问 GitHub 等外部 URL。如果服务器无法直接访问，需配置本地代理。

默认配置在 `src/webu/google_api/constants.py`：

```python
FETCH_PROXY = "http://127.0.0.1:11119"
```

如需修改，直接编辑该常量，或在创建 `ProxyCollector` 时传入 `fetch_proxy` 参数。

---

## 3. 验证安装

### 3.1 检查 Python 环境

```bash
python -c "
from webu.google_api import ProxyPool, GoogleScraper
print('✓ Python modules OK')
"
```

### 3.2 检查 MongoDB 连接

```bash
python -c "
import pymongo
c = pymongo.MongoClient('localhost', 27017, serverSelectionTimeoutMS=3000)
c.admin.command('ping')
print('✓ MongoDB OK')
"
```

### 3.3 检查 Playwright 浏览器

```bash
python -c "
import asyncio
from playwright.async_api import async_playwright
async def check():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        await browser.close()
        print('✓ Playwright OK')
asyncio.run(check())
"
```

### 3.4 运行单元测试

```bash
# 运行所有不需要网络的单元测试
python -m pytest tests/google_api/ -xvs -m "not integration"
```

### 3.5 运行集成测试

```bash
# 需要 MongoDB 运行 + 网络连接
python -m pytest tests/google_api/test_mongo.py -xvs -m integration
python -m pytest tests/google_api/test_live.py -xvs -m integration
```

### 3.6 验证 ggsc CLI

```bash
# 检查 ggsc 命令已注册
ggsc --help

# 快速采集 + 检测
ggsc collect
ggsc check --level 1 --limit 10
ggsc stats

# 启动服务
ggsc start
curl http://localhost:18000/health
```

---

## 4. 目录结构

```
src/webu/google_api/
├── __init__.py           # 模块导出
├── __main__.py           # python -m webu.google_api 入口
├── cli.py                # CLI 服务管理工具
├── constants.py          # 常量和配置
├── mongo.py              # MongoDB 数据访问层
├── proxy_collector.py    # 代理 IP 采集
├── proxy_checker.py      # 代理可用性检测
├── proxy_pool.py         # 代理池管理器
├── scraper.py            # Playwright Google 抓取器
├── parser.py             # HTML 解析器
└── server.py             # FastAPI HTTP 服务

tests/google_api/
├── test_cli.py           # CLI 单元测试
├── test_cli_e2e.py       # CLI 端到端测试
├── test_live.py          # 实时环境集成测试
├── test_live_server.py   # 服务运行时集成测试
├── test_mongo.py         # MongoDB 测试
├── test_parser.py        # HTML 解析器测试
├── test_proxy_checker.py # 代理检测器测试
├── test_proxy_collector.py # 代理采集测试
├── test_scraper.py       # Scraper 测试
├── test_search.py        # 搜索全流程测试
├── test_server.py        # FastAPI 服务测试
├── run_check_proxies.py  # 代理批量检测脚本
├── run_full_diagnosis.py # 全面诊断脚本
└── run_diagnose_proxies.py # 网络连通性诊断

data/google_api/          # 运行时数据（自动创建）
├── server.pid            # 服务 PID 文件
└── server.log            # 服务日志文件
```

---

*文档更新日期：2026-03-01*
