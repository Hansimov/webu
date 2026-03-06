# 使用说明

## 默认行为

常用 `ggdk hf-*` 命令现在都会自动读取本地配置：

1. 默认 Space：取 `configs/hf_spaces.json` 中的第一个 `space`。
2. 默认 HF 服务地址：从 `google_api.json` 和 `hf_spaces.json` 自动解析。
3. 默认搜索 token：取 `google_api.json` 中 `hf-space` 项的 `api_token`。
4. 默认管理 token：取 `google_docker.json` 中的 `admin_token`。

所以日常使用通常不再需要手写 `jq`、`python - <<'PY'` 或 `curl`。

## 配置检查

```bash
ggdk print-config
ggdk hf-url
```

## 本地 Docker

```bash
ggdk docker-build
ggdk docker-run --bind-source --mount-configs --replace
ggdk docker-logs --follow
ggdk docker-stop
```

如果只想以前台方式直接跑服务：

```bash
python -m webu.google_docker serve --host 0.0.0.0 --port 18000
```

## HF 日常工作流

同步当前代码：

```bash
ggdk hf-sync
```

同步并请求 factory rebuild：

```bash
ggdk hf-sync --restart --factory
```

查看运行状态：

```bash
ggdk hf-status
```

读取远端日志：

```bash
ggdk hf-logs
```

重启实例：

```bash
ggdk hf-restart
```

压缩远端提交历史：

```bash
ggdk hf-super-squash
```

## 在线接口验证

健康检查：

```bash
ggdk hf-health
```

查看隐藏首页：

```bash
ggdk hf-home
```

查看管理运行时：

```bash
ggdk hf-runtime
```

发起搜索：

```bash
ggdk hf-search "OpenAI news"
```

如果需要临时跳过鉴权头，专门验证匿名行为：

```bash
ggdk hf-search "OpenAI news" --no-auth
```

## 调试与审计

列出远端仓库文件：

```bash
ggdk hf-files
```

只看 bootstrap 相关文件：

```bash
ggdk hf-files --prefix bootstrap/
```

查看远端提交数量：

```bash
ggdk hf-commit-count
```

## 覆盖默认值

只有以下场景才需要额外传参：

1. 操作非默认 Space：加 `--space owner/other-space`。
2. 临时覆盖管理 token：加 `--admin-token ...`。
3. 临时覆盖搜索 token：加 `--api-token ...`。
4. 需要更多搜索结果：加 `--num 10`。
