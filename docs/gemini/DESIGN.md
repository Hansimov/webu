# Gemini 模块 — 设计文档

## 概述

`gemini` 模块通过 Playwright 浏览器自动化实现对 Google Gemini Web 界面的程序化访问。它在运行中的 Chrome 实例上操作 Gemini 的 Angular Material UI，提供聊天、图片生成、文件上传、模式/工具切换等功能，并通过 FastAPI REST API 和 Python HTTP 客户端两种方式对外暴露。

## 架构

### 文件结构

```
src/webu/gemini/
├── __init__.py      # 公共 API 导出（所有类、错误、工厂函数）
├── constants.py     # URL、端口、CSS 选择器、超时、轮询间隔（263 行）
├── errors.py        # 10 个自定义异常类的层次结构
├── config.py        # 三级优先级配置管理（TypedDict + 属性）
├── browser.py       # 底层：Chrome 进程 + TCP 代理 + Xvnc + noVNC + Playwright CDP（854 行）
├── parser.py        # 响应解析：HTML → 文本/Markdown/图片/代码块（BeautifulSoup，456 行）
├── agency.py        # 代理层：所有浏览器页面交互逻辑（2092 行）
├── chatdb.py        # 聊天数据库：JSON 文件存储的本地聊天记录管理（501 行）
├── server.py        # 服务层：FastAPI REST 接口（37 个端点，1038 行）
├── client.py        # 客户端层：同步 HTTP 封装（requests，650 行）
└── run.py           # 管理层：CLI 守护进程（start/stop/restart/status/logs/fg，610 行）
```

### 四层架构

```
┌──────────────────────────────────────────────────────────────┐
│  Browser (browser.py)                                        │
│    Chrome 进程 + Xvnc 虚拟显示 + noVNC Web 查看器             │
│    TCP 代理（Host 头重写 + URL 重写）                          │
│    Playwright 通过 CDP 本地连接                               │
│    图片下载（新页面导航方式）                                   │
├──────────────────────────────────────────────────────────────┤
│  Agency (agency.py)                                          │
│    页面交互：登录检测、聊天管理、模式/工具切换                   │
│    输入操作（4 策略输入 + 3 策略提交 + 提交验证）               │
│    响应等待（结构性信号 + 长度稳定性 + 卡顿检测）               │
│    服务器回退检测与自动重试                                    │
│    图片提取（canvas + 新页面下载 + blob 转换）                 │
├──────────────────────────────────────────────────────────────┤
│  Server (server.py)                                          │
│    FastAPI REST API（37 个端点）                              │
│    预设管理（mode/tool 自动验证与纠正）                        │
│    名称标准化（别名映射 + 模糊匹配）                           │
│    错误 → HTTP 状态码映射                                    │
│    聊天数据库 CRUD（ChatDatabase 集成）                       │
├──────────────────────────────────────────────────────────────┤
│  Client (client.py)                                          │
│    同步 HTTP 客户端（requests.Session）                       │
│    与服务端点一一对应的 Python 方法                            │
│    便捷方法：send_message() = set_input() + send_input()     │
├──────────────────────────────────────────────────────────────┤
│  Run (run.py)                                                │
│    CLI 守护进程管理：start / stop / restart / status / logs    │
│    PID 文件 + 进程组信号（os.killpg）                         │
│    前台/后台两种运行模式                                      │
└──────────────────────────────────────────────────────────────┘
```

## 模块职责

### `constants.py`（263 行）

定义所有常量，模块中的其他文件均从此导入：

- **URL & 端口**：`GEMINI_URL`, 端口 30001–30004, noVNC 目录路径
- **超时时间**：页面加载 60s, 响应等待 120s, 图片生成 180s, 导航 30s
- **轮询参数**：`GEMINI_POLL_INTERVAL=500`ms, `GEMINI_MAX_RETRIES=3`, `GEMINI_RETRY_DELAY=1.0`s
- **CSS 选择器**（15 组）：每组按优先级排列多个选择器，用逗号分隔
  - 登录状态：`SEL_LOGIN_AVATAR`, `SEL_LOGIN_BUTTON`, `SEL_PRO_BADGE`
  - 侧边栏：`SEL_SIDEBAR_TOGGLE`, `SEL_NEW_CHAT_BUTTON`, `SEL_CHAT_LIST_ITEM`
  - 输入区：`SEL_INPUT_AREA`（Quill 编辑器 contenteditable）, `SEL_SEND_BUTTON`
  - 工具/模式：`SEL_TOOLS_BUTTON`, `SEL_TOOL_OPTION`, `SEL_MODEL_SELECTOR`, `SEL_MODE_OPTION`
  - 响应区：`SEL_RESPONSE_CONTAINER`, `SEL_RESPONSE_TEXT`, `SEL_RESPONSE_IMAGES`, `SEL_RESPONSE_CODE_BLOCKS`
  - 状态指示：`SEL_LOADING_INDICATOR`（排除了思考模式永久 thinking 区域）, `SEL_STOP_BUTTON`
  - 错误指示：`SEL_ERROR_MESSAGE`, `SEL_QUOTA_WARNING`
  - 文件上传：`SEL_FILE_UPLOAD_BUTTON`, `SEL_FILE_UPLOAD_INPUT`, `SEL_ATTACHMENT_CHIP`, `SEL_ATTACHMENT_REMOVE`

### `errors.py`（110 行）

以 `GeminiError` 为根的 10 个自定义异常：

```
GeminiError (message + details dict)
├── GeminiLoginRequiredError     # 用户未登录
├── GeminiNetworkError           # 代理/连接失败
├── GeminiTimeoutError           # 操作超时 (携带 timeout_ms)
├── GeminiResponseParseError     # 解析响应 HTML 失败 (携带 raw_content)
├── GeminiImageGenerationError   # 图片生成失败
├── GeminiBrowserError           # 浏览器启动/控制失败
├── GeminiPageError              # 页面元素交互失败
├── GeminiRateLimitError         # 触发 Gemini 速率/配额限制
├── GeminiServerRollbackError    # 服务器处理失败后页面回退到零状态
└── GeminiImageDownloadError     # 图片下载失败 (data:/blob:/http)
```

错误分类对重试策略有直接影响：
- **可重试**：`GeminiPageError`, `PlaywrightTimeoutError` → `with_retry()` 自动重试
- **内部重试**：`GeminiServerRollbackError` → `send_input`/`send_message` 内部最多重试 3 次
- **不重试**：`GeminiLoginRequiredError`, `GeminiRateLimitError`, `GeminiServerRollbackError`（在 `with_retry` 中直接抛出，在 `send_input` 内部已处理）

### `config.py`（170 行）

三级优先级链配置，使用 `TypedDict` 定义类型：

```
默认配置 (DEFAULT_GEMINI_CONFIG) < 配置文件 (JSON) < 输入配置 (dict)
```

- `GeminiConfigType`：TypedDict 定义所有配置项的类型
- `GeminiConfig`：配置类，通过 `@property` 提供类型安全的属性访问
- 配置文件：`configs/gemini.json`（已 gitignore 以保护代理地址和凭据信息）
- 属性：`proxy`, `browser_port`, `api_port`, `vnc_port`, `novnc_port`, `user_data_dir`, `chrome_executable`, `headless`, `page_load_timeout`, `response_timeout`, `image_generation_timeout`, `verbose`

### `browser.py`（854 行）

浏览器生命周期管理，包含 3 个核心组件：

#### Chrome 进程管理
- 使用 `find_chrome_executable()` 查找 Chrome（配置路径 > 系统 chrome > chromium > Playwright 默认）
- 启动 Chrome 子进程，配置 `--remote-debugging-port`（内部端口 = 外部端口 + 10）
- 反检测标志：`--disable-blink-features=AutomationControlled`
- 启动前自动清理缓存（`_clear_browser_cache`）：清理 HTTP 缓存、Service Worker、GPU 缓存、HSTS 缓存等，保留登录 Cookie 和偏好设置
- 使用持久化用户数据目录（`data/chrome/gemini/`）保留登录状态

#### TCP 代理 (`_TCPProxy`)
Chrome DevTools 绑定到 127.0.0.1 且拒绝非 IP Host 头。TCP 代理解决两个问题：
1. 在 `0.0.0.0:{external_port}` 监听，支持远程访问
2. 重写请求 `Host` 头为 `127.0.0.1:{internal_port}`
3. 重写响应中的内部地址（WebSocket URL 等）为 `{hostname}:{external_port}`
4. 地址重写导致体积变化时更新 `Content-Length` 头

#### 虚拟显示器
- 优先使用 **Xvnc**（TigerVNC）：同时提供虚拟 X 显示和内置 VNC 服务器
- 回退到 **Xvfb**（无 VNC 可视化但 Chrome 仍可运行）
- 最终回退到无头模式
- **noVNC**：通过 websockify 提供基于 Web 的 VNC 查看器，远程用户可在浏览器中操作

#### 图片下载 (`download_image_as_base64`)
多策略下载，按优先级：
1. **data: URL** → 直接提取 base64
2. **http/https URL** → **在新页面中导航**（`context.new_page()` → `goto(url)` → `resp.body()`），自动携带 Cookie 且无 CORS 限制
3. **blob: URL 或 http 回退** → `page.evaluate` + canvas/fetch 在浏览器内下载

#### 标签页管理
- 设置 `popup` 事件处理器自动关闭新标签页
- `close_extra_pages()` 在关键操作前清理多余标签

### `parser.py`（456 行）

使用 BeautifulSoup 的 HTML 响应解析管线。

**数据类**：
- `GeminiImage`：图片数据（url, alt, base64_data, mime_type, width, height），含 `save_to_file()` 和 `get_extension()` 方法
- `GeminiCodeBlock`：代码块（language, code）
- `GeminiResponse`：完整响应（text, markdown, images, code_blocks, is_error, error_message, raw_html），含 `to_dict()` 序列化

**`GeminiResponseParser` 解析流程**：
1. `parse_text()` → BeautifulSoup `get_text()` + 空白规范化
2. `parse_markdown()` → DOM 树递归遍历 (`_element_to_markdown`)，处理：标题 h1–h6, 粗体/斜体/删除线, 行内/块级代码, 链接, 图片, 列表, 段落, 引用块, 水平线, 表格
3. `parse_code_blocks()` → 查找 `<pre><code>` 结构，提取 `language-*` 类名
4. `parse_images_from_elements()` → 从页面评估结果解析图片，跳过 <50px 小图标，处理 data: URL 和预下载 base64
5. `parse_images_from_html()` → 从 HTML `<img>` 标签直接提取（回退方案）
6. `parse()` → 整合以上所有步骤，容错处理（部分失败仍返回结果）

### `agency.py`（2092 行）

核心交互代理层，封装所有浏览器页面交互逻辑。

#### 公共方法

| 方法 | 描述 |
|---|---|
| `start()` / `stop()` | 启动/停止 Agency（含浏览器和导航） |
| `browser_status()` | 综合状态：就绪、登录、页面、模式、工具 |
| `check_login_status()` | 多策略登录检测（头像/按钮/URL/输入框/文本搜索） |
| `ensure_logged_in()` | 未登录则抛 `GeminiLoginRequiredError` |
| `new_chat()` | 新建会话（URL 导航，避免新标签页） |
| `switch_chat(chat_id)` | 切换到指定会话 |
| `get_mode()` / `set_mode(mode)` | 读取/切换模式（快速/思考/Pro/Flash/Deep Think） |
| `get_tool()` / `set_tool(tool)` | 读取/切换工具（Deep Research/生成图片/创作音乐/Canvas/Google 搜索/代码执行） |
| `clear_input()` / `set_input(text)` | 清空/设置输入框 |
| `add_input(text)` / `get_input()` | 追加/读取输入框 |
| `send_input(wait_response)` | 发送输入（同步/异步），含回退重试 |
| `send_message(text, ...)` | 便捷方法：输入 + 发送 + 等待 + 解析 |
| `generate_image(prompt)` | 便捷方法：图片生成 |
| `attach(file_path)` | 上传文件 |
| `detach()` / `get_attachments()` | 清除/查看附件 |
| `get_messages()` | 获取会话中所有消息列表 |
| `enable_image_generation()` | 通过工具菜单启用图片生成模式 |
| `screenshot(path)` | 对当前页面截图 |
| `save_images(response, ...)` | 将响应图片保存到磁盘 |
| `toggle_sidebar()` | 切换侧边栏 |

#### 核心内部机制

**多策略文本输入 (`_type_message`)**：4 种策略依次尝试，每次带验证：
1. `keyboard.type()` — 逐字符输入，多行用 `Shift+Enter` 换行
2. JS `innerHTML` — 通过 `<p>` 标签注入，触发 input/change/compositionend 事件
3. `document.execCommand('insertText')` — 旧式文本插入
4. 剪贴板粘贴 — `navigator.clipboard.writeText()` + `Ctrl+V`

**多策略消息提交 (`_submit_message`)**：最多 3 轮尝试，每轮 3 步：
1. 查找发送按钮 → `_click_send_button()` 尝试 3 种点击方式：
   - Playwright `force click`（模拟真实鼠标事件序列）
   - 完整 PointerEvent 序列（pointerdown→mousedown→pointerup→mouseup→click）
   - 简单 JS `el.click()`
2. DOM 直接查找按钮 + 完整事件序列
3. Enter 键

每步之后调用 `_verify_submit_success()` 检查 3 个信号（任一为 True 即确认提交成功）：
- 输入框内容已清空
- `user-query` 元素数量增加
- 加载指示器或停止按钮可见

**结构性响应检测 (`_wait_for_response`)**：分两个阶段

*Phase 1 — 等待响应开始*：轮询检查 3 个正面信号 + 1 个负面信号：
- `model-response` 元素数量增加
- `mat-progress-bar` 等加载指示器可见
- 停止按钮可见
- 服务器回退检测（负面信号，提交后 > 3s 开始检查）

*Phase 2 — 等待响应完成*：使用长度稳定性 + 卡顿检测
- **长度比较**（非精确字符串比较）：`len(current) == len(last)` 且 `len > 0` 视为稳定。避免 DOM 微变（动画/时间戳）导致的误判
- **理想结束**：内容稳定 + 无加载 + 无停止按钮 → 连续 3 次确认
- **次优结束**：内容稳定 + 停止按钮消失（思考模式 thinking 区域可能保持 loading）→ 连续 5 次确认
- **卡顿检测**：内容超过 `stall_timeout`（最多 30s）未变化，但仍有加载/生成信号 → 自动点击停止按钮并返回已有内容
- **服务器回退**：Phase 2 中也持续检测

**服务器回退检测 (`_detect_server_rollback`)**：

当 Gemini 后端处理失败时，页面自动回退到发送前的"零状态"。检测信号：
- 主判定：`body.zero-state-theme` + `.greeting-container` 可见 + `user-query=0` + `model-response=0`
- 次判定：`.card-zero-state` ≥ 3 个可见 + 无对话元素 + 输入框有文本

检测到回退后抛出 `GeminiServerRollbackError`，由 `send_input`/`send_message` 内部自动重试（最多 3 次，间隔 3s，并截图记录）。

**图片提取 (`_extract_images`)**：
- 等待图片加载完成（`img.complete && naturalHeight > 0`，最多 20s）
- 遍历 `<img>` 和 `<canvas>` 元素
- 对已加载图片尝试 canvas 提取（避免额外网络请求）
- canvas tainted（CORS）时标记 `needs_download`，后续通过 `download_image_as_base64` 下载

### `server.py`（1038 行）

FastAPI REST 服务端 v4.0.0：

#### 端点（37 个）

| 端点 | 方法 | 标签 | 描述 |
|---|---|---|---|
| `/health` | GET | 系统 | 健康检查 |
| `/browser_status` | GET | 状态 | 浏览器全面状态（含预设信息） |
| `/set_presets` | POST | 预设 | 同时设置 mode + tool 预设 |
| `/get_presets` | GET | 预设 | 获取当前预设配置 |
| `/new_chat` | POST | 聊天 | 新建聊天（可选 mode/tool 参数） |
| `/switch_chat` | POST | 聊天 | 切换到指定聊天 |
| `/get_mode` | GET | 模式 | 获取当前模式 |
| `/set_mode` | POST | 模式 | 设置模式 |
| `/get_tool` | GET | 工具 | 获取当前工具 |
| `/set_tool` | POST | 工具 | 设置工具 |
| `/clear_input` | POST | 输入 | 清空输入框 |
| `/set_input` | POST | 输入 | 设置输入内容 |
| `/add_input` | POST | 输入 | 追加输入内容 |
| `/get_input` | GET | 输入 | 获取输入框内容 |
| `/send_input` | POST | 消息 | 发送输入（含预设自动验证） |
| `/attach` | POST | 文件 | 上传附件 |
| `/detach` | POST | 文件 | 移除所有附件 |
| `/get_attachments` | GET | 文件 | 获取附件列表 |
| `/get_messages` | GET | 消息 | 获取消息列表 |
| `/store_images` | POST | 图片 | 在服务器端保存最新响应图片到磁盘 |
| `/download_images` | POST | 图片 | 下载最新响应图片的 base64 数据到客户端 |
| `/store_screenshot` | POST | 截图 | 在服务器端保存截图到指定路径 |
| `/download_screenshot` | POST | 截图 | 下载截图的 PNG 二进制数据到客户端 |
| `/chatdb/create` | POST | 聊天数据库 | 创建新的聊天记录 |
| `/chatdb/list` | GET | 聊天数据库 | 列出所有聊天记录（摘要） |
| `/chatdb/stats` | GET | 聊天数据库 | 获取数据库统计信息 |
| `/chatdb/{chat_id}` | GET | 聊天数据库 | 获取指定聊天的完整数据 |
| `/chatdb/{chat_id}` | DELETE | 聊天数据库 | 删除指定聊天 |
| `/chatdb/{chat_id}/title` | PUT | 聊天数据库 | 更新聊天标题 |
| `/chatdb/{chat_id}/messages` | GET | 聊天数据库 | 获取聊天的所有消息 |
| `/chatdb/{chat_id}/messages` | POST | 聊天数据库 | 添加新消息 |
| `/chatdb/{chat_id}/messages/{index}` | GET | 聊天数据库 | 获取指定索引的消息 |
| `/chatdb/{chat_id}/messages/{index}` | PUT | 聊天数据库 | 更新指定索引的消息 |
| `/chatdb/{chat_id}/messages/{index}` | DELETE | 聊天数据库 | 删除指定索引的消息 |
| `/chatdb/search` | POST | 聊天数据库 | 搜索聊天内容 |
| `/restart` | POST | 系统 | 重启 Agency |
| `/evaluate` | POST | 调试 | 在页面执行 JavaScript（仅调试用） |

#### 图片端点重设计（v4.0.0）

v4.0.0 将原 `/download_images` 和 `/screenshot` 拆分为"存储"和"下载"两类端点：

- **`/store_images`**：在服务器端提取图片并保存到指定目录，返回保存路径列表
- **`/download_images`**：在服务器端提取图片 base64 数据，返回 JSON（含 base64 编码），由客户端在本地保存
- **`/store_screenshot`**：在服务器端截图并保存到指定路径
- **`/download_screenshot`**：返回 PNG 二进制数据（`Response(media_type="image/png")`），由客户端在本地保存

内部共享 `_get_parsed_images()` 辅助方法，避免图片提取逻辑重复。

#### 名称标准化

支持中英文别名和模糊匹配：
- 模式别名：`fast`→`快速`, `think`→`思考`, `pro`→`Pro`, `deep_think`→`Deep Think`
- 工具别名：`image`→`生成图片`, `music`→`创作音乐`, `search`→`Google 搜索`, `code`→`代码执行`, `deep_research`→`Deep Research`
- Pydantic `field_validator` 在请求模型中自动标准化

#### 预设管理

预设系统确保浏览器状态与期望一致：
1. 通过 `/set_presets` 或 `/new_chat` 设置预设
2. 首次 `/send_input` 前自动调用 `_ensure_presets()` 验证并纠正当前 mode/tool
3. 验证后标记 `verified=True`，后续发送不再重复验证

#### 错误响应映射

| 异常类 | HTTP 状态码 |
|---|---|
| `GeminiLoginRequiredError` | 401 |
| `GeminiRateLimitError` | 429 |
| `GeminiServerRollbackError` | 503 |
| `GeminiTimeoutError` | 504 |
| `GeminiPageError` / 其他 `GeminiError` | 500 |

### `client.py`（650 行）

同步 HTTP 客户端，使用 `requests.Session`：

- `GeminiClientConfig`：连接配置（host, port, timeout=300s, scheme）
- `GeminiClient`：与 Server 端点一一对应的方法，支持 GET/POST/PUT/DELETE
- 支持上下文管理器（`with GeminiClient() as client:`）
- `send_message(text)` 便捷方法：自动调用 `set_input()` + `send_input()`
- `store_images(output_dir, prefix)` 服务器端保存图片
- `download_images(output_dir, prefix)` 下载 base64 数据并在客户端本地保存
- `store_screenshot(path)` 服务器端保存截图
- `download_screenshot(path)` 下载 PNG 数据并在客户端本地保存
- `chatdb_*` 系列方法（12 个）：对应 `/chatdb/*` 所有端点
- 错误映射：`ConnectionError`（无法连接）, `TimeoutError`（请求超时）, `RuntimeError`（HTTP 错误 + 服务端详情）

### `chatdb.py`（501 行）

本地聊天记录数据库，使用 JSON 文件存储：

**数据类**：
- `ChatMessage`：消息记录（role, content, timestamp, files）
- `ChatSession`：聊天会话（chat_id, title, created_at, updated_at, messages）

**`ChatDatabase` 核心功能**：
- **存储结构**：`data/gemini/chats/index.json`（索引）+ `{chat_id}.json`（每个聊天独立文件）
- **CRUD 操作**：创建/读取/删除聊天，添加/读取/更新/删除消息
- **搜索**：按关键词搜索聊天内容（标题 + 消息内容）
- **统计**：聊天数、消息总数、第一条/最后一条记录时间
- **标题管理**：更新聊天标题
- **线程安全**：使用 `threading.Lock` 保护并发访问
- **自动时间戳**：创建/更新操作自动记录 ISO 格式时间戳
- **数据持久化**：每次写操作后立即同步到磁盘

### `run.py`（610 行）

CLI 守护进程管理器：

- **前台模式** (`fg`)：直接运行，日志输出到终端，Ctrl+C 停止
- **后台模式** (`start`)：fork 子进程（`start_new_session=True`），日志写入 `data/gemini/runner.log`
- **停止** (`stop`)：使用 `os.killpg(pgid, SIGTERM)` 发送信号到整个进程组，确保 Chrome/Xvnc/noVNC 等子进程全部终止；超时 15s 后 `SIGKILL` 强制终止
- **状态文件**：PID 和状态信息保存在 `data/gemini/runner_state.json` 和 `data/gemini/runner.pid`
- **日志追踪** (`logs`)：类似 `tail -f`，支持 `-n` 参数指定初始行数
- **日志去色**：后台模式使用 `_DecoloredWriter` 去除 ANSI 颜色控制符
- **信号处理**：SIGINT/SIGTERM → 优雅停机

## 核心设计决策

### 为什么选择 Playwright + Chrome CDP？
- Playwright 原生支持异步，适合 FastAPI 集成
- 通过 CDP 连接到独立 Chrome 进程，支持持久化用户数据目录保留登录状态
- 强大的 `page.evaluate()` 可直接在浏览器上下文执行 JS，处理 Angular Material 等复杂 UI
- 完善的事件系统（popup 处理、file chooser 等）

### 为什么使用多策略输入和提交？
Gemini 使用 Angular Material + Quill 编辑器，标准的 Playwright 操作经常不足：
- 输入框是 `contenteditable` 而非标准 `<input>`，需特殊处理
- Angular Material 按钮需要完整的 PointerEvent 序列才能可靠触发
- 不同浏览器版本和 Gemini 前端更新可能改变 DOM 结构
- 多策略 + 每步验证确保在各种环境下的可靠性

### 为什么使用结构性信号检测响应？
- Gemini DOM 因动画、时间戳等会产生微小变化，精确 innerHTML 比较不可靠
- 长度比较（`len(current) == len(last)`）容忍字符级 DOM 微变
- model-response 元素计数 + 加载指示器 + 停止按钮提供可靠的结构性判定
- 卡顿检测兜底：内容长时间不变 + 仍在"生成中" → 自动停止

### 为什么需要服务器回退检测？
- Gemini 后端偶尔处理失败，页面静默回退到初始状态，不抛任何错误
- 零状态信号（body 类、欢迎区域、建议卡片、对话元素计数）组合提供可靠检测
- 回退后输入框文本仍在，重试只需重新提交而无需重新输入

### 为什么用新页面导航下载图片？
- 原始方案使用 `APIRequestContext.get()`，但 Gemini CDN 存在 CORS/TLS 限制
- 新页面导航（`context.new_page()` → `goto(url)`）自动携带 Cookie 且无 CORS 限制
- 比 `page.evaluate` + `fetch` 更可靠（可能被 CSP/CORS 阻断）

### 为什么使用进程组信号停止？
- Runner 启动时 Chrome/Xvnc/noVNC 等都作为子进程运行
- 仅发送 SIGTERM 到主进程不会终止子进程树
- `start_new_session=True` + `os.killpg()` 确保整个进程组被终止

### 为什么使用 BeautifulSoup 解析 HTML？
- 正则表达式无法可靠处理嵌套/深层 HTML 结构
- DOM 树递归遍历处理任意深度嵌套（如 `<b><i>...</i></b>`）
- 内置 HTML 实体解码和脏 HTML 容错
- `html.parser` 无需额外 C 依赖

### 端口分配

| 端口 | 用途 |
|---|---|
| 30001 | CDP TCP 代理（0.0.0.0 → Chrome 127.0.0.1:30011） |
| 30002 | FastAPI REST API |
| 30003 | Xvnc 原始 VNC |
| 30004 | noVNC WebSocket + Web 查看器（websockify） |
