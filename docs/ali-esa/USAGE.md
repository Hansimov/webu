# ali_esa 常用命令

本文整理 `ali_esa` 模块的常见操作命令和一条已验证通过的 ddns-go / ESA origin pool 调试路径。

命令默认在 `webu` 项目根目录执行，统一使用：

```bash
aesa
```

本文中的域名、路径和记录名示例均已脱敏。请把 `example.com` 一类占位值替换成你自己的实际对象。

如果需要显式指定项目根目录或配置目录，可以给任意子命令追加：

```bash
--project-root /abs/path/to/webu --config-dir /abs/path/to/webu/configs
```

## 1. 配置和站点检查

打印 schema：

```bash
aesa config-schema
```

校验本地配置：

```bash
aesa config-check
```

查看账号下可用的 ESA 套餐实例：

```bash
aesa plan-list
```

检查目标域名能否创建站点，以及 ESA 中是否已经存在：

```bash
aesa site-check --site-name example.com
```

确保站点存在，并把站点状态写回 `configs/ali_esa.json`：

```bash
aesa site-ensure \
  --site-name example.com \
  --coverage overseas \
  --access-type NS \
  --save-config
```

如果站点已经存在，`site-ensure` 现在也会在你显式传入 `--coverage` 或 `--access-type` 时同步更新远端站点配置。这意味着站点级 canary 可以直接用同一条命令推进，例如：

```bash
aesa site-ensure \
  --site-name example.com \
  --coverage global
```

如果你尝试把站点切到 `global` 或 `domestic` 时收到 `InvalidSiteICP`，那不是 CLI 自身的问题，而是 ESA 控制面要求该站点具备有效 ICP 备案后才能启用对应覆盖范围。此时站点会继续停留在原有 coverage，不会被半切换到中间状态。

查看站点状态、分配的 NS 和当前公网 NS：

```bash
aesa site-status --site-name example.com
```

## 2. 查看 ESA 记录和 origin pool

列出站点上的 ESA 记录：

```bash
aesa site-records --site-name example.com
```

按记录名过滤：

```bash
aesa site-records \
  --site-name example.com \
  --record-name search.example.com
```

按类型过滤，例如只看阿里云 `A/AAAA` 代理记录：

```bash
aesa site-records \
  --site-name example.com \
  --record-type A/AAAA
```

列出 origin pool：

```bash
aesa site-origin-pools --site-name example.com
```

创建或更新一个 origin pool，并确保指定 origin 指向目标地址：

```bash
aesa site-origin-pool-upsert \
  --site-name example.com \
  --pool-name relay-origin-canary \
  --origin-name hk4 \
  --origin-address ***.***.**.***
```

这个命令适合把 HK relay 之类的 IPv4 回源地址正式纳入 ESA origin pool 管理，而不需要借助 `wdns` 的 IPv6-only 流程。

在更新公开 helptext、文档或测试示例前，建议先跑一次：

```bash
conda run -n ai python -m webu.safety_scan --root .
```

它会扫描当前仓库的 tracked `docs/`、`src/`、`tests/` 等文本文件，检查是否误带入了本地运行时配置中的真实站点名、NS、IP、token 或其他敏感值。

精确匹配某一个 pool：

```bash
aesa site-origin-pools \
  --site-name example.com \
  --name example-ddns-probe \
  --match-type exact
```

模糊匹配：

```bash
aesa site-origin-pools \
  --site-name example.com \
  --name probe \
  --match-type fuzzy
```

列出 ESA load balancer：

```bash
aesa site-load-balancers --site-name example.com
```

按名称过滤 load balancer：

```bash
aesa site-load-balancers \
  --site-name example.com \
  --name search \
  --match-type fuzzy
```

查看一个或多个 load balancer 下的 origin 健康状态：

```bash
aesa site-load-balancer-origin-status \
  --site-name example.com \
  --load-balancer-id 21 \
  --pool-type default_pool
```

如果不传 `--load-balancer-id`，`aesa` 会先列出站点上的所有 load balancer，再批量查询这些对象的 origin status。

创建一个最小可用的 load balancer probe：

```bash
aesa site-load-balancer-create \
  --site-name example.com \
  --name lb-probe \
  --default-pool-name example-origin-pool \
  --monitor-type off
```

如果只知道 pool ID，也可以直接传 ID：

```bash
aesa site-load-balancer-create \
  --site-name example.com \
  --name lb-probe \
  --default-pool-id 101 \
  --fallback-pool-id 101 \
  --monitor-type off
```

删除一个 probe load balancer：

```bash
aesa site-load-balancer-delete \
  --site-name example.com \
  --name lb-probe.example.com
```

如果当前 ESA 套餐没有可用的 load balancer 配额，`aesa site-load-balancer-create` 会直接报出明确错误，例如：

```text
ESA load balancer 'lb-probe.example.com' cannot be created on site 'example.com' because the current plan does not expose usable load balancer quota
```

创建一个直接引用 origin pool 的代理 CNAME：

```bash
aesa site-origin-pool-cname-apply \
  --site-name example.com \
  --record-name op-probe \
  --pool-name example-origin-pool \
  --biz-name web
```

这个命令会创建或更新一个：

- `RecordType=CNAME`
- `Proxied=true`
- `RecordSourceType=OP`

并把记录值写成目标 origin pool 的 `RecordName`。

删除这条 OP-backed CNAME：

```bash
aesa site-origin-pool-cname-delete \
  --site-name example.com \
  --record-name op-probe.example.com
```

## 3. 从 Cloudflare 导入 DNS

把当前 Cloudflare zone 记录导入 ESA：

```bash
aesa site-sync-cloudflare-dns \
  --site-name example.com \
  --save-config
```

如果只想尽力导入，遇到不支持的记录类型跳过而不是整批失败：

```bash
aesa site-sync-cloudflare-dns \
  --site-name example.com \
  --allow-skip-unsupported \
  --save-config
```

按完整记录名排除：

```bash
aesa site-sync-cloudflare-dns \
  --site-name example.com \
  --skip-record-name dev.example.com \
  --skip-record-name old.example.com
```

导入逻辑会自动跳过：

- SOA
- 根域的 NS
- 指向 `cfargotunnel.com` 的旧 Cloudflare Tunnel 记录
- 严格模式下不支持的 Cloudflare 记录类型

如果当前 Cloudflare token 已失效或无 zone 读取权限，导入会直接失败。这是当前已知的真实阻塞项之一。

## 4. 创建或更新公开暴露记录

把某个公开域名指向本机服务，并创建配套回源规则：

```bash
aesa exposure-apply \
  --domain-name search.example.com \
  --local-url http://127.0.0.1:8930 \
  --origin-address auto \
  --save-config
```

`exposure-apply` 现在默认会对 `Site.ServiceBusy` 之类的 ESA 控制面抖动做有限重试，并在记录已经被改动但最终 apply 失败时尝试恢复先前的公网记录。需要调节时可以显式传：

```bash
aesa exposure-apply \
  --domain-name search.example.com \
  --local-url http://127.0.0.1:8930 \
  --origin-address auto \
  --retry-attempts 5 \
  --retry-delay-seconds 0.5
```

如需关闭失败回滚保护，可以额外传 `--no-restore-on-failure`，但这只适合你明确接受失败窗口的场景。

如果希望优先走公网 IPv6：

```bash
aesa exposure-apply \
  --domain-name search.example.com \
  --local-url http://127.0.0.1:8930 \
  --origin-address auto6 \
  --save-config
```

如果当前公网 IPv4 并不适合作为 ESA 回源，而你已经有一个由 `wdns` 维护的 IPv6 origin pool，可以改成让公开 hostname 通过 origin pool 暴露：

```bash
aesa exposure-apply \
  --domain-name search.example.com \
  --local-url http://127.0.0.1:8930 \
  --zone-name example.com \
  --record-mode origin-pool \
  --origin-pool-name pool-alpha-prod \
  --biz-name web \
  --purge-conflicts \
  --save-config
```

这个模式会同时做两件事：

- 创建或更新一个 `RecordType=CNAME`、`Proxied=true`、`RecordSourceType=OP` 的公开记录。
- 为该 hostname 创建或更新 ESA origin rule，把流量送到 `--local-url` 对应的本机端口。

如果站点的真实 origin 仍然只能通过现有 Cloudflare Tunnel 对外提供，而你又已经把权威 NS 切到了 ESA，可以改成让 ESA 通过 Cloudflare 双栈边缘地址做 HTTPS bridge：

```bash
aesa exposure-apply \
  --domain-name search.example.com \
  --local-url https://127.0.0.1:443 \
  --zone-name example.com \
  --record-mode direct \
  --origin-address cloudflare \
  --purge-conflicts \
  --save-config
```

这个模式会从本地 `configs/ali_esa.json` 里保存的 `sites[].cloudflare_name_server_list` 直接查询旧 Cloudflare 权威 NS 的 A/AAAA 结果，并生成：

- 指向当前 Cloudflare 双栈边缘地址的 ESA 代理 `A/AAAA` 记录。
- `OriginScheme=https`、`OriginHttpsPort=443`、`OriginSni=<hostname>` 的 hostname 级 origin rule。

它适合“ESA authoritative DNS 已接管，但 ESA edge 还不能直连真实 home origin”的过渡阶段。这个模式不会覆盖 `sites[].public_origin_address` 中保存的真实回源地址。

这里有两个必须牢记的限制：

- ESA 当前公开代理路径使用的是 `A/AAAA`，不是独立 `AAAA`。
- 即使使用 `auto6`，ESA 仍要求记录值中至少包含一个 IPv4 地址；因此请先在 `configs/ali_esa.json` 中配置 `default_public_origin_ipv4`。

如果使用 `--record-mode origin-pool`，上面第二条 IPv4 限制就不再由公开记录承担，而是改由 origin pool 自己维护真实回源地址。这也是当前公网 IPv4 不通、但公网 IPv6 可用时更稳妥的路径。

应用后可以再次用 `site-records` 检查生成的记录值和代理状态。

## 5. 用 DNS-01 管理 ACME TXT 记录

创建或复用一个 `_acme-challenge` TXT 记录：

```bash
aesa dns-01-auth \
  --site-name example.com \
  --domain api.example.com \
  --validation test-token \
  --wait-seconds 15
```

删除这条 TXT 记录：

```bash
aesa dns-01-cleanup \
  --site-name example.com \
  --domain api.example.com \
  --validation test-token
```

如果命令是由 `certbot --manual` 调用，`aesa` 会自动读取 `CERTBOT_DOMAIN` / `CERTBOT_IDENTIFIER` / `CERTBOT_VALIDATION`，因此 hook 里通常只需要固定 `--site-name`、`--project-root` 和 `--config-dir`。

下面是一条已经实测通过的 staging 签发模式；它不会为了 ACME 验证去暴露公网 `80/443`：

```bash
certbot certonly --manual --preferred-challenges dns \
  --manual-auth-hook 'conda run -n ai aesa dns-01-auth --project-root /abs/path/to/webu --config-dir /abs/path/to/webu/configs --site-name example.com --wait-seconds 15' \
  --manual-cleanup-hook 'conda run -n ai aesa dns-01-cleanup --project-root /abs/path/to/webu --config-dir /abs/path/to/webu/configs --site-name example.com' \
  --register-unsafely-without-email \
  --agree-tos \
  --non-interactive \
  --test-cert \
  --config-dir /tmp/certbot/config \
  --work-dir /tmp/certbot/work \
  --logs-dir /tmp/certbot/logs \
  -d api.example.com
```

需要注意两点：

- DNS-01 只解决“证书怎么签发”的问题，不解决“浏览器如何直连到 home origin”的问题。
- 如果最终目标是让 ESA 直接回源到家宽主机，那么真实公网 `443` 仍然必须可达；DNS-01 不能替代真实业务流量的公网入站能力。

## 6. 生成 ESA edge 快照

对一个或多个域名抓取当前解析结果和 ESA edge 匹配情况：

```bash
aesa snapshot --name search.example.com
```

指定输出目录：

```bash
aesa snapshot \
  --name search.example.com \
  --name api.example.com \
  --output-dir debugs/ali-esa-snapshots
```

如果快照里看到 `dns_lookup_failed`、`dns_mismatch` 或 `recursive_dns_mismatch`，说明公网 DNS 还没有完全切到 ESA edge。

## 6. 切换注册商 NS

仅在 ESA 站点、记录和公网回源验证都准备好之后，才执行 NS 切换：

```bash
aesa site-activate-ns \
  --site-name example.com \
  --wait \
  --verify-site \
  --save-config
```

常用参数：

- `--wait`：轮询注册商任务直到不再是 pending。
- `--verify-site`：切换后轮询 ESA 的站点校验结果。
- `--verify-attempts`：校验尝试次数。
- `--verify-interval-seconds`：校验间隔秒数。

如果当前站点仍处于 `pending`，且公网 NS 还没有切到 ESA，那么这个命令依然不应提前执行。

## 7. ddns-go 与 ESA origin pool 实测流程

这一部分是目前已经跑通的实验路径，用于验证“纯 IPv6 origin pool 可行，且能被 ddns-go 更新”。

### 7.1 生成测试 pool 和 ddns-go 配置

```bash
cd <webu-project-root>
python debugs/ddns_go_aliesa_origin_pool_probe.py \
  --site-name example.com \
  --pool-name example-ddns-probe \
  --origin-name origin-alpha \
  --seed-existing
```

这个调试脚本会：

- 读取 `ali_esa.json` 和必要的 fallback 凭据
- 创建或查找指定的 origin pool
- 在需要时把 origin 重置为一个 seed IPv6，方便观察后续更新是否真的发生
- 生成 ddns-go 配置文件 `debugs/ddns-go/example-ddns-probe.yaml`

### 7.2 用 Go 探针验证配置是否被 ddns-go 正确加载

查看 ddns-go 自己 marshal 出来的 canonical YAML 形状：

```bash
cd <webu-project-root>/debugs/ddns_go_run_once
go run . --show-template
```

用 one-shot 探针执行一次 `dns.RunOnce()`：

```bash
cd <webu-project-root>/debugs/ddns_go_run_once
go run . ../ddns-go/example-ddns-probe.yaml
```

如果输出中看到 `dns_conf_count: 1`，说明配置已经被 ddns-go 正确加载。

关键注意事项：

- ddns-go 识别的是它自己 Go 结构体 marshal 出来的全小写 YAML 键，例如 `dnsconf`、`dns`、`gettype`、`httpinterface`。
- 如果误写成 `DnsConf`、`DNS`、`GetType` 这类 JSON 风格键名，ddns-go 会静默加载出 `0` 个 provider。

### 7.3 用真实 ddns-go 二进制执行一次更新

```bash
cd <webu-project-root>/debugs/ddns-go/bin
timeout 15s ./ddns-go -noweb -c ../example-ddns-probe.yaml -f 300 -cacheTimes 1
```

在 2026-04-21 的实测中，这条命令已经成功把 `example-ddns-probe.origin-pool.example.com?Name=origin-alpha` 对应的 origin 地址从 `2001:db8::1` 更新为真实公网 IPv6。

### 7.4 回读 ESA 控制面确认更新结果

```bash
cd <webu-project-root>
aesa site-origin-pools \
  --site-name example.com \
  --name example-ddns-probe \
  --match-type exact
```

只要 `Origins[].Address` 已经变成目标公网 IPv6，就说明这条 ddns-go -> ESA origin pool 的更新链路已经成立。

如果要继续确认这个 origin pool 是否已经被 ESA 公网对象引用，可以再执行：

```bash
aesa site-load-balancers --site-name example.com
```

以及：

```bash
aesa site-load-balancer-origin-status --site-name example.com
```

## 8. 常见故障与解释

- `dns_conf_count: 0`：ddns-go 配置键名不对，通常是把 canonical lower-case YAML 写成了 `Dns` / `GetType` 风格。
- `Record.AorAAAARecordValueContainInvalidIP`：你把 `*.origin-pool.<site>` 记录名当成了普通代理 `A/AAAA` 记录的值。ESA 当前不接受这种写法。
- Cloudflare 导入时报鉴权错误：当前 token 无法读取 zone records，需要换成具备相应权限的新 token。
- `site-status` 里 ESA 还是 `pending`：通常代表注册商 NS 还没有切过去，或者 ESA 还没有完成校验。

## 9. 当前结论

- 纯 IPv6 的 ESA origin pool 已经验证可创建、可查询、可由 ddns-go 自动更新。
- 普通公开代理 `A/AAAA` 记录目前不能直接引用 origin pool 记录名。
- 因此，ddns-go 当前的价值是“维护 origin pool 中的真实回源地址”，而不是直接替代现有公开代理记录流程。