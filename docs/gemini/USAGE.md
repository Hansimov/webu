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
from webu.gemini import GeminiClient

async def first_login():
    client = GeminiClient()
    await client.start()

    # 检查登录状态
    status = await client.check_login_status()
    print(status)
    # 如果未登录: {"logged_in": False, "message": "用户未登录..."}
    # → 在浏览器窗口中手动登录

    # 手动登录后再次检查
    status = await client.check_login_status()
    print(status)
    # {"logged_in": True, "is_pro": True, "message": "用户已登录 (PRO)"}

    # 保持浏览器打开以完成登录
    input("登录后按 Enter 键...")
    await client.stop()

asyncio.run(first_login())
```

登录一次后会话会被保存，跨重启持续有效。

### 3. 发送聊天消息

```python
import asyncio
from webu.gemini import GeminiClient

async def chat_example():
    async with GeminiClient() as client:
        # 发送消息
        response = await client.send_message("Python 是什么？")

        # 访问响应数据
        print(response.text)        # 纯文本
        print(response.markdown)    # Markdown 格式
        print(response.code_blocks) # GeminiCodeBlock 列表
        print(response.images)      # GeminiImage 列表

        # 转为字典（用于 JSON 序列化）
        print(response.to_dict())

asyncio.run(chat_example())
```

### 4. 生成图片

```python
import asyncio
from webu.gemini import GeminiClient

async def image_example():
    async with GeminiClient() as client:
        response = await client.generate_image(
            "一只戴礼帽的可爱猫咪，水彩画风格"
        )

        for img in response.images:
            print(f"图片 URL: {img.url}")
            print(f"替代文本: {img.alt}")
            if img.base64_data:
                print(f"Base64 数据: {img.base64_data[:50]}...")

asyncio.run(image_example())
```

### 5. 多轮对话

```python
import asyncio
from webu.gemini import GeminiClient

async def conversation():
    async with GeminiClient() as client:
        # 开始新对话
        await client.new_chat()

        # 第 1 轮
        r1 = await client.send_message("介绍一下机器学习")
        print(r1.markdown)

        # 第 2 轮（在同一对话中继续）
        r2 = await client.send_message("什么是神经网络？")
        print(r2.markdown)

        # 重新开始
        await client.new_chat()
        r3 = await client.send_message("新话题：解释量子计算")
        print(r3.markdown)

asyncio.run(conversation())
```

## REST API

### 启动 API 服务器

```python
from webu.gemini.api import run_gemini_api
run_gemini_api()
# 服务器启动在 http://0.0.0.0:30002
```

或从命令行：
```bash
python -m webu.gemini.api
```

### API 接口

#### 检查状态
```bash
curl http://localhost:30002/status
```
响应：
```json
{
  "status": "ok",
  "message": "用户已登录 (PRO)",
  "is_ready": true,
  "is_logged_in": true
}
```

#### 发送聊天消息
```bash
curl -X POST http://localhost:30002/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "解释 Python 装饰器", "new_chat": true}'
```
响应：
```json
{
  "success": true,
  "text": "Python 装饰器是...",
  "markdown": "## Python 装饰器\n\nPython 装饰器是...",
  "images": [],
  "code_blocks": [
    {"language": "python", "code": "@my_decorator\ndef hello():\n    print('hello')"}
  ],
  "error": ""
}
```

#### 生成图片
```bash
curl -X POST http://localhost:30002/generate-image \
  -H "Content-Type: application/json" \
  -d '{"prompt": "日落时的山景"}'
```

#### 新建对话
```bash
curl -X POST http://localhost:30002/new-chat
```

#### 调试截图
```bash
curl -X POST "http://localhost:30002/screenshot?path=debug.png"
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
)

async def safe_chat():
    async with GeminiClient() as client:
        try:
            response = await client.send_message("你好")
        except GeminiLoginRequiredError:
            print("请先登录！")
        except GeminiNetworkError as e:
            print(f"网络问题: {e}")
            print(f"代理: {e.details.get('proxy')}")
        except GeminiTimeoutError as e:
            print(f"超时: {e.details.get('timeout_ms')}ms")
        except GeminiError as e:
            print(f"一般错误: {e}")
```

## 测试

### 运行单元测试（不需要浏览器）
```bash
cd /path/to/webu
pytest tests/gemini/test_gemini.py tests/gemini/test_tcp_proxy.py -v --tb=short -m "not integration"
```

### 运行集成测试（需要浏览器）
```bash
pytest tests/gemini/test_gemini.py -v -m integration
```

### 运行所有测试
```bash
pytest tests/gemini/test_gemini.py -v
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
