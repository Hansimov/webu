# gghb 使用说明

`gghb` 是本地 `google_hub` 的专用 CLI。

它负责：

1. 本地 hub 进程生命周期。
2. hub 健康检查和后端状态查询。
3. 通过 hub 发起真实搜索。
4. 对 hub 执行顺序和并发 benchmark。
5. 对本地 hub 和远端 HF Spaces 执行发布后真实巡检。

## 常用命令

```bash
gghb start --host 0.0.0.0 --port 18100
gghb status
gghb logs --lines 80
gghb check
gghb backends
gghb search "OpenAI news" --num 5
gghb audit --target all --output data/debug/google_api_hub_and_spaces_audit.json
gghb benchmark --query "OpenAI news" --requests 24 --concurrency 6
gghb restart
gghb stop
```

## 发布后巡检

```bash
# 同时检查本地 hub 和全部远端 HF Spaces
gghb audit --target all

# 只检查远端 HF Spaces，并保存完整 JSON 报告
gghb audit --target spaces --output data/debug/google_api_spaces_audit.json

# 只检查本地 hub
gghb audit --target hub

# 同时打印摘要和完整 JSON
gghb audit --target all --format both
```

`gghb audit` 当前会验证：

1. `/health` 是否正常。
2. `wikipedia` 查询是否返回修复后的 Google Play 结果。
3. 中文 `search_raw` 相关修复是否已在远端 space 生效。
4. 中 / 日 / 法三类查询在未显式指定 `lang` / `locale` 时是否工作正常。

`gghb audit` 的 stdout 默认是人类可读摘要；如果需要机器可解析输出，可使用：

```bash
gghb audit --format json
gghb audit --format both
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