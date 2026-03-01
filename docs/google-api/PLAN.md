# Google Search API — 自建方案规划

> **背景：** 基于 Cloudflare Workers 的 Google 搜索解析方案已被证明不可行（详见 [`docs/google-cf/ISSUES.md`](../google-cf/ISSUES.md)）。
> 本文档规划自建替代方案，核心需求：**每天数万次 Google 搜索请求，结构化返回搜索结果。**

---

## 目录

1. [浏览器环境 — Playwright 方案分析](#1-浏览器环境--playwright-方案分析)
2. [自建代理池管理系统](#2-自建代理池管理系统)
3. [免费代理 IP 源](#3-免费代理-ip-源)
4. [系统架构设计](#4-系统架构设计)
5. [备选方案](#5-备选方案)

---

## 1. 浏览器环境 — Playwright 方案分析

### 1.1 为什么需要浏览器？

Google Web Search 对所有非浏览器 HTTP 请求返回 JavaScript-only 壳页面（~86KB）。搜索结果数据被加密嵌入在 JS 变量中，需要执行 JavaScript 才能解密和渲染。因此，**获取 Google 搜索结果必须使用真实浏览器环境**。

### 1.2 Playwright 浏览器成本分析

#### 单次搜索的开销

| 操作 | 耗时 | 内存 |
|------|------|------|
| 冷启动浏览器 (`browser.launch`) | 1-3 秒 | ~100-200 MB |
| 新建浏览器上下文 (`browser.newContext`) | 50-100 ms | ~20-50 MB |
| 打开新页面 + 导航到 Google | 2-5 秒 | ~50-100 MB/页 |
| 等待搜索结果渲染 | 1-3 秒 | — |
| 提取 HTML + 关闭页面 | <100 ms | — |

#### 关键优化：浏览器复用 vs 上下文复用

**策略 A：每次搜索启动新浏览器** ❌ 不可行
- 成本：1-3 秒启动 + ~200MB 内存/实例
- 30,000 次/天 → 需要同时运行数十个浏览器实例
- 内存需求：30-50 GB

**策略 B：持久浏览器 + 新上下文/页面** ✅ 推荐
- 浏览器只启动一次（或少数几个实例）
- 每次搜索创建新 `BrowserContext`（50-100ms，~20-50MB）
- 每个上下文使用不同的代理 IP（通过 `proxy` 参数）
- 搜索完成后关闭页面/上下文释放内存

**策略 C：持久浏览器 + Tab 复用** ✅ 最高效
- 维持固定数量的 Tab（如 10-20 个）
- 每个 Tab 循环使用：`page.goto(newSearchUrl)` → 提取结果
- 内存稳定，不需频繁创建/销毁
- 缺点：同一上下文的 Cookie/指纹关联，需要配合 IP 轮换

### 1.3 吞吐量估算（策略 B/C）

| 参数 | 保守估计 | 乐观估计 |
|------|---------|---------|
| 单次搜索耗时 | 5 秒 | 3 秒 |
| 并发浏览器实例 | 3 个 | 5 个 |
| 每实例并发页面 | 5 个 | 10 个 |
| 每秒搜索量 | 3 次 | 16.7 次 |
| 每天搜索量 | ~260,000 次 | ~1,440,000 次 |
| 内存需求 | ~2-3 GB | ~5-8 GB |

**结论：3 个 Playwright 浏览器实例 + 每实例 5 个并发页面即可满足每天 30,000 次搜索。** 只需要一台 4GB 内存的 VPS。

### 1.4 自建 Playwright 服务架构

```
自有服务器（VPS）
├── Playwright 浏览器池（Python）
│   ├── 浏览器实例 1 (Chromium headless)
│   │   ├── Context/Page 1 → 搜索任务
│   │   ├── Context/Page 2 → 搜索任务
│   │   └── ...
│   ├── 浏览器实例 2
│   └── 浏览器实例 3
├── HTTP API 服务（FastAPI）
│   └── /search?q=xxx → 分配到空闲 Page → 返回解析结果
├── 自建代理池管理（MongoDB）
│   ├── IP 采集模块 — 从免费代理列表 URL 批量获取
│   ├── IP 存储模块 — MongoDB collection: ips
│   ├── IP 检测模块 — Google 可用性检测 → collection: google_ips
│   └── IP 选择模块 — 从可用池中智能选取代理
└── 反检测模块
    ├── UA 轮换
    ├── 浏览器指纹随机化
    └── 请求间隔随机化
```

**关键依赖库：**

| 工具 | 说明 |
|------|------|
| [Playwright](https://playwright.dev/) | 浏览器自动化库，支持 Chromium/Firefox/WebKit |
| [playwright-stealth](https://github.com/nicholasgasior/playwright-stealth) | Playwright 反检测插件，隐藏 headless 特征 |
| [FastAPI](https://fastapi.tiangolo.com/) | HTTP API 服务框架 |
| [pymongo](https://pymongo.readthedocs.io/) | MongoDB Python 驱动 |
| [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) | HTML 解析 |

### 1.5 Playwright 方案的风险与对策

| 风险 | 对策 |
|------|------|
| Google 检测 headless 浏览器 | 使用 stealth 插件 + 随机指纹 + 真实浏览器启动参数 |
| 触发 CAPTCHA | 降低请求频率 + IP 轮换 + 随机延迟 |
| 浏览器内存泄漏 | 定期重启浏览器实例（每 100-200 次搜索） |
| 浏览器崩溃 | 进程监控 + 自动重启 + 请求重试 |
| Google 更新页面结构 | 解析器使用多策略匹配，兼容结构变化 |

---

## 2. 自建代理池管理系统

### 2.1 设计目标

不依赖任何第三方代理框架，完全自建代理池管理系统，包含：

1. **IP 数据采集** — 从免费代理列表 URL 批量拉取 IP
2. **IP 数据存储** — 使用 MongoDB 统一存储和管理
3. **IP 可用性检测** — 针对不同用途分别检测（首先是 Google 搜索）
4. **IP 智能选取** — 从已验证可用的 IP 中选取代理

### 2.2 MongoDB 数据模型

连接地址：`mongodb://localhost:27017`，数据库：`webu`

#### Collection: `ips`（原生采集的 IP 数据）

```json
{
    "ip": "1.2.3.4",
    "port": 8080,
    "protocol": "https",
    "source": "proxifly",
    "collected_at": "2026-03-01T12:00:00"
}
```

- 唯一索引：`(ip, port, protocol)`
- 用于去重和跨来源合并

#### Collection: `google_ips`（Google 搜索可用性检测结果）

```json
{
    "ip": "1.2.3.4",
    "port": 8080,
    "protocol": "https",
    "proxy_url": "http://1.2.3.4:8080",
    "is_valid": true,
    "latency_ms": 1200,
    "checked_at": "2026-03-01T12:05:00",
    "fail_count": 0,
    "success_count": 5,
    "last_error": ""
}
```

- 唯一索引：`(ip, port, protocol)`
- 查询可用 IP 时按 `is_valid=true` + `latency_ms` 排序

### 2.3 代理池工作流程

```
1. 采集阶段（定时 / 手动触发）
   ├── 从多个免费代理列表 URL 拉取 IP 列表
   ├── 解析为 (ip, port, protocol) 三元组
   └── 写入 MongoDB `ips` collection（upsert 去重）

2. 检测阶段（定时 / 手动触发）
   ├── 从 `ips` 中取出待检测的 IP
   ├── 并发检测 Google 搜索可用性
   │   ├── 通过代理访问 Google 搜索页
   │   ├── 检查是否返回有效搜索结果
   │   └── 记录延迟和错误信息
   └── 将检测结果写入 `google_ips`（upsert）

3. 选取阶段（搜索请求时）
   ├── 从 `google_ips` 中查询 is_valid=true 的 IP
   ├── 按 latency_ms 排序，优先选择低延迟 IP
   ├── 排除最近 N 次请求已使用的 IP（避免频繁复用）
   └── 返回 proxy_url 供 Playwright 使用
```

---

## 3. 免费代理 IP 源

### 3.1 活跃的 GitHub 免费代理列表项目

#### Tier 1：高活跃度（分钟级更新）

| 项目 | Stars | 更新频率 | 代理数量 | 协议 |
|------|-------|---------|---------|------|
| **proxifly/free-proxy-list** | 4k | 每 5 分钟 | ~2,630 | HTTP/HTTPS/SOCKS4/SOCKS5 |
| **zloi-user/hideip.me** | 424 | 每 10 分钟 | ~1,400 | HTTP/HTTPS/SOCKS4/SOCKS5/CONNECT |

#### Tier 2：高活跃度（小时级更新）

| 项目 | Stars | 更新频率 | 代理数量 | 协议 |
|------|-------|---------|---------|------|
| **TheSpeedX/PROXY-List** | 5.3k | 每日多次 | ~7,891 | HTTP/SOCKS4/SOCKS5 |

### 3.2 直接可用的代理列表 URL（已集成）

```bash
# proxifly — 每 5 分钟更新（推荐）
https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/https/data.txt
https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt

# TheSpeedX — 每日更新，量大
https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt
https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt

# zloi-user — 每 10 分钟更新
https://github.com/zloi-user/hideip.me/raw/refs/heads/master/https.txt
https://github.com/zloi-user/hideip.me/raw/refs/heads/master/socks5.txt
```

### 3.3 免费代理的局限性与对策

| 问题 | 影响 | 对策 |
|------|------|------|
| **可用率低** | 通常 10-30% 的代理可用 | 批量获取 + 实时验证 + 缓存可用列表 |
| **速度慢** | 延迟高、带宽低 | 选择低延迟代理，设置超时淘汰 |
| **生命周期短** | 代理可能在几分钟内失效 | 持续刷新 + 健康检查 |
| **被 Google 封禁** | 数据中心 IP 可能已被标记 | 优先选择住宅 IP 类型 |
| **安全风险** | 免费代理可能截取流量 | 仅用于 Google 搜索，不传输敏感数据 |

### 3.4 付费代理推荐（如免费方案不足）

| 服务 | 类型 | 价格 | 特点 |
|------|------|------|------|
| [Webshare](https://www.webshare.io/) | 数据中心/住宅 | Free: 10 代理 / $2.99起 | 有免费层，API 友好 |
| [IPRoyal](https://iproyal.com/) | 住宅 | $1.75/GB | 性价比高 |

---

## 4. 系统架构设计

### 4.1 总体架构

```
┌──────────────────────────────────────────────────────┐
│                     VPS 服务器                         │
│  (4GB+ RAM, 推荐 8GB)                                 │
│                                                       │
│  ┌───────────┐     ┌──────────────────────┐          │
│  │ HTTP API  │────→│ Playwright 浏览器池    │          │
│  │ (FastAPI) │     │  ├── Browser 1        │          │
│  │           │     │  │   ├── Context 1-5  │          │
│  │ /search   │     │  ├── Browser 2        │          │
│  │ /proxy/*  │     │  │   ├── Context 1-5  │          │
│  │ /health   │     │  └── Browser 3        │          │
│  └───────────┘     │      └── Context 1-5  │          │
│       │            └──────────────────────┘          │
│       │                       │                       │
│       │            ┌──────────┴───────────┐          │
│       │            │  自建代理池 (MongoDB)   │          │
│       │            │  ├── ips (原生数据)     │          │
│       │            │  ├── google_ips (检测)  │          │
│       │            │  ├── IP 采集模块        │          │
│       │            │  ├── IP 检测模块        │          │
│       │            │  └── IP 选取模块        │          │
│       │            └──────────────────────┘          │
│       │                                               │
│  ┌────┴──────┐                                       │
│  │ HTML 解析  │                                       │
│  │ (parser)  │                                       │
│  └───────────┘                                       │
└──────────────────────────────────────────────────────┘
```

### 4.2 模块结构

```
src/webu/google-api/
├── __init__.py           # 模块导出
├── constants.py          # 常量：代理源 URL、MongoDB 配置、UA 列表等
├── mongo.py              # MongoDB 操作封装（参考 sedb/mongo.py）
├── proxy_collector.py    # IP 源采集：从 URL 拉取 → 解析 → 存储到 ips
├── proxy_checker.py      # IP 可用性检测：Google 页面检测 → 更新 google_ips
├── proxy_pool.py         # 代理池管理：编排采集/检测/选取
├── scraper.py            # Playwright Google 抓取器：浏览器池 + 搜索执行
├── parser.py             # HTML 解析：纯化 HTML → 提取搜索结果数据
└── server.py             # FastAPI 服务：搜索 API + 代理管理 API
```

### 4.3 实施路线图

#### 阶段 1：代理池基础（MVP）

- [x] 定义常量与配置（代理源 URL、MongoDB 配置）
- [x] 实现 MongoDB 操作封装
- [x] 实现 IP 源采集模块（从 URL 拉取 + 解析 + 存储）
- [x] 实现 IP 可用性检测模块（Google 页面检测）
- [x] 实现代理池管理器（编排采集/检测/选取）

#### 阶段 2：搜索系统（MVP）

- [x] 实现 Playwright 抓取器（浏览器池 + 代理轮换 + 搜索执行）
- [x] 实现 HTML 解析模块（纯化 HTML + 提取搜索结果）
- [x] 实现 FastAPI 服务（搜索 API + 代理管理 API）
- [x] 编写测试

#### 阶段 3：稳定性与性能（后续）

- [ ] 浏览器健康监控 + 自动重启
- [ ] 请求队列 + 并发控制
- [ ] CAPTCHA 检测 + 降级处理
- [ ] 搜索结果缓存
- [ ] 压力测试

### 4.4 成本估算

| 项目 | 月成本 |
|------|--------|
| VPS (4-8GB RAM) | $5-20 |
| 免费代理 | $0 |
| 付费代理（如需） | $10-50 |
| **总计** | **$5-70/月** |

---

## 5. 备选方案

### 5.1 DuckDuckGo HTML Search ✅ 已验证可行

- **无需浏览器** — DuckDuckGo 返回服务端渲染的 HTML
- **无需代理** — 对爬虫较为友好
- **适用场景：** 不严格要求 Google 结果时，成本最低的方案

### 5.2 Google Custom Search JSON API

- **官方 API**，返回 JSON，无需解析 HTML
- **免费额度**：100 次/天
- **付费**：$5 / 1,000 次查询 → 30,000 次/天 = $4,500/月 ❌ 成本过高
- **适用场景：** 低频搜索 (<100 次/天) 或混合方案

### 5.3 第三方 SERP API

| 服务 | 免费额度 | 付费价格 | 说明 |
|------|---------|---------|------|
| [Serper](https://serper.dev/) | 2,500 次 (首次) | $50/月 (50,000 次) | 性价比较高 |
| [ScraperAPI](https://www.scraperapi.com/) | 5,000 次/月 | $49/月 (100,000 次) | 通用爬虫 API |

**适用场景：** 不想维护自建基础设施时的备选。

---

## 6. 最终建议

| 方案 | 适用场景 | 月成本 | 复杂度 | 推荐度 |
|------|---------|--------|--------|--------|
| **自建 Playwright + 自建代理池** | 通用，高频，完全可控 | $5-20 | 中 | ⭐⭐⭐⭐⭐ |
| **DuckDuckGo 直接解析** | 不要求 Google 结果 | $5 | 低 | ⭐⭐⭐⭐ |
| **Serper API** | 不想自建，中频 | $50 | 极低 | ⭐⭐⭐⭐ |
| **自建 Playwright + 付费代理** | 高频，要求稳定 | $20-70 | 中 | ⭐⭐⭐⭐ |
| **Google Custom Search API** | 低频 (<100/天) | $0 | 极低 | ⭐⭐⭐ |

**首选推荐：自建 Playwright 浏览器池 + 自建 MongoDB 代理池管理系统。** 成本最低、灵活度最高、完全可控。

---

*文档创建日期：2026-03-01*
*基于 CF Workers 方案失败后的调研与规划*