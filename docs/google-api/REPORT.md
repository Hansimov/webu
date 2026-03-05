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

- `_launch_uc_chrome()`: 移除 `--proxy-server`，添加 `--disable-features=DnsOverHttps`, `--disable-background-networking`, `--disable-component-update`
- `GoogleScraper.__init__()`: `proxy_url` 改存为 `_fixed_proxy`，新增 Cookie 文件路径
- `GoogleScraper.start()`: 启动 UC Chrome 不传代理
- `GoogleScraper._do_search()`: 每次创建新 Context + 设置 proxy，自动恢复/保存 Cookie
- `GoogleScraper.search()`: 重试时清除固定代理，从 ProxyManager 获取新代理
