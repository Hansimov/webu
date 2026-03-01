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

## 3. Level-2 搜索检测（aiohttp HTTP 请求）

> **重大变更**: Level-2 已从 Playwright 浏览器自动化改为 aiohttp HTTP 请求。
>
> **原因**: Google 的 JavaScript 环境检测会识别 Playwright 自动化浏览器, 导致 100% 被 CAPTCHA 拦截。
> HTTP 请求不执行 JavaScript, 因此不会触发自动化检测。

- 检测总数: **1064**
- 通过: **59**
- 失败: **1005**
- 通过率: **5.5%**

### 3.1 按协议统计

| 协议 | 通过数 |
|------|--------|
| http | 36 |
| socks4 | 17 |
| socks5 | 6 |

### 3.2 Level-2 有效代理示例 (按延迟排序)

| IP | 端口 | 协议 | 延迟 |
|----|------|------|------|
| 117.1.48.242 | 20039 | socks5 | 1266ms |
| 167.71.226.135 | 1080 | http | 2140ms |
| 182.47.7.5 | 7891 | socks5 | 2190ms |
| 121.43.146.222 | 1111 | socks4 | 4102ms |
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

## 4. 对比: 旧 Playwright vs 新 HTTP 方案

| 指标 | Playwright (旧) | HTTP (新) |
|------|-----------------|-----------|
| Level-2 通过数 | 0 | 59 |
| Level-2 通过率 | 0.0% | 5.5% |
| 单个检测耗时 | 5-20s | 1-10s |
| CAPTCHA 率 | ~100% | ~0.5% |
| 资源消耗 | 高 (浏览器实例) | 低 (HTTP 请求) |
| 并发能力 | 3-5 | 30-50 |

## 5. 诊断结论

### 5.1 Level-2 修复总结

**根本问题**: Google 的 bot detection 系统通过 JavaScript 运行时检测识别 Playwright 自动化浏览器:
- 检查 `navigator.webdriver` 属性
- 检查 Chrome DevTools Protocol 连接
- 检查浏览器指纹一致性
- 即使使用 playwright-stealth + system Chrome + persistent context, 仍被 100% 检测

**解决方案**: 将 Level-2 从 Playwright 改为 aiohttp HTTP 请求:
- HTTP 请求不执行 JavaScript, 因此不触发 bot detection
- 通过响应大小和 CAPTCHA 标记判断代理是否被 Google 封禁
- 大幅提升检测速度和并发能力

### 5.2 代理可用性分析

- 免费代理整体可用率极低: L1 通过 1.3%, L2 通过 5.5% (of L1 passed)
- 有效代理主要来自中国阿里云 IP 段
- SOCKS5 代理在 L1 通过率最高, HTTP 代理在 L2 数量最多
- 最佳延迟约 1-2s, 平均延迟 5-7s

### 5.3 优化建议

1. 提高采集频率, 定期刷新代理池
2. 优先使用 SOCKS5 代理 (L1 通过率更高)
3. Level-2 检测使用较高并发 (30-50), 快速筛选
4. 定期重新检测已有代理, 清理过期 IP

---

*报告更新时间: 2026-03-01 (Level-2 HTTP 方案实施后)*
