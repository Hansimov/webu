# CF Email 配置

`cf_email` 管理 Cloudflare Email Routing，用于开发环境收取注册/重置密码验证码，并把入站邮件交给 Worker 处理。

## 目标链路

```text
register@example.com
  -> user@example.net
  -> Cloudflare Email Routing
  -> Email Worker
  -> account/internal webhook
```

Worker 会把原始 MIME、发件人、收件人和主题 POST 到内部 webhook。内部服务再解析验证码。

Cloudflare Dashboard 的 Email Routing Activity Log 用于查看路由动作、认证状态和投递结果，不是邮箱收件箱；不要依赖 Dashboard 查看邮件正文。需要人工查看正文时，应把邮件转发到一个已验证的目标邮箱，或让 Worker 把原始 MIME 写入受控存储/内部 webhook。

## 开通与域名

1. 域名接入 Cloudflare。
2. 在 Cloudflare Dashboard 进入 Email Service / Email Routing。
3. 启用 Email Routing，并确认域名 MX 指向 Cloudflare，例如：

```text
route1.mx.cloudflare.net
route2.mx.cloudflare.net
route3.mx.cloudflare.net
```

4. 准备一个专用地址，例如 `user1@example.net`，不要把 catch-all 在早期测试时指向公网 webhook。

Cloudflare 文档说明，Routing rule 可以选择 “Send to a Worker”，Worker 名称改动后需要同步修正规则。

## API Token

`cf_account_api_tokens_edit_token` 可以用于通过 API 创建新的 Cloudflare API Token，前提是它本身具备账户级 Token 管理权限。`cfem token-create` 会读取 `cf_tunnel.json` 中的该 bootstrap token，然后创建一个更小权限的 Email Routing token：

```bash
cfem token-create --name cfem-example-email-routing --no-expiry
```

生成 token 会写入忽略提交的 `configs/cf_email.json`。不要把 token 值写入文档、日志或测试输出。

当前工具创建的 token 需要这些权限：

```text
Account: Email Routing Addresses Read
Account: Email Routing Addresses Write
Account: Workers Scripts Read
Account: Workers Scripts Write
Zone: Zone Read
Zone: DNS Read
Zone: DNS Write
Zone: Email Routing Rules Read
Zone: Email Routing Rules Write
```

如果需要用 GraphQL 查询 Email Routing Activity/Analytics，还需要额外授予 Analytics Read。

## 本地配置

```bash
cfem config-init
```

编辑忽略提交的 `configs/cf_email.json`：

```json
{
  "cf_account_id": "",
  "cf_api_token": "",
  "zone_name": "example.net",
  "zone_id": "",
  "worker_name": "account-email-inbox",
  "route_local_part": "user1",
  "webhook_url": "http://127.0.0.1:14567/api/dev/email/inbound",
  "webhook_secret": "",
  "webhook_required": true,
  "forward_to": "",
  "code_regex": "\\b([0-9]{6})\\b"
}
```

本地 webhook 端口使用 `14567` 这类大于 `10000` 的端口，避免和前端、后端、dash 等服务混用。`webhook_secret` 用随机值，且只保存在本地配置或安全密钥系统里。

如果还需要把同一封邮件投递到人工邮箱，把 `forward_to` 设置为 Cloudflare Email Routing 中已经验证过的 Destination Address。该值会通过 Worker secret `FORWARD_TO` 写入，不会出现在 Worker 脚本文本中。

`webhook_required` 默认保持 `true`，这样自动化收信链路不可达时会在 Cloudflare Activity Log 中暴露为 Worker 处理失败。如果某个地址主要用于人工转发，而 webhook 只是临时辅助解析，可设为 `false`，避免 webhook 暂时不可达影响人工收信。

注意：`127.0.0.1` 只能用于本机脚本检查。真实 Cloudflare Worker 无法访问你的本机 loopback 地址。端到端测试时需要：

```bash
cloudflared tunnel --url http://127.0.0.1:14567
```

然后把 `webhook_url` 临时改为 `https://<随机子域>.trycloudflare.com/api/dev/email/inbound`，再部署 Worker。

## Worker 和路由

检查配置：

```bash
cfem config-check
cfem plan
```

部署 Worker，并把 `WEBHOOK_SECRET` 写入 Worker secret：

```bash
cfem worker-deploy
```

创建或确认 `user1@example.net -> account-email-inbox` 的 Email Routing rule：

```bash
cfem ensure-worker-rule --dry-run
cfem ensure-worker-rule
```

如果 `ensure-worker-rule` 返回 `Workers Script Info not found`，说明目标 Worker 还没有部署，先执行 `cfem worker-deploy`。

## 验证

1. 启动本地 webhook，监听 `127.0.0.1:14567`。
2. 用 cloudflared quick tunnel 暴露该 webhook。
3. 更新 `webhook_url` 并执行 `cfem worker-deploy`。
4. 向路由地址发送一封验证码邮件。
5. 确认 webhook 收到 Worker POST，并用 `cfem extract-code` 解析 raw MIME。

示例：

```bash
cfem extract-code .playwright/cf-email-inbound.eml
```

## 参考

- Cloudflare Email Routing rules and addresses：https://developers.cloudflare.com/email-service/configuration/email-routing-addresses/
- Cloudflare Email logs / Activity log：https://developers.cloudflare.com/email-service/observability/logs/
- Cloudflare Email Workers API：https://developers.cloudflare.com/email-service/api/route-emails/email-handler/
- Cloudflare Worker multipart upload metadata：https://developers.cloudflare.com/workers/configuration/multipart-upload-metadata/
- Cloudflare Workers secrets：https://developers.cloudflare.com/workers/configuration/secrets/
