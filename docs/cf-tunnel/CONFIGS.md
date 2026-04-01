# Configs

## cf_tunnel

- File: `configs/cf_tunnel.json`
- Purpose: 管理 Cloudflare zone、API token、remote-managed tunnel 和阿里云注册商凭据。
- Purpose: 让 cftn 能在命令行完成 DNS 迁移、Tunnel 创建、Tunnel 安装与状态查询。
- Note: cf_account_api_tokens_edit_token 是可选的 bootstrap token，仅用于自动创建后续更小权限的工作 token。
- Note: cf_api_token 可直接作为工作 token 使用；若为空且选择 --cf-token-mode auto，则优先尝试自动创建。
- Note: 复杂公共后缀域名请显式填写 zone_name，不要依赖自动推断。
- Note: domains[].zone_id、domains[].cloudflare_nameservers、domains[].aliyun_task_no 会在 dns-migrate 成功后自动回写。
- Note: cf_tunnels[].tunnel_id、cf_tunnels[].tunnel_token 会在 tunnel-apply 成功后自动回写。
- Note: cf_tunnels[].cloudflared_run 对应本机 cloudflared service 的 tunnel run 参数，用于稳定 origin 到 Cloudflare edge 的连接。
- Note: 低延迟稳定性当前推荐基线：origin_request.connect_timeout=5、keep_alive_connections=256、keep_alive_timeout=120，并配合 cloudflared_run.protocol=http2、edge_ip_version=4、dns_resolver_addrs=[1.1.1.1:53, 1.0.0.1:53] 作为首选起点。
- Note: 这组参数是当前验证过的首选起点，不代表所有网络都能永久保持 <1s；若访客侧仍抖动，继续用 edge-trace、snapshot 和 client-canary 做分群测量与回滚。
- Note: 本文件包含敏感信息，不应出现在公开文档、测试断言或日志输出中。

Example:
```json
{
  "cf_account_id": "<cloudflare-account-id>",
  "cf_api_token": "",
  "cf_account_api_tokens_edit_token": "",
  "domains": [
    {
      "domain_name": "example.com",
      "zone_name": "example.com",
      "zone_id": "",
      "cloudflare_nameservers": [],
      "aliyun_task_no": ""
    }
  ],
  "cf_tunnels": [
    {
      "tunnel_name": "dev.example.com",
      "zone_name": "example.com",
      "domain_name": "dev.example.com",
      "local_url": "http://127.0.0.1:21002",
      "origin_request": {
        "connect_timeout": 5,
        "keep_alive_connections": 256,
        "keep_alive_timeout": 120
      },
      "cloudflared_run": {
        "protocol": "http2",
        "edge_ip_version": "4",
        "dns_resolver_addrs": [
          "1.1.1.1:53",
          "1.0.0.1:53"
        ]
      },
      "tunnel_id": "",
      "tunnel_token": ""
    }
  ],
  "aliyun_access_id": "",
  "aliyun_access_secret": ""
}
```
