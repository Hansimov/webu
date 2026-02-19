# Gemini 模块 - 安装指南

本指南涵盖 Gemini 模块的完整安装，包括用于远程浏览器访问的 noVNC。

## 系统要求

- **操作系统**：Linux（推荐 Ubuntu 22.04+）
- **Python**：3.11+
- **Chrome/Chromium**：系统安装的 Google Chrome
- **Xvnc**：TigerVNC 服务器（用于带 VNC 访问的虚拟显示器）
- **网络**：访问 Google 服务的 HTTP 代理（如果在防火墙后面）

## 1. 安装系统包

### Chrome

```bash
# 安装 Google Chrome
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb
sudo apt-get install -f  # 修复缺失的依赖
```

### TigerVNC（用于 Xvnc 虚拟显示器）

```bash
sudo apt install tigervnc-standalone-server tigervnc-common tigervnc-tools
```

### Xvfb（备用虚拟显示器，无 VNC）

```bash
sudo apt install xvfb
```

## 2. 安装 Python 依赖

### 核心依赖

```bash
pip install -e .
```

这会安装 `pyproject.toml` 中定义的包：
- `playwright` — 通过 CDP 的浏览器自动化
- `pyvirtualdisplay` — 虚拟显示器管理（Xvfb/Xvnc）
- `fastapi`、`uvicorn` — REST API 层
- `beautifulsoup4` — HTML 解析
- `tclogger` — 日志

### Playwright 浏览器（可选）

```bash
# 仅在使用 Playwright 内置 Chromium 时需要（不推荐）
# 我们使用系统 Chrome
playwright install chromium
```

### noVNC 依赖

```bash
# websockify：桥接 WebSocket ↔ VNC TCP，实现基于 Web 的 VNC 访问
pip install websockify

# noVNC：基于 Web 的 VNC 查看器（静态 HTML/JS 文件）
git clone --depth=1 https://github.com/novnc/noVNC.git /tmp/noVNC
cp -r /tmp/noVNC/* data/novnc/
```

`data/novnc/` 目录应包含 `vnc.html` 和 noVNC JavaScript 文件。

## 3. 配置

### 创建配置文件

```bash
mkdir -p configs
cat > configs/gemini.json << 'EOF'
{
  "proxy": "http://127.0.0.1:11119",
  "browser_port": 30001,
  "api_port": 30002,
  "vnc_port": 30003,
  "novnc_port": 30004,
  "user_data_dir": "./data/chrome/gemini",
  "chrome_executable": "/usr/bin/google-chrome",
  "headless": false,
  "page_load_timeout": 60000,
  "response_timeout": 120000,
  "image_generation_timeout": 180000,
  "verbose": false
}
EOF
```

### 配置选项

| 选项 | 默认值 | 描述 |
|--------|---------|-------------|
| `proxy` | `http://127.0.0.1:11119` | 访问 Google 的 HTTP 代理 |
| `browser_port` | `30001` | Chrome DevTools CDP 代理端口 (0.0.0.0) |
| `api_port` | `30002` | FastAPI REST API 端口 |
| `vnc_port` | `30003` | Xvnc 原始 VNC 端口 |
| `novnc_port` | `30004` | noVNC Web 查看器端口 (websockify) |
| `user_data_dir` | `./data/chrome/gemini` | Chrome 配置文件目录 |
| `chrome_executable` | `/usr/bin/google-chrome` | Chrome 二进制文件路径 |
| `headless` | `false` | 以无头模式运行 Chrome（禁用 VNC） |

### 端口布局

```
端口 30001 — CDP TCP 代理 (0.0.0.0) ←→ Chrome DevTools (127.0.0.1:30011)
端口 30002 — FastAPI REST API
端口 30003 — Xvnc 原始 VNC (0.0.0.0)
端口 30004 — noVNC WebSocket + Web 查看器 (websockify)
```

## 4. 架构

```
┌─────────────────── 远程服务器 ───────────────────────┐
│                                                     │
│  Xvnc（虚拟显示器 + VNC 服务器）    :30003           │
│    └── Chrome（子进程）                              │
│          ├── CDP 调试端口  127.0.0.1:30011           │
│          └── 通过 HTTP 代理  127.0.0.1:11119         │
│                                                     │
│  TCP 代理（Host 重写 + URL 重写）    :30001           │
│    └── 转发到 Chrome CDP :30011                      │
│                                                     │
│  websockify（WebSocket ↔ VNC 桥接） :30004           │
│    ├── 提供 noVNC Web 查看器                         │
│    └── 桥接到 Xvnc VNC :30003                       │
│                                                     │
│  Playwright（异步 API，通过 CDP）                     │
│    └── 本地连接 Chrome :30011                        │
│                                                     │
│  FastAPI REST API                    :30002          │
│    └── 使用 Playwright 进行自动化                     │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 为什么需要 TCP 代理？

Chrome 的 `--remote-debugging-port` 始终绑定到 `127.0.0.1`，忽略 `--remote-debugging-address`。TCP 代理：
1. 在 `0.0.0.0:30001` 监听以支持远程访问
2. 将 `Host` 头重写为 `127.0.0.1:30011`（Chrome 拒绝非 IP Host 头）
3. 重写响应中的内部 URL（`127.0.0.1:30011` → `主机名:30001`）
4. 重写后如果响应体大小变化则更新 `Content-Length`

### 为什么使用 Xvnc 而非 Xvfb？

Xvnc 同时提供虚拟 X 显示器和内置 VNC 服务器。结合 websockify + noVNC，用户可以通过 Web 浏览器查看和操作浏览器——这对远程 Google 登录至关重要。

## 5. 使用方法

### 启动浏览器进行交互式登录

```bash
# 从项目根目录
python -m tests.gemini.launch_browser
```

这会启动带 noVNC 的 Chrome。在浏览器中打开显示的 URL：
```
http://<主机名>:30004/vnc.html?autoconnect=true&resize=remote
```

导航到 `gemini.google.com` 并登录你的 Google 账号。登录会话保存在 Chrome 配置文件中（`data/chrome/gemini/`）。

按 `Ctrl+C` 停止。

### 运行自动化测试

```bash
# 单元测试（不需要浏览器）
python -m pytest tests/gemini/test_gemini.py tests/gemini/test_tcp_proxy.py -m "not integration" -q

# CDP + 代理集成测试
python tests/gemini/test_cdp.py

# 完整交互式测试（需要登录）
python -m tests.gemini.test_interactive
```

### 使用 Python API

```python
import asyncio
from webu.gemini import GeminiClient

async def main():
    async with GeminiClient() as client:
        response = await client.send_message("Hello, Gemini!")
        print(response.text)

asyncio.run(main())
```

### 使用 REST API

```bash
# 启动 API 服务器
python -m webu.gemini.api

# 发送消息
curl -X POST http://localhost:30002/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, Gemini!"}'
```

## 6. 故障排除

### "Host header is specified and is not an IP address or localhost"

从远程机器访问 Chrome DevTools 时会出现此错误。TCP 代理（端口 30001）通过重写 Host 头来处理此问题。确保通过代理端口访问，而非内部 Chrome 端口（30011）。

### Chrome 渲染器崩溃（net::ERR_ABORTED）

Chrome 启动参数中添加 `--disable-extensions` 和 `--disable-background-networking`。用户配置文件中的扩展可能会干扰导航。这些参数已包含在默认配置中。

### noVNC 显示空白屏幕

1. 验证 Xvnc 正在运行：`ss -tlnp | grep 30003`
2. 验证 websockify 正在运行：`ss -tlnp | grep 30004`
3. 检查 Chrome 已启动：`ss -tlnp | grep 30011`

### 无法访问 Google/Gemini 页面

确保 HTTP 代理正在运行且可访问：
```bash
curl -x http://127.0.0.1:11119 -s -o /dev/null -w "%{http_code}\n" https://www.google.com
```

### Chrome 用户配置文件损坏导致无法访问 google.com

**症状**：浏览器可以启动，但无法通过代理访问 google.com（页面加载失败或超时），即使代理本身正常工作（curl 测试成功）。

**原因**：Chrome 用户数据目录（`data/chrome/gemini/`）中的缓存、扩展或组件数据可能损坏，干扰了网络连接。Chrome 后台组件更新和扩展自动加载也会导致代理连接不稳定。

**解决方案**：

1. **重置 Chrome 配置文件**：删除用户数据目录，让 Chrome 使用全新配置：
   ```bash
   rm -rf data/chrome/gemini/
   ```
   注意：这会清除已保存的登录会话，需要重新登录 Google 账号。

2. **确保 Chrome 启动参数正确**：`browser.py` 中已添加以下关键启动参数来防止此问题：
   ```python
   '--disable-extensions',            # 禁用扩展，防止干扰
   '--disable-background-networking', # 禁用后台网络请求
   '--disable-default-apps',          # 禁用默认应用
   '--disable-component-update',      # 禁用组件更新
   '--disable-client-side-phishing-detection',  # 禁用钓鱼检测
   ```

3. **浏览器启动时自动清理缓存**：`GeminiBrowser.start()` 方法在启动时会自动调用 `_clear_browser_cache()` 清理可能导致问题的缓存目录，包括：
   - `ShaderCache/`、`GrShaderCache/`、`GraphiteDawnCache/` — GPU 缓存
   - `component_crx_cache/`、`extensions_crx_cache/` — 组件和扩展缓存
   - `Safe Browsing/` — 安全浏览数据

4. **手动清理特定缓存**：如果不想重置整个配置文件，可以只删除缓存目录：
   ```bash
   cd data/chrome/gemini/
   rm -rf ShaderCache GrShaderCache GraphiteDawnCache
   rm -rf component_crx_cache extensions_crx_cache
   rm -rf "Safe Browsing"
   ```

### VNC 密码提示

Xvnc 配置为 `-SecurityTypes None`（无密码）。如果出现提示，可能需要重启 VNC 服务器。

### Xvnc 不可用（回退到 Xvfb）

如果未安装 TigerVNC，浏览器会回退到 Xvfb。远程可视化访问将不可用，但自动化仍然有效。安装 TigerVNC：
```bash
sudo apt install tigervnc-standalone-server
```
