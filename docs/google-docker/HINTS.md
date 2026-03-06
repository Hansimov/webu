# 使用提示

> 本文档由 `ggdk docs-sync` 从共享帮助源自动生成。

## 先用命令，不要先拼 shell

优先顺序：

1. 状态检查用 `ggdk hf-check` 或 `ggdk hf-doctor`。
2. Docker 本地联调用 `ggdk docker-up`、`ggdk docker-check`、`ggdk docker-down`。
3. 仓库内容排查用 `ggdk hf-files --prefix bootstrap/`。
4. 配置排查用 `ggdk config-init` 和 `ggdk config-check`。

## 常见排查动作

```bash
ggdk hf-health
ggdk hf-runtime
ggdk hf-logs --lines 80
ggdk hf-files --prefix bootstrap/
```

## 推荐诊断顺序

1. `ggdk config-init` 或 `ggdk config-check`
2. `ggdk docker-check` 或 `ggdk hf-check --check-auth`
3. `ggdk hf-doctor --check-auth`
4. `ggdk hf-logs --lines 80`

## 文档维护原则

1. `USAGE.md`、`SETUP.md`、`HINTS.md`、`CONFIGS.md` 都由生成器维护。
2. 命令帮助和文档示例要共用同一份说明源。
3. 配置模板和约束要共用同一份 schema 源。

