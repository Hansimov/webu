# 部署步骤

> 本文档由 `ggdk docs-sync` 从共享帮助源自动生成。

## 1. 先准备最小配置

必须先准备以下文件：

1. `configs/hf_spaces.json`
2. `configs/google_api.json`
3. `configs/google_docker.json`
4. `configs/google_hub.json`

如果要启用验证码 VLM 或本地代理，再额外维护 `configs/captcha.json`、`configs/llms.json`、`configs/proxies.json`。

配置写完后，先跑一次校验：

```bash
ggdk config-init --name google_hub
ggdk config-check
```

## 2. 本地中心服务启动

```bash
ggdk api-docker-up --mount-configs --replace
ggdk hub-docker-up --mount-configs --replace
gghb check
gghb benchmark --query "OpenAI news" --requests 24 --concurrency 6
```

其中 `ggdk` 负责容器生命周期，`gghb` 负责 hub 本身的检查、查询和 benchmark。

## 3. 同步到 HF Space

```bash
ggdk hf-create-space --space owner/space2 --exist-ok
ggdk hf-sync-all --restart
```

如果想拿到更完整的诊断信息，用：

```bash
ggdk hf-doctor --space owner/space1 --check-auth
ggdk hf-doctor --space owner/space2 --check-auth
```

## 4. 常见临时覆盖

1. 切换 Space：为相关命令追加 `--space owner/other-space`。
2. 切换管理 token：追加 `--admin-token ...`。
3. 切换搜索 token：对 `hf-search` 追加 `--api-token ...`。
4. 本地 hub 直接调试：使用 `gghb serve` 或 `gghb search`。
5. 修改共享说明源后，执行 `ggdk docs-sync`。
