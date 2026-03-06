# 使用说明

> 本文档由 `ggdk docs-sync` 从共享帮助源自动生成。

## 默认行为

1. 默认 Space：取 configs/hf_spaces.json 中的第一个 space。
2. 默认 HF 服务地址：从 google_api.json 和 hf_spaces.json 自动解析。
3. 默认搜索 token：取 google_api.json 中 hf-space 项的 api_token。
4. 默认管理 token：取 google_docker.json 中的 admin_token。
5. 因此日常使用通常不再需要手写 jq、python heredoc 或 curl。

## 推荐最短路径

```bash
ggdk hub-docker-up --mount-configs --replace
```
```bash
ggdk hub-check
```
```bash
ggdk hf-sync-all
```
```bash
ggdk hub-search "OpenAI news"
```

## 命令速查

### `print-config`

查看当前解析后的运行时配置。

```bash
ggdk print-config
```

### `hub-serve`

以前台方式直接启动中心化 google_hub 服务。

```bash
python -m webu.google_docker hub-serve --host 0.0.0.0 --port 18100
```

### `docker-build`

构建本地 Docker 镜像。

```bash
ggdk docker-build
ggdk docker-build --no-cache
```

### `docker-run`

手动运行本地 Docker 容器。

```bash
ggdk docker-run --bind-source --mount-configs --replace
ggdk docker-run --proxy-mode disabled --replace
```

### `docker-up`

按默认建议完成本地 build + run。

```bash
ggdk docker-up
ggdk docker-up --skip-build
ggdk docker-up --proxy-mode disabled
```

### `docker-check`

检查本地容器状态、服务健康和同端口冲突提示。

```bash
ggdk docker-check
ggdk docker-check --port 18200
```

### `docker-logs`

查看本地 Docker 日志。

```bash
ggdk docker-logs --follow
ggdk docker-logs --lines 50
```

### `docker-down`

停止并删除本地 Docker 容器。

```bash
ggdk docker-down
```

### `hub-docker-up`

构建并启动本地 hub Docker 服务。

```bash
ggdk hub-docker-up --mount-configs --replace
ggdk hub-docker-up --skip-build --port 18100
```

### `hub-docker-down`

停止并删除本地 hub Docker 容器。

```bash
ggdk hub-docker-down
```

### `hub-check`

检查本地 hub 服务和所有后端状态。

```bash
ggdk hub-check
ggdk hub-check --port 18100
```

### `hub-backends`

列出 hub 当前维护的后端状态和指标。

```bash
ggdk hub-backends
```

### `hub-search`

通过中心化 hub 路由搜索请求。

```bash
ggdk hub-search "OpenAI news"
ggdk hub-search "OpenAI news" --num 20
```

### `hf-create-space`

创建新的 HF Docker Space。

```bash
ggdk hf-create-space --space owner/space2 --exist-ok
```

### `hf-url`

打印当前解析出的 HF 服务地址。

```bash
ggdk hf-url
```

### `hf-sync`

同步当前代码到默认 HF Space。

```bash
ggdk hf-sync
ggdk hf-sync --restart --factory
ggdk hf-sync --space owner/other-space
```

### `hf-sync-all`

并行把当前代码同步到所有启用的 HF Spaces。

```bash
ggdk hf-sync-all
ggdk hf-sync-all --restart
ggdk hf-sync-all --max-workers 4
```

### `hf-status`

查看 HF Space 运行状态。

```bash
ggdk hf-status
```

### `hf-health`

读取远端 /health。

```bash
ggdk hf-health
```

### `hf-home`

读取远端隐藏首页。

```bash
ggdk hf-home
```

### `hf-runtime`

读取远端 /admin/runtime。

```bash
ggdk hf-runtime
```

### `hf-search`

向远端 /search 发起请求。

```bash
ggdk hf-search "OpenAI news"
ggdk hf-search "OpenAI news" --num 10
ggdk hf-search "OpenAI news" --no-auth
```

### `hf-check`

聚合远端状态、健康检查、运行时和匿名鉴权检查。

```bash
ggdk hf-check
ggdk hf-check --check-auth
```

### `hf-doctor`

输出更完整的远端诊断信息，包括 bootstrap 文件、提交数和日志摘要。

```bash
ggdk hf-doctor
ggdk hf-doctor --check-auth --lines 80
```

### `hf-logs`

读取远端服务日志。

```bash
ggdk hf-logs
ggdk hf-logs --lines 80
```

### `hf-files`

列出远端仓库文件。

```bash
ggdk hf-files
ggdk hf-files --prefix bootstrap/
```

### `hf-commit-count`

查看远端提交数量。

```bash
ggdk hf-commit-count
```

### `hf-restart`

请求重启远端 Space。

```bash
ggdk hf-restart
ggdk hf-restart --factory
```

### `hf-super-squash`

压缩远端提交历史。

```bash
ggdk hf-super-squash
```

### `config-check`

按共享 schema 校验本地 configs/*.json。

```bash
ggdk config-check
ggdk config-check --name google_api
```

### `config-init`

按共享 schema 生成最小配置骨架。

```bash
ggdk config-init
ggdk config-init --name google_api --force
```

### `config-schema`

打印某个配置文件对应的 schema。

```bash
ggdk config-schema google_api
ggdk config-schema llms
```

### `docs-sync`

用共享说明源重写 docs/google-docker 下的主要文档。

```bash
ggdk docs-sync
```

## 覆盖默认值

1. 操作非默认 Space：加 `--space owner/other-space`。
2. 临时覆盖管理 token：加 `--admin-token ...`。
3. 临时覆盖搜索 token：加 `--api-token ...`。
4. 验证匿名行为：对 `hf-search` 使用 `--no-auth`。
5. 初始化多实例 hub 配置：先运行 `ggdk config-init --name google_hub`。
6. 配置有疑问时，先运行 `ggdk config-check`。
7. 修改帮助源或 schema 后，运行 `ggdk docs-sync` 更新文档。
