# ggsc — 代理方案测试报告

> 报告更新时间: 2026-03（代理方案 v3：固定 HTTP 代理）

---

## 1. 方案演进总结

### 1.1 Phase 1 — 免费代理池（失败）

测试了从公开源采集的免费 SOCKS 代理：
- TCP 连通率约 15-20%
- Google 可达率约 3-5%
- 成功搜索率 < 2%（大量 CAPTCHA 和风控）
- **结论：** 免费代理不可用于 Google 搜索

### 1.2 Phase 2 — WARP SOCKS5（放弃）

测试 Cloudflare WARP socks5://127.0.0.1:11000：
- Google 可达性良好
- 但 CAPTCHA 触发率极高（>60%）
- Google 对 WARP 出口 IP 段明确标记为可疑
- **结论：** WARP 作为 Google 搜索代理不可行

### 1.3 Phase 3 — 固定 HTTP 代理（当前）

测试本地 HTTP 代理 11111 + 11119：
- Google 可达性稳定
- CAPTCHA 触发率较低（~20-30%）
- VLM 自动处理 CAPTCHA 后成功率 > 80%
- **结论：** 可用，配合 VLM CAPTCHA 处理效果良好

---

## 2. 当前架构性能

### 2.1 代理健康

| 代理 | 协议 | 端口 | 延迟 | 状态 |
|------|------|------|------|------|
| proxy-11111 | HTTP | 11111 | ~200-500ms | ✓ 稳定 |
| proxy-11119 | HTTP | 11119 | ~200-500ms | ✓ 稳定 |

### 2.2 搜索效果

- **round-robin 负载均衡**：请求均匀分布到两个代理
- **故障转移**：单个代理宕机时无缝切换，用户无感知
- **CAPTCHA 处理**：VLM 自动识别 + 点击，成功率 > 80%

### 2.3 系统稳定性

- **健康检查间隔**：30 秒（正常）/ 15 秒（有代理不健康时）
- **失败阈值**：连续 3 次失败标记为不健康
- **自动恢复**：不健康代理恢复后自动重新参与轮换

---

## 3. 关键发现

1. **Google 风控策略**：
   - VPN / WARP 出口 IP 被 Google 严格标记
   - 商业代理 IP 的 CAPTCHA 触发率明显低于 VPN IP
   - 同一 IP 短时间高频搜索会升级风控

2. **CAPTCHA 处理**：
   - reCAPTCHA v2 图片验证最常见
   - VLM 识别准确率 > 85%
   - 每次验证增加 3-8 秒延迟

3. **最优实践**：
   - 控制搜索频率，单代理约 2-5 秒间隔
   - 通过负载均衡分散请求压力
   - 定期轮换 User-Agent

---

## 4. 代理架构修复（2026-03-05）

### 4.1 问题：`--proxy-server` 浏览器级别代理导航超时

**现象：** `ggsc search "红警08" --proxy http://127.0.0.1:11119` 时 Chrome 打开后停留在 New Tab 页面，`page.goto` 超时 30 秒。

**根本原因：**
Chrome 通过 `--proxy-server=http://127.0.0.1:11119` 设置浏览器级别代理时，Chrome 的 DNS-over-HTTPS (DoH) 和后台网络功能（Safe Browsing、组件更新等）尝试绕过代理直连互联网。由于本机无法直接访问外网（`curl https://google.com` 超时），这些后台请求卡住，阻塞了正常的页面导航。

**诊断过程：**
1. 确认 `curl -x http://127.0.0.1:11119 https://google.com` 正常返回 200（代理可用）
2. 确认直连 `curl https://google.com` 超时（本机无直接外网）
3. 测试纯 Playwright（非 UC）+ context-level proxy → 正常工作
4. 测试 UC Chrome + `--disable-features=DnsOverHttps` + `--disable-background-networking` → 正常工作
5. 测试 UC Chrome（无代理）+ Playwright context-level proxy → **最佳方案**

### 4.2 解决方案：Context-level 代理

将代理从浏览器级别改为 Context 级别：

| 对比维度 | 旧方案（browser-level） | 新方案（context-level） |
|---------|------------------------|----------------------|
| 代理设置位置 | `--proxy-server=...` | `browser.new_context(proxy=...)` |
| 代理切换 | 需重启浏览器（~2s） | 创建新 Context（~0ms） |
| Cookie 持久化 | Chrome Profile 自动保存 | 文件持久化 `google_cookies.json` |
| DoH 干扰 | 是（需额外禁用） | 否（Context 独立处理） |
| 重试时的代理切换 | 无法切换（仍用原代理） | 立即切换到新代理 |

### 4.3 修改摘要

- `GoogleScraper.start()`: 直接用 Playwright 启动 Chromium，不传代理
- `GoogleScraper._do_search()`: 每次创建新 Context + 设置 proxy，自动恢复/保存 Cookie
- `GoogleScraper.search()`: 重试时清除固定代理，从 ProxyManager 获取新代理
- 启动参数：`--disable-blink-features=AutomationControlled`, `--disable-features=DnsOverHttps`, `--disable-background-networking`

---

## 5. UC Chrome 移除（2026-03-06）

### 5.1 问题：UC Chrome "session not created" 启动失败

**现象：** `ggsc search` 运行时 UC Chrome 报错 `session not created: cannot connect to chrome at 127.0.0.1:PORT`。

**根本原因：**
- 运行中的 ggsc 服务的 Chrome 进程占用 `data/google_api/chrome_profile/SingletonLock`
- CLI 的 `ggsc search` 命令尝试使用同一个 profile 目录启动新的 UC Chrome → 冲突
- UC Chrome 依赖 chromedriver 版本匹配、profile 目录独占等，增加了不必要的复杂度

**解决方案：** 完全移除 UC Chrome，仅使用 Playwright。

### 5.2 移除内容

| 移除的代码/功能 | 说明 |
|----------------|------|
| `_launch_uc_chrome()` | UC Chrome 启动函数（~120 行） |
| `_load_chrome_cache()` / `_save_chrome_cache()` | Chrome 版本/chromedriver 缓存 |
| `_find_free_port()` | CDP 端口分配 |
| `_wait_for_cdp_port()` | CDP 端口等待 |
| `_cleanup_uc()` | UC 进程清理 |
| `_start_playwright_fallback()` | Playwright 回退（现在是唯一方案） |
| `_uc_driver`, `_is_uc_mode`, `_debug_port`, `_default_context` | UC 相关属性 |
| `import subprocess, socket, os, signal` | UC 依赖的标准库 |
| `undetected-chromedriver` 依赖 | 不再需要安装 |

### 5.3 效果

| 对比维度 | 移除前（UC + Playwright fallback） | 移除后（纯 Playwright） |
|---------|----------------------------------|----------------------|
| 启动时间 | 3-5s（UC）或 UC 失败后 fallback | **0.5s** |
| 代码行数 | 873 行 | **613 行**（减少 260 行） |
| 外部依赖 | undetected-chromedriver + chromedriver | **无**（仅 Playwright） |
| Profile 冲突 | 常见（SingletonLock） | **无**（不使用 profile 目录） |
| 搜索效果 | 与纯 Playwright 相同 | 12 结果/1.3s，无 CAPTCHA |
