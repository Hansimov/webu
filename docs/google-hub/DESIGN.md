# google_hub CLI 设计

`google_hub` 的 CLI 和 `google_docker` 分离，核心原因是职责不同。

## 目标

`gghu` 只面向 hub 本身：

1. 进程启动与停止。
2. 路由状态可视化和后端检查。
3. 面向 hub 的真实请求验证。
4. 面向 hub 的 benchmark。

## 不放进 ggdk 的原因

1. `ggdk` 已经承担 Docker、本地容器和 HF 运维，如果再叠加 hub 本地查询，会继续膨胀。
2. hub 的 `check`、`backends`、`search`、`benchmark` 都是运行态命令，不属于镜像或远端仓库管理。
3. 把它们拆出来后，`ggdk` 和 `gghu` 的边界更稳定：前者管部署，后者管 hub 行为。

## 运行模型

1. `ggdk hub-docker-up` 负责把 hub 以容器形式拉起。
2. `gghu check` / `gghu backends` / `gghu search` / `gghu benchmark` 负责对这个 hub 实例做真实检查。
3. 如果需要非容器前台调试，则直接使用 `gghu serve`。

## Benchmark 目标

`gghu benchmark` 关注两类结果：

1. 单体性能：平均延迟、`p50`、`p95`、吞吐。
2. 路由质量：后端分布、整体成功率、并发下的稳定性。