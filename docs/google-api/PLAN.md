# Google Search API — 替代方案规划

> **背景：** 基于 Cloudflare Workers 的 Google 搜索解析方案已被证明不可行（详见 [`docs/google-cf/ISSUES.md`](../google-cf/ISSUES.md)）。
> 本文档规划可行的替代方案，核心需求：**每天数万次 Google 搜索请求，结构化返回搜索结果。**

---

## 目录

1. [问题 1：浏览器环境 — Playwright 方案分析](#1-浏览器环境--playwright-方案分析)
2. [问题 2：Cloudflare 多出口 IP 可能性](#2-cloudflare-多出口-ip-可能性)
3. [问题 3：免费代理 IP 源](#3-免费代理-ip-源)
4. [综合方案建议](#4-综合方案建议)
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
- 或在同一上下文中打开新 `Page`（更快，~50MB）
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

### 1.4 推荐技术栈

#### 方案 A：自建 Playwright 服务（推荐）

```
自有服务器（VPS）
├── Playwright 浏览器池（Python / Node.js）
│   ├── 浏览器实例 1 (Chromium headless)
│   │   ├── Context/Page 1 → 搜索任务
│   │   ├── Context/Page 2 → 搜索任务
│   │   └── ...
│   ├── 浏览器实例 2
│   └── 浏览器实例 3
├── HTTP API 服务（FastAPI / Express）
│   └── /search?q=xxx → 分配到空闲 Page → 返回解析结果
├── 代理轮换模块
│   └── 每个搜索请求使用不同代理 IP
└── 反检测模块
    ├── UA 轮换
    ├── 浏览器指纹随机化
    └── 请求间隔随机化
```

**关键框架/库：**

| 工具 | 说明 | 语言 |
|------|------|------|
| [Playwright](https://playwright.dev/) | 浏览器自动化库，支持 Chromium/Firefox/WebKit | Python / Node.js |
| [Crawlee](https://github.com/apify/crawlee) (22k ⭐) | 基于 Playwright/Puppeteer 的爬虫框架，内置代理轮换、会话管理、自动扩缩 | Node.js / Python |
| [playwright-stealth](https://github.com/nicholasgasior/playwright-stealth) | Playwright 反检测插件，隐藏 headless 特征 | Python |
| [undetected-playwright](https://github.com/nicholasgasior/undetected-playwright) | 社区维护的反检测 Playwright | Python |

#### 方案 B：Crawlee 框架（推荐用于大规模场景）

[Crawlee](https://crawlee.dev/) 是 Apify 开源的爬虫框架（22k GitHub Stars，Apache-2.0），内置：

- **自动浏览器管理** — 浏览器池、自动重启、内存管理
- **代理轮换** — 内置 `ProxyConfiguration`，支持列表轮换
- **会话管理** — 自动检测封禁并切换会话
- **请求队列** — 持久化队列，支持失败重试
- **自动扩缩** — 根据系统资源自动调整并发

```python
# Crawlee for Python 示例
from crawlee.playwright_crawler import PlaywrightCrawler, PlaywrightCrawlingContext

crawler = PlaywrightCrawler(
    max_requests_per_crawl=1000,
    headless=True,
    browser_pool_options={
        'max_open_pages_per_browser': 10,  # 每个浏览器最多 10 个页面
    },
    proxy_configuration=ProxyConfiguration(
        proxy_urls=['http://proxy1:8080', 'http://proxy2:8080', ...]
    ),
)

@crawler.router.default_handler
async def handler(context: PlaywrightCrawlingContext):
    page = context.page
    # 等待搜索结果加载
    await page.wait_for_selector('#search')
    html = await page.content()
    # 解析搜索结果...
```

### 1.5 Playwright 方案的风险与对策

| 风险 | 对策 |
|------|------|
| Google 检测 headless 浏览器 | 使用 stealth 插件 + 随机指纹 + 真实浏览器启动参数 |
| 触发 CAPTCHA | 降低请求频率 + IP 轮换 + 随机延迟 + CAPTCHA 解决服务 |
| 浏览器内存泄漏 | 定期重启浏览器实例（每 100-200 次搜索） |
| 浏览器崩溃 | 进程监控 + 自动重启 + 请求重试 |
| Google 更新页面结构 | 解析器使用多策略匹配，兼容结构变化 |

---

## 2. Cloudflare 多出口 IP 可能性

### 2.1 结论：CF Workers 无法提供多出口 IP

Cloudflare Workers 的 `fetch()` 请求从 Cloudflare 边缘节点发出，存在以下限制：

1. **出口 IP 不可控** — Workers 没有选择或绑定出口 IP 的机制
2. **IP 共享** — 同一数据中心的所有 Workers 共享出口 IP 段
3. **数据中心 IP** — CF 的 IP 属于已知的数据中心 ASN，Google 会识别并限制
4. **无代理支持** — Workers 的 `fetch()` 不支持 HTTP CONNECT 隧道代理

### 2.2 CF 可能的间接方案

| 方案 | 可行性 | 说明 |
|------|--------|------|
| Cloudflare WARP | ❌ 不适用 | WARP 是客户端 VPN，不适用于 Workers |
| Cloudflare Spectrum | ❌ 不适用 | Spectrum 是入站代理（TCP/UDP），不控制出站 IP |
| Workers + 外部代理 | ❌ 受限 | `fetch()` 不支持 CONNECT 代理 |
| 多 CF 账号部署 | ⚠️ 理论可行 | 不同账号可能分配不同边缘节点，但 IP 仍是 CF ASN |
| Browser Rendering | ⚠️ 有限 | 支持 Playwright，但 IP 仍从 CF 边缘出口，且有严格限流 |

### 2.3 Browser Rendering 限制回顾

即使使用 CF Browser Rendering：

- **Free Plan**: 10 分钟/天，6 次/分钟 → 每天最多 ~60 次搜索
- **Paid Plan**: $0.09/小时，180 次/分钟，30 并发浏览器
  - 30,000 次/天 × 5 秒 = 41.7 小时 → $3.75/天 ≈ **$112/月**
  - IP 仍然从 CF 边缘出口，Google 反爬虫风险不变

**结论：CF 无法解决 IP 轮换问题，Browser Rendering 成本高且依然有 IP 风险。建议放弃 CF 路线，使用自建服务器。**

---

## 3. 免费代理 IP 源

### 3.1 活跃的 GitHub 免费代理列表项目

以下项目按活跃度排序，均截至 2026 年 3 月仍在更新：

#### Tier 1：高活跃度（分钟级更新）

| 项目 | Stars | 更新频率 | 代理数量 | 协议 | 链接 |
|------|-------|---------|---------|------|------|
| **proxifly/free-proxy-list** | 4k | 每 5 分钟 | ~2,630 | HTTP/HTTPS/SOCKS4/SOCKS5 | [GitHub](https://github.com/proxifly/free-proxy-list) |
| **zloi-user/hideip.me** | 424 | 每 10 分钟 | ~1,400 | HTTP/HTTPS/SOCKS4/SOCKS5/CONNECT | [GitHub](https://github.com/zloi-user/hideip.me) |
| **hookzof/socks5_list** | — | 持续更新 | — | SOCKS5 | [GitHub](https://github.com/hookzof/socks5_list) |
| **elliottophellia/proxylist** | — | 持续更新 | — | HTTP/SOCKS4/SOCKS5 | [GitHub](https://github.com/elliottophellia/proxylist) |

#### Tier 2：高活跃度（小时级更新）

| 项目 | Stars | 更新频率 | 代理数量 | 协议 | 链接 |
|------|-------|---------|---------|------|------|
| **TheSpeedX/PROXY-List** | 5.3k | 每日多次 | ~7,891 | HTTP/SOCKS4/SOCKS5 | [GitHub](https://github.com/TheSpeedX/PROXY-List) |
| **Anonym0usWork1221/Free-Proxies** | — | 每 2 小时 | — | HTTP/HTTPS/SOCKS4/SOCKS5 | [GitHub](https://github.com/Anonym0usWork1221/Free-Proxies) |
| **officialputuid/KangProxy** | — | 每日 | — | HTTP/HTTPS/SOCKS4/SOCKS5 | [GitHub](https://github.com/officialputuid/KangProxy) |
| **roosterkid/openproxylist** | — | 每小时 | — | HTTPS/SOCKS4/SOCKS5/V2Ray | [GitHub](https://github.com/roosterkid/openproxylist) |
| **sunny9577/proxy-scraper** | — | 每 3 小时 | — | HTTP/HTTPS/SOCKS4/SOCKS5 | [GitHub](https://github.com/sunny9577/proxy-scraper) |

#### Tier 3：代理工具（自行抓取/验证）

| 项目 | Stars | 说明 | 链接 |
|------|-------|------|------|
| **bluet/proxybroker2** | — | ProxyBroker 的活跃 fork，自动发现 + 验证 + 轮换代理 | [GitHub](https://github.com/bluet/proxybroker2) |
| **mubeng/mubeng** | — | Go 语言代理检查器 + IP 轮换器，内置代理服务器 | [GitHub](https://github.com/mubeng/mubeng) |
| **constverum/ProxyBroker** | — | 经典代理发现工具（Python，asyncio） | [GitHub](https://github.com/constverum/ProxyBroker) |
| **ForceFledgling/proxyhub** | — | 代理发现 + 验证 + 服务器 | [GitHub](https://github.com/ForceFledgling/proxyhub) |
| **iw4p/proxy-scraper** | — | 多源代理抓取 + 可用性验证 | [GitHub](https://github.com/iw4p/proxy-scraper) |

### 3.2 直接可用的代理列表 URL

```bash
# proxifly — 每 5 分钟更新（推荐）
curl -sL https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/https/data.txt
curl -sL https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt

# TheSpeedX — 每日更新，量大
curl -sL https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt
curl -sL https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt

# zloi-user — 每 10 分钟更新
curl -sL https://github.com/zloi-user/hideip.me/raw/refs/heads/master/https.txt
curl -sL https://github.com/zloi-user/hideip.me/raw/refs/heads/master/socks5.txt

# proxifly — 按国家筛选（美国）
curl -sL https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/countries/US/data.txt
```

### 3.3 免费代理的局限性

| 问题 | 影响 | 对策 |
|------|------|------|
| **可用率低** | 通常 10-30% 的代理可用 | 批量获取 + 实时验证 + 缓存可用列表 |
| **速度慢** | 延迟高、带宽低 | 选择低延迟代理，设置超时淘汰 |
| **生命周期短** | 代理可能在几分钟内失效 | 持续刷新 + 健康检查 |
| **被 Google 封禁** | 数据中心 IP 可能已被标记 | 优先选择住宅 IP 类型 |
| **安全风险** | 免费代理可能截取流量 | 仅用于 Google 搜索，不传输敏感数据 |

### 3.4 付费代理推荐（如免费方案不足）

如果免费代理的可用率和稳定性无法满足每天数万次搜索的需求，以下是成本较低的付费选择：

| 服务 | 类型 | 价格 | 特点 |
|------|------|------|------|
| [Webshare](https://www.webshare.io/) | 数据中心/住宅 | Free: 10 代理 / $2.99起 | 有免费层，API 友好 |
| [ProxyScrape](https://proxyscrape.com/) | 聚合列表 | Free / Premium | API 获取代理列表 |
| [Bright Data](https://brightdata.com/) | 住宅 | $10起/GB | 最大的住宅代理网络 |
| [IPRoyal](https://iproyal.com/) | 住宅 | $1.75/GB | 性价比高 |

---

## 4. 综合方案建议

### 4.1 推荐架构

```
┌─────────────────────────────────────────────┐
│                  VPS 服务器                    │
│  (4GB+ RAM, 推荐 8GB)                        │
│                                              │
│  ┌──────────┐    ┌─────────────────────┐     │
│  │ HTTP API │───→│ Playwright 浏览器池   │     │
│  │ (FastAPI)│    │  ├── Browser 1       │     │
│  │          │    │  │   ├── Page 1-5    │     │
│  │ /search  │    │  ├── Browser 2       │     │
│  │ /health  │    │  │   ├── Page 1-5    │     │
│  └──────────┘    │  └── Browser 3       │     │
│       │          │      └── Page 1-5    │     │
│       │          └─────────────────────┘     │
│       │                     │                │
│       │          ┌──────────┴──────────┐     │
│       │          │   代理轮换模块        │     │
│       │          │  ├── 免费代理池       │     │
│       │          │  │   └── 自动刷新     │     │
│       │          │  ├── 健康检查         │     │
│       │          │  └── 智能选择         │     │
│       │          └─────────────────────┘     │
│       │                                      │
│  ┌────┴─────┐    ┌─────────────────────┐     │
│  │ 结果解析  │    │   缓存/去重模块      │     │
│  │ (parser) │    │  ├── Redis/SQLite    │     │
│  └──────────┘    │  └── 相同查询缓存     │     │
│                  └─────────────────────┘     │
└─────────────────────────────────────────────┘
```

### 4.2 实施路线图

#### 阶段 1：基础搭建（1-2 天）

- [ ] 搭建 FastAPI 服务
- [ ] 实现 Playwright 浏览器池（固定 2-3 个浏览器实例）
- [ ] 实现单次搜索流程：导航 → 等待渲染 → 提取 HTML → 解析
- [ ] 复用之前 `parser.ts` 的解析逻辑（改写为 Python）

#### 阶段 2：代理与反检测（1-2 天）

- [ ] 集成免费代理源（proxifly + TheSpeedX）
- [ ] 实现代理验证 + 健康检查
- [ ] 实现代理轮换（每次搜索或每 N 次搜索切换）
- [ ] 配置 Playwright 反检测：stealth 插件、随机指纹、随机延迟

#### 阶段 3：稳定性与性能（2-3 天）

- [ ] 实现请求队列 + 并发控制
- [ ] 实现搜索结果缓存（相同查询 TTL 缓存）
- [ ] 添加浏览器健康监控 + 自动重启
- [ ] 添加错误处理：CAPTCHA 检测、重试、降级
- [ ] 压力测试：验证 30,000 次/天的吞吐量

#### 阶段 4：可选优化

- [ ] 考虑引入 Crawlee 框架替换自建池
- [ ] CAPTCHA 解决方案（2Captcha、CapSolver 等）
- [ ] 评估是否需要付费代理
- [ ] 监控告警（Prometheus + Grafana 或简单日志告警）

### 4.3 成本估算

| 项目 | 月成本 |
|------|--------|
| VPS (4-8GB RAM) | $5-20 |
| 免费代理 | $0 |
| 付费代理（如需） | $10-50 |
| **总计** | **$5-70/月** |

对比 CF Browser Rendering Paid Plan 的 ~$112/月，自建方案成本更低且更灵活。

---

## 5. 备选方案

### 5.1 DuckDuckGo HTML Search ✅ 已验证可行

在之前的测试中，DuckDuckGo 被证明可以直接通过 HTTP 请求获取结构化搜索结果：

- **无需浏览器** — DuckDuckGo 返回服务端渲染的 HTML
- **无需代理** — 对爬虫较为友好
- **实测提取了 10 个搜索结果**，包含标题、URL、摘要

**适用场景：** 如果搜索需求不严格要求 Google 结果，DuckDuckGo 是成本最低的方案。

### 5.2 Google Custom Search JSON API

- **官方 API**，返回 JSON，无需解析 HTML
- **免费额度**：100 次/天（约 3,000 次/月）
- **付费**：$5 / 1,000 次查询
- **30,000 次/天 = $150/天 = $4,500/月** ❌ 成本过高

**适用场景：** 低频搜索 (<100 次/天) 或混合方案（小部分请求走官方 API 确保准确性）。

### 5.3 SerpAPI / SearchAPI 等第三方服务

| 服务 | 免费额度 | 付费价格 | 说明 |
|------|---------|---------|------|
| [SerpAPI](https://serpapi.com/) | 100 次/月 | $50/月 (5,000 次) | 最成熟的 Google SERP API |
| [SearchAPI](https://www.searchapi.io/) | 100 次/月 | $40/月 (5,000 次) | SerpAPI 替代品 |
| [Serper](https://serper.dev/) | 2,500 次 (首次) | $50/月 (50,000 次) | 性价比较高 |
| [ScraperAPI](https://www.scraperapi.com/) | 5,000 次/月 | $49/月 (100,000 次) | 通用爬虫 API |

**适用场景：** 如果不想维护自建基础设施，Serper ($50/月 50,000 次) 是性价比最高的选择。

### 5.4 Google Scholar（特定场景）

之前已验证 Google Scholar 返回服务端渲染的 HTML，可用简单 HTTP + 解析器获取。

**限制：** 仅搜索学术论文/学术内容，不适合通用搜索。

---

## 6. 最终建议

| 方案 | 适用场景 | 月成本 | 复杂度 | 推荐度 |
|------|---------|--------|--------|--------|
| **自建 Playwright + 免费代理** | 通用，高频 | $5-20 | 中 | ⭐⭐⭐⭐⭐ |
| **Crawlee 框架** | 通用，高频，需要快速搭建 | $5-20 | 低-中 | ⭐⭐⭐⭐⭐ |
| **DuckDuckGo 直接解析** | 不要求 Google 结果 | $5 | 低 | ⭐⭐⭐⭐ |
| **Serper API** | 不想自建，中频 | $50 | 极低 | ⭐⭐⭐⭐ |
| **Playwright + 付费代理** | 高频，要求稳定 | $20-70 | 中 | ⭐⭐⭐⭐ |
| **Google Custom Search API** | 低频 (<100/天) | $0 | 极低 | ⭐⭐⭐ |

**首选推荐：自建 Playwright 浏览器池 + 免费代理轮换。** 成本最低、灵活度最高、完全可控。

---

*文档创建日期：2026-03-01*
*基于 CF Workers 方案失败后的调研与规划*
