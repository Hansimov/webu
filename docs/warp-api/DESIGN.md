# cfwp (CloudFlare WarP) — 架构设计

> 通过 Cloudflare WARP 隧道的 SOCKS5/HTTP 代理服务，提供 CLI 管理和 Tailscale 网络兼容性修复。

---

## 1. 架构概览

```
┌──────────────────────────────────────────────────────────────┐
│                      warp_api 模块                            │
│                                                               │
│  ┌──────────────┐      ┌──────────────────┐                  │
│  │  FastAPI 服务  │      │  WARP 代理服务器    │                  │
│  │  (server.py)  │      │  (proxy.py)       │                  │
│  │               │      │  WarpSocksProxy   │                  │
│  │  /health      │      │                   │                  │
│  │  /warp/*      │      │  SOCKS5 / HTTP    │                  │
│  │  /proxy/stats │      │  :11000           │                  │
│  │  :11001       │      └──────┬────────────┘                  │
│  └──────────────┘             │                               │
│                                │ SO_BINDTODEVICE               │
│                                ▼                               │
│                     ┌─────────────────────┐                   │
│                     │  CloudflareWARP      │                   │
│                     │  (WireGuard tunnel)  │                   │
│                     │  100.96.0.3/32       │                   │
│                     └─────────────────────┘                   │
│                                │                               │
│                                ▼                               │
│                     ┌─────────────────────┐                   │
│                     │  Cloudflare Edge     │                   │
│                     │  Exit IP: 104.28.x.x│                   │
│                     └─────────────────────┘                   │
│                                                               │
│  ┌─────────────────────────────────────────────┐             │
│  │  CLI 管理 (cli.py) — cfwp 命令               │             │
│  │  start / stop / restart / status / logs      │             │
│  │  ip / connect / disconnect / fix             │             │
│  └─────────────────────────────────────────────┘             │
│                                                               │
│  ┌─────────────────────────────────────────────┐             │
│  │  网络修复 (netfix.py)                         │             │
│  │  fix_tailscale_compat — nftables + ip rule   │             │
│  │  fix_ipv6_routing  — ip -6 rule 保护 ndppd   │             │
│  │  fix_dns_routing   — 修复 WARP DNS 劫持       │             │
│  └─────────────────────────────────────────────┘             │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 模块文件结构

```
src/webu/warp_api/
├── __init__.py      # 包入口，导出核心符号
├── __main__.py      # python -m webu.warp_api 入口
├── constants.py     # 端口、接口名、数据目录等配置
├── warp.py          # WarpClient — warp-cli Python 封装
├── proxy.py         # WarpSocksProxy — 异步代理（SOCKS5 + HTTP）
├── server.py        # FastAPI 管理 API
├── cli.py           # cfwp CLI 命令行工具
└── netfix.py        # WARP/Tailscale 网络冲突修复
```

| 模块 | 核心类/函数 | 职责 |
|------|------------|------|
| `constants.py` | `WARP_INTERFACE`, `WARP_PROXY_PORT`, ... | 集中管理所有配置常量 |
| `warp.py` | `WarpClient` | 封装 `warp-cli` 命令，提供 Python API |
| `proxy.py` | `WarpSocksProxy` | 异步代理服务器，流量通过 WARP 转发 |
| `server.py` | `create_warp_server()` | RESTful API，提供状态查询和 WARP 控制 |
| `cli.py` | `main()`, `cfwp` | CLI 服务管理（启停/状态/日志） |
| `netfix.py` | `fix_tailscale_compat()` / `fix_ipv6_routing()` / `fix_dns_routing()` | 修复 WARP 与 Tailscale 网络冲突、IPv6 路由保护、DNS 劫持修复 |

---

## 3. 代理转发机制

代理使用 `SO_BINDTODEVICE` 将出站 socket 绑定到 `CloudflareWARP` 设备:

```python
sock.setsockopt(
    socket.SOL_SOCKET,
    socket.SO_BINDTODEVICE,
    b"CloudflareWARP\0",
)
```

**为什么不用 `bind(IP)`？**

WARP 的路由表 (table 65743) 只包含 Include 范围的路由，不是默认路由。
`bind(100.96.0.3)` 后，内核查路由表时找不到到目标 IP 的路由，连接会失败。
`SO_BINDTODEVICE` 强制流量通过 WireGuard tun 设备，绕过路由表查找。

> ⚠️ `SO_BINDTODEVICE` 需要 `CAP_NET_RAW` 权限，通常需要 root。

---

## 4. 协议支持

代理同时支持三种协议，通过窥探首字节自动检测：

- `0x05` → **SOCKS5** (RFC 1928 CONNECT)
- `CONNECT ...` → **HTTP CONNECT** (HTTPS 隧道)
- `GET/POST/... http://...` → **HTTP Forward Proxy** (明文 HTTP 转发)

```
Client → Proxy(:11000) → [SO_BINDTODEVICE] → CloudflareWARP → Cloudflare Edge → Target

# SOCKS5
curl --socks5-hostname 127.0.0.1:11000 https://example.com

# HTTP CONNECT (HTTPS 隧道)
curl --proxy http://127.0.0.1:11000 https://example.com

# HTTP Forward Proxy (明文 HTTP)
curl --proxy http://127.0.0.1:11000 http://example.com
```

---

## 5. 网络拓扑

```
                         Internet
                            │
                    ┌───────┴───────┐
                    │ Cloudflare    │
                    │ Edge Network  │
                    │ 104.28.208.x  │
                    └───────┬───────┘
                            │ WireGuard
                            │
          ┌─────────────────┼─────────────────────┐
          │                 │                      │
          │    CloudflareWARP (100.96.0.3/32)      │
          │                 │                      │
          │    ┌────────────┴───────────┐          │
          │    │  WarpSocksProxy :11000 │          │
          │    │  Management API :11001 │          │
          │    └────────────┬───────────┘          │
          │                 │            enp100s0f1│
          │    tailscale0   │       (192.168.1.5)  │
          │    (100.99.x.x) │                      │
          │                 │                      │
          │              Server                    │
          └────────────────────────────────────────┘
                    │                    │
            Tailscale mesh          Direct Internet
            (100.x.x.x)            (223.166.172.201)
```

---

*文档更新日期：2026-03-05*（代理绑定 0.0.0.0，DNS/IPv6 修复）
*详细内容请见: SETUP.md, USAGE.md, HINTS.md*
