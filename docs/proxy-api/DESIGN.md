# pxsc (ProXy-SearCh) — proxy_api 设计文档

> 通用代理池基础设施模块，提供 IP 采集、Level-1 连通性检测、代理选取和轮换。

---

## 1. 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                     proxy_api 模块                           │
│                                                              │
│  ┌──────────────┐     ┌───────────────────┐                 │
│  │  FastAPI 服务  │     │  代理池管理器        │                 │
│  │  (server.py)  │────→│  (pool.py)         │                 │
│  │               │     │  ProxyPool         │                 │
│  │  /proxy/*     │     └───────────────────┘                 │
│  │  /health      │          │       │                        │
│  └──────────────┘          │       │                        │
│                            ▼       ▼                        │
│              ┌───────────────┐  ┌──────────────┐            │
│              │  采集模块       │  │  检测模块      │            │
│              │  (collector.py)│  │  (checker.py) │            │
│              │  ProxyCollector│  │  check_level1 │            │
│              └───────────────┘  └──────────────┘            │
│                       │              │                       │
│                       ▼              ▼                       │
│              ┌────────────────────────────┐                  │
│              │  MongoDB (mongo.py)         │                  │
│              │  MongoProxyStore            │                  │
│              │  ├── ips (原始代理)           │                  │
│              │  └── google_ips (检测结果)    │                  │
│              └────────────────────────────┘                  │
│                                                              │
│  ┌─────────────────────────────────────────────┐            │
│  │  CLI 管理 (cli.py) — pxsc 命令               │            │
│  │  start / stop / restart / status / logs      │            │
│  │  collect / check / stats / refresh / abandon │            │
│  └─────────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 模块说明

### 2.1 模块文件结构

```
src/webu/proxy_api/
├── __init__.py      # 包入口，导出核心符号
├── __main__.py      # python -m webu.proxy_api 入口
├── constants.py     # MongoDB 配置、代理源 URL、检测常量
├── mongo.py         # MongoProxyStore — 代理数据 CRUD
├── collector.py     # ProxyCollector — 从免费列表采集代理
├── checker.py       # Level-1 连通性检测（aiohttp）
├── pool.py          # ProxyPool — 编排采集/检测/选取
├── cli.py           # pxsc CLI 命令行工具
└── server.py        # FastAPI 代理管理 API
```

### 2.2 与 google_api 的关系

```
proxy_api (基础设施)          google_api (业务扩展)
├── MongoProxyStore     ←──  google_api 直接使用
├── ProxyCollector      ←──  google_api 直接使用
├── check_level1_batch  ←──  google_api.checker 调用
├── ProxyPool           ←──  GoogleSearchPool(ProxyPool) 继承
└── build_proxy_url     ←──  google_api.checker 调用
```

proxy_api 只负责通用代理基础设施（采集、连通性检测、选取），
Google 搜索特有的 Level-2 检测、浏览器搜索、结果解析 留在 google_api。

---

## 3. 核心类

### 3.1 MongoProxyStore

管理两个 MongoDB 集合：
- `ips` — 原始代理记录（ip, port, protocol, source, created_at, updated_at）
- `google_ips` — 检测结果（proxy_url, is_valid, latency_ms, last_checked, fail_count, abandoned）

支持参数化 `check_collection` 以便不同业务使用不同检测集合。

### 3.2 ProxyPool

编排代理池的完整生命周期：
1. `collect()` — 从 18 个免费代理源采集 IP
2. `check_unchecked()` — Level-1 aiohttp 连通性检测
3. `get_proxy()` — 从通过检测的 IP 中选取一个
4. `scan_abandoned()` — 标记连续失败的代理为废弃
5. `refresh()` — 一键采集 + 废弃扫描 + 检测

### 3.3 check_level1_batch

使用 aiohttp + aiohttp-socks 异步检测代理连通性：
- 检测端点：generate_204, robots.txt, favicon.ico, www.google.com/ncr
- 并发控制：Semaphore(80)
- 超时控制：12s per proxy
- 记录延迟和错误信息

---

## 4. CLI 命令

```bash
# 启动代理管理 API 服务
pxsc start [--host HOST] [--port PORT]

# 服务管理
pxsc stop / restart / status / logs [-f]

# 代理操作
pxsc collect [--source NAME]   # 采集代理
pxsc check [--limit N]         # Level-1 检测
pxsc stats                     # 统计信息
pxsc refresh [--limit N]       # 一键刷新
pxsc abandon                   # 扫描废弃代理
```

---

## 5. API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/proxy/stats` | GET | 代理池统计 |
| `/proxy/collect` | POST | 采集代理 IP |
| `/proxy/check` | POST | Level-1 检测 |
| `/proxy/refresh` | POST | 一键刷新 |
| `/proxy/valid` | GET | 获取可用代理列表 |
| `/proxy/get` | GET | 获取一个推荐代理 |
