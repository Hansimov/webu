# 设计说明

## 目标

`google_docker` 的目标是把 `webu.google_api` 统一到一套可重复的运行模型里，同时覆盖三类环境：

1. 本地源码调试。
2. 本地 Docker 容器运行。
3. Hugging Face Docker Space 远程部署。

## 核心设计

运行时差异统一收敛在 `webu.runtime_settings` 中处理。

当前约束如下：

1. 敏感信息只在运行时注入，不写入镜像。
2. HF 上传只使用最小 bundle，不上传完整仓库。
3. HF bundle 中的 `pyproject.toml` 会做脱敏处理，不包含作者和仓库链接。
4. 本地代理地址只允许存在于 `configs/proxies.json`，不允许硬编码在 `src/webu/`。
5. 远程服务器和 HF Space 默认不依赖本地代理配置。
6. `google_api` 的服务访问配置放在 `configs/google_api.json`，因为它描述的是搜索服务本身，而不是 docker 容器控制逻辑或 HF 仓库信息。

## 服务访问模型

`configs/google_api.json` 中的每个服务项都采用同一结构：

1. `url`：服务地址。
2. `type`：环境类型，只允许 `local`、`remote-server`、`hf-space`。
3. `api_token`：搜索接口 token，可为空；为空表示该环境下不启用搜索鉴权。

这样放置的原因：

1. 这是 `google_api` 的访问面配置，不属于 `google_docker` 容器控制参数。
2. `hf_spaces.json` 只负责 HF 仓库和 HF token，不应该承载搜索接口的业务鉴权配置。
3. `google_api.json` 可以同时描述本地、远程服务器、HF Space 三种服务地址和 token，便于调试和文档统一。

## `/search` 鉴权行为

如果当前环境解析出的 `api_token` 为空，则 `/search` 保持匿名可访问。

如果当前环境解析出的 `api_token` 非空，则：

1. `GET /search` 必须通过查询参数 `api_token` 或请求头 `X-Api-Token` 传入正确 token。
2. `POST /search` 必须通过查询参数 `api_token` 或请求头 `X-Api-Token` 传入正确 token。
3. 缺失或错误时返回 `401 Invalid api token`。

## HF 部署设计

CLI 在同步 HF Space 时会：

1. 生成最小上传 bundle。
2. 用 `delete_patterns="*"` 清除远端陈旧文件。
3. 注入 `WEBU_ADMIN_TOKEN`。
4. 注入 `WEBU_GOOGLE_API_TOKEN`，使 HF Space 的 `/search` 可以独立鉴权。
5. 将本地 `google_api` profile 目录打包为 bootstrap 快照，在新容器首次启动时灌入运行目录，用于尽量保留已有的 Google Cookie / 浏览器状态。

## CLI 简化策略

常用的 HF 运维动作已经被收敛到 `ggdk`：

1. `ggdk hf-sync`、`ggdk hf-status`、`ggdk hf-logs` 默认直接使用 `hf_spaces.json` 的第一项。
2. `ggdk hf-health`、`ggdk hf-home`、`ggdk hf-runtime`、`ggdk hf-search` 不再要求手写 `curl`。
3. `ggdk hf-files`、`ggdk hf-commit-count` 不再要求手写 `python - <<'PY'`。
4. `ggdk hf-url` 负责打印当前解析出的服务地址，便于脚本和排查。
5. `ggdk hf-check` 负责把状态、健康检查、管理运行时和匿名鉴权检查聚合到一次输出里。

本地 Docker 工作流也做了同样的简化：

1. `ggdk docker-up` 用默认参数完成 build + run。
2. `ggdk docker-down` 统一 stop/remove。
3. `ggdk docker-check` 聚合容器运行状态、本地 `/health` 和 `/admin/runtime` 检查。

## 管理接口

`/admin/runtime`
返回运行时环境、服务类型、服务地址、是否配置搜索 token。

`/admin/config`
返回当前生效配置，但不会返回 token 明文。

`/admin/logs`
返回日志 tail。

所有 `/admin/*` 都继续由 `WEBU_ADMIN_TOKEN` 保护。