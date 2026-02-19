# Gemini 模块 - 设计文档

## 概述

`gemini` 模块通过浏览器自动化提供与 Google Gemini Web 界面的自动化交互。使用 **Playwright** 控制 Chromium 浏览器，实现对 Gemini 聊天和图片生成功能的程序化访问。

## 架构

```
src/webu/gemini/
├── __init__.py      # 公共 API 导出
├── constants.py     # URL、选择器、超时时间、端口
├── errors.py        # 异常层次结构
├── config.py        # 配置管理（基于文件，带优先级链）
├── browser.py       # Playwright 浏览器生命周期（启动、导航、停止）
├── parser.py        # 响应解析（HTML → 文本/Markdown/图片/代码）
├── client.py        # 高级 Gemini 交互（登录、聊天、图片生成）
└── api.py           # FastAPI REST 接口
```

## 模块职责

### `constants.py`
- Gemini URL 和默认端口（30001+ 以避免冲突）
- 所有页面元素的 CSS 选择器（登录、聊天输入、响应、工具等）
- 超时时间和轮询间隔值

### `errors.py`
以 `GeminiError` 为根的自定义异常层次结构：

```
GeminiError
├── GeminiLoginRequiredError    # 用户未登录
├── GeminiNetworkError          # 代理或连接失败
├── GeminiTimeoutError          # 操作超时
├── GeminiResponseParseError    # 解析响应 HTML 失败
├── GeminiImageGenerationError  # 图片生成特定失败
├── GeminiBrowserError          # 浏览器启动/控制失败
├── GeminiPageError             # 页面元素交互失败
├── GeminiRateLimitError        # 触发 Gemini 速率/配额限制
└── GeminiImageDownloadError    # 图片下载失败（blob/data/http URL）
```

每个错误都携带结构化的 `details` 字典用于调试。

### `config.py`
三级优先级链配置：

```
默认配置 < 配置文件 (JSON) < 输入配置 (dict)
```

- 配置文件默认为 `configs/gemini.json`（已 gitignore 以保护代理/凭据）
- 属性：`proxy`、`browser_port`、`api_port`、`user_data_dir`、`headless`、超时时间、`verbose`

### `browser.py`
Playwright 浏览器管理：

- 使用**持久化上下文**在会话间保留登录 Cookie/状态
- 可配置代理（默认：`http://127.0.0.1:11119`）
- 独立用户数据目录（`data/chrome/gemini/`）以避免冲突
- 反检测标志（`--disable-blink-features=AutomationControlled`）
- 支持异步上下文管理器（`async with GeminiBrowser() as browser:`）
- TCP 代理将 Chrome 调试端口从 127.0.0.1 暴露到 0.0.0.0
- Xvnc 虚拟显示器 + noVNC Web 查看器支持远程可视化操作
- **图片下载**：`download_image_as_base64()` 在浏览器上下文中下载图片（处理 data:、blob:、http/https URL），保留 Cookie/认证
- **页面信息**：`get_page_info()` 返回当前 URL、标题、视口信息，用于调试

### `parser.py`
响应解析管线（**使用 BeautifulSoup 进行 DOM 解析**）：

- **纯文本提取**：BeautifulSoup `get_text()` → 规范化空白
- **Markdown 转换**：DOM 树递归遍历，处理标题、粗体/斜体/删除线、代码块（行内/块级）、链接、图片、列表、引用块、表格、水平线
- **代码块提取**：查找 `<pre><code>` 结构，提取语言和代码内容
- **图片提取**：从页面元素属性或 HTML `<img>` 标签中提取，处理 URL 图片和 base64 嵌入图片，自动跳过小图标（<50px）
- **表格支持**：`_table_to_markdown()` 将 HTML 表格转换为 Markdown 表格

输出为结构化的 `GeminiResponse` 数据类，带 `to_dict()` 序列化。

### `client.py`
高级自动化：

1. **登录检测**：多策略检查（头像、登录按钮、URL、输入框、Pro 徽章），含可见性验证
2. **会话管理**：新建会话（按钮点击或 URL 导航回退）
3. **消息发送**：`_find_element_with_fallback()` 通用元素查找 → 输入消息 → 提交（按钮或回车键）
4. **响应等待**：容器数量跟踪 + 加载指示器/停止按钮多信号检测 + 内容稳定性检测
5. **图片生成**：工具菜单导航 → 图片生成选项 → 延长超时
6. **图片下载**：`_extract_images()` 通过浏览器上下文下载图片为 base64
7. **模型选择**：确保 Pro 模型处于活动状态
8. **重试机制**：`with_retry()` 装饰器自动重试 `GeminiPageError`（指数退避），不重试认证/限流错误
9. **错误检测**：`_check_for_errors()` 检测配额/速率限制警告
10. **状态跟踪**：`get_status()` 返回就绪状态、登录状态和消息计数

### `api.py`
FastAPI REST 接口：

| 接口 | 方法 | 描述 |
|---|---|---|
| `/health` | GET | 健康检查（无需客户端） |
| `/status` | GET | 客户端就绪和登录状态 |
| `/login-status` | GET | 详细登录状态 |
| `/chat` | POST | 发送消息，接收解析后的响应 |
| `/generate-image` | POST | 图片生成并返回解析结果 |
| `/new-chat` | POST | 开始新会话 |
| `/screenshot` | POST | 调试截图 |
| `/restart` | POST | 重启客户端连接 |

错误响应使用适当的 HTTP 状态码：
- 401：需要登录
- 429：触发速率限制
- 503：客户端未就绪
- 504：超时
- 500：其他错误

## 设计决策

### 为什么选择 Playwright 而非 DrissionPage？
- Playwright 原生支持异步，更适合 FastAPI 集成
- 持久化上下文 API 优雅地保留登录状态
- 更好的选择器引擎，支持 `:has-text()` 处理动态内容
- 更强大的截图和求值 API

### 为什么使用持久化浏览器上下文？
- Gemini 需要 Google 账号登录
- 用户手动登录一次后，会话在重启间持续保存
- Cookie/localStorage 存储在 `data/chrome/gemini/`（已 gitignore）

### 为什么使用轮询检测响应完成？
- Gemini 渐进式流式输出响应
- 没有可靠的 DOM 事件标识"响应完成"
- 多信号检测：容器数量跟踪 + 加载指示器/停止按钮可见性 + 内容稳定性检测
- 比单一内容稳定性检测更可靠

### 为什么使用 BeautifulSoup 解析 HTML？
- 正则表达式无法可靠处理嵌套/深层 HTML 结构
- DOM 树递归遍历处理任意深度嵌套（如 `<b><i>...</i></b>`）
- 内置 HTML 实体解码和脏 HTML 容错
- `html.parser` 无需额外 C 依赖

### 为什么添加重试机制？
- 浏览器页面交互天生不稳定（网络延迟、DOM 渲染时机）
- `with_retry()` 装饰器使用指数退避自动重试 `GeminiPageError`
- 认证错误 (`GeminiLoginRequiredError`) 和限流错误 (`GeminiRateLimitError`) 不重试，因为这些不是瞬态问题
- 最大重试次数和延迟可配置

### 端口分配
- 浏览器调试端口：`30001`（按要求在 30000 以上）
- API 服务器端口：`30002`
- VNC 端口：`30003`（Xvnc 原始 VNC）
- noVNC 端口：`30004`（websockify Web 查看器）
- 避免与现有 Chrome 实例冲突（29001、29002）

### 配置文件安全
- `configs/gemini.json` 已 gitignore 以保护代理地址
- 默认配置通过 `GeminiConfig.create_default_config()` 程序化创建
