# cftn Usage

Manage Cloudflare remote-managed tunnels and Aliyun registrar DNS migration from the command line.

## Recommended Workflow

1. 先检查配置结构是否完整：`cftn config-check`。
2. 如果还没有工作 token，先生成或确认 token：`cftn token-ensure --zone-name example.com --cf-token-mode auto --save-config`。
3. 迁移注册商 DNS 到 Cloudflare：`cftn dns-migrate example.com --cf-token-mode auto --save-config`。
4. 用 tunnel 配置把域名入口指向本地服务：`cftn tunnel-apply --name app-example --install-service --save-config`。
5. 检查 tunnel 控制面状态和连接：`cftn tunnel-status --name app-example`。
6. 用 `dig example.com NS`、`dig +trace example.com A` 和实际业务 URL 做最终验证。

## Common Commands

- 初始化空白配置：`cftn config-init --force`
- 查看配置 schema：`cftn config-schema`
- 自动创建或确认工作 token：`cftn token-ensure --zone-name example.com --cf-token-mode auto --save-config`
- 迁移 zone 到 Cloudflare：`cftn dns-migrate example.com --cf-token-mode auto --save-config`
- 应用单个 tunnel：`cftn tunnel-apply --name app-example --install-service --save-config`
- 批量应用所有 tunnel：`cftn tunnel-apply --all --install-service --save-config`
- 查看 tunnel 实时状态：`cftn tunnel-status --name app-example`
- 重新生成文档：`cftn docs-sync`

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
