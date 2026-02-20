# Gemini 模块 — 安装与配置指南

## 系统要求

| 组件 | 要求 |
|---|---|
| 操作系统 | Linux（推荐 Ubuntu 22.04+） |
| Python | 3.11+ |
| Chrome | 系统安装的 Google Chrome（非 Chromium 优先） |
| TigerVNC | Xvnc 虚拟显示器 + 内置 VNC 服务器 |
| 网络 | HTTP 代理（如需翻墙访问 Google 服务） |

## 1. 安装系统包

### Chrome

```bash
# 安装 Google Chrome
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb
sudo apt-get install -f  # 修复缺失依赖

# 验证安装
google-chrome --version
```

### TigerVNC（Xvnc 虚拟显示器）

```bash
sudo apt install tigervnc-standalone-server tigervnc-common tigervnc-tools
```

> **为什么选择 Xvnc 而非 Xvfb？**
> Xvnc 同时提供虚拟 X 显示器和内置 VNC 服务器。结合 websockify + noVNC，用户可通过 Web 浏览器远程查看和操作 Chrome——这对远程 Google 登录至关重要。

### Xvfb（备用，无 VNC 可视化）

```bash
# 如果不需要远程可视化，可只安装 Xvfb
sudo apt install xvfb
```

## 2. 安装 Python 依赖

### 核心依赖

```bash
pip install -e .
```

这会安装 `pyproject.toml` 中定义的所有依赖：
- `playwright` — 浏览器自动化（通过 CDP 连接 Chrome）
- `pyvirtualdisplay` — 虚拟显示器管理（Xvfb/Xvnc）
- `fastapi` + `uvicorn` — REST API 层
- `beautifulsoup4` — HTML 响应解析
- `requests` — HTTP 客户端
- `tclogger` — 彩色日志

### Playwright 浏览器

```bash
# 通常不需要 Playwright 内置 Chromium，我们直接使用系统 Chrome
# 但如果系统没有 Chrome，可以安装：
playwright install chromium
```

### noVNC 依赖

```bash
# websockify：WebSocket ↔ VNC TCP 桥接
pip install websockify

# noVNC：基于 Web 的 VNC 查看器（静态 HTML/JS）
git clone --depth=1 https://github.com/novnc/noVNC.git /tmp/noVNC
cp -r /tmp/noVNC/* data/novnc/
```

确保 `data/novnc/` 目录包含 `vnc.html` 和 noVNC JavaScript 文件。

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

> **安全提示**：`configs/gemini.json` 已被 gitignore，以保护代理地址等敏感信息。

### 配置选项

| 选项 | 类型 | 默认值 | 描述 |
|---|---|---|---|
| `proxy` | string | `http://127.0.0.1:11119` | 访问 Google 的 HTTP 代理 |
| `browser_port` | int | `30001` | Chrome DevTools CDP 代理端口 |
| `api_port` | int | `30002` | FastAPI REST API 端口 |
| `vnc_port` | int | `30003` | Xvnc 原始 VNC 端口 |
| `novnc_port` | int | `30004` | noVNC Web 查看器端口 |
| `user_data_dir` | string | `./data/chrome/gemini` | Chrome 用户数据目录（持久化登录） |
| `chrome_executable` | string | `/usr/bin/google-chrome` | Chrome 可执行文件路径 |
| `headless` | bool | `false` | 无头模式运行（禁用 VNC 可视化） |
| `page_load_timeout` | int | `60000` | 页面加载超时（毫秒） |
| `response_timeout` | int | `120000` | 聊天响应等待超时（毫秒） |
| `image_generation_timeout` | int | `180000` | 图片生成超时（毫秒） |
| `verbose` | bool | `false` | 启用详细日志 |

### 配置优先级

```
默认配置 (constants.py) → 配置文件 (JSON) → 运行时传入 (dict)
```

后者覆盖前者，允许灵活地按需覆盖。

## 4. 架构与端口布局

```
┌──────────────────── 远程服务器 ────────────────────────┐
│                                                       │
│  Xvnc（虚拟显示器 + VNC 服务器）           :30003      │
│    └── Chrome（子进程）                                │
│          ├── CDP 调试端口   127.0.0.1:30011            │
│          └── 通过 HTTP 代理  127.0.0.1:11119           │
│                                                       │
│  TCP 代理（Host 重写 + URL 重写）          :30001      │
│    └── 转发到 Chrome CDP :30011                        │
│                                                       │
│  websockify（WebSocket ↔ VNC 桥接）        :30004      │
│    ├── 提供 noVNC Web 查看器                           │
│    └── 桥接到 Xvnc VNC :30003                         │
│                                                       │
│  Playwright（异步 API，通过 CDP）                       │
│    └── 本地连接 Chrome :30011                          │
│                                                       │
│  FastAPI REST API                          :30002      │
│    └── 使用 Playwright 进行自动化                       │
│                                                       │
└───────────────────────────────────────────────────────┘
```

### 端口一览

| 端口 | 组件 | 绑定地址 | 用途 |
|---|---|---|---|
| 30001 | TCP 代理 | 0.0.0.0 | Chrome DevTools 远程访问 |
| 30002 | FastAPI | 0.0.0.0 | REST API + Swagger UI |
| 30003 | Xvnc | 0.0.0.0 | VNC 原始协议 |
| 30004 | websockify | 0.0.0.0 | noVNC Web 查看器 |
| 30011 | Chrome | 127.0.0.1 | CDP 内部端口（外部不可直连） |

### 为什么需要 TCP 代理？

Chrome 的 `--remote-debugging-port` 始终绑定到 `127.0.0.1`（忽略 `--remote-debugging-address`），且拒绝 `Host` 头不是 IP 地址或 `localhost` 的请求。TCP 代理解决两个问题：
1. 在 `0.0.0.0:30001` 监听以支持远程访问
2. 将请求的 `Host` 头重写为 `127.0.0.1:30011`
3. 将响应中的内部地址（`127.0.0.1:30011`）重写为 `{主机名}:30001`
4. 地址重写导致体积变化时更新 `Content-Length` 头

## 5. 首次登录

首次使用时必须手动登录 Google 账号，登录状态会保存在 Chrome 用户数据目录中。

### 方式一：使用 launch_browser 脚本（推荐）

```bash
python -m tests.gemini.launch_browser
```

这会启动带 noVNC 的 Chrome。在浏览器中打开显示的 URL：

```
http://<主机名>:30004/vnc.html?autoconnect=true&resize=remote
```

在 VNC 查看器中导航到 `gemini.google.com` 并登录。按 `Ctrl+C` 停止。

### 方式二：使用 Runner 前台模式

```bash
python -m webu.gemini.run fg
```

这会启动完整的 Browser + API Server。通过 noVNC 登录后，可以直接开始使用 API。

### 登录持久化

登录后的 Cookie/localStorage 保存在 `data/chrome/gemini/` 中。后续重启无需重新登录。

> **注意**：如果登录过期或 Cookie 损坏，删除用户数据目录即可重置：
> ```bash
> rm -rf data/chrome/gemini/
> ```

## 6. 快速启动

### 后台运行（生产环境推荐）

```bash
# 启动
python -m webu.gemini.run start

# 查看状态
python -m webu.gemini.run status

# 追踪日志
python -m webu.gemini.run logs
python -m webu.gemini.run logs -n 100  # 查看最后 100 行

# 重启
python -m webu.gemini.run restart

# 停止
python -m webu.gemini.run stop
```

### 前台运行（调试用）

```bash
python -m webu.gemini.run fg
# Ctrl+C 停止
```

### 使用自定义配置

```bash
python -m webu.gemini.run start -c /path/to/my_config.json
```

### 启动后的访问地址

```
API Server:  http://<主机名>:30002
Swagger UI:  http://<主机名>:30002/docs
VNC Viewer:  http://<主机名>:30004/vnc.html?autoconnect=true&resize=remote
DevTools:    chrome://inspect → Configure → '<主机名>:30001'
JSON API:    http://<主机名>:30001/json
```

## 7. 故障排除

### Chrome 无法启动

- 检查 Chrome 是否安装：`which google-chrome`
- 检查配置中的 `chrome_executable` 路径是否正确
- SSH 环境需要虚拟显示器：确保 TigerVNC 或 Xvfb 已安装

### 无法登录 / 登录未检测到

- 通过 noVNC 查看浏览器实际状态
- 如果在同意页面，手动点击同意按钮
- 删除用户数据目录重新登录：`rm -rf data/chrome/gemini/`

### "Host header is specified and is not an IP address or localhost"

从远程访问 Chrome DevTools 时出现此错误。TCP 代理（端口 30001）通过重写 Host 头来处理。确保通过代理端口访问，而非内部 Chrome 端口（30011）。

### 无法通过代理访问 Google

```bash
# 验证代理是否工作
curl -x http://127.0.0.1:11119 -s -o /dev/null -w "%{http_code}\n" https://www.google.com
```

### Chrome 配置文件损坏导致无法访问 google.com

**症状**：Chrome 启动正常，但通过代理无法访问 Google（curl 测试成功）。

**原因**：Chrome 用户数据目录中的缓存、扩展或组件数据损坏。

**解决方案**：
1. **完全重置**：`rm -rf data/chrome/gemini/`（需重新登录）
2. **仅清理缓存**（保留登录状态）：
   ```bash
   cd data/chrome/gemini/
   rm -rf Default/Cache Default/"Code Cache" Default/"Service Worker"
   rm -rf Default/GPUCache GraphiteDawnCache GrShaderCache ShaderCache
   ```
3. 模块在每次启动时已自动调用 `_clear_browser_cache()` 清理关键缓存

### noVNC 显示空白

1. 验证 Xvnc 运行中：`ss -tlnp | grep 30003`
2. 验证 websockify 运行中：`ss -tlnp | grep 30004`
3. 验证 Chrome 启动：`ss -tlnp | grep 30011`

### 响应超时

- 增加配置中的 `response_timeout`（默认 120s）
- 图片生成默认 180s（`image_generation_timeout`）
- 检查网络/代理是否稳定

### VNC 密码提示

Xvnc 配置为 `-SecurityTypes None`（无密码）。重启 VNC 服务器即可解决。

### Xvnc 不可用

如果未安装 TigerVNC，系统会自动回退到 Xvfb（无远程可视化但自动化仍可用）。如果 Xvfb 也不可用，则回退到无头模式。安装 TigerVNC：

```bash
sudo apt install tigervnc-standalone-server
```
