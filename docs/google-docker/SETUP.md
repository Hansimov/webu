# 安装与准备

## 最小必需配置

如果你只维护一套默认 HF 目标，通常只需要下面 3 个文件：

1. `configs/hf_spaces.json`
2. `configs/google_api.json`
3. `configs/google_docker.json`

下面这些文件只有在需要对应能力时再补：

1. `configs/captcha.json`
2. `configs/llms.json`
3. `configs/proxies.json`

## `hf_spaces.json`

这是 `ggdk hf-*` 命令默认使用的 Space 列表。

第一项会被当作默认目标。

```json
[
  {
    "space": "owner/space-name",
    "hf_token": "your-hf-token"
  }
]
```

## `google_api.json`

这个文件描述服务监听参数，以及不同环境下的访问方式。

最常用的最小结构如下：

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
			"api_token": "你的长期搜索 token"
		}
	]
}
```

常用规则：

1. 本地 `local` 一般可以不设 token。
2. HF Space 建议配置独立 token，并通过同步逻辑注入为 secret。
3. `hf-space` 项可以不写 `url`，系统会从 `configs/hf_spaces.json` 自动推导域名。
4. 只有当你还维护独立远程服务器时，才需要额外添加 `remote-server` 项。

## `google_docker.json`

这个文件只保留管理接口 token：

```json
{
	"admin_token": "your-admin-token"
}
```

## `proxies.json`

该文件只在本地使用，不用于远端环境。

```json
{
	"google_api": {
		"proxies": [
			{"url": "http://127.0.0.1:11111", "name": "proxy-11111"},
			{"url": "http://127.0.0.1:11119", "name": "proxy-11119"}
		]
	},
	"gemini": {"default_proxy": "http://127.0.0.1:11119"},
	"proxy_api": {"fetch_proxy": "http://127.0.0.1:11119"},
	"searches": {"chrome_proxy": "http://127.0.0.1:11111"}
}
```

如果远程服务器或 HF Space 上没有这个文件，系统会自然退化为无本地代理模式。

## token 生成

生成管理 token 或搜索 token：

```bash
openssl rand -hex 24
```

## 本地 Docker

构建镜像：

```bash
ggdk docker-build --image webu/google-api:dev
```

运行容器：

```bash
ggdk docker-run --bind-source --mount-configs --replace
```

## HF 启动 profile 快照

HF bundle 现在会把本地 `google_api` 的 profile 目录一起打包为启动快照。

默认来源是本地当前生效的 `google_api.profile_dir`。

这个快照现在只保留 cookies、Preferences、Local Storage、WebStorage 等对“真实用户状态”更关键的内容，不再携带大体积组件缓存和浏览历史。

## HF Space 初始化

同步：

```bash
ggdk hf-sync
```

如果要附带 factory rebuild 请求：

```bash
ggdk hf-sync --restart --factory
```
