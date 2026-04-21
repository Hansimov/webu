# ddns 模块配置指南

本文说明如何在 `webu` 项目中初始化新的 `ddns` 模块，并通过 `wdns` 管理基于 `ddns-go` 的 DDNS 任务与 systemd 服务。

## 模块定位

`webu.ddns` 当前面向两个紧邻的阿里云 DDNS 场景：

- 用 `ddns-go` 维护阿里云 ESA origin pool 中的 origin 地址。
- 用 `ddns-go` 维护阿里云 ESA 站点中的 direct record。
- 把 ddns-go 的配置生成、单次执行和常驻服务管理统一到 `wdns` CLI。
- 避免继续把 DDNS 相关逻辑散落在 `debugs/` 脚本里。

当前已支持的 provider：

- `aliesa-origin-pool`
- `aliesa-record`

## 运行前提

- 在 `webu` 项目根目录执行命令。
- 当前 Python 环境中已经安装了 `webu`，并且可以直接调用 `wdns`、`aesa`。
- 本地已经准备好 `ddns-go` 二进制，或者在 `configs/ddns.json` 中显式配置 `ddns_go_binary` / `binary_path`。
- `configs/ali_esa.json` 中已经具备可用的阿里云 ESA 凭据，或者能通过 `configs/cf_tunnel.json` fallback 获取这些凭据。

本文中的命令示例统一使用：

```bash
wdns
```

## 配置文件

- 主配置文件：`configs/ddns.json`
- 依赖的 ESA 运行时配置：`configs/ali_esa.json`
- 凭据 fallback：`configs/cf_tunnel.json`

`ddns.json` 属于本地运行时配置，不应提交真实站点、origin、binary 路径或公网地址。

## 初始化配置

生成最小骨架：

```bash
wdns config-init
```

如果文件已经存在，需要显式覆盖：

```bash
wdns config-init --force
```

生成后立刻校验：

```bash
wdns config-check
```

## 推荐字段说明

顶层字段：

- `ddns_go_binary`：默认 ddns-go 二进制路径。
- `default_run_interval_seconds`：ddns-go 常驻模式的刷新周期。
- `default_cache_times`：ddns-go 的 IP 缓存次数。
- `targets[]`：DDNS 目标列表。

每个 target 的关键字段：

- `name`：本地 target 标识，也是默认 systemd unit 名称的来源。
- `provider`：当前支持 `aliesa-origin-pool` 或 `aliesa-record`。
- `site_name`：ESA 站点名。
- `pool_name`：目标 origin pool 名称。
- `origin_name`：pool 中具体要维护的 origin 名称。
- `record_name`：当 provider=`aliesa-record` 时要维护的完整记录名。
- `target_ipv6`：目标 IPv6；留空时回退读取 `ali_esa.json`。
- `seed_ipv6`：用于可观察测试的 seed IPv6。
- `ipv6_source_mode`：`cmd` 或 `url`。
- `ipv6_url`：当 `ipv6_source_mode=url` 时使用的 IPv6 获取地址。
- `ttl`：生成 ddns-go YAML 时写入的 TTL。
- `binary_path`：target 级 ddns-go 二进制覆盖路径。
- `config_path`：target 级 ddns-go YAML 输出路径。
- `run_interval_seconds`：常驻服务刷新间隔。
- `cache_times`：ddns-go 缓存次数。
- `service_name`：可选的 systemd unit 名称覆盖值。

## 推荐配置流程

1. 用 `wdns config-init` 生成 `configs/ddns.json`。
2. 用 `wdns target-upsert` 创建一个 ESA origin-pool 或 direct-record target，而不是手工编辑 JSON。
3. 如果误加了 target，用 `wdns target-delete` 清理本地配置。
4. 用 `wdns target-prepare` 确认目标对象和 ddns-go YAML 能正常生成。
5. 用 `wdns target-run-once` 做一次可验证的单次更新。
6. 确认无误后，再用 `wdns service-install` 把目标托管为 systemd 服务。

## 最小示例

```bash
wdns target-upsert \
  --name example-origin-pool \
  --site-name example.com \
  --pool-name example-origin-pool \
  --origin-name home6 \
  --save-config
```

direct-record 示例：

```bash
wdns target-upsert \
  --name example-direct-record \
  --provider aliesa-record \
  --site-name example.com \
  --record-name home.example.com \
  --save-config
```

## 当前已知限制

- 当前 `wdns` 负责维护 ESA origin pool 中的 origin 地址，以及 ESA direct record；它仍然不负责创建更复杂的公网对象，例如 ESA load balancer。
- `aliesa-record` 在 ESA 实际接口上使用 direct `A/AAAA` 记录，并以单个 IPv6 值运行在 DNS-only 模式，适合家宽 IPv6 直出或单独的 IPv6 探测链路，不自动补齐 IPv4 能力。
- `wdns` 生成的 ddns-go YAML 已经验证必须使用 ddns-go 自己 Go YAML marshal 出来的 canonical lower-case 键名。
- 普通 ESA 代理 `A/AAAA` 记录不能直接把 `*.origin-pool.<site>` 记录名当成值；如果需要对公网生效，仍要进一步结合 ESA 的 load balancer / IPA 等对象。
- 如果目标是彻底下线当前 Cloudflare bridge，除了 DDNS 控制面，还必须先补齐本机公网 `443/TLS` 入口；当前仅验证到 IPv6 `80` 可直达，IPv6 `443` 仍拒绝，IPv4 明文入口也未证实可公网直达。