# Gemini 模块 - 使用指南

## 安装

### 前置条件

1. 安装 Playwright：
```bash
pip install playwright
playwright install chromium
```

2. 确保依赖可用：
```bash
pip install -e .
```

## 快速开始

### 1. 创建配置

```python
from webu.gemini import GeminiConfig

# 创建默认配置文件
config = GeminiConfig.create_default_config()
# 保存到 configs/gemini.json
```

或手动创建 `configs/gemini.json`：
```json
{
  "proxy": "http://127.0.0.1:11119",
  "browser_port": 30001,
  "api_port": 30002,
  "vnc_port": 30003,
  "novnc_port": 30004,
  "user_data_dir": "./data/chrome/gemini",
  "headless": false,
  "page_load_timeout": 60000,
  "response_timeout": 120000,
  "image_generation_timeout": 180000,
  "verbose": false
}
```

### 2. 首次登录

首次使用时会打开浏览器窗口，你必须**手动登录** Google 账号：

```python
import asyncio
from webu.gemini import GeminiAgency

async def first_login():
    agency = GeminiAgency()
    await agency.start()

    # 检查登录状态
    status = await agency.check_login_status()
    print(status)
    # 如果未登录: {"logged_in": False, "message": "用户未登录..."}
    # → 在浏览器窗口中手动登录

    # 手动登录后再次检查
    status = await agency.check_login_status()
    print(status)
    # {"logged_in": True, "is_pro": True, "message": "用户已登录 (PRO)"}

    # 保持浏览器打开以完成登录
    input("登录后按 Enter 键...")
    await agency.stop()

asyncio.run(first_login())
```

登录一次后会话会被保存，跨重启持续有效。

### 3. 发送聊天消息（直接使用 Agency）

```python
import asyncio
from webu.gemini import GeminiAgency

async def chat_example():
    agency = GeminiAgency()
    await agency.start()

    try:
        # 发送消息
        response = await agency.send_message("Python 是什么？")

        # 访问响应数据
        print(response.text)        # 纯文本
        print(response.markdown)    # Markdown 格式
        print(response.code_blocks) # GeminiCodeBlock 列表
        print(response.images)      # GeminiImage 列表

        # 转为字典（用于 JSON 序列化）
        print(response.to_dict())
    finally:
        await agency.stop()

asyncio.run(chat_example())
```

### 4. 使用 HTTP 客户端（通过 Server）

如果 Server 已启动（见下方"CLI 管理"），可使用 HTTP 客户端：

```python
from webu.gemini import GeminiClient, GeminiClientConfig

# 连接到运行中的 Server
config = GeminiClientConfig(host="127.0.0.1", port=30002)
client = GeminiClient(config)

# 检查状态
status = client.browser_status()
print(status)

# 发送消息（便捷方法：自动 set_input + send_input）
result = client.send_message("Python 是什么？")
print(result)

# 细粒度操作
client.set_input("解释量子计算")
result = client.send_input(wait_response=True)
print(result)

# 获取消息历史
messages = client.get_messages()
print(messages)
```

### 5. 生成图片

```python
import asyncio
from webu.gemini import GeminiAgency

async def image_example():
    agency = GeminiAgency()
    await agency.start()

    try:
        response = await agency.generate_image(
            "一只戴礼帽的可爱猫咪，水彩画风格"
        )

        for img in response.images:
            print(f"图片 URL: {img.url}")
            print(f"替代文本: {img.alt}")
            if img.base64_data:
                print(f"Base64 数据: {img.base64_data[:50]}...")
                print(f"MIME 类型: {img.mime_type}")
    finally:
        await agency.stop()

asyncio.run(image_example())
```

发送消息时也可以下载图片（默认启用）：
```python
async def chat_with_images():
    agency = GeminiAgency()
    await agency.start()

    try:
        # download_images=True 时自动下载图片为 base64
        response = await agency.send_message(
            "生成一张猫咪图片",
            download_images=True,  # 默认值
        )
        for img in response.images:
            if img.base64_data:
                # 可直接用于显示或保存
                import base64
                data = base64.b64decode(img.base64_data)
                with open("cat.png", "wb") as f:
                    f.write(data)
    finally:
        await agency.stop()
```

### 6. 多轮对话

```python
import asyncio
from webu.gemini import GeminiAgency

async def conversation():
    agency = GeminiAgency()
    await agency.start()

    try:
        # 开始新对话
        await agency.new_chat()

        # 第 1 轮
        r1 = await agency.send_message("介绍一下机器学习")
        print(r1.markdown)

        # 第 2 轮（在同一对话中继续）
        r2 = await agency.send_message("什么是神经网络？")
        print(r2.markdown)

        # 重新开始
        await agency.new_chat()
        r3 = await agency.send_message("新话题：解释量子计算")
        print(r3.markdown)
    finally:
        await agency.stop()

asyncio.run(conversation())
```

### 7. 模式和工具管理

```python
import asyncio
from webu.gemini import GeminiAgency

async def mode_tool_example():
    agency = GeminiAgency()
    await agency.start()

    try:
        # 获取/设置模式
        mode = await agency.get_mode()
        print(f"当前模式: {mode}")

        await agency.set_mode("Pro")

        # 获取/设置工具
        tool = await agency.get_tool()
        print(f"当前工具: {tool}")

        await agency.set_tool("生成图片")
    finally:
        await agency.stop()

asyncio.run(mode_tool_example())
```

### 8. 附件操作

```python
import asyncio
from webu.gemini import GeminiAgency

async def attachment_example():
    agency = GeminiAgency()
    await agency.start()

    try:
        # 上传附件
        await agency.attach("/path/to/document.pdf")

        # 查看附件
        attachments = await agency.get_attachments()
        print(attachments)

        # 移除附件
        await agency.detach()
    finally:
        await agency.stop()

asyncio.run(attachment_example())
```

## REST API (Server)

### 启动服务器

**方式一：CLI 管理器（推荐）**
```bash
# 启动浏览器 + API 服务器
python -m webu.gemini.run start

# 查看状态
python -m webu.gemini.run status

# 重启
python -m webu.gemini.run restart

# 停止
python -m webu.gemini.run stop
```

**方式二：直接启动**
```python
from webu.gemini.server import run_gemini_server
run_gemini_server()
# 服务器启动在 http://0.0.0.0:30002
```

### API 端点

#### 健康检查
```bash
curl http://localhost:30002/health
```
响应：
```json
{
  "status": "ok",
  "version": "2.0.0"
}
```

#### 浏览器状态
```bash
curl http://localhost:30002/browser_status
```
响应：
```json
{
  "is_ready": true,
  "browser": {"is_started": true, "has_display": true, "has_page": true},
  "login": {"logged_in": true, "is_pro": true},
  "mode": {"mode": "Pro"},
  "tool": {"tool": "none"}
}
```

#### 聊天管理
```bash
# 新建聊天
curl -X POST http://localhost:30002/new_chat

# 切换聊天
curl -X POST http://localhost:30002/switch_chat \
  -H "Content-Type: application/json" \
  -d '{"chat_id": "abc123"}'
```

#### 模式和工具
```bash
# 获取/设置模式
curl http://localhost:30002/get_mode
curl -X POST http://localhost:30002/set_mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "Pro"}'

# 获取/设置工具
curl http://localhost:30002/get_tool
curl -X POST http://localhost:30002/set_tool \
  -H "Content-Type: application/json" \
  -d '{"tool": "生成图片"}'
```

#### 输入操作
```bash
# 设置输入内容
curl -X POST http://localhost:30002/set_input \
  -H "Content-Type: application/json" \
  -d '{"text": "解释 Python 装饰器"}'

# 追加输入内容
curl -X POST http://localhost:30002/add_input \
  -H "Content-Type: application/json" \
  -d '{"text": "，并给出示例代码"}'

# 获取输入框内容
curl http://localhost:30002/get_input

# 清空输入框
curl -X POST http://localhost:30002/clear_input
```

#### 发送消息
```bash
# 同步发送（等待 Gemini 回复后返回结果）
curl -X POST http://localhost:30002/send_input \
  -H "Content-Type: application/json" \
  -d '{"wait_response": true}'

# 异步发送（立即返回，不等待回复）
curl -X POST http://localhost:30002/send_input \
  -H "Content-Type: application/json" \
  -d '{"wait_response": false}'
```
同步响应：
```json
{
  "status": "ok",
  "response": {
    "text": "Python 装饰器是...",
    "markdown": "## Python 装饰器\n\n...",
    "images": [],
    "code_blocks": [{"language": "python", "code": "@my_decorator\ndef hello():..."}]
  }
}
```

#### 附件操作
```bash
# 上传附件
curl -X POST http://localhost:30002/attach \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/path/to/document.pdf"}'

# 获取附件列表
curl http://localhost:30002/get_attachments

# 移除所有附件
curl -X POST http://localhost:30002/detach
```

#### 获取消息历史
```bash
curl http://localhost:30002/get_messages
```
响应：
```json
{
  "messages": [
    {"role": "user", "content": "解释装饰器"},
    {"role": "model", "content": "装饰器是..."}
  ]
}
```

#### 调试工具
```bash
# 截图
curl -X POST http://localhost:30002/screenshot \
  -H "Content-Type: application/json" \
  -d '{"path": "debug.png"}'

# 重启 Agency
curl -X POST http://localhost:30002/restart
```

### Swagger UI
访问 `http://localhost:30002/` 查看交互式 API 文档。

## 配置

### 配置文件位置
默认：`configs/gemini.json`

此文件已 **gitignore**，以保证安全（包含代理地址）。

### 配置属性

| 属性 | 类型 | 默认值 | 描述 |
|---|---|---|---|
| `proxy` | string | `http://127.0.0.1:11119` | 访问 Gemini 的 HTTP 代理 |
| `browser_port` | int | `30001` | 浏览器调试端口 |
| `api_port` | int | `30002` | FastAPI 服务器端口 |
| `vnc_port` | int | `30003` | Xvnc 原始 VNC 端口 |
| `novnc_port` | int | `30004` | noVNC Web 查看器端口 |
| `user_data_dir` | string | `./data/chrome/gemini` | 浏览器配置文件目录 |
| `headless` | bool | `false` | 以无头模式运行浏览器 |
| `page_load_timeout` | int | `60000` | 页面加载超时（毫秒） |
| `response_timeout` | int | `120000` | 聊天响应超时（毫秒） |
| `image_generation_timeout` | int | `180000` | 图片生成超时（毫秒） |
| `verbose` | bool | `false` | 启用详细日志 |

### 配置优先级
```
默认值 → 配置文件 → 输入参数
```

## 错误处理

所有错误继承自 `GeminiError`：

```python
from webu.gemini import (
    GeminiError,
    GeminiLoginRequiredError,
    GeminiNetworkError,
    GeminiTimeoutError,
    GeminiResponseParseError,
    GeminiImageGenerationError,
    GeminiRateLimitError,
    GeminiImageDownloadError,
)

async def safe_chat():
    agency = GeminiAgency()
    await agency.start()

    try:
        response = await agency.send_message("你好")
    except GeminiLoginRequiredError:
        print("请先登录！")
    except GeminiRateLimitError as e:
        print(f"触发速率限制: {e}")
        print(f"详情: {e.details}")
    except GeminiNetworkError as e:
        print(f"网络问题: {e}")
        print(f"代理: {e.details.get('proxy')}")
    except GeminiTimeoutError as e:
        print(f"超时: {e.details.get('timeout_ms')}ms")
    except GeminiImageDownloadError as e:
        print(f"图片下载失败: {e}")
    except GeminiError as e:
        print(f"一般错误: {e}")
    finally:
        await agency.stop()
```

**注意**：`GeminiPageError` 和 `PlaywrightTimeoutError` 会被 `with_retry()` 装饰器自动重试（默认 3 次，指数退避）。`GeminiLoginRequiredError` 和 `GeminiRateLimitError` 不会重试。

## 测试

### 运行单元测试（不需要浏览器）
```bash
cd /path/to/webu

# Gemini 模块全量单元测试 (128 tests)
pytest tests/gemini/test_gemini.py -v --tb=short

# TCP 代理测试
pytest tests/gemini/test_tcp_proxy.py -v --tb=short
```

### 运行实时端到端测试（需要运行中的 Server）

先启动服务器：
```bash
python -m webu.gemini.run start
```

再运行测试：
```bash
# 基础功能测试 (15 tests)
# 覆盖: health, browser_status, screenshot, get/set_mode, get/set_tool,
# get/set/add/clear_input, get_messages, get_attachments, new_chat, send_message
python tests/gemini/test_live.py

# 全场景端到端测试 (6 scenarios)
# 覆盖: 模式轮换(快速→思考→Pro), 工具轮换(生成图片→Canvas→Deep Research),
# 多轮对话, 新建聊天重置, 输入框边界情况(特殊字符/多行/追加), 思考模式发送
python tests/gemini/test_live_scenarios.py
```

测试截图保存在 `data/debug/` 和 `data/debug/scenarios/` 目录。

### 运行所有单元测试
```bash
pytest tests/gemini/ -v
```

## 故障排除

### 浏览器无法启动
- 检查 Playwright Chromium 是否已安装：`playwright install chromium`
- 检查代理是否可访问：`curl -x http://127.0.0.1:11119 https://gemini.google.com`

### 登录未检测到
- 确保浏览器配置文件目录存在且有有效的 Cookie
- 尝试删除 `data/chrome/gemini/` 并重新登录

### 响应超时
- 在配置中增加 `response_timeout`（默认：120 秒）
- 对于图片生成，`image_generation_timeout` 默认为 180 秒

### 代理连接错误
- 验证代理是否在配置的端口上运行
- 检查 `configs/gemini.json` 中的代理地址是否正确
