# Gemini 模块 — 使用指南

## 快速开始

### 1. 启动服务

```bash
# 后台启动（推荐）
python -m webu.gemini.run start

# 或前台运行（调试用）
python -m webu.gemini.run fg
```

### 2. 发送消息（HTTP 客户端）

```python
from webu.gemini import GeminiClient, GeminiClientConfig

config = GeminiClientConfig(host="127.0.0.1", port=30002)
client = GeminiClient(config)

# 发送消息并获取响应
result = client.send_message("Python 是什么？")
print(result["response"]["text"])
print(result["response"]["markdown"])
```

### 3. 使用 REST API

```bash
# 设置输入
curl -X POST http://localhost:30002/set_input \
  -H "Content-Type: application/json" \
  -d '{"text": "Python 是什么？"}'

# 发送并等待响应
curl -X POST http://localhost:30002/send_input \
  -H "Content-Type: application/json" \
  -d '{"wait_response": true}'
```

## 三种使用方式

### 方式一：直接使用 Agency（异步 Python）

`GeminiAgency` 是最底层的接口，直接控制浏览器页面交互。适合需要最大灵活性的场景。

```python
import asyncio
from webu.gemini import GeminiAgency

async def main():
    async with GeminiAgency() as agency:
        # 发送消息
        response = await agency.send_message("解释量子计算")

        print(response.text)        # 纯文本
        print(response.markdown)    # Markdown 格式
        print(response.code_blocks) # list[GeminiCodeBlock]
        print(response.images)      # list[GeminiImage]

        # 转为字典（JSON 序列化）
        print(response.to_dict())

asyncio.run(main())
```

### 方式二：HTTP 客户端（同步 Python）

`GeminiClient` 封装 HTTP 请求，连接到运行中的 Server。适合从其他进程或远程机器调用。

```python
from webu.gemini import GeminiClient, GeminiClientConfig

config = GeminiClientConfig(host="192.168.1.100", port=30002)
client = GeminiClient(config)

# 所有操作都是同步的
result = client.send_message("你好")
print(result)

client.close()
```

也支持上下文管理器：
```python
with GeminiClient(GeminiClientConfig()) as client:
    result = client.send_message("你好")
```

### 方式三：REST API（curl / 任意语言）

Server 启动后通过 HTTP 访问。Swagger UI 地址：`http://<主机名>:30002/docs`

```bash
curl -X POST http://localhost:30002/set_input \
  -H "Content-Type: application/json" \
  -d '{"text": "你好"}'

curl -X POST http://localhost:30002/send_input \
  -H "Content-Type: application/json" \
  -d '{"wait_response": true}'
```

## CLI 管理

```bash
# 启动 / 停止 / 重启 / 状态
python -m webu.gemini.run start
python -m webu.gemini.run stop
python -m webu.gemini.run restart
python -m webu.gemini.run status

# 日志追踪
python -m webu.gemini.run logs          # 默认最后 30 行
python -m webu.gemini.run logs -n 100   # 最后 100 行

# 前台运行（调试用）
python -m webu.gemini.run fg

# 使用自定义配置
python -m webu.gemini.run start -c /path/to/config.json
```

## 聊天会话管理

### 新建聊天

```python
# Agency
await agency.new_chat()

# Client
client.new_chat()

# Client: 新建聊天并设置 mode/tool
client.new_chat(mode="Pro", tool="生成图片")
```

```bash
# REST API
curl -X POST http://localhost:30002/new_chat

# 带参数
curl -X POST http://localhost:30002/new_chat \
  -H "Content-Type: application/json" \
  -d '{"mode": "Pro", "tool": "image"}'
```

### 切换聊天

```python
# Agency
await agency.switch_chat("abc123def456")

# Client
client.switch_chat("abc123def456")
```

```bash
curl -X POST http://localhost:30002/switch_chat \
  -H "Content-Type: application/json" \
  -d '{"chat_id": "abc123def456"}'
```

### 多轮对话

```python
async with GeminiAgency() as agency:
    await agency.new_chat()
    r1 = await agency.send_message("介绍机器学习")
    r2 = await agency.send_message("什么是神经网络？")  # 同一会话
    await agency.new_chat()  # 新会话
    r3 = await agency.send_message("量子计算")
```

## 模式管理

支持的模式：`快速`, `思考`, `Pro`, `Flash`, `Deep Think`

```python
# Agency
mode = await agency.get_mode()   # {"mode": "快速"}
await agency.set_mode("Pro")

# Client
client.get_mode()
client.set_mode("Pro")
```

```bash
curl http://localhost:30002/get_mode
curl -X POST http://localhost:30002/set_mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "Pro"}'
```

支持别名（自动标准化）：
- `fast` / `quick` → `快速`
- `think` / `thinking` → `思考`
- `pro` → `Pro`
- `deep_think` / `deep think` → `Deep Think`
- `flash` → `Flash`

## 工具管理

支持的工具：`Deep Research`, `生成图片`, `创作音乐`, `Canvas`, `Google 搜索`, `代码执行`, `none`

```python
# Agency
tool = await agency.get_tool()   # {"tool": "none"}
await agency.set_tool("生成图片")

# Client
client.get_tool()
client.set_tool("image")  # 别名，自动转为 "生成图片"
```

```bash
curl http://localhost:30002/get_tool
curl -X POST http://localhost:30002/set_tool \
  -H "Content-Type: application/json" \
  -d '{"tool": "image"}'
```

支持别名：
- `image` / `generate_image` / `图片` → `生成图片`
- `music` / `音乐` → `创作音乐`
- `search` / `搜索` → `Google 搜索`
- `code` / `代码` → `代码执行`
- `deep_research` / `deep research` → `Deep Research`
- `canvas` → `Canvas`
- `none` / `无` → 清除工具

## 预设管理

预设系统允许同时设置 mode 和 tool，并在首次发送消息前自动验证和纠正：

```python
# Client
client.set_presets(mode="Pro", tool="生成图片")
client.get_presets()  # {"presets": {"mode": "Pro", "tool": "生成图片", "verified": false}}

# 首次 send_input 会自动验证预设
result = client.send_input()  # 内部检查并纠正 mode/tool
```

```bash
# 同时设置
curl -X POST http://localhost:30002/set_presets \
  -H "Content-Type: application/json" \
  -d '{"mode": "Pro", "tool": "image"}'

# 查看预设
curl http://localhost:30002/get_presets
```

## 输入框操作

```python
# Agency
await agency.set_input("你好")      # 清空并设置
await agency.add_input("，世界")    # 追加
text = await agency.get_input()     # 读取 → {"text": "你好，世界"}
await agency.clear_input()          # 清空

# Client
client.set_input("你好")
client.add_input("，世界")
client.get_input()
client.clear_input()
```

```bash
curl -X POST http://localhost:30002/set_input \
  -H "Content-Type: application/json" \
  -d '{"text": "你好"}'

curl -X POST http://localhost:30002/add_input \
  -H "Content-Type: application/json" \
  -d '{"text": "，世界"}'

curl http://localhost:30002/get_input

curl -X POST http://localhost:30002/clear_input
```

## 消息发送

### 同步发送（等待响应）

```python
# Agency: send_message 自动输入 + 发送 + 等待 + 解析
response = await agency.send_message("解释装饰器")
print(response.text)
print(response.markdown)
print(response.code_blocks)

# Client: send_message = set_input + send_input
result = client.send_message("解释装饰器")
print(result["response"]["text"])
```

```bash
# REST API: 先设置输入，再发送
curl -X POST http://localhost:30002/set_input \
  -H "Content-Type: application/json" \
  -d '{"text": "解释装饰器"}'

curl -X POST http://localhost:30002/send_input \
  -H "Content-Type: application/json" \
  -d '{"wait_response": true}'
```

同步响应格式：
```json
{
  "status": "ok",
  "response": {
    "text": "装饰器是...",
    "markdown": "## 装饰器\n\n...",
    "images": [],
    "code_blocks": [{"language": "python", "code": "@decorator\ndef func():..."}],
    "is_error": false
  }
}
```

### 异步发送（不等待响应）

```python
# Agency
result = await agency.send_input(wait_response=False)
# → {"status": "ok", "message": "已发送，不等待响应"}

# Client
result = client.send_input(wait_response=False)
```

## 图片生成

### 使用 Agency

```python
async with GeminiAgency() as agency:
    # 便捷方法：自动启用图片生成工具
    response = await agency.generate_image("一只戴礼帽的猫咪，水彩画风格")

    for img in response.images:
        print(f"URL: {img.url}")
        print(f"尺寸: {img.width}x{img.height}")
        print(f"MIME: {img.mime_type}")
        if img.base64_data:
            img.save_to_file(f"cat_{i}.{img.get_extension()}")

    # 或手动方式
    await agency.set_tool("生成图片")
    response = await agency.send_message("画一只狗", image_mode=True)

    # 批量保存图片
    saved = agency.save_images(response, output_dir="output/images", prefix="dog")
    print(saved)  # ["output/images/dog_1234567_1.jpg", ...]
```

### 使用 Client / REST API

```python
# Client: 通过 store_images 在服务器端保存
client.set_presets(tool="生成图片")
client.new_chat()
client.set_input("画一只猫")
result = client.send_input(wait_response=True)

# 方式一：在服务器端保存图片
saved = client.store_images(output_dir="output/images", prefix="cat")
print(saved)  # {"status": "ok", "image_count": 4, "saved_count": 4, "saved_paths": [...]}

# 方式二：下载图片到客户端本地保存
saved = client.download_images(output_dir="local/images", prefix="cat")
print(saved)  # {"status": "ok", "image_count": 4, "saved_count": 4, "saved_paths": [...]}
```

```bash
# REST API: 在服务器端保存
curl -X POST http://localhost:30002/store_images \
  -H "Content-Type: application/json" \
  -d '{"output_dir": "output/images", "prefix": "cat"}'

# REST API: 下载 base64 数据到客户端
curl -X POST http://localhost:30002/download_images \
  -H "Content-Type: application/json" \
  -d '{"prefix": "cat"}'
# 返回 JSON：{"status": "ok", "images": [{"filename": "cat_xxx_1.jpg", "base64_data": "...", "mime_type": "image/jpeg"}, ...]}
```

## 文件上传

```python
# Agency
await agency.attach("/path/to/document.pdf")
attachments = await agency.get_attachments()  # {"attachments": [...]}
await agency.detach()  # 移除所有附件

# Client
client.attach("/path/to/document.pdf")
client.get_attachments()
client.detach()
```

```bash
curl -X POST http://localhost:30002/attach \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/path/to/document.pdf"}'

curl http://localhost:30002/get_attachments

curl -X POST http://localhost:30002/detach
```

## 消息历史

```python
# Agency
messages = await agency.get_messages()
# {"messages": [
#   {"role": "user", "content": "你好", "html": "..."},
#   {"role": "model", "content": "你好！", "html": "...", "images": [...], "code_blocks": [...]}
# ]}

# Client
messages = client.get_messages()
```

```bash
curl http://localhost:30002/get_messages
```

## 状态查看

```python
# Agency
status = await agency.browser_status()
# {
#   "is_ready": true,
#   "message_count": 3,
#   "image_mode": false,
#   "browser": {"is_started": true, "has_display": true, "has_chrome": true, ...},
#   "page": {"url": "https://gemini.google.com/app/...", "title": "Gemini"},
#   "login": {"logged_in": true, "is_pro": true, "message": "用户已登录 (PRO)"},
#   "mode": {"mode": "Pro"},
#   "tool": {"tool": "none"}
# }

# Client
status = client.browser_status()
```

```bash
curl http://localhost:30002/browser_status
curl http://localhost:30002/health
# {"status": "ok", "version": "4.0.0"}
```

## 调试工具

### 截图

```python
# Agency
await agency.screenshot(path="debug.png")

# Client: 在服务器端保存截图
client.store_screenshot(path="debug.png")

# Client: 下载截图到客户端本地
client.download_screenshot(path="local_debug.png")
```

```bash
# REST API: 在服务器端保存
curl -X POST http://localhost:30002/store_screenshot \
  -H "Content-Type: application/json" \
  -d '{"path": "debug.png"}'

# REST API: 下载 PNG 数据
curl -X POST http://localhost:30002/download_screenshot \
  -H "Content-Type: application/json" \
  -d '{"path": "debug.png"}' --output debug.png
```

### JavaScript 执行（调试用）

```bash
curl -X POST http://localhost:30002/evaluate \
  -H "Content-Type: application/json" \
  -d '{"js": "document.querySelectorAll(\"model-response\").length"}'
```

### 重启 Agency

```python
client.restart()
```

```bash
curl -X POST http://localhost:30002/restart
```

## REST API 完整参考

| 端点 | 方法 | 请求体 | 描述 |
|---|---|---|---|
| `/health` | GET | — | 健康检查 |
| `/browser_status` | GET | — | 浏览器全面状态 |
| `/set_presets` | POST | `{mode?, tool?}` | 设置预设 |
| `/get_presets` | GET | — | 获取预设 |
| `/new_chat` | POST | `{mode?, tool?}` | 新建聊天 |
| `/switch_chat` | POST | `{chat_id}` | 切换聊天 |
| `/get_mode` | GET | — | 获取模式 |
| `/set_mode` | POST | `{mode}` | 设置模式 |
| `/get_tool` | GET | — | 获取工具 |
| `/set_tool` | POST | `{tool}` | 设置工具 |
| `/clear_input` | POST | — | 清空输入框 |
| `/set_input` | POST | `{text}` | 设置输入 |
| `/add_input` | POST | `{text}` | 追加输入 |
| `/get_input` | GET | — | 获取输入 |
| `/send_input` | POST | `{wait_response}` | 发送输入 |
| `/attach` | POST | `{file_path}` | 上传附件 |
| `/detach` | POST | — | 移除附件 |
| `/get_attachments` | GET | — | 获取附件列表 |
| `/get_messages` | GET | — | 获取消息列表 |
| `/store_images` | POST | `{output_dir?, prefix?}` | 服务器端保存图片 |
| `/download_images` | POST | `{prefix?}` | 下载图片 base64 数据 |
| `/store_screenshot` | POST | `{path?}` | 服务器端保存截图 |
| `/download_screenshot` | POST | `{path?}` | 下载截图 PNG 数据 |
| `/chatdb/create` | POST | `{title?, chat_id?}` | 创建聊天记录 |
| `/chatdb/list` | GET | — | 列出所有聊天记录 |
| `/chatdb/stats` | GET | — | 数据库统计信息 |
| `/chatdb/{chat_id}` | GET | — | 获取聊天详情 |
| `/chatdb/{chat_id}` | DELETE | — | 删除聊天 |
| `/chatdb/{chat_id}/title` | PUT | `{title}` | 更新聊天标题 |
| `/chatdb/{chat_id}/messages` | GET | — | 获取聊天消息 |
| `/chatdb/{chat_id}/messages` | POST | `{role, content, files?}` | 添加消息 |
| `/chatdb/{chat_id}/messages/{index}` | GET | — | 获取指定消息 |
| `/chatdb/{chat_id}/messages/{index}` | PUT | `{content?, role?}` | 更新消息 |
| `/chatdb/{chat_id}/messages/{index}` | DELETE | — | 删除消息 |
| `/chatdb/search` | POST | `{query, max_results?}` | 搜索聊天内容 |
| `/restart` | POST | — | 重启 Agency |
| `/evaluate` | POST | `{js}` | 执行 JS（调试） |

## 聊天数据库（ChatDB）

本地 JSON 文件存储的聊天记录管理系统，用于持久化保存聊天历史。

### 数据存储

聊天数据保存在 `data/gemini/chats/` 目录：
```
data/gemini/chats/
├── index.json           # 聊天索引（chat_id → 元数据）
├── {chat_id_1}.json     # 聊天 1 的完整数据
├── {chat_id_2}.json     # 聊天 2 的完整数据
└── ...
```

### 使用 Client

```python
from webu.gemini import GeminiClient, GeminiClientConfig

client = GeminiClient(GeminiClientConfig())

# 创建聊天记录
result = client.chatdb_create(title="Python 学习笔记")
chat_id = result["chat_id"]

# 添加消息
client.chatdb_add_message(chat_id, role="user", content="什么是装饰器？")
client.chatdb_add_message(chat_id, role="model", content="装饰器是一种设计模式...")

# 查看消息列表
messages = client.chatdb_get_messages(chat_id)

# 获取单条消息
msg = client.chatdb_get_message(chat_id, message_index=0)

# 更新消息
client.chatdb_update_message(chat_id, message_index=1, content="更新后的内容")

# 更新标题
client.chatdb_update_title(chat_id, title="Python 进阶笔记")

# 列出所有聊天
chats = client.chatdb_list()

# 搜索聊天内容
results = client.chatdb_search(query="装饰器", max_results=10)

# 获取统计信息
stats = client.chatdb_stats()

# 删除消息
client.chatdb_delete_message(chat_id, message_index=0)

# 删除聊天
client.chatdb_delete(chat_id)
```

### 使用 REST API

```bash
# 创建聊天
curl -X POST http://localhost:30002/chatdb/create \
  -H "Content-Type: application/json" \
  -d '{"title": "Python 学习笔记"}'

# 添加消息
curl -X POST http://localhost:30002/chatdb/{chat_id}/messages \
  -H "Content-Type: application/json" \
  -d '{"role": "user", "content": "什么是装饰器？"}'

# 获取聊天详情
curl http://localhost:30002/chatdb/{chat_id}

# 列出所有聊天
curl http://localhost:30002/chatdb/list

# 搜索
curl -X POST http://localhost:30002/chatdb/search \
  -H "Content-Type: application/json" \
  -d '{"query": "装饰器"}'

# 获取统计
curl http://localhost:30002/chatdb/stats

# 更新标题
curl -X PUT http://localhost:30002/chatdb/{chat_id}/title \
  -H "Content-Type: application/json" \
  -d '{"title": "新标题"}'

# 删除聊天
curl -X DELETE http://localhost:30002/chatdb/{chat_id}
```

### 直接使用 ChatDatabase

```python
from webu.gemini import ChatDatabase

db = ChatDatabase(data_dir="data/gemini/chats")

# 创建聊天
session = db.create_chat(title="测试聊天")

# 添加消息
db.add_message(session.chat_id, role="user", content="你好")
db.add_message(session.chat_id, role="model", content="你好！有什么可以帮您的？")

# 获取聊天
session = db.get_chat(session.chat_id)
for msg in session.messages:
    print(f"[{msg.role}] {msg.content}")

# 搜索
results = db.search_chats("你好")

# 统计
stats = db.get_stats()
print(f"共 {stats['total_chats']} 个聊天，{stats['total_messages']} 条消息")
```

## 配置参考

### 配置文件

默认路径：`configs/gemini.json`（已 gitignore）

```json
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
```

### 编程式配置

```python
from webu.gemini import GeminiConfig

# 从配置文件
config = GeminiConfig(config_path="configs/gemini.json")

# 从字典（覆盖默认值）
config = GeminiConfig(config={"proxy": "http://myproxy:8080", "headless": True})

# 混合：配置文件 + 覆盖
config = GeminiConfig(
    config_path="configs/gemini.json",
    config={"response_timeout": 300000}  # 覆盖文件中的值
)

# 访问属性
print(config.api_port)       # 30002
print(config.proxy)          # http://myproxy:8080
print(config.headless)       # True
```

### GeminiClientConfig

```python
from webu.gemini import GeminiClientConfig

config = GeminiClientConfig(
    host="192.168.1.100",  # 服务器地址
    port=30002,            # API 端口
    timeout=300,           # 请求超时（秒）
    scheme="http",         # http 或 https
)

print(config.base_url)  # "http://192.168.1.100:30002"
```
