# ali_esa 配置指南

本文说明如何在 `webu` 项目中初始化 `ali_esa` 模块，并准备好阿里云 ESA 的站点、凭据和本地运行时配置。

## 适用范围

- 初始化 `configs/ali_esa.json`
- 复用 `configs/cf_tunnel.json` 中已有的阿里云和 Cloudflare 凭据
- 为站点创建、DNS 迁移、公开暴露和 origin pool 检查准备控制面配置
- 明确当前已确认的限制和切换前提

## 运行前提

- 在 `webu` 项目根目录执行命令。
- 使用已经安装项目依赖、并且可以直接调用 `aesa` 的 Python 环境。
- 如需从 Cloudflare 导入 DNS，必须提供能读取对应 zone records 的 Cloudflare token。
- `configs/ali_esa.json` 和 `configs/cf_tunnel.json` 都属于本地敏感运行时配置，不应提交真实凭据或公网回源地址。

本文中的 CLI 示例统一使用：

```bash
aesa
```

以下示例默认当前 shell 已经能直接调用 `aesa`。

## 配置文件关系

- 主配置文件：`configs/ali_esa.json`
- 凭据和 zone 元数据 fallback：`configs/cf_tunnel.json`

`ali_esa.json` 负责保存：

- ESA 默认区域、默认套餐实例、默认 coverage 和 access type
- 公网 IPv4 / IPv6 回源地址
- 每个站点的 ESA 控制面状态，例如 `site_id`、`status`、`verify_code`、`name_server_list`
- Cloudflare zone id、注册商任务号、最近校验时间和最近同步时间

## 初始化配置

先从 `cf_tunnel.json` 生成一份带 fallback 字段的骨架：

```bash
aesa config-init --from-cf-tunnel
```

如果只是生成纯模板，不复用 `cf_tunnel.json`，去掉 `--from-cf-tunnel` 即可。

如果配置文件已经存在，需要显式覆盖：

```bash
aesa config-init --from-cf-tunnel --force
```

生成后立刻校验：

```bash
aesa config-check
```

## 关键字段说明

- `region_id`：ESA API 使用的阿里云地域，默认是 `cn-hangzhou`。
- `default_instance_id`：默认使用的 ESA 套餐实例。账号里如果有多个可选实例，最好固定写入。
- `default_coverage`：默认覆盖范围，当前建议优先使用 `overseas`。
- `default_access_type`：站点接入方式，当前主流程使用 `NS`。
- `public_origin_detection_url`：自动检测公网 IPv4 时使用的地址，默认是 `https://ifconfig.me/ip`。
- `default_public_origin_ipv4`：默认公网 IPv4。`exposure-apply --origin-address auto` 和 `auto6` 都可能依赖它。
- `default_public_origin_ipv6`：默认公网 IPv6。适用于 `auto6` 或 ddns-go / origin pool 方案。
- `aliyun_access_id` / `aliyun_access_secret`：阿里云 ESA 和域名控制面凭据。
- `cf_api_token` / `cf_account_id`：Cloudflare zone 导入所需凭据。
- `sites[]`：每个站点一条记录，保存站点级状态和切换过程中的中间信息。

常见 `sites[]` 字段含义：

- `site_name`：根站点域名。
- `coverage`：站点覆盖范围。
- `access_type`：接入方式，当前通常为 `NS`。
- `instance_id`：该站点绑定的 ESA 套餐实例。
- `site_id`：ESA 返回的站点 ID。
- `status`：ESA 站点状态，例如 `pending`。
- `verify_code`：ESA 分配的站点校验串。
- `name_server_list`：ESA 分配的 NS。
- `current_ns`：当前公网实际解析到的 NS。
- `public_origin_address`：站点级公开回源地址覆盖值。
- `cloudflare_zone_id`：导入 Cloudflare DNS 时使用的 zone id。
- `registrar_task_no`：最近一次注册商 NS 切换任务号。

## 凭据 fallback 规则

- 如果 `aliyun_access_id` 或 `aliyun_access_secret` 留空，`ali_esa` 会回退读取 `configs/cf_tunnel.json` 中的阿里云凭据。
- 如果 `cf_api_token` 或 `cf_account_id` 留空，`ali_esa` 会回退读取 `configs/cf_tunnel.json` 中的 Cloudflare 工作凭据。
- 如果 `sites[].cloudflare_zone_id` 留空，`ali_esa` 会尝试根据 `site_name` 匹配 `cf_tunnel.json` 中的 zone 元数据。
- `default_public_origin_ipv4`、`default_public_origin_ipv6` 和 `sites[].public_origin_address` 只应保存在本地配置，不应硬编码进公开源码或文档。

## 推荐的最小配置模板

```json
{
  "region_id": "cn-hangzhou",
  "default_instance_id": "",
  "default_coverage": "overseas",
  "default_access_type": "NS",
  "public_origin_detection_url": "https://ifconfig.me/ip",
  "default_public_origin_ipv4": "203.0.113.10",
  "default_public_origin_ipv6": "2001:db8::10",
  "aliyun_access_id": "",
  "aliyun_access_secret": "",
  "cf_api_token": "",
  "cf_account_id": "",
  "sites": [
    {
      "site_name": "example.com",
      "coverage": "overseas",
      "access_type": "NS",
      "instance_id": "",
      "site_id": 0,
      "status": "",
      "verify_code": "",
      "name_server_list": [],
      "current_ns": [],
      "public_origin_address": "",
      "cloudflare_zone_id": "",
      "registrar_task_no": "",
      "last_verified_at": "",
      "last_cloudflare_sync_at": "",
      "last_exposure_applied_at": ""
    }
  ]
}
```

其中示例 IP 只用于占位，真实值应写入本地文件，不要复制到仓库中的公开样例或测试断言。

## 推荐初始化顺序

1. 生成或更新 `configs/ali_esa.json`。
2. 手动补齐默认 coverage、instance id 和公网回源地址。
3. 执行 `config-check`，确保 schema 校验通过。
4. 执行 `plan-list`，确认账号下可用的 ESA 套餐实例。
5. 执行 `site-check`，确认目标根域名是否能作为 ESA 根站点创建。
6. 执行 `site-ensure --save-config`，把站点创建结果和 NS 信息写回本地配置。
7. 执行 `site-status`，确认站点状态、分配 NS 和当前公网 NS 是否一致。

## 当前已知限制

- 当前工作流中，普通代理记录使用的是阿里云特有的 `A/AAAA` 类型，而不是标准 `A` 或 `AAAA`。
- `exposure-apply --origin-address auto6` 虽然会优先选择公网 IPv6，但 ESA 侧仍要求同一条代理记录中至少带一个 IPv4 地址。
- ESA 的 `*.origin-pool.<site>` 记录名不能直接拿来当普通代理 `A/AAAA` 记录的值。
- `ddns-go` 已经验证可以维护 ESA origin pool 里的 IPv6 origin，但那是 origin pool 维护路径，不是当前普通公开记录的直接替代方案。
- 在修复 Cloudflare token、补齐 DNS 导入和完成外部回源验证之前，不要执行公网 NS 切换。