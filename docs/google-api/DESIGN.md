# ggsc (GooGle-SearCh) — 系统设计文档

> 基于 undetected-chromedriver + Playwright CDP 的自建 Google 搜索服务。
>
> 使用固定 HTTP 代理列表 + round-robin 负载均衡 + 自动故障转移。
>
> **代理在 context 级别设置（非浏览器级别），支持无需重启浏览器的即时代理切换。**

---

## 1. 整体架构

```
┌─────────┐     ┌─────────────┐     ┌─────────────┐     ┌──────────┐
│  客户端   │────▶│  FastAPI     │────▶│  GoogleScraper│────▶│  Google   │
│ (SDK/CLI)│◀────│  Server      │◀────│  + Parser    │◀────│  搜索页面  │
└─────────┘     └─────────────┘     └─────────────┘     └──────────┘
                       │                    │
                       │              ┌─────▼──────┐
                       │              │ ProxyManager│
                       │              │ (round-robin│
                       │              │  + 健康检查) │
                       └──────────────┴────────────┘
                                          │
                              ┌───────────┼───────────┐
                              ▼                       ▼
                     http://127.0.0.1:11111  http://127.0.0.1:11119
```

### 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| **ProxyManager** | `proxy_manager.py` | 固定代理列表管理，健康检查，round-robin 负载均衡，故障转移 |
| **GoogleScraper** | `scraper.py` | 通过 undetected-chromedriver + Playwright CDP 驱动浏览器执行搜索 |
| **GoogleResultParser** | `parser.py` | 解析 Google 搜索结果 HTML，提取标题/URL/摘要 |
| **FastAPI Server** | `server.py` | HTTP API 服务，提供搜索和代理状态接口 |
| **CLI** | `cli.py` | 命令行工具 `ggsc`，管理服务生命周期和手动搜索 |

### 浏览器 + 代理架构（关键设计）

```
UC Chrome (无代理启动)          ← 仅提供反指纹检测
    └─ Playwright CDP 连接
         ├─ Context A (proxy: http://127.0.0.1:11119)  ← 搜索 1
         ├─ Context B (proxy: http://127.0.0.1:11111)  ← 搜索 2（换代理）
         └─ Context C (proxy: http://127.0.0.1:11119)  ← 搜索 3
```

**设计要点：**
- UC Chrome 启动时**不设置** `--proxy-server`（避免 DoH/背景网络干扰）
- 代理在**每次搜索的 BrowserContext 级别**设置
- 代理切换无需重启浏览器（~0ms vs ~2s）
- Cookie 通过文件持久化（`google_cookies.json`），CAPTCHA 绕过状态跨 context 共享

---

## 2. 代理管理设计

### 2.1 固定代理列表

放弃了旧的基于 MongoDB 的动态代理池方案，改用固定代理列表：

```python
DEFAULT_PROXIES = [
    {"url": "http://127.0.0.1:11111", "name": "proxy-11111"},
    {"url": "http://127.0.0.1:11119", "name": "proxy-11119"},
]
```

**设计理由：**
- WARP SOCKS5 代理 (11000) 已被 Google 严格风控，不再可用
- 两个 HTTP 代理地位平等，无主备之分
- 固定代理更可控、更稳定，避免免费代理的不可靠性

### 2.2 负载均衡策略

采用 **round-robin 轮换 + 健康感知** 的策略：

```python
def get_proxy(self) -> Optional[str]:
    # 1. 在健康代理中 round-robin 轮换
    healthy = [p for p in self._proxies if p.healthy]
    if healthy:
        idx = self._round_robin_index % len(healthy)
        self._round_robin_index += 1
        return healthy[idx].url

    # 2. 降级：所有代理都不健康，选失败次数最少的
    all_sorted = sorted(self._proxies, key=lambda p: p.consecutive_failures)
    return all_sorted[0].url if all_sorted else None
```

### 2.3 健康检查机制

- **定期检查**：每 30 秒对所有代理执行健康检查
- **加速恢复**：有代理不健康时，缩短检查间隔到 15 秒
- **使用反馈**：搜索成功/失败实时更新代理状态
- **阈值控制**：连续失败 3 次后标记为不健康
- **自动恢复**：不健康代理通过健康检查恢复后自动重新参与轮换

### 2.4 ProxyState 数据模型

```python
@dataclass
class ProxyState:
    url: str              # 代理 URL
    name: str             # 名称标识
    healthy: bool         # 是否健康
    latency_ms: int       # 最近一次检查延迟
    consecutive_failures: int   # 连续失败次数
    consecutive_successes: int  # 连续成功次数
    total_successes: int  # 累计成功
    total_failures: int   # 累计失败
```

---

## 3. 搜索流程

```
用户请求 → Server → Scraper.search()
  ├─ ProxyManager.get_proxy() → 获取代理 URL
  ├─ 创建新 BrowserContext（设置 context-level 代理）
  ├─ 恢复持久化 Cookie（CAPTCHA bypass 状态）
  ├─ 导航到 Google 搜索页面
  ├─ 检测是否出现 CAPTCHA
  │   ├─ 是 → VLM 识别验证码，自动处理
  │   └─ 否 → 继续
  ├─ 获取页面 HTML
  ├─ GoogleResultParser 解析结果
  ├─ 保存 Cookie 到文件
  ├─ report_success() / report_failure()
  ├─ 关闭 Context（释放资源）
  └─ 返回 GoogleSearchResponse
```

### 重试与代理切换

搜索失败时的重试策略：
1. 失败（超时/CAPTCHA/无结果）→ `report_failure(proxy)`
2. 清除固定代理，从 ProxyManager 获取下一个代理
3. 创建新 Context（新代理），无需重启浏览器
4. 最多重试 2 次（共 3 次尝试）

### CAPTCHA 处理

scraper 内置 VLM (Vision Language Model) CAPTCHA 自动识别：
- 检测 reCAPTCHA / hCaptcha 等
- 通过 VLM API 分析验证码图片
- 自动点击验证选项

---

## 4. API 设计

### 4.1 FastAPI 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 服务健康检查 |
| GET/POST | `/search` | 执行 Google 搜索 |
| GET | `/proxy/status` | 获取所有代理健康状态 |
| GET | `/proxy/current` | 获取当前推荐代理 |
| POST | `/proxy/check` | 立即执行代理健康检查 |

### 4.2 搜索响应结构

```json
{
  "query": "搜索关键词",
  "results": [
    {
      "position": 1,
      "title": "结果标题",
      "url": "https://example.com",
      "displayed_url": "example.com",
      "snippet": "结果摘要..."
    }
  ],
  "total_results": 10,
  "has_captcha": false,
  "error": null
}
```

---

## 5. 文件结构

```
src/webu/google_api/
├── __init__.py          # 模块导出
├── __main__.py          # python -m webu.google_api 入口
├── cli.py               # ggsc CLI 工具 (525 行)
├── constants.py         # 配置常量 (47 行)
├── parser.py            # Google 结果解析器 (321 行)
├── proxy_manager.py     # 代理管理器 (415 行)
├── scraper.py           # 浏览器搜索引擎 (585 行)
└── server.py            # FastAPI 服务 (252 行)

tests/google_api/
├── test_cli.py          # CLI 单元测试
├── test_cli_e2e.py      # CLI E2E 测试
├── test_parser.py       # 解析器测试
├── test_proxy_manager.py# 代理管理器测试
├── test_scraper.py      # 搜索引擎测试
├── test_search.py       # 搜索集成测试
├── test_server.py       # API 服务测试
└── test_uc_cdp.py       # UC + CDP 连接测试
```
