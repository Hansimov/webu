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

---

## 6. 后续 Bug 修复与优化（2026-03 后）

> 报告更新时间: 2026-03（代理方案 v3 稳定后的持续改进）

### 6.1 重试时意外回退直连（`original_proxy` 修复）

**现象：** 没有 `ProxyManager`（使用 `--proxy` 参数固定代理）时，搜索失败重试会 `requested_proxy = None`，导致下一次尝试直连 Google（无代理）→ 连接超时。

**根本原因：** 原重试逻辑无条件清除 `requested_proxy`，未区分"有 ProxyManager 需要换代理"和"固定代理模式"。

**修复：** 引入 `original_proxy` 记录首次代理；只有在 `proxy_manager` 存在时才清除 `requested_proxy` 允许轮换，否则保持原代理重试。

---

### 6.2 EU 代理触发 Google Cookie 同意弹窗

**现象：** 代理 11119 路由出口在 EU，Google 弹出 "Before you continue to Google" GDPR 同意框，遮挡搜索结果，导致解析返回 0 结果。

**诊断过程：**
1. 观察到特定代理（11119）稳定出现 0 结果，另一代理（11111）正常
2. 保存 debug HTML，发现页面为同意弹窗而非搜索结果
3. `parser.detect_consent()` 检测 "before you continue" 文本确认

**解决方案：** `_dismiss_consent()` 方法：
- 检测同意弹窗（HTML 文本判断）
- 通过多语言按钮文本点击 "Reject all"
- Cookie 持久化后，后续请求自动跳过弹窗

**效果：** EU 代理恢复正常搜索，结果数与非 EU 代理一致。

---

### 6.3 「无结果」页面导航超时 9.5s → 1.2s

**现象：** `site:bilibili.com uupers` 等 Google 无匹配查询，每次搜索耗时约 9.5 秒。

**根本原因：** 「无结果」页面中 `#search` DOM 存在但为空，`wait_for_selector` 必须等待完整的 8s 超时。

**关键技术发现：**
- `page.locator('text=did not match any documents')` **不可靠**：Google 的提示文字横跨多个嵌套 DOM 节点，单个节点不包含完整文本
- `page.evaluate("document.body.innerText.includes('...)')` **有效**：`innerText` 递归合并子节点文本，能检测跨节点文本

**解决方案：** 在等待 `#search` 选择器之前先执行 JS 检查：

```python
no_results = await page.evaluate(
    "document.body.innerText.includes('did not match any documents')"
)
if no_results:
    return early  # 立即返回，不等 8s
```

**效果：** 无结果页耗时 9.5s → **1.2s**（减少 87%）。

---

### 6.4 CAPTCHA 图片截图偏移导致 VLM 识别失败

**现象：** VLM 网格标注（GridAnnotator）的 `grid_top` 偏移量约偏差 100px，导致点击位置错误，CAPTCHA 解题失败率偏高。

**根本原因：** 截图为完整 challenge frame（bframe），高度约 480px，宽度约 300px。GridAnnotator 用 `grid_top = h - w = 480 - 300 = 180` 估算网格起始点，实际网格起点约在 280px，误差约 100px。

**解决方案：** `_capture_challenge_image()` 优先截取 grid TABLE 元素（`.rc-imageselect-table-44` / `.rc-imageselect-table-33`），使截图仅包含图片网格，`grid_top ≈ 0`：

```python
table = challenge_frame.locator('.rc-imageselect-table-44, .rc-imageselect-table-33')
if await table.count() > 0:
    return await table.screenshot()
# fallback: 截取完整 challenge frame
```

**效果：** GridAnnotator 坐标精度显著提升，CAPTCHA 点击准确率提高。

---

### 6.5 解析器 Snippet 噪音文本

**现象：** 部分搜索结果的摘要（snippet）包含标题文字重复、"Translate this page"、日期前缀、引用链接文本等噪音，影响下游处理质量。

**修复：**
- `_clean_snippet(text)`：regex 去除各类噪音模式
- `_clean_video_title(text)`：去除 YouTube metadata 后缀（频道名、时间等），提取纯视频标题
- `_extract_snippet()` 的所有 3 条提取路径均调用 `_clean_snippet()`

---

### 6.6 日志格式统一优化

#### 搜索日志前缀

旧格式（所有尝试均带计数）：
```
> Search [1/3]: "python编程" via proxy-11111
> Search [2/3]: "python编程" via proxy-11119
```

新格式（首次无计数，重试才显示）：
```
> Search: "python编程" via proxy-11111
> [2/3] Search: "python编程" via proxy-11119
```

**理由：** 绝大多数搜索一次成功，`[1/3]` 计数对用户是噪音。

#### URL/路径着色

CLI、scraper、bypass、solver 中的 URL 和文件路径统一通过 `logstr.file()` 输出，在终端中以不同颜色区分，提升日志可读性。
