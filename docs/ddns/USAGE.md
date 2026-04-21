# wdns 常用命令

本文整理 `webu.ddns` 模块的常见操作命令，以及与 `aesa` 组合使用时的推荐调试路径。

本文中的域名、路径和记录名示例均已脱敏。请把 `example.com` 一类占位值替换成你自己的实际对象。

## 1. 配置初始化

生成模板：

```bash
wdns config-init
```

校验配置：

```bash
wdns config-check
```

打印 schema：

```bash
wdns config-schema
```

## 2. 管理 target

列出当前 target：

```bash
wdns target-list
```

创建或更新一个 ESA origin-pool target：

```bash
wdns target-upsert \
  --name example-origin-pool \
  --site-name example.com \
  --pool-name example-origin-pool \
  --origin-name home6 \
  --save-config
```

创建或更新一个 ESA direct-record target：

```bash
wdns target-upsert \
  --name example-direct-record \
  --provider aliesa-record \
  --site-name example.com \
  --record-name home.example.com \
  --save-config
```

显式指定 target IPv6 和 ddns-go binary 路径：

```bash
wdns target-upsert \
  --name example-origin-pool \
  --site-name example.com \
  --pool-name example-origin-pool \
  --origin-name home6 \
  --target-ipv6 2001:db8::10 \
  --binary-path /opt/ddns-go/bin/ddns-go \
  --save-config
```

如果要停用某个 target：

```bash
wdns target-upsert \
  --name example-origin-pool \
  --site-name example.com \
  --pool-name example-origin-pool \
  --origin-name home6 \
  --disable \
  --save-config
```

删除一个 target：

```bash
wdns target-delete --name example-origin-pool
```

## 3. 生成 ddns-go YAML 并准备 ESA 对象

准备 target，对应动作包括：

- 确认 ESA site 存在
- origin-pool target：创建或查找 origin pool，并在需要时把 origin 重置成 seed IPv6
- direct-record target：按需创建或回读 direct `A/AAAA` 记录，并在需要时把记录值重置成 seed IPv6，同时切到 DNS-only 模式
- 生成 ddns-go YAML

命令：

```bash
wdns target-prepare --name example-origin-pool
```

如果想先把 origin 覆盖成 seed IPv6，再观察一次真正更新：

```bash
wdns target-prepare --name example-origin-pool --seed-existing
```

## 4. 执行一次 ddns-go 更新

做单次 run-once 验证：

```bash
wdns target-run-once --name example-origin-pool --timeout-seconds 15
```

如果需要先 seed 再跑：

```bash
wdns target-run-once \
  --name example-origin-pool \
  --seed-existing \
  --timeout-seconds 15
```

返回结果里重点关注：

- `ddns_go_config_path`
- `binary_path`
- `process.stdout` / `process.stderr`
- `verified`
- `current_origin_address`
- `current_record_value`

对于 origin-pool target，只要 `verified=true`，并且 `current_origin_address` 已经变成目标 IPv6，就说明这条 `wdns -> ddns-go -> ESA origin pool` 链路已经成立。

对于 direct-record target，只要 `verified=true`，并且 `current_record_value` 已经变成目标 IPv6，就说明这条 `wdns -> ddns-go -> ESA direct AAAA record` 链路已经成立。
对于 direct-record target，只要 `verified=true`，并且 `current_record_value` 已经变成目标 IPv6，就说明这条 `wdns -> ddns-go -> ESA direct A/AAAA record` 链路已经成立。

## 5. 托管为 systemd 服务

安装并启动服务：

```bash
wdns service-install --name example-origin-pool
```

如果希望先 seed 再启动服务：

```bash
wdns service-install --name example-origin-pool --seed-existing
```

查看服务状态：

```bash
wdns service-status --name example-origin-pool
```

查看最近日志：

```bash
wdns service-logs --name example-origin-pool --lines 100
```

重启服务：

```bash
wdns service-restart --name example-origin-pool
```

停用服务：

```bash
wdns service-disable --name example-origin-pool
```

停用并删除 unit 文件：

```bash
wdns service-disable --name example-origin-pool --purge-unit-file
```

## 6. 与 aesa 联动观察 ESA 对象

查看当前 origin pool：

```bash
aesa site-origin-pools \
  --site-name example.com \
  --name example-origin-pool \
  --match-type exact
```

查看 ESA 站点上已有的 load balancer：

```bash
aesa site-load-balancers --site-name example.com
```

查看一个或多个 load balancer 下的 origin health：

```bash
aesa site-load-balancer-origin-status \
  --site-name example.com \
  --load-balancer-id 21 \
  --pool-type default_pool
```

如果不传 `--load-balancer-id`，`aesa` 会先列出站点上的所有 load balancer，再批量查询它们的 origin status。

## 7. 当前推荐调试链路

origin-pool 路径：

1. 用 `aesa site-origin-pools` 确认目标 pool 存在。
2. 用 `wdns target-prepare --seed-existing` 把 pool 准备到可观察状态。
3. 用 `wdns target-run-once` 验证 ddns-go 是否真的把 origin 地址更新回目标 IPv6。
4. 如果准备长期开启，再用 `wdns service-install` 托管为 systemd 服务。
5. 用 `aesa site-load-balancers` 和 `aesa site-load-balancer-origin-status` 继续确认这个 origin pool 是否已经被公网对象引用。

direct-record 路径：

1. 用 `wdns target-prepare --name example-direct-record` 生成 direct-record 的 ddns-go YAML。
2. 如果想观察一次真实改动，用 `wdns target-prepare --name example-direct-record --seed-existing` 先把记录回退到 seed IPv6。
3. 用 `wdns target-run-once --name example-direct-record` 验证 ddns-go 是否真的把 ESA 的 direct `A/AAAA` 记录更新回目标 IPv6。
4. 如果准备长期开启，再用 `wdns service-install --name example-direct-record` 托管为 systemd 服务。

## 8. 常见故障

- `Could not find ddns-go binary`：需要在 `configs/ddns.json` 中设置 `ddns_go_binary` 或 target 级 `binary_path`，或者把 `ddns-go` 放到 PATH。
- `target_ipv6 is required`：`configs/ali_esa.json` 中没有可回退使用的 IPv6，需要在 target 里显式传 `--target-ipv6`。
- `verified=false`：ddns-go 可能没有真正更新 ESA 对象；origin-pool target 继续配合 `aesa site-origin-pools` 排查，direct-record target 则配合 `aesa site-records --record-name <fqdn> --record-type 'A/AAAA'` 排查。
- `service-install` 失败：通常是 sudo / systemd 权限不足，或者目标 binary / YAML 路径不可访问。
- 想用 direct-record 彻底替代当前 Cloudflare bridge：先确认家宽公网 `443/TLS` 入口已经补齐；仅有 DDNS 自动更新还不够，当前实测只确认了 IPv6 `80` 直达，本机并没有可用的公网 `443` 监听。