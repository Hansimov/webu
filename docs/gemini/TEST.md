# Gemini 模块 — 测试与错误处理

## 错误体系

### 错误类层次

所有错误继承自 `GeminiError`，均支持 `message` 和 `details` 属性：

```
GeminiError                      基类，所有错误的父类
├── GeminiLoginRequiredError     用户未登录
├── GeminiNetworkError           网络连接失败（代理等）
├── GeminiTimeoutError           操作超时  (details: timeout_ms)
├── GeminiResponseParseError     响应解析失败 (details: raw_content)
├── GeminiImageGenerationError   图片生成失败
├── GeminiImageDownloadError     图片下载失败
├── GeminiBrowserError           浏览器操作失败
├── GeminiPageError              页面交互失败
├── GeminiRateLimitError         速率限制
└── GeminiServerRollbackError    服务器处理失败，页面回退
```

### 错误详情

| 错误类 | 默认消息 | 特殊字段 | 典型场景 |
|---|---|---|---|
| `GeminiLoginRequiredError` | 用户未登录 Gemini | — | Cookie 过期、首次使用、profile 损坏 |
| `GeminiNetworkError` | 访问 Gemini 时发生网络错误 | `details` | 代理配置错误、网络不通 |
| `GeminiTimeoutError` | 操作超时 | `timeout_ms` | 页面加载超时、响应等待超时 |
| `GeminiResponseParseError` | 解析 Gemini 响应失败 | `raw_content`（截断 500 字符） | DOM 结构变化、空响应 |
| `GeminiImageGenerationError` | 图片生成失败 | `details` | 内容审核拒绝、服务不可用 |
| `GeminiImageDownloadError` | 图片下载失败 | `details` | 新页面导航失败、URL 无效 |
| `GeminiBrowserError` | 浏览器操作失败 | `details` | Chrome 启动失败、GPU 进程崩溃 |
| `GeminiPageError` | 页面交互失败 | `details` | 元素定位失败、弹窗阻断 |
| `GeminiRateLimitError` | 已达到 Gemini 速率限制 | `details` | 请求过于频繁 |
| `GeminiServerRollbackError` | 服务器处理失败，页面已回退 | `details` | 消息提交后后端处理失败，页面自动重置 |

### 源码位置

所有错误类定义在 `src/webu/gemini/errors.py`（约 110 行）。

## HTTP 错误映射

Server 通过 `_handle_gemini_error()` 将错误转换为 HTTP 状态码：

| GeminiError 子类 | HTTP 状态码 | 含义 |
|---|---|---|
| `GeminiLoginRequiredError` | 401 Unauthorized | 需要登录 |
| `GeminiRateLimitError` | 429 Too Many Requests | 速率限制 |
| `GeminiServerRollbackError` | 503 Service Unavailable | 服务端回退 |
| `GeminiTimeoutError` | 504 Gateway Timeout | 操作超时 |
| `GeminiPageError` | 500 Internal Server Error | 页面交互失败 |
| 其他 `GeminiError` | 500 Internal Server Error | 通用错误 |
| 非 Gemini 异常 | 500 Internal Server Error | 意外错误 |

REST API 错误响应格式：
```json
{
  "detail": "具体错误消息 | Details: {\"timeout_ms\": 120000}"
}
```

## 重试机制

### with_retry 装饰器

`agency.py` 中的 `with_retry` 装饰器为异步方法提供自动重试：

```python
@with_retry(max_retries=2)
async def some_operation(self, ...):
    ...
```

**重试策略**：

| 异常类型 | 处理方式 | 说明 |
|---|---|---|
| `GeminiPageError` | ✅ 重试 | 页面交互临时失败，可重试 |
| `PlaywrightTimeoutError` | ✅ 重试 | Playwright 操作超时，可重试 |
| 其他未知异常 | ✅ 重试 | 未知错误也尝试重试 |
| `GeminiLoginRequiredError` | ❌ 立即抛出 | 认证问题无法通过重试解决 |
| `GeminiRateLimitError` | ❌ 立即抛出 | 限流需要等待，不自动重试 |
| `GeminiServerRollbackError` | ❌ 立即抛出 | 回退已在内部处理，不重复重试 |

**退避策略**：`delay × attempt`（线性退避），默认 delay = `GEMINI_RETRY_DELAY`。

**应用范围**：Agency 中有 7 个关键操作使用了 `@with_retry(max_retries=2)`：
- `new_chat` — 新建聊天
- `switch_chat` — 切换聊天
- `set_mode` — 设置模式
- `set_tool` — 设置工具
- `clear_input` — 清空输入
- `set_input` — 设置输入
- `send_input` — 发送消息（含响应等待）

### 回退检测与处理

当 Gemini 后端处理失败时，页面会自动回退到初始状态。`_detect_server_rollback()` 通过以下信号检测：

1. **body class 包含 `zero-state-theme`** — 页面进入空状态主题
2. **欢迎标语可见** — greeting/title 元素在视口内可见
3. **无用户查询和模型响应** — user-query 和 model-response 元素数量均为 0
4. **卡片零状态** — `card-zero-state` 标签出现

检测到回退时抛出 `GeminiServerRollbackError`，由调用方决定是否重试。

## Python 错误处理示例

### 捕获特定错误

```python
from webu.gemini import (
    GeminiClient,
    GeminiClientConfig,
    GeminiError,
    GeminiLoginRequiredError,
    GeminiTimeoutError,
    GeminiRateLimitError,
    GeminiServerRollbackError,
)

client = GeminiClient(GeminiClientConfig())

try:
    result = client.send_message("你好")
except GeminiLoginRequiredError:
    print("请先登录 Gemini")
except GeminiRateLimitError:
    print("请求过快，请稍后再试")
    time.sleep(60)
except GeminiTimeoutError as e:
    print(f"操作超时: {e.details.get('timeout_ms')}ms")
except GeminiServerRollbackError:
    print("服务器回退，自动重试...")
    result = client.send_message("你好")
except GeminiError as e:
    print(f"Gemini 错误: {e.message}")
    print(f"   详情: {e.details}")
```

### HTTP 客户端错误处理

通过 REST API 时，错误以 HTTP 状态码返回：

```python
import requests

resp = requests.post("http://localhost:30002/send_input",
                     json={"wait_response": True})

if resp.status_code == 401:
    print("未登录")
elif resp.status_code == 429:
    print("速率限制")
elif resp.status_code == 503:
    print("服务器回退")
elif resp.status_code == 504:
    print("超时")
elif resp.status_code != 200:
    print(f"错误 {resp.status_code}: {resp.json()['detail']}")
```

## 测试体系

### 测试文件结构

```
tests/gemini/
├── test_gemini.py          # 核心模块单元测试 (1422 行)
├── test_run_server.py      # 运行管理器 + Server/Client 测试 (892 行)
├── test_server_client.py   # Server ↔ Client 测试 (708 行)
├── test_tcp_proxy.py       # TCP 代理测试 (382 行)
├── test_cdp.py             # Chrome DevTools 协议测试 (132 行)
├── test_live.py            # 端到端测试脚本 (336 行)
├── test_live_scenarios.py  # 全场景端到端测试 (349 行)
└── test_live_diag*.py      # 诊断测试脚本
```

### 单元测试分类

#### test_gemini.py（14 个测试类）

| 测试类 | 覆盖范围 |
|---|---|
| `TestErrors` | 所有 10 个错误类的创建、继承、details 字段 |
| `TestConfig` | 3 级配置优先级、配置文件加载、属性访问 |
| `TestParser` | HTML→文本/Markdown/代码块/图片解析 |
| `TestDataClasses` | GeminiResponse / GeminiImage / GeminiCodeBlock 数据类 |
| `TestRetryDecorator` | with_retry 重试逻辑、退避、错误分流 |
| `TestConstants` | URL、端口、CSS 选择器、超时常量 |
| `TestAPIModels` | Pydantic 请求模型的验证 |
| `TestImageSaving` | 图片保存到文件系统 |
| `TestParserBase64Handling` | Base64 图片数据解析 |
| `TestSaveImages` | 批量图片保存（Agency） |
| `TestBrowserIntegration` | 浏览器启动/关闭（集成） |
| `TestChatIntegration` | 聊天操作（集成） |
| `TestImageIntegration` | 图片生成（集成） |
| `TestAPIIntegration` | Server API（集成） |

#### test_run_server.py（14 个测试类）

| 测试类 | 覆盖范围 |
|---|---|
| `TestNormalization` | mode/tool 名称标准化和别名解析 |
| `TestRunStateManagement` | PID/状态文件的读写清除 |
| `TestGeminiRunner` | Runner 初始化和配置 |
| `TestServerModels` | Pydantic 模型和名称标准化 |
| `TestPresetValidation` | 预设验证逻辑（_ensure_presets） |
| `TestClientNewMethods` | Client 新方法 (set_presets, download_images 等) |
| `TestServerEndpoints` | Server 端点 mock 测试 |
| `TestParserImageHandling` | 解析器图片处理 |
| `TestGeminiResponse` | 响应序列化 (to_dict) |
| `TestGeminiConfig` | 配置属性访问 |
| `TestErrors` | 错误类和 HTTP 映射 |
| `TestServerErrorHandling` | Server 错误处理函数 |
| `TestIntegrationRunModule` | 运行管理器集成测试 |
| `TestIntegrationImageGeneration` | 图片生成集成测试 |

#### test_server_client.py（Server ↔ Client 测试）

- `TestClientConfig` — 客户端配置
- Client HTTP mock 测试
- Server 端点 mock 测试
- 完整的 Server ↔ Client 集成测试（标记 `@pytest.mark.integration`）

#### test_tcp_proxy.py

TCP 代理的 Host 头部重写、URL 重写、Content-Length 更新。

### 运行单元测试

```bash
# 运行所有单元测试（排除集成测试）
pytest tests/gemini/ -m "not integration" -v

# 运行特定模块
pytest tests/gemini/test_gemini.py -v
pytest tests/gemini/test_run_server.py -v
pytest tests/gemini/test_server_client.py -v

# 运行特定测试类
pytest tests/gemini/test_gemini.py::TestParser -v
pytest tests/gemini/test_run_server.py::TestNormalization -v

# 运行特定测试方法
pytest tests/gemini/test_gemini.py::TestErrors::test_timeout_error_with_timeout -v

# 显示标准输出
pytest tests/gemini/ -m "not integration" -v -s
```

### 运行集成测试

集成测试需要浏览器和网络，标记为 `@pytest.mark.integration`：

```bash
# 需要先启动服务器
python -m webu.gemini.run start

# 运行集成测试
pytest tests/gemini/ -m integration -v
```

### 运行端到端测试（Live Tests）

Live 测试是独立脚本，不使用 pytest 框架，直接运行：

```bash
# 需要先启动服务器
python -m webu.gemini.run start

# 端到端基础测试
python tests/gemini/test_live.py

# 全场景测试（模式切换、工具切换、多轮对话等）
python tests/gemini/test_live_scenarios.py
```

**Live 测试覆盖的场景**（test_live_scenarios.py）：
1. 模式切换：快速 → 思考 → Pro → 快速
2. 工具切换：生成图片 → Canvas → 无工具
3. 多轮对话
4. 新建聊天后的状态重置
5. 输入框操作边界：空文本、长文本、特殊字符
6. `get_messages` 消息内容验证

截图保存位置：`data/debug/`（基础测试）和 `data/debug/scenarios/`（场景测试）。

## 调试技巧

### 截图调试

遇到问题时随时截图检查页面状态：

```python
client.screenshot(path="data/debug/problem.png")
```

### JavaScript 控制台

通过 `/evaluate` 端点执行 JavaScript 检查 DOM 状态：

```bash
# 检查 model-response 数量
curl -X POST http://localhost:30002/evaluate \
  -H "Content-Type: application/json" \
  -d '{"js": "document.querySelectorAll(\"model-response\").length"}'

# 检查是否有回退状态
curl -X POST http://localhost:30002/evaluate \
  -H "Content-Type: application/json" \
  -d '{"js": "document.body.classList.contains(\"zero-state-theme\")"}'

# 检查输入框内容
curl -X POST http://localhost:30002/evaluate \
  -H "Content-Type: application/json" \
  -d '{"js": "document.querySelector(\".ql-editor\")?.innerText"}'
```

### noVNC 实时观察

在浏览器中打开 `http://<主机名>:30004/vnc_lite.html` 实时观察 Chrome 页面状态。

### 日志追踪

```bash
# 查看最新日志
python -m webu.gemini.run logs

# 实时跟踪日志文件
tail -f data/gemini/gemini.log
```

## 常见错误排查

| 现象 | 可能原因 | 解决方法 |
|---|---|---|
| 401 Unauthorized | Cookie 过期 | 通过 noVNC 手动登录 |
| 429 Too Many Requests | 请求过于频繁 | 增加请求间隔 |
| 503 Service Unavailable | 服务器回退 | 自动重试，或新建聊天 |
| 504 Gateway Timeout | 响应超时 | 增加 `response_timeout`，或检查网络 |
| 500 + "页面交互失败" | 弹窗或 DOM 变化 | 截图检查，或重启 Agency |
| 500 + "浏览器操作失败" | Chrome 崩溃 | 执行 `/restart`，检查 GPU 设置 |
| 500 + "图片下载失败" | URL 过期 | 重新生成图片 |
| 图片生成无结果 | 工具未激活 | 确认 `set_tool("生成图片")` |
| 响应为空 | 页面回退 | 检查 `browser_status` |
| 模式/工具切换失败 | 别名不匹配 | 使用标准名称或查看别名表 |
