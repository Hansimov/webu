# WebU

Web Utils for browsing and scraping.

![](https://img.shields.io/pypi/v/webu?label=webu&color=blue&cacheSeconds=60)

## Install

```sh
pip install webu --upgrade
```

默认安装现在只包含最基础的运行依赖：`requests` 和 `tclogger`。
浏览器自动化、FastAPI 服务、面板、代理池、验证码识别、MongoDB、Hugging Face 等重依赖都拆到了可选 extras 里，按需安装即可。

### Common Installs

基础能力，适合 `LLMClient`、`GeminiClient` 这类纯 HTTP 客户端：

```sh
pip install -U webu
```

HTML / 搜索结果解析，适合 `webu.google_api.parser`、`webu.gemini.parser`：

```sh
pip install -U "webu[parsing]"
```

DrissionPage 浏览器能力，适合 `webu.browsers.chrome` 和 `webu.searches.*`：

```sh
pip install -U "webu[browser]"
```

嵌入向量客户端，适合 `webu.embed`：

```sh
pip install -U "webu[embed]"
```

CAPTCHA 自动解题，适合 `webu.captcha`：

```sh
pip install -U "webu[captcha]"
playwright install chromium
```

### Service Installs

Google Search API 服务 `ggsc`：

```sh
pip install -U "webu[google-api]"
playwright install chromium
```

如果还需要内置 Dash 面板：

```sh
pip install -U "webu[google-api,google-api-panel]"
playwright install chromium
```

如果需要自动处理 reCAPTCHA 图片题，再额外加上 `captcha`：

```sh
pip install -U "webu[google-api,captcha]"
playwright install chromium
```

Google Docker / HF Spaces 工具 `ggdk`：

```sh
pip install -U "webu[google-docker]"
playwright install chromium
```

如果还需要内置 Dash 面板：

```sh
pip install -U "webu[google-docker,google-docker-panel]"
playwright install chromium
```

Google Hub 调度服务 `gghb`：

```sh
pip install -U "webu[google-hub]"
```

如果还需要内置 Dash 面板：

```sh
pip install -U "webu[google-hub,google-hub-panel]"
```

Gemini 浏览器服务端能力：

```sh
pip install -U "webu[gemini]"
playwright install chromium
```

Proxy API 服务 `pxsc`：

```sh
pip install -U "webu[proxy-api]"
```

WARP API 服务 `cfwp`：

```sh
pip install -U "webu[warp-api]"
```

Cloudflare Tunnel 工具 `cftn`：

```sh
pip install -U "webu[cf-tunnel]"
```

IPv6 相关能力：

```sh
pip install -U "webu[ipv6]"
```

安装全部功能：

```sh
pip install -U "webu[all]"
playwright install chromium
```

### Extra Summary

| Extra | 适用模块 / 命令 | 说明 |
| --- | --- | --- |
| `parsing` | `webu.google_api.parser`, `webu.gemini.parser` | 仅安装 HTML 解析相关依赖 |
| `browser` / `searches` | `webu.browsers.chrome`, `webu.searches.*` | DrissionPage + 虚拟显示 |
| `embed` | `webu.embed` | 仅安装 `numpy` |
| `captcha` | `webu.captcha` | Playwright + OpenCV + `numpy` + `httpx` |
| `fastapi` | `webu.fastapis.*` | FastAPI / Uvicorn / Pydantic |
| `dashboard` | Google API / Hub 面板 | Dash + A2WSGI |
| `proxy` | `webu.proxy_api.*`, `webu.google_api.proxy_manager` | `aiohttp` / SOCKS / MongoDB |
| `cf-tunnel` | `webu.cf_tunnel.*`, `cftn` | Cloudflare Tunnel CLI 相关依赖 |
| `gemini` | `webu.gemini.*` | Gemini 浏览器服务端所需依赖 |
| `google-api` | `webu.google_api.*`, `ggsc` | Google 搜索服务本体，不含 CAPTCHA 图像解题和 Dash 面板 |
| `google-api-panel` | Google API panel | Google API 的 Dash 面板依赖 |
| `google-docker` | `webu.google_docker.*`, `ggdk` | Google Docker / HF Spaces 工具本体，不含 Dash 面板 |
| `google-docker-panel` | Google Docker panel | Google Docker 的 Dash 面板依赖 |
| `google-hub` | `webu.google_hub.*`, `gghb` | Hub 调度服务本体，不含 Dash 面板 |
| `google-hub-panel` | Google Hub panel | Google Hub 的 Dash 面板依赖 |
| `proxy-api` | `webu.proxy_api.*`, `pxsc` | 代理采集、校验、服务 |
| `warp-api` | `webu.warp_api.*`, `cfwp` | WARP 管理服务 |
| `ipv6` | `webu.ipv6.*` | IPv6 路由、会话、服务 |
| `all` | 全部模块 | 安装所有可选依赖 |
| `dev` | 测试 / 开发 | `pytest` + `pytest-asyncio` |

### Combining Extras

可以一次安装多个功能组：

```sh
pip install -U "webu[google-api,google-api-panel,captcha,google-hub]"
```

### Notes

- `playwright` 只是 Python 包；首次使用浏览器相关功能后，仍需执行 `playwright install chromium`。
- `google-api` / `google-hub` / `google-docker` 现在即使未安装 Dash 也能启动服务，只是不会挂载 panel。
- `import webu` 和若干子包入口现在采用惰性导入，不会再因为未安装某个可选依赖就把整个包导入失败。
- 如果只需要某个轻量子模块，尽量直接安装对应 extra，不要默认使用 `webu[all]`。
