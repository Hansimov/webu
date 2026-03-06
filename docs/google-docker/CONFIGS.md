# 配置模板

本文档汇总 `google_docker` 相关模块的配置模板和说明。

## 最常用的最小配置集合

多数情况下，只需要维护以下三个文件：

1. `configs/hf_spaces.json`
2. `configs/google_api.json`
3. `configs/google_docker.json`

只有在需要验证码远程识别或本地代理时，再补 `captcha.json`、`llms.json`、`proxies.json`。

## 1. `configs/google_api.json`

用途：

1. 约定 `google_api` 服务的监听参数。
2. 维护不同环境的服务地址和 `/search` 访问 token。

模板：

```json
{
  "host": "0.0.0.0",
  "port": 18000,
  "proxy_mode": "auto",
  "services": [
    {
      "url": "http://127.0.0.1:18000",
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

1. `type` 只允许 `local`、`remote-server`、`hf-space`。
2. `api_token` 为空表示该环境不强制校验 `/search`。
3. 当前运行环境会自动选择匹配类型的服务项。
4. `hf-space` 项可以不写 `url`，此时会从 `configs/hf_spaces.json` 或 `WEBU_HF_SPACE_NAME` 自动推导域名。
5. 只有当你真的在用独立远程服务器时，才需要额外添加 `remote-server` 项。

## 2. `configs/google_docker.json`

用途：

1. 管理 `google_docker` 的管理接口 token。
2. 作为 `/admin/*` 的长期鉴权源。
3. `ggdk hf-runtime`、`ggdk hf-logs` 默认会从这里读 token。

模板：

```json
{
  "admin_token": "your-admin-token"
}
```

## 3. `configs/proxies.json`

用途：

1. 收敛所有本地代理地址。
2. 供 `google_api`、`gemini`、`proxy_api`、`searches` 共用。

模板：

```json
{
  "google_api": {
    "proxies": [
      {"url": "http://127.0.0.1:11111", "name": "proxy-11111"},
      {"url": "http://127.0.0.1:11119", "name": "proxy-11119"}
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

## 4. `configs/captcha.json`

用途：

1. 指定验证码识别用的 VLM 配置。
2. 可以直接写 endpoint，也可以通过 `profile` 关联 `llms.json`。

模板：

```json
{
  "vlm": {
    "profile": "sf_qwen3_vl_8b"
  }
}
```

## 5. `configs/llms.json`

用途：

1. 管理可复用的 LLM/VLM profile。
2. 提供 captcha 等模块统一复用。

模板：

```json
{
  "sf_qwen3_vl_8b": {
    "endpoint": "https://api.siliconflow.cn/v1/chat/completions",
    "api_key": "your-api-key",
    "model": "Qwen/Qwen3-VL-8B-Thinking",
    "api_format": "openai"
  }
}
```

## 6. `configs/hf_spaces.json`

用途：

1. 维护 HF Space 名称和 HF token。
2. 仅用于 CLI 访问 Hugging Face Hub。
3. 第一项会被 `ggdk hf-sync`、`ggdk hf-status`、`ggdk hf-files` 等命令当作默认 Space。

模板：

```json
[
  {
    "space": "owner/space-name",
    "hf_token": "your-hf-token"
  }
]
```

说明：

1. 这里不要放 `/search` 的业务 token。
2. 这里也不要放 `admin_token`。