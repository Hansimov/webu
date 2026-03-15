# cftn Usage

Manage Cloudflare remote-managed tunnels and Aliyun registrar DNS migration from the command line.

## Recommended Workflow

1. 先检查配置结构是否完整：`cftn config-check`。
2. 如果还没有工作 token，先生成或确认 token：`cftn token-ensure --zone-name example.com --cf-token-mode auto --save-config`。
3. 迁移注册商 DNS 到 Cloudflare：`cftn dns-migrate example.com --cf-token-mode auto --save-config`。
4. 用 tunnel 配置把域名入口指向本地服务：`cftn tunnel-apply --name app-example --install-service --save-config`。
5. 检查 tunnel 控制面状态和连接：`cftn tunnel-status --name app-example`。
6. 如果大陆访问慢、必须挂代理或浏览器提示连接不安全，运行：`cftn access-diagnose --name app-example`。
7. 如果页面本身异常、空白、资源报错或疑似 mixed content，运行：`cftn page-audit --name app-example`。
8. 如果要继续判断当前网络命中的 Cloudflare 边缘、colo 和是否适合做客户端侧优选实验，运行：`cftn edge-trace --name app-example`。
9. 用 `dig example.com NS`、`dig +trace example.com A` 和实际业务 URL 做最终验证。

## Common Commands

- 初始化空白配置：`cftn config-init --force`
- 查看配置 schema：`cftn config-schema`
- 自动创建或确认工作 token：`cftn token-ensure --zone-name example.com --cf-token-mode auto --save-config`
- 迁移 zone 到 Cloudflare：`cftn dns-migrate example.com --cf-token-mode auto --save-config`
- 应用单个 tunnel：`cftn tunnel-apply --name app-example --install-service --save-config`
- 批量应用所有 tunnel：`cftn tunnel-apply --all --install-service --save-config`
- 查看 tunnel 实时状态：`cftn tunnel-status --name app-example`
- 诊断 DNS 污染、TLS 异常和大陆访问问题：`cftn access-diagnose --name app-example`
- 审计页面内容、mixed content 和 dev server 暴露：`cftn page-audit --name app-example`
- 查看当前命中的 Cloudflare 边缘与 colo：`cftn edge-trace --name app-example`
- 重新生成文档：`cftn docs-sync`

## Mainland Access Notes

- 社区里常说的“优选 Cloudflare IP”主要适用于直接测试 Cloudflare CDN Anycast IP，或者本地 hosts/自建 DNS 的加速实验。
- 对于 Cloudflare Tunnel 的访客入口，不应该把业务 hostname 改成手选 A 记录 IP；Tunnel 依赖 Cloudflare 托管的代理链路和证书匹配，强行固定 IP 很容易引入证书错误、路由漂移或直接失效。
- `cftn edge-trace` 适合先看当前网络到底打到了哪些 Cloudflare 边缘、返回了什么 colo，再决定是否值得做客户端侧 hosts/本地 DNS 实验。
- 如果大陆用户必须稳定低延迟访问，通常需要额外的接入层，例如香港/日本/新加坡附近的反向代理入口，或者具备合规能力的大陆前置 CDN/加速层。
- 如果 HTTPS 已经启用但浏览器仍提示不安全，除了 DNS 劫持命中错误 IP 之外，还要重点排查页面是否加载了 `http://` 资源或不安全表单。
- 如果页面返回里出现 `@vite/client`、`@vite-plugin-checker-runtime`、`/.quasar/client-entry.js` 这类标记，往往说明你公开的是开发服务器而不是生产构建，这本身就容易带来资源错误、HMR websocket 异常和浏览器安全提示。

## Commands

### dns-migrate

- Summary: 把域名的 DNS 托管从阿里云切到 Cloudflare。
- Examples:
  - `cftn dns-migrate example.com --cf-token-mode auto`
  - `cftn dns-migrate example.com --cf-token-mode manual --save-config`

### tunnel-apply

- Summary: 为某个 domain_name/local_url 创建或更新 remote-managed tunnel。
- Examples:
  - `cftn tunnel-apply --name app-example --install-service`
  - `cftn tunnel-apply --all`

### tunnel-status

- Summary: 查看 tunnel 在 Cloudflare 控制面的状态和连接数。
- Examples:
  - `cftn tunnel-status --name app-example`

### access-diagnose

- Summary: 诊断大陆访问慢、DNS 解析异常、证书异常或浏览器提示连接不安全的问题。
- Examples:
  - `cftn access-diagnose --name app-example`
  - `cftn access-diagnose --hostname app.example.com`

### page-audit

- Summary: 检查页面返回、mixed content、dev server 暴露和静态资源 4xx 问题。
- Examples:
  - `cftn page-audit --name app-example`
  - `cftn page-audit --hostname app.example.com --path /`

### edge-trace

- Summary: 追踪当前命中的 Cloudflare 边缘 IP、colo 和 trace 信息，辅助大陆访问与优选 IP 评估。
- Examples:
  - `cftn edge-trace --name app-example`
  - `cftn edge-trace --hostname app.example.com --path /cdn-cgi/trace`

### config-check

- Summary: 校验 configs/cf_tunnel.json 的结构。
- Examples:
  - `cftn config-check`

### config-init

- Summary: 生成最小配置骨架。
- Examples:
  - `cftn config-init`
  - `cftn config-init --force`

### config-schema

- Summary: 打印 cf_tunnel 的共享 schema。
- Examples:
  - `cftn config-schema`

### docs-sync

- Summary: 重写 docs/cf-tunnel/USAGE.md 和 CONFIGS.md。
- Examples:
  - `cftn docs-sync`

### token-ensure

- Summary: 确保存在可用的 Cloudflare 工作 token，可自动创建或手动输入。
- Examples:
  - `cftn token-ensure --zone-name example.com --cf-token-mode auto`
  - `cftn token-ensure --zone-name example.com --cf-token-mode manual`
