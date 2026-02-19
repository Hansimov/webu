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
└── GeminiPageError             # 页面元素交互失败
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

### `parser.py`
响应解析管线：

- **纯文本提取**：去除 HTML → 规范化空白 → 反转义实体
- **Markdown 转换**：标题、粗体/斜体、代码块、链接、图片、列表、引用块
- **代码块提取**：语言检测、代码内容
- **图片提取**：URL 图片、base64 嵌入图片、自动跳过小图标（<50px）

输出为结构化的 `GeminiResponse` 数据类，带 `to_dict()` 序列化。

### `client.py`
高级自动化：

1. **登录检测**：多策略检查（头像、登录按钮、URL、输入框）
2. **会话管理**：新建会话（按钮点击或 URL 导航回退）
3. **消息发送**：检测输入框 → 输入消息 → 提交（按钮或回车键）
4. **响应等待**：基于轮询的稳定性检测（连续 3 次稳定检查）
5. **图片生成**：工具菜单导航 → 图片生成选项 → 延长超时
6. **模型选择**：确保 Pro 模型处于活动状态

### `api.py`
FastAPI REST 接口：

| 接口 | 方法 | 描述 |
|---|---|---|
| `/status` | GET | 客户端就绪和登录状态 |
| `/login-status` | GET | 详细登录状态 |
| `/chat` | POST | 发送消息，接收解析后的响应 |
| `/generate-image` | POST | 图片生成并返回解析结果 |
| `/new-chat` | POST | 开始新会话 |
| `/screenshot` | POST | 调试截图 |

错误响应使用适当的 HTTP 状态码：
- 401：需要登录
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
- 基于稳定性的检测（内容连续 3 次轮询不变）处理可变响应长度

### 端口分配
- 浏览器调试端口：`30001`（按要求在 30000 以上）
- API 服务器端口：`30002`
- VNC 端口：`30003`（Xvnc 原始 VNC）
- noVNC 端口：`30004`（websockify Web 查看器）
- 避免与现有 Chrome 实例冲突（29001、29002）

### 配置文件安全
- `configs/gemini.json` 已 gitignore 以保护代理地址
- 默认配置通过 `GeminiConfig.create_default_config()` 程序化创建
