# ggsc (GooGle-SearCh) — 使用指南

> ggsc CLI 工具和 API 的完整使用说明。

---

## 1. CLI 命令

### 1.1 服务管理

```bash
# 启动服务（后台运行）
ggsc start [--port 7800] [--headless] [--proxies "url1,url2"]

# 停止服务
ggsc stop

# 重启服务
ggsc restart

# 查看服务状态
ggsc status

# 查看服务日志
ggsc logs [--follow] [--lines 50]
```

### 1.2 搜索

```bash
# 手动搜索（通过运行中的服务）
ggsc search "Python programming" [--proxy http://127.0.0.1:11111] [--num 10]

# 批量搜索测试
ggsc search-test
```

### 1.3 代理管理

```bash
# 查看代理状态
ggsc proxy-status

# 立即执行代理健康检查
ggsc proxy-check [--proxies "url1,url2"]
```

---

## 2. API 接口

### 2.1 健康检查

```bash
curl http://127.0.0.1:7800/health
```

```json
{"status": "ok", "browser_ready": true}
```

### 2.2 搜索

```bash
# GET 请求
curl "http://127.0.0.1:7800/search?q=hello+world&num=10"

# POST 请求
curl -X POST http://127.0.0.1:7800/search \
  -H "Content-Type: application/json" \
  -d '{"query": "hello world", "num_results": 10}'
```

响应：

```json
{
  "query": "hello world",
  "results": [
    {
      "position": 1,
      "title": "结果标题",
      "url": "https://example.com",
      "displayed_url": "example.com",
      "snippet": "摘要内容..."
    }
  ],
  "total_results": 10,
  "has_captcha": false,
  "error": null
}
```

### 2.3 代理状态

```bash
curl http://127.0.0.1:7800/proxy/status
```

```json
{
  "total_proxies": 2,
  "healthy_proxies": 2,
  "unhealthy_proxies": 0,
  "proxies": [
    {
      "url": "http://127.0.0.1:11111",
      "name": "proxy-11111",
      "healthy": true,
      "latency_ms": 350,
      "consecutive_failures": 0,
      "total_successes": 42,
      "total_failures": 1,
      "success_rate": "97.7%",
      "last_check": "14:30:00"
    },
    {
      "url": "http://127.0.0.1:11119",
      "name": "proxy-11119",
      "healthy": true,
      "latency_ms": 280,
      "consecutive_failures": 0,
      "total_successes": 38,
      "total_failures": 0,
      "success_rate": "100.0%",
      "last_check": "14:30:00"
    }
  ]
}
```

### 2.4 当前代理

```bash
curl http://127.0.0.1:7800/proxy/current
```

```json
{"proxy_url": "http://127.0.0.1:11111"}
```

### 2.5 立即健康检查

```bash
curl -X POST http://127.0.0.1:7800/proxy/check
```

---

## 3. Python SDK

### 3.1 基础用法

```python
from webu.google_api import ProxyManager, GoogleScraper

# 使用默认代理
manager = ProxyManager()
await manager.start()

scraper = GoogleScraper(proxy_manager=manager, headless=True)
await scraper.start()

response = await scraper.search("Python programming")
for result in response.results:
    print(f"[{result.position}] {result.title}")
    print(f"  {result.url}")

await scraper.stop()
await manager.stop()
```

### 3.2 自定义代理

```python
custom_proxies = [
    {"url": "http://my-proxy-1:8080", "name": "proxy-1"},
    {"url": "http://my-proxy-2:8080", "name": "proxy-2"},
]
manager = ProxyManager(proxies=custom_proxies)
```

### 3.3 手动代理控制

```python
# 获取当前推荐代理
proxy_url = manager.get_proxy()

# 搜索后报告结果
manager.report_success(proxy_url)
# 或
manager.report_failure(proxy_url)

# 获取统计信息
stats = manager.stats()
print(f"Healthy: {stats['healthy_proxies']}/{stats['total_proxies']}")
```

---

## 4. 配置参数

### 4.1 ProxyManager 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `proxies` | DEFAULT_PROXIES | 代理列表 |
| `check_interval` | 30 | 健康检查间隔（秒）|
| `recovery_interval` | 15 | 恢复检查间隔（秒）|
| `failure_threshold` | 3 | 连续失败阈值 |
| `verbose` | True | 是否输出日志 |

### 4.2 Server 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `port` | 7800 | 服务端口 |
| `headless` | True | Chrome 是否无头模式 |
| `proxies` | DEFAULT_PROXIES | 代理列表 |

### 4.3 常量配置 (`constants.py`)

| 常量 | 值 | 说明 |
|------|-----|------|
| `DEFAULT_PORT` | 7800 | 默认服务端口 |
| `PID_FILE` | `/tmp/ggsc.pid` | PID 文件路径 |
| `LOG_FILE` | `/tmp/ggsc.log` | 日志文件路径 |

---

## 5. CLI 日志输出格式

### 5.1 搜索日志

`ggsc search` 执行时的终端输出遵循以下格式：

**首次尝试**（无计数前缀）：
```
> Search: "python编程" via proxy-11111
✓ 10 results (1234ms)
```

**重试**（带 `[N/M]` 计数前缀）：
```
> Search: "python编程" via proxy-11111
✗ No results / timeout ...
> [2/3] Search: "python编程" via proxy-11119
✓ 10 results (987ms)
```

**无结果页面**（快速返回，约 1.2s）：
```
> Search: "uupers site:bilibili.com" via proxy-11111
⏳ Google returned no results (1170ms)
```

**设计理由：** 绝大多数搜索一次成功，`[1/3]` 计数对用户是噪音；重试时才显示计数，让异常情况更显眼。

### 5.2 URL 和路径着色

CLI 输出中的 URL 和文件路径统一通过 `logstr.file()` 以专用颜色渲染，在终端中与普通文本区分。例如：
- 代理 URL：`http://127.0.0.1:11111`（彩色）
- 结果 URL：`https://example.com`（彩色）
- 日志文件路径：`/tmp/ggsc.log`（彩色）
