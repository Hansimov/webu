# 使用提示

> 本文档由 `ggdk docs-sync` 从共享帮助源自动生成。

## 先用命令，不要先拼 shell

优先顺序：

1. 单实例 google_api 用 `ggsc`；hub 本身用 `gghb`；容器和 HF 部署用 `ggdk`。
2. Docker 本地联调用 `ggdk api-docker-up`、`ggdk hub-docker-up`、`gghb check`。
3. Space 仓库排查用 `ggdk hf-files --space owner/space1 --prefix bootstrap/`。
4. 配置排查用 `ggdk config-init` 和 `ggdk config-check`。

## 常见排查动作

```bash
gghb check
gghb backends
gghb benchmark --query "OpenAI news" --requests 12 --concurrency 4
ggdk hf-logs --space owner/space1 --lines 80
ggdk hf-files --space owner/space2 --prefix bootstrap/
```

## 推荐诊断顺序

1. `ggdk config-init --name google_hub` 或 `ggdk config-check`
2. `gghb check`
3. `gghb benchmark --query "OpenAI news" --requests 12 --concurrency 4`
4. `ggdk hf-doctor --space owner/space1 --check-auth`
5. `ggdk hf-doctor --space owner/space2 --check-auth`

## 文档维护原则

1. `USAGE.md`、`SETUP.md`、`HINTS.md`、`CONFIGS.md` 都由生成器维护。
2. 命令帮助和文档示例要共用同一份说明源。
3. 配置模板和约束要共用同一份 schema 源。

