# cfwp — 技术要点与排障

---

## 1. WARP DNS 劫持导致 IPv6 会话无法连接（核心排障案例）

### 现象

IPv6 随机出口会话（`IPv6Session`）在 WARP 启动后无法连接目标服务（如 bilibili API），
报错 `[Errno -5] No address associated with hostname`。

单独测试随机 IPv6 地址的绑定/发包都正常，但 `getaddrinfo()` 对中国 CDN 域名返回空。

### 根因

**WARP 劫持了全局 DNS**：

| 项目 | 详情 |
|------|------|
| WARP 设置的 DNS | `127.0.2.2` / `127.0.2.3`（Cloudflare DOH 代理） |
| routing domain | `~.`（catch-all，所有域名查询都走 WARP DNS） |
| Cloudflare DNS 的问题 | 不返回中国 CDN 域名的 **AAAA 记录** |
| ISP DNS (`192.168.1.1`) | 正常返回 AAAA 记录 |

```bash
# WARP 启动后
dig +short api.bilibili.com AAAA   # 返回空！

# 通过 ISP DNS 查询
dig +short api.bilibili.com AAAA @192.168.1.1
# 2408:8722:1810:107::35
# 2408:873c:6810:3::12  ...
```

`IPv6Session` 通过 `force_ipv6()` 强制使用 `AF_INET6`，当 DNS 无法返回 AAAA 记录时，
`getaddrinfo()` 报 `No address associated with hostname`，所有请求失败。

### 修复

在物理网口设置 routing domain `~.`，使 ISP DNS 优先于全局 WARP DNS：

```bash
sudo resolvectl domain enp100s0f1 ~.
```

**原理**：systemd-resolved 中，接口级 routing domain 优先于全局 routing domain。
将 `~.` 设置在 `enp100s0f1` 上后，该接口的 ISP DNS 成为所有域名查询的首选，
Cloudflare WARP 的全局 DNS 降为备用（且实际上不再有机会处理普通域名查询）。

`cfwp start` 在 `fix_dns_routing()` 中自动执行此操作，幂等设计（重复执行安全）。

### 验证

```bash
resolvectl status enp100s0f1
# DNS Domain: ~.

dig +short api.bilibili.com AAAA
# 2408:8722:1810:107::35  <-- 正常返回

# 测试 IPv6Session
python -m webu.ipv6.route && python -m webu.ipv6.server -p 16000 -n 200 -v
# 正常 spawn 地址并通过 IPv6 访问 bilibili
```

---

## 2. SO_BINDTODEVICE vs bind(IP)

**问题**：`bind(100.96.0.3)` 不能让流量走 WARP 隧道。

**原因**：WARP 路由表 (table 65743) 只包含 Include 范围（`100.96.0.0/12`, `10.250.0.0/24`），不包含默认路由。`bind()` 仅设置源地址，内核仍查路由表找出口 — 找不到到目标 IP 的路由时连接失败。

**解决**：`SO_BINDTODEVICE` 强制流量走指定网络设备，绕过路由表查找。需要 `CAP_NET_RAW`（root）。

---

## 3. WARP/Tailscale 兼容性

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

`cfwp start` 自动执行全部修复：

```bash
# 1. nftables: 在 DROP 规则前插入 Tailscale 接口例外
nft insert rule inet cloudflare-warp input  ... iifname "tailscale0" accept
nft insert rule inet cloudflare-warp output ... oifname "tailscale0" accept

# 2. ip rule: 提升 Tailscale 路由查找优先级
ip rule add priority 5200 table 52    # 在 WARP 的 5209 之前

# 3. ip -6 rule: 保护 ndppd IPv6 前缀流量不被 WARP 路由表捕获
ip -6 rule add priority 5200 from 2408:820c:685a:f860::/64 lookup main

# 4. DNS: 让 ISP DNS 优先于 WARP 全局 DNS
sudo resolvectl domain enp100s0f1 ~.
```

> ⚠️ 这些修复是运行时的，重启后需重新应用。`cfwp start` 启动时自动修复。

---

## 4. IPv6 ndppd 路由保护

**问题**：WARP 的 `ip -6 rule` (priority 5209) 规则：
```
not from all fwmark 0x100cf lookup 65743
```
将所有未打标记的 IPv6 流量送入 table 65743（WARP 路由表）。
通常该表只有 WARP 专用 IPv6 路由，正常流量会 fall-through。
但 WARP 重连或配置变更时，该表可能短暂存在默认路由，捕获 ndppd 随机 IPv6 出口流量，
导致流量被送入 CloudflareWARP 接口，被 nftables `tun` 链 reject。

**修复**：在 WARP 规则之前插入一条专用 ip -6 规则，将 ndppd 前缀流量锁定走 main 表：
```bash
ip -6 rule add priority 5200 from 2408:820c:685a:f860::/64 lookup main
```
`cfwp start` 中 `fix_ipv6_routing()` 自动检测前缀并添加此规则。

---

## 5. IPv4 Only

WARP 接口只有 IPv4 地址（`100.96.0.3/32`），不支持 IPv6。
代理会将目标地址强制解析为 IPv4 (`AF_INET`)。连接 IPv6 目标时返回错误。

IP 检测也强制 IPv4，避免与 `ipv6.route` 配置的 IPv6 出口混淆。

---

## 6. HTTP 代理协议区分

代理通过窥探首字节自动检测协议：

| 首字节 | 协议 | 用途 |
|--------|------|------|
| `0x05` | SOCKS5 | `--socks5-hostname` |
| `C` (CONNECT) | HTTP CONNECT | HTTPS 隧道 (`--proxy https://...`) |
| `G/P/H/D/O` | HTTP Forward | 明文 HTTP 转发 (`--proxy http://...` 访问 `http://`) |

HTTP Forward Proxy 流程：代理解析请求中的绝对 URL，通过 WARP 连接目标，
将请求头中的绝对路径改为相对路径后转发，再将响应原样返回。

---

## 7. 常见问题

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

### IPv6 会话连接失败 / No address associated with hostname

WARP 劫持了全局 DNS，导致中国 CDN 域名无 AAAA 记录：
```bash
cfwp fix          # 包含 DNS 修复
# 或手动
sudo resolvectl domain enp100s0f1 ~.
```

### 从其他机器（Tailscale 节点）使用代理

代理绑定 `0.0.0.0:11000`，直接使用 `<hostname>` 的 Tailscale IP 或主机名：
```bash
curl --proxy http://<hostname>:11000 https://ifconfig.me/ip
curl --socks5-hostname <hostname>:11000 https://ifconfig.me/ip
```

---

## 8. 已知限制

1. **仅 IPv4 出口**：WARP 接口无 IPv6，代理出口 IP 为 IPv4
2. **需 root**：`SO_BINDTODEVICE` 需要 `CAP_NET_RAW`
3. **修复非持久化**：nftables / ip rule / resolvectl 修复重启后丢失，`cfwp start` 自动重新应用
4. **WARP Include 模式**：非全局代理，通过 `SO_BINDTODEVICE` 强制走隧道

---

*文档更新日期：2026-03-05*（新增 DNS 劫持排查、IPv6 ndppd 路由保护、远程访问说明）
