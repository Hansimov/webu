# ggsc (GooGle-SearCh) — 使用指南

> 如何使用 CLI 管理服务、调用 API 接口、以及管理代理池。

---

## 1. CLI 命令行工具

CLI 工具通过 `ggsc` 命令使用（`pip install -e .` 安装后自动注册）。

> `ggsc` 全称 **G**oo**G**le-**S**ear**C**h，是一个集代理池管理、Google 搜索 API 于一体的命令行工具。

### 1.1 服务管理

```bash
# 启动服务（后台模式，默认端口 18000）
ggsc start

# 指定端口启动
ggsc start --port 19000

# 查看服务状态（PID、内存、CPU）
ggsc status

# 查看日志（最后 50 行）
ggsc logs

# 实时跟踪日志（Ctrl+C 退出）
ggsc logs -f

# 查看更多日志
ggsc logs -n 200

# 停止服务
ggsc stop

# 重启服务
ggsc restart
```

### 1.2 代理池管理

```bash
# 从所有代理源采集 IP
ggsc collect

# 从指定代理源采集
ggsc collect --source proxifly

# 检测代理可用性 — 两级检测（默认 200 个）
ggsc check

# 仅运行 Level-1 快速检测（aiohttp，过滤死亡 IP）
ggsc check --level 1

# 仅运行 Level-2 搜索检测（Playwright，验证 Google 搜索）
ggsc check --level 2

# 运行完整两级检测（Level-1 过滤 → Level-2 验证）
ggsc check --level all

# 检测更多代理
ggsc check --limit 500

# 检测所有代理
ggsc check --mode all --limit 0

# 重新检测已过期的代理
ggsc check --mode stale

# 一键刷新（采集 + 检测）
ggsc refresh

# 查看代理池统计
ggsc stats

# 全面诊断（采集 + 全量检测 + 生成报告）
ggsc diag
```

#### 两级检测说明

| 级别 | 方式 | 目的 | 速度 | 流量 |
|------|------|------|------|------|
| Level-1 | aiohttp HTTP 请求 | 过滤死亡 IP | 极快（~100 并发） | 极小（204 响应） |
| Level-2 | Playwright 浏览器 | 验证 Google 搜索 | 较慢（~10 并发） | 较大（渲染搜索页）|

典型结果：免费 SOCKS5 代理 Level-1 通过率 ~15-50%，SOCKS4 ~38%，HTTP ~0%。Level-2 通过率较低（Google 反爬）。

---

## 2. HTTP API 接口

服务启动后，API 文档可在 `http://HOST:PORT/docs` 查看（Swagger UI）。

### 2.1 搜索接口

#### GET /search

```bash
# 基本搜索
curl "http://localhost:18000/search?q=python+programming&num=10"

# 指定语言
curl "http://localhost:18000/search?q=test&num=5&lang=zh"
```

#### POST /search

```bash
curl -X POST "http://localhost:18000/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "python programming", "num": 10, "lang": "en"}'
```

**响应示例：**

```json
{
  "success": true,
  "query": "python programming",
  "results": [
    {
      "title": "Welcome to Python.org",
      "url": "https://www.python.org/",
      "displayed_url": "https://www.python.org",
      "snippet": "The official home of the Python Programming Language...",
      "position": 1
    }
  ],
  "result_count": 10,
  "total_results_text": "About 1,200,000,000 results",
  "has_captcha": false,
  "error": ""
}
```

### 2.2 代理池接口

```bash
# 查看代理池统计
curl "http://localhost:18000/proxy/stats"

# 采集代理
curl -X POST "http://localhost:18000/proxy/collect"

# 检测代理（未检测的）
curl -X POST "http://localhost:18000/proxy/check?limit=100&mode=unchecked"

# 一键刷新
curl -X POST "http://localhost:18000/proxy/refresh?check_limit=200"

# 获取可用代理列表
curl "http://localhost:18000/proxy/valid?limit=20"

# 获取一个推荐代理
curl "http://localhost:18000/proxy/get"
```

### 2.3 健康检查

```bash
curl "http://localhost:18000/health"
# {"status": "ok", "version": "1.0.0"}
```

---

## 3. Python SDK 用法

### 3.1 代理池操作

```python
from webu.google_api import ProxyPool

pool = ProxyPool()

# 采集
pool.collect()

# 获取统计
print(pool.stats())

# 获取一个可用代理
proxy = pool.get_proxy()
print(proxy)  # {"ip": "...", "port": ..., "proxy_url": "...", "latency_ms": ...}
```

### 3.2 搜索操作

```python
import asyncio
from webu.google_api import ProxyPool, GoogleScraper

async def search():
    pool = ProxyPool()
    scraper = GoogleScraper(proxy_pool=pool, headless=True)
    await scraper.start()

    result = await scraper.search(query="Python tutorial")
    for r in result.results:
        print(f"[{r.position}] {r.title}")
        print(f"    {r.url}")

    await scraper.stop()

asyncio.run(search())
```

### 3.3 批量搜索

```python
import asyncio
from webu.google_api import ProxyPool, GoogleScraper

async def batch_search():
    pool = ProxyPool()
    scraper = GoogleScraper(proxy_pool=pool)
    await scraper.start()

    results = await scraper.search_batch(
        queries=["Python", "JavaScript", "Rust"],
        num=10,
        delay_range=(2, 5),  # 随机延迟 2-5 秒
    )

    for resp in results:
        print(f"Query: {resp.query}, Results: {len(resp.results)}")

    await scraper.stop()

asyncio.run(batch_search())
```

---

## 4. 常见操作流程

### 4.1 首次部署

```bash
# 1. 安装依赖
pip install -e .
playwright install chromium

# 2. 采集代理
ggsc collect

# 3. 检测代理
ggsc check --limit 200

# 4. 查看统计
ggsc stats

# 5. 启动服务
ggsc start
```

### 4.2 日常维护

```bash
# 一键刷新代理池
ggsc refresh

# 检查服务状态
ggsc status

# 查看日志
ggsc logs -n 50
```

### 4.3 全面诊断

```bash
# 全面诊断：采集所有源 → Level-1 全量检测 → Level-2 检测 → 生成 REPORT.md
ggsc diag
```

---

## 5. 配置说明

主要配置在 `src/webu/google_api/constants.py`：

| 常量 | 默认值 | 说明 |
|------|--------|------|
| `MONGO_CONFIGS` | `localhost:27017/webu` | MongoDB 连接 |
| `FETCH_PROXY` | `http://127.0.0.1:11119` | 采集代理列表时使用的 HTTP 代理 |
| `PROXY_CHECK_TIMEOUT` | 15 秒 | Level-2 代理检测超时 |
| `SEARCH_TIMEOUT` | 30 秒 | 搜索超时 |
| `CHECK_CONCURRENCY` | 20 | Level-2 并发检测数 |
| Level-1 timeout | 10 秒 | Level-1 快速检测超时 |
| Level-1 concurrency | 100 | Level-1 并发检测数 |

### 5.1 依赖说明

| 包 | 用途 |
|----|------|
| `aiohttp` | Level-1 快速 HTTP 代理检测 |
| `aiohttp-socks` | Level-1 SOCKS4/5 代理支持 |
| `playwright` | Level-2 浏览器检测 + Google 搜索 |
| `pymongo` | MongoDB 数据存储 |
| `fastapi` + `uvicorn` | HTTP API 服务 |
| `beautifulsoup4` | HTML 解析 |

---

*文档更新日期：2026-03-01*
