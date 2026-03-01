# Google Search API — 使用指南

> 如何使用 CLI 管理服务、调用 API 接口、以及管理代理池。

---

## 1. CLI 命令行工具

CLI 工具通过 `python -m webu.google_api` 或安装后的 `google-api-cli` 使用。

### 1.1 服务管理

```bash
# 启动服务（后台模式，默认端口 18000）
python -m webu.google_api start

# 指定端口启动
python -m webu.google_api start --port 19000

# 查看服务状态（PID、内存、CPU）
python -m webu.google_api status

# 查看日志（最后 50 行）
python -m webu.google_api logs

# 实时跟踪日志（Ctrl+C 退出）
python -m webu.google_api logs -f

# 查看更多日志
python -m webu.google_api logs -n 200

# 停止服务
python -m webu.google_api stop

# 重启服务
python -m webu.google_api restart
```

### 1.2 代理池管理

```bash
# 从所有代理源采集 IP
python -m webu.google_api collect

# 从指定代理源采集
python -m webu.google_api collect --source proxifly

# 检测代理可用性（默认 50 个）
python -m webu.google_api check

# 检测更多代理
python -m webu.google_api check --limit 200

# 重新检测已过期的代理
python -m webu.google_api check --mode stale

# 一键刷新（采集 + 检测）
python -m webu.google_api refresh

# 查看代理池统计
python -m webu.google_api stats
```

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
python -m webu.google_api collect

# 3. 检测代理
python -m webu.google_api check --limit 200

# 4. 查看统计
python -m webu.google_api stats

# 5. 启动服务
python -m webu.google_api start
```

### 4.2 日常维护

```bash
# 一键刷新代理池
python -m webu.google_api refresh

# 检查服务状态
python -m webu.google_api status

# 查看日志
python -m webu.google_api logs -n 50
```

---

## 5. 配置说明

主要配置在 `src/webu/google_api/constants.py`：

| 常量 | 默认值 | 说明 |
|------|--------|------|
| `MONGO_CONFIGS` | `localhost:27017/webu` | MongoDB 连接 |
| `FETCH_PROXY` | `http://127.0.0.1:11119` | 采集代理列表时使用的 HTTP 代理 |
| `PROXY_CHECK_TIMEOUT` | 15 秒 | 代理检测超时 |
| `SEARCH_TIMEOUT` | 30 秒 | 搜索超时 |
| `CHECK_CONCURRENCY` | 20 | 并发检测数 |

---

*文档更新日期：2026-03-01*
