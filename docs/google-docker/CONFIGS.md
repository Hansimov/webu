# 配置模板

> 本文档由 `ggdk docs-sync` 从共享 schema 定义自动生成。

## 最常用的最小配置集合

多数情况下，只需要维护以下三个文件：

1. `configs/hf_spaces.json`
2. `configs/google_api.json`
3. `configs/google_docker.json`

只有在需要验证码远程识别或本地代理时，再补 `captcha.json`、`llms.json`、`proxies.json`。

## 1. `configs/captcha.json`

用途：

1. 指定验证码识别用的 VLM 配置。
2. 可以直接写 endpoint，也可以通过 profile 关联 llms.json。

模板：

```json
{
  "vlm": {
    "profile": "sf_qwen3_vl_8b"
  }
}
```

## 2. `configs/google_api.json`

用途：

1. 约定 google_api 服务的监听参数。
2. 维护不同环境的服务地址和 /search 访问 token。

模板：

```json
{
  "host": "0.0.0.0",
  "port": 18200,
  "proxy_mode": "auto",
  "services": [
    {
      "url": "http://127.0.0.1:18200",
      "type": "local",
      "api_token": ""
    },
    {
      "type": "hf-space",
      "api_token": "your-hf-search-token"
    }
  ]
}
```

说明：

1. type 只允许 local、remote-server、hf-space。
2. api_token 为空表示该环境不强制校验 /search。
3. hf-space 项可以不写 url，此时会从 configs/hf_spaces.json 或 WEBU_HF_SPACE_NAME 自动推导域名。
4. 只有当你真的在用独立远程服务器时，才需要额外添加 remote-server 项。

## 3. `configs/google_docker.json`

用途：

1. 管理 google_docker 的管理接口 token。
2. 作为 /admin/* 的长期鉴权源。
3. ggdk hf-runtime、ggdk hf-logs、ggdk hf-check、ggdk hf-doctor 默认会从这里读 token。

模板：

```json
{
  "admin_token": "your-admin-token"
}
```

## 4. `configs/google_hub.json`

用途：

1. 定义本地中心化调度服务的监听参数和调度策略。
2. 集中管理多个 Google API / HF Space 后端。
3. 供 google_hub 服务执行健康检查、路由和负载均衡。

模板：

```json
{
  "host": "0.0.0.0",
  "port": 18100,
  "strategy": "adaptive",
  "health_interval_sec": 30,
  "health_timeout_sec": 10,
  "request_timeout_sec": 90,
  "backends": [
    {
      "name": "local-google-api",
      "kind": "local-google-api",
      "base_url": "http://127.0.0.1:18200",
      "enabled": true,
      "weight": 2,
      "tags": [
        "local",
        "primary"
      ]
    },
    {
      "name": "space1",
      "kind": "hf-space",
      "space": "owner/space1",
      "enabled": true,
      "weight": 1,
      "tags": [
        "hf",
        "primary"
      ]
    },
    {
      "name": "space2",
      "kind": "hf-space",
      "space": "owner/space2",
      "enabled": true,
      "weight": 1,
      "tags": [
        "hf",
        "secondary"
      ]
    }
  ]
}
```

说明：

1. kind 只允许 local-google-api、google-api、hf-space。
2. hf-space 后端可以只写 space，不写 base_url。
3. search_api_token 和 admin_token 为空时，会回退到现有 google_api/google_docker 配置中的默认 token。

## 5. `configs/hf_spaces.json`

用途：

1. 维护 HF Space 名称和 HF token。
2. 仅用于 CLI 访问 Hugging Face Hub。
3. 第一项会被 ggdk hf-sync、ggdk hf-status、ggdk hf-files 等命令当作默认 Space。

模板：

```json
[
  {
    "space": "owner/space1",
    "hf_token": "your-hf-token",
    "enabled": true,
    "weight": 1,
    "tags": [
      "primary"
    ]
  },
  {
    "space": "owner/space2",
    "hf_token": "your-hf-token",
    "enabled": true,
    "weight": 1,
    "tags": [
      "secondary"
    ]
  }
]
```

说明：

1. 这里不要放 /search 的业务 token。
2. 这里也不要放 admin_token。
3. 可以通过 enabled、weight、tags 参与本地 google_hub 的调度配置。

## 6. `configs/llms.json`

用途：

1. 管理可复用的 LLM/VLM profile。
2. 提供 captcha 等模块统一复用。

模板：

```json
{
  "sf_qwen3_vl_8b": {
    "endpoint": "https://api.siliconflow.cn/v1/chat/completions",
    "api_key": "your-api-key",
    "model": "Qwen/Qwen3-VL-8B-Instruct",
    "api_format": "openai"
  }
}
```

## 7. `configs/proxies.json`

用途：

1. 收敛所有本地代理地址。
2. 供 google_api、gemini、proxy_api、searches 共用。

模板：

```json
{
  "google_api": {
    "proxies": [
      {
        "url": "http://127.0.0.1:11111",
        "name": "proxy-11111"
      },
      {
        "url": "http://127.0.0.1:11119",
        "name": "proxy-11119"
      }
    ]
  },
  "gemini": {
    "default_proxy": "http://127.0.0.1:11119"
  },
  "proxy_api": {
    "fetch_proxy": "http://127.0.0.1:11119"
  },
  "searches": {
    "chrome_proxy": "http://127.0.0.1:11111"
  }
}
```

说明：

1. 该文件只在本地使用，不用于远端环境。

## Schema 用法

初始化最小配置骨架：

```bash
ggdk config-init
```

查看某个配置的 schema：

```bash
ggdk config-schema google_api
```

校验当前本地配置：

```bash
ggdk config-check
```
