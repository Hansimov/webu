# ggsc 使用说明

`ggsc` 现在只负责单实例 `google_api`：

1. 后台启动、停止、重启和查看本地 `google_api` 进程。
2. 直接执行单实例搜索调试。
3. 查看和检查本地代理状态。

如果你要管理中心化 hub，请改用 `gghb`。

如果你要管理本地 Docker、HF Spaces、配置模板和部署诊断，请改用 `ggdk`。

## 常用命令

```bash
ggsc start --host 0.0.0.0 --port 18200
ggsc status
ggsc logs --lines 80
ggsc search "OpenAI news" --num 5
ggsc proxy-status
ggsc proxy-check
ggsc restart
ggsc stop
```

## 命令边界

`ggsc` 负责：

1. 单实例 `google_api` 进程。
2. 单实例搜索调试。
3. 本地代理检查。

`ggsc` 不负责：

1. 多后端路由和负载均衡。
2. hub benchmark。
3. Docker 容器生命周期。
4. HF Space 同步和远端诊断。

远端 HF Spaces 和 hub 的发布后巡检请使用 `gghb audit`，不要在 `debugs/` 里维护长期复用脚本。

## 相关 CLI

```bash
# 本地 hub 调试、查询、benchmark
gghb check
gghb search "OpenAI news"
gghb audit --target all
gghb benchmark --query "OpenAI news" --requests 20 --concurrency 5

# Docker / HF / 配置管理
ggdk api-docker-up --mount-configs --replace
ggdk hub-docker-up --mount-configs --replace
ggdk hf-sync-all --restart
```

## 接口调试

```bash
curl http://127.0.0.1:18200/health
curl http://127.0.0.1:18200/proxy/status
curl "http://127.0.0.1:18200/search?q=OpenAI+news&num=5"
```

CLI 输出中的 URL 和文件路径统一通过 `logstr.file()` 以专用颜色渲染，在终端中与普通文本区分。例如：
- 代理 URL：`http://127.0.0.1:11111`（彩色）
- 结果 URL：`https://example.com`（彩色）
- 日志文件路径：`/tmp/ggsc.log`（彩色）
