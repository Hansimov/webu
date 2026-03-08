# gghb 使用说明

`gghb` 是本地 `google_hub` 的专用 CLI。

它负责：

1. 本地 hub 进程生命周期。
2. hub 健康检查和后端状态查询。
3. 通过 hub 发起真实搜索。
4. 对 hub 执行顺序和并发 benchmark。

## 常用命令

```bash
gghb start --host 0.0.0.0 --port 18100
gghb status
gghb logs --lines 80
gghb check
gghb backends
gghb search "OpenAI news" --num 5
gghb benchmark --query "OpenAI news" --requests 24 --concurrency 6
gghb restart
gghb stop
```

## 与其他 CLI 的关系

```bash
# 单实例 google_api
ggsc search "OpenAI news"

# 本地 / 远端部署
ggdk api-docker-up --mount-configs --replace
ggdk hub-docker-up --mount-configs --replace
ggdk hf-sync-all --restart
```

## 推荐排查顺序

```bash
ggdk config-check
ggdk api-docker-up --mount-configs --replace
ggdk hub-docker-up --mount-configs --replace
gghb check
gghb benchmark --query "OpenAI news" --requests 12 --concurrency 4
```