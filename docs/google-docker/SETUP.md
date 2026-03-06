# 部署步骤

> 本文档由 `ggdk docs-sync` 从共享帮助源自动生成。

## 1. 先准备最小配置

必须先准备以下文件：

1. `configs/hf_spaces.json`
2. `configs/google_api.json`
3. `configs/google_docker.json`

如果要启用验证码 VLM 或本地代理，再额外维护 `configs/captcha.json`、`configs/llms.json`、`configs/proxies.json`。

配置写完后，先跑一次校验：

```bash
ggdk config-init
ggdk config-check
```

## 2. 本地 Docker 启动

```bash
ggdk docker-up
ggdk docker-check
```

如果你已经在本机直接跑了 google_api，又想检查 Docker 状态，优先用 `ggdk docker-check`，它会提示是否出现同端口冲突。

## 3. 同步到 HF Space

```bash
ggdk hf-sync
ggdk hf-check --check-auth
```

如果想拿到更完整的诊断信息，用：

```bash
ggdk hf-doctor --check-auth
```

## 4. 常见临时覆盖

1. 切换 Space：为相关命令追加 `--space owner/other-space`。
2. 切换管理 token：追加 `--admin-token ...`。
3. 切换搜索 token：对 `hf-search` 追加 `--api-token ...`。
4. 修改共享说明源后，执行 `ggdk docs-sync`。
