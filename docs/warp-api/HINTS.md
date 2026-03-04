# cfwp — 技术要点与排障

---

## 1. SO_BINDTODEVICE vs bind(IP)

**问题**：`bind(100.96.0.3)` 不能让流量走 WARP 隧道。

**原因**：WARP 路由表 (table 65743) 只包含 Include 范围（`100.96.0.0/12`, `10.250.0.0/24`），不包含默认路由。`bind()` 仅设置源地址，内核仍查路由表找出口 — 找不到到目标 IP 的路由时连接失败。

**解决**：`SO_BINDTODEVICE` 强制流量走指定网络设备，绕过路由表查找。需要 `CAP_NET_RAW`（root）。

---

## 2. WARP/Tailscale 兼容性

### 冲突根源

WARP 的 nftables 表 (`inet cloudflare-warp`) 对 `100.96.0.0/12` 设置了 DROP 规则。
Tailscale 的 CGNAT 地址恰好落在此范围内：

| 地址 | 用途 |
|------|------|
| `100.100.100.100` | Tailscale MagicDNS |
| `100.74.x.x` | Tailscale 节点 |
| `100.99.x.x` | 本机 Tailscale IP |

同时 WARP ip rule (priority 5209) 优先于 Tailscale (priority 5270)。

### 修复方案

`cfwp start` 自动执行 `fix_tailscale_compat()`：

```bash
# 1. nftables: 在 DROP 规则前插入 Tailscale 接口例外
nft insert rule inet cloudflare-warp input  ... iifname "tailscale0" accept
nft insert rule inet cloudflare-warp output ... oifname "tailscale0" accept

# 2. ip rule: 提升 Tailscale 路由优先级
ip rule add priority 5200 table 52    # 在 WARP 的 5209 之前
```

> ⚠️ 这些修复是运行时的，重启后需重新应用。`cfwp start` 启动时自动修复。

---

## 3. IPv4 Only

WARP 接口只有 IPv4 地址（`100.96.0.3/32`），不支持 IPv6。
代理会将目标地址强制解析为 IPv4 (`AF_INET`)。连接 IPv6 目标时返回错误。

IP 检测也强制 IPv4，避免与 `ipv6.route` 配置的 IPv6 出口混淆。

---

## 4. HTTP 代理协议区分

代理通过窥探首字节自动检测协议：

| 首字节 | 协议 | 用途 |
|--------|------|------|
| `0x05` | SOCKS5 | `--socks5-hostname` |
| `C` (CONNECT) | HTTP CONNECT | HTTPS 隧道 (`--proxy https://...`) |
| `G/P/H/D/O` | HTTP Forward | 明文 HTTP 转发 (`--proxy http://...` 访问 `http://`) |

HTTP Forward Proxy 流程：代理解析请求中的绝对 URL，通过 WARP 连接目标，
将请求头中的绝对路径改为相对路径后转发，再将响应原样返回。

---

## 5. 常见问题

### `cfwp start` 提示需要 SUDOPASS

```bash
export SUDOPASS="your_password"
cfwp start
```

### `cfwp stop` 无法停止（权限不足）

`cfwp stop` 已自动使用 `SUDOPASS` + `sudo -S` 提权 kill。
若仍然失败，手动：`echo $SUDOPASS | sudo -S kill -9 $(cat data/warp_api/server.pid)`

### ping baidu.com 超时

可能是 WARP/Tailscale 冲突未修复：

```bash
cfwp fix            # 修复兼容性
cfwp fix --check    # 仅检查状态
```

### 代理返回 empty reply

确认 WARP 已连接：`warp-cli status`，确认代理已启动：`cfwp status`

---

## 6. 已知限制

1. **仅 IPv4**：WARP 接口无 IPv6
2. **需 root**：`SO_BINDTODEVICE` 需要 `CAP_NET_RAW`
3. **Tailscale 修复非持久化**：nftables / ip rule 修复重启后丢失
4. **WARP Include 模式**：非全局代理，通过 `SO_BINDTODEVICE` 强制走隧道

---

*文档更新日期：2026-03-05*
