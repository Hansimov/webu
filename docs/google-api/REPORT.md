# ggsc — 代理池测试报告

> 报告生成时间: 2026-03-01 (Updated: Level-2 HTTP 重写后)

---

## 1. 采集总览

- 本次采集: **12284** 个代理 (from 8 sources)
- 新增: **3295**
- 更新: **8739**
- 数据库总量: **14261**

### 1.1 协议分布

| 协议 | 数量 | 占比 |
|------|------|------|
| http | ~5500 | ~38.6% |
| socks4 | ~3300 | ~23.1% |
| socks5 | ~2700 | ~18.9% |
| https | ~800 | ~5.6% |

### 1.2 来源分布

| 来源 | 总数 | 协议构成 |
|------|------|---------|
| thespeedx | 7356 | http, socks4, socks5 |
| sunny9577 | ~1700 | http, socks5 |
| proxyscrape | ~1900 | http, socks4 |
| zloi-user | 863 | https, socks4, socks5 |
| proxifly | 868 | http, socks4, socks5 |
| monosans | 63 | http, socks4, socks5 |
| hookzof | 23 | socks5 |
| roosterkid | 8 | socks5 |

## 2. Level-1 快速检测（aiohttp）

- 检测总数: **13196**
- 通过: **174** (含新采集批次)
- 失败: **13022**
- 通过率: **1.3%**

### 2.1 失败原因分析

| 原因 | 描述 |
|------|------|
| timeout | 大部分代理已过期或不可达 |
| connection_error | 连接被重置或拒绝 |
| other | 各种网络错误 |

> 注: Level-1 通过率较低是正常现象, 免费代理列表中大量 IP 已失效。

## 3. Level-2 搜索检测（aiohttp HTTP 请求）—— 已证实对 SOCKS 代理无效

> **结论 (2026-03-04)**: Level-2 HTTP 检测对当前免费 SOCKS 代理池 **0% 通过率**，无效。

### 3.1 实测数据（SOCKS 专项批次）

| 批次 | 代理数 | 协议 | L2 通过 | 通过率 |
|------|--------|------|---------|--------|
| 2026-03-04 | 200 | socks4/socks5 | **0** | **0.0%** |

### 3.2 L2 失败原因分布

| 原因 | 数量 | 说明 |
|------|------|------|
| timeout | 141 | SOCKS 代理慢 + Google 主动切断 |
| other (连接错误) | 48 | ServerDisconnectedError、连接拒绝 |
| CAPTCHA | 11 | Google 检测到异常流量（HTTP 层） |

### 3.3 根本原因分析

Level-2 使用 `aiohttp` raw HTTP 请求 `https://www.google.com/search?q=test`：
- **Google 对非浏览器 HTTP 流量做了 IP 层封锁**，SOCKS 代理 IP 直接被识别并断开连接
- `ServerDisconnectedError` 说明 Google 在 TLS 握手后主动关闭连接
- 超时比例高（71%）说明即使没有主动拒绝，响应也极慢
- `_MIN_SEARCH_RESPONSE_SIZE = 30000` 阈值在连接就被断开的情况下根本无法到达

> 历史记录：早期测试（2026-03-01）包含 HTTP 代理时，整体通过率为 5.5%（59/1064），其中 HTTP 协议代理通过数最多（36）。SOCKS 代理在 L2 的实际通过率从未有效。
| 47.92.82.167 | 3129 | socks4 | 4253ms |
| 47.121.129.129 | 80 | socks4 | 4269ms |
| 8.210.17.35 | 3128 | socks4 | 4380ms |
| 106.14.91.83 | 8080 | http | 5060ms |
| ... | ... | ... | ... |

### 3.3 失败原因分析

| 原因 | 数量 | 占比 |
|------|------|------|
| timeout | 345 | 34.3% |
| connection reset | 286 | 28.5% |
| Playwright legacy errors | ~250 | ~24.9% |
| CAPTCHA/sorry | 5 | 0.5% |
| other | ~119 | ~11.8% |

> 注: "Playwright legacy errors" 来自旧的 Playwright Level-2 实现, 已被替换。

### 3.4 检测方法说明

Level-2 HTTP 检测流程:
1. 通过代理发送 HTTP GET 请求到 `https://www.google.com/search?q=test&num=5&hl=en`
2. 使用标准浏览器 UA 和请求头
3. 判定标准:
   - HTTP 200 响应
   - 响应大小 > 30KB (正常搜索页面约 86KB)
   - 无 CAPTCHA / sorry 重定向标记
4. 正常 Google 搜索页面返回 ~86KB 的 JS 应用, CAPTCHA/sorry 页面 < 10KB

## 4. 浏览器方案（UC + Playwright）对 SOCKS 代理搜索测试

由于 L2 HTTP 检测完全失效，改用 UC+Playwright 直接测试 L1 通过的 SOCKS 代理能否执行真实 Google 搜索。

### 4.1 实测结果（2026-03-04, 15 个 SOCKS 代理）

| 指标 | 结果 |
|------|------|
| 总测试数 | 15 |
| **成功数** | **0 (0%)** |
| CAPTCHA（无限循环） | 3 |
| 超时（30s） | 4 |
| empty/network error | 5 |
| proxy_conn_failed | 1 |
| socks_failed | 2 |

### 4.2 失败模式分析

| 模式 | 协议 | 原因 |
|------|------|------|
| CAPTCHA 无限循环 | socks5 | Google 对此 IP 永久要求 CAPTCHA，VLM 解对了也继续出新挑战 |
| ERR_EMPTY_RESPONSE | socks4 | Playwright 与 socks4 兼容性差，全部返回空响应 |
| 超时 (30s) | socks5 | 代理速度过慢，无法在超时内完成 Google 页面加载 |
| ERR_NETWORK_CHANGED | socks5 | 代理不稳定，连接中途断开 |

### 4.3 CAPTCHA 绕过情况

VLM 解题器（Qwen3-VL）工作正常，能正确识别：火栓、人行横道、公共汽车等。
问题在于 **Google 的 IP 信誉系统**，对已知代理 IP 触发永久 CAPTCHA 循环：
- VLM 答对 → Google 继续出新题（无限循环）
- 切换代理后重试 → 同样 IP 信誉差

## 5. 诊断结论（2026-03-04 更新）

### 5.1 免费 SOCKS 代理对 Google 搜索的可用性

**结论：公开免费 SOCKS 代理池对 Google 搜索的实际可用率为 0%。**

失败原因层层递进：

| 层级 | 检测方式 | 通过率 | 原因 |
|------|----------|--------|------|
| L1 | aiohttp → Google generate_204 | ~9% | 大部分 IP 已过期 |
| L2 (HTTP) | aiohttp → Google Search | 0% (SOCKS) | Google IP 层封锁 |
| 浏览器测试 | UC+Playwright → Google Search | 0% | IP 信誉 + 无限 CAPTCHA |

### 5.2 根本原因

免费代理和公共 SOCKS 代理的 IP 地址早已被 Google 列入黑名单：
- **IP 层封锁**：Google 在 TCP/TLS 层断开已知代理 IP 的连接（raw HTTP 0%）
- **CAPTCHA 永久循环**：浏览器加反检测也无效，Google 对黑名单 IP 持续出新 CAPTCHA 题，无限循环
- **socks4 协议**：Playwright 对 socks4 支持差，全部返回 ERR_EMPTY_RESPONSE

### 5.3 管道架构调整

`run_proxy_search_test.py` 已更新：
- **移除** Level-2 HTTP 检测步骤（0% 通过率，无意义）
- 流程改为：采集 → L1 检测 → **直接** UC+Playwright 浏览器搜索
- 新增 `--socks5-only` 选项（socks4 对 Playwright 不兼容）

新增独立测试脚本 `run_socks_browser_test.py`：
- 直接从 DB 取 L1 通过的 SOCKS 代理，用浏览器测试 Google 搜索
- 包含详细错误分类（captcha/timeout/proxy_conn_failed/socks_failed/network_changed）

### 5.4 对未来代理策略的建议

1. **付费住宅代理**（Residential Proxy）IP 信誉远比数据中心 IP 好，成功率会显著提升
2. **自建出口节点**而非依赖公开代理列表——自有 VPS 的 IP 更干净
3. 公开 SOCKS 代理仅适合不被 Google 严格检测的场景（如 L1 连通性测试）
4. 定期刷新采集频率意义有限——问题在 IP 信誉而非 IP 数量

---

*报告更新时间: 2026-03-04 (SOCKS 代理 Google 搜索实测分析)*
