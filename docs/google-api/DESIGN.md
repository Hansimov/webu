# Google Search API — 系统设计文档

> 基于 Playwright + MongoDB 的自建 Google 搜索服务，核心设计思路和模块拆解。

---

## 1. 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                       VPS 服务器                              │
│                                                              │
│  ┌──────────────┐     ┌───────────────────────┐             │
│  │  FastAPI 服务  │────→│  Playwright 浏览器池     │             │
│  │  (server.py)  │     │  (scraper.py)          │             │
│  │               │     │  ├── Browser instances  │             │
│  │  /search      │     │  └── Context per search │             │
│  │  /proxy/*     │     └───────────────────────┘             │
│  │  /health      │              │                             │
│  └──────────────┘              │                             │
│         │                      ▼                             │
│  ┌──────┴──────┐     ┌───────────────────┐                  │
│  │  HTML 解析   │     │  代理池 (MongoDB)    │                  │
│  │ (parser.py)  │     │  (mongo.py)        │                  │
│  └─────────────┘     │  ├── ips            │                  │
│                      │  └── google_ips     │                  │
│                      └───────────────────┘                  │
│                           ▲       ▲                          │
│                      ┌────┘       └────┐                     │
│              ┌───────────┐    ┌──────────────┐              │
│              │ 采集模块    │    │ 检测模块       │              │
│              │ collector  │    │ checker       │              │
│              └───────────┘    └──────────────┘              │
│                                                              │
│  ┌─────────────────────────────────────────┐                │
│  │  CLI 管理 (cli.py)                        │                │
│  │  start / stop / restart / status / logs   │                │
│  └─────────────────────────────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 模块设计

### 2.1 模块依赖关系

```
constants.py ──────────────────────────────────────────┐
    │                                                    │
    ▼                                                    ▼
mongo.py ──────────────────┐                         各模块引用
    │                        │
    ▼                        ▼
proxy_collector.py      proxy_checker.py
    │                        │
    └────────┬───────────────┘
             ▼
        proxy_pool.py  ←── 编排层
             │
             ▼
        scraper.py  ←── Playwright 浏览器控制
             │
             ▼
        parser.py  ←── HTML 解析
             │
             ▼
        server.py  ←── FastAPI HTTP 接口
             │
             ▼
         cli.py  ←── 命令行服务管理
```

### 2.2 各模块职责

| 模块 | 职责 | 关键类/函数 |
|------|------|------------|
| `constants.py` | 全局常量和配置 | `MONGO_CONFIGS`, `PROXY_SOURCES`, `USER_AGENTS` |
| `mongo.py` | MongoDB 数据访问层 | `MongoProxyStore` |
| `proxy_collector.py` | 从免费代理列表 URL 采集 IP | `ProxyCollector` |
| `proxy_checker.py` | 两级代理可用性检测 (aiohttp + Playwright) | `ProxyChecker`, `check_level1_batch`, `check_level2_batch` |
| `proxy_pool.py` | 编排采集/检测/选取流程 | `ProxyPool` |
| `scraper.py` | Playwright 驱动的 Google 搜索 | `GoogleScraper` |
| `parser.py` | Google 搜索结果 HTML 解析 | `GoogleResultParser` |
| `server.py` | FastAPI HTTP API 服务 | `create_google_search_server()` |
| `cli.py` | 命令行服务管理工具 | `main()` |

---

## 3. 数据流设计

### 3.1 代理采集流程

```
[代理源 URL] ──HTTP GET──→ [ProxyCollector]
     ▲ (需通过本地代理)          │ 解析 ip:port
     │ FETCH_PROXY               ▼
     │                      [MongoProxyStore]
     │                           │ upsert 到 ips collection
     │                           ▼
     │                      [MongoDB: ips]
```

- 采集时使用 `FETCH_PROXY`（默认 `http://127.0.0.1:11119`）访问代理源 URL
- 支持 `ip:port` 和 `protocol://ip:port` 两种格式
- 通过 `(ip, port, protocol)` 唯一索引实现自动去重

### 3.2 代理检测流程（两级系统）

```
[MongoDB: ips] ──取未检测的 IP──→ [ProxyChecker]
                                      │
                                ┌─────┴─────┐
                                ▼           │
                          [Level-1: aiohttp]│
                          HTTP 请求轻量端点   │
                          generate_204 (204)│
                          robots.txt (200)  │
                          并发 50，超时 10s   │
                                │           │
                          ┌─────┴─────┐     │
                          ▼           ▼     │
                       通过 IP      失败 IP  │
                          │         存储结果 │
                          ▼               │
                    [Level-2: Playwright]  │
                    Google 搜索页面检测     │
                    检查结果/CAPTCHA       │
                    并发 20，超时 15s       │
                          │               │
                          ▼               │
                    [MongoProxyStore]      │
                    upsert 到 google_ips   │
                          │               │
                          ▼               │
                    [MongoDB: google_ips]──┘
```

**Level-1 (快速过滤)**：
- 使用 `aiohttp` + `aiohttp-socks` 发送 HTTP 请求
- 检测 Google 轻量端点（`generate_204`、`robots.txt`）
- 并发度 50，超时 10s，流量极小
- HTTP 代理用 `proxy=` 参数，SOCKS5 用 `ProxyConnector`
- 可过滤 ~85% 的死亡 IP

**Level-2 (搜索验证)**：
- 使用 Playwright 浏览器访问 Google 搜索页面
- 验证搜索结果 DOM（`#search`、`#rso`、`.g`）
- 检测 CAPTCHA / 封禁
- 每个代理通过新的 `BrowserContext` 独立检测
- 记录 `is_valid`、`latency_ms`、`fail_count`、`success_count`、`check_level`

### 3.3 搜索执行流程

```
[用户请求] ──/search──→ [FastAPI Server]
                              │
                              ▼
                        [GoogleScraper]
                              │
                              ├── 从 ProxyPool 获取可用代理
                              │     └── 排除最近使用的 IP
                              │
                              ▼
                        [Playwright Browser]
                        新建 Context(proxy=选中的代理)
                        随机化: UA / Viewport / Locale
                        导航到 Google 搜索 URL
                        等待 DOM 渲染
                              │
                              ▼
                        [GoogleResultParser]
                        纯化 HTML
                        三策略解析搜索结果
                        检测 CAPTCHA
                              │
                              ▼
                        [SearchResponse] ──JSON──→ 用户
```

---

## 4. 关键设计决策

### 4.1 浏览器策略：持久浏览器 + 新上下文

选择 **策略 B**（持久浏览器 + 每次搜索新上下文）：
- 浏览器启动开销大（1-3s），只启动一次
- 每次搜索创建新 `BrowserContext`（50-100ms），指定不同代理
- 搜索完成后关闭 Context 释放内存
- 每 200 次搜索自动重启浏览器，避免内存泄漏

### 4.2 代理选取策略

- 按 `latency_ms` 升序排序，从 top 10 中随机选取
- 维护 `_recent_ips` 列表（最近 20 个），优先排除已用 IP
- 如果排除后无可用代理，放宽限制重新查询

### 4.3 反检测策略

- 每次搜索随机化 User-Agent、Viewport、Locale
- 请求间添加 1-3 秒随机延迟
- 使用 `--disable-blink-features=AutomationControlled` 参数
- CAPTCHA 检测：自动切换代理重试

### 4.4 HTML 解析三策略

1. **标准策略**：从 `div.g` 容器中提取 title/url/snippet
2. **RSO 策略**：从 `#rso` 容器子元素中提取
3. **退化策略**：从所有 `<a href>` 链接中提取

---

## 5. MongoDB 数据模型

### 5.1 `ips` Collection

| 字段 | 类型 | 说明 |
|------|------|------|
| `ip` | string | IP 地址 |
| `port` | int | 端口号 |
| `protocol` | string | 协议 (http/https/socks5) |
| `source` | string | 来源标识 |
| `collected_at` | string | 采集时间 (ISO 8601) |

唯一索引：`(ip, port, protocol)`

### 5.2 `google_ips` Collection

| 字段 | 类型 | 说明 |
|------|------|------|
| `ip` | string | IP 地址 |
| `port` | int | 端口号 |
| `protocol` | string | 协议 |
| `proxy_url` | string | 完整代理 URL |
| `is_valid` | bool | 是否可用 |
| `latency_ms` | int | 检测延迟 (ms) |
| `checked_at` | string | 检测时间 |
| `fail_count` | int | 累计失败次数 |
| `success_count` | int | 累计成功次数 |
| `last_error` | string | 最后一次错误信息 |
| `check_level` | int | 检测级别（1=Level-1, 2=Level-2）|

唯一索引：`(ip, port, protocol)`
查询索引：`(is_valid, latency_ms)`

---

## 6. API 接口设计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET/POST | `/search` | 执行 Google 搜索 |
| GET | `/proxy/stats` | 代理池统计 |
| POST | `/proxy/collect` | 采集代理 IP |
| POST | `/proxy/check` | 检测代理可用性 |
| POST | `/proxy/refresh` | 一键刷新（采集+检测）|
| GET | `/proxy/valid` | 获取可用代理列表 |
| GET | `/proxy/get` | 获取推荐的可用代理 |

---

*文档更新日期：2026-03-01*
