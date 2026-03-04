# cfwp (CloudFlare WarP) — warp_api 设计文档

> 通过 Cloudflare WARP 隧道的 SOCKS5/HTTP CONNECT 代理服务，提供 CLI 管理和 Tailscale 网络兼容性修复。

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
│  └─────────────────────────────────────────────┘             │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 模块说明

### 2.1 模块文件结构

```
src/webu/warp_api/
├── __init__.py      # 包入口，导出核心符号
├── __main__.py      # python -m webu.warp_api 入口
├── constants.py     # 端口、接口名、数据目录等配置
├── warp.py          # WarpClient — warp-cli Python 封装
├── proxy.py         # WarpSocksProxy — 异步 SOCKS5/HTTP CONNECT 代理
├── server.py        # FastAPI 管理 API
├── cli.py           # cfwp CLI 命令行工具
└── netfix.py        # WARP/Tailscale 网络冲突修复
```

### 2.2 各模块职责

| 模块 | 核心类/函数 | 职责 |
|------|------------|------|
| `constants.py` | `WARP_INTERFACE`, `WARP_PROXY_PORT`, ... | 集中管理所有配置常量 |
| `warp.py` | `WarpClient` | 封装 `warp-cli` 命令，提供 Python API |
| `proxy.py` | `WarpSocksProxy` | 异步代理服务器，流量通过 WARP 转发 |
| `server.py` | `create_warp_server()` | RESTful API，提供状态查询和 WARP 控制 |
| `cli.py` | `main()`, `cfwp` | CLI 服务管理（启停/状态/日志） |
| `netfix.py` | `fix_tailscale_compat()` | 修复 WARP 与 Tailscale 的网络冲突 |

---

## 3. 核心设计

### 3.1 代理转发机制

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

### 3.2 协议支持

代理同时支持 **SOCKS5** 和 **HTTP CONNECT**，通过窥探首字节自动检测：

- `0x05` → SOCKS5 (RFC 1928)
- 其他 → 尝试解析为 HTTP CONNECT

```
Client → Proxy(11000) → [SO_BINDTODEVICE] → CloudflareWARP → Cloudflare Edge → Target

curl --socks5-hostname 127.0.0.1:11000 https://example.com    # SOCKS5
curl --proxy http://127.0.0.1:11000 https://example.com        # HTTP CONNECT
```

### 3.3 权限管理 (SUDOPASS)

参考 `ipv6/route.py` 的模式，使用 `SUDOPASS` 环境变量实现免交互提权：

```bash
export SUDOPASS="your_password"
cfwp start     # 自动通过 sudo -S 提权启动
cfwp stop      # 自动 sudo kill 停止
```

`cfwp start` 内部执行：
```
echo "$SUDOPASS" | sudo -S env "PATH=$PATH" python -m webu.warp_api _serve ...
```

### 3.4 WARP/Tailscale 兼容性

#### 问题

WARP 的 nftables 规则 (`inet cloudflare-warp`) 会阻断 Tailscale 流量：

1. **IP 冲突**：WARP Include 范围 `100.96.0.0/12` 覆盖了 Tailscale 的 CGNAT 地址
   - Tailscale DNS: `100.100.100.100` (在 `100.96.0.0/12` 范围内)
   - Tailscale 节点: `100.74.x.x`, `100.99.x.x` (也在范围内)
2. **nftables 防火墙**：WARP 的 inet cloudflare-warp 表 DROP 了所有非 WARP 的 `100.96.0.0/12` 流量
3. **路由优先级**：WARP ip rule (priority 5209) 优先于 Tailscale (priority 5270)

#### 修复方案 (`netfix.py`)

```bash
# 1. nftables: 在 DROP 规则前插入 Tailscale 接口例外
nft insert rule inet cloudflare-warp input position <before_drop> iifname "tailscale0" accept
nft insert rule inet cloudflare-warp output position <before_drop> oifname "tailscale0" accept

# 2. ip rule: 提升 Tailscale 路由优先级
ip rule add priority 5200 table 52    # Tailscale table, 优先于 WARP 的 5209
```

> ⚠️ 这些修复是运行时的，重启后需要重新应用。`cfwp start` 会自动调用 `fix_tailscale_compat()`。

---

## 4. API 接口

管理 API 运行在 `:11001`，提供以下端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/warp/status` | WARP 连接状态 |
| GET | `/warp/ip` | IP 信息（直连/WARP/接口） |
| POST | `/warp/connect` | 连接 WARP |
| POST | `/warp/disconnect` | 断开 WARP |
| GET | `/proxy/stats` | 代理统计（活跃/总连接数） |

---

## 5. CLI 命令

```
cfwp — Cloudflare WARP 代理管理工具

命令:
  cfwp start [--proxy-port 11000] [--api-port 11001]
      启动 WARP 代理 + 管理 API（后台运行，自动修复 Tailscale 兼容性）

  cfwp stop
      停止服务（SIGTERM → SIGKILL 回退，进程组级别）

  cfwp restart
      重启服务

  cfwp status
      查看服务运行状态 + WARP 连接状态

  cfwp logs [-n 50] [-f]
      查看/跟踪服务日志

  cfwp ip
      检测直连/WARP 出口 IP

  cfwp connect
      连接 WARP

  cfwp disconnect
      断开 WARP

  cfwp fix [--check]
      修复 WARP/Tailscale 网络冲突（--check 仅检查不修复）
```

---

## 6. 数据文件

```
data/warp_api/
├── server.log    # 服务日志
└── server.pid    # 服务 PID 文件
```

---

## 7. 配置常量

| 常量 | 默认值 | 说明 |
|------|--------|------|
| `WARP_INTERFACE` | `CloudflareWARP` | WARP 网络接口名 |
| `WARP_PROXY_HOST` | `127.0.0.1` | 代理监听地址 |
| `WARP_PROXY_PORT` | `11000` | 代理端口 |
| `WARP_API_HOST` | `0.0.0.0` | API 监听地址 |
| `WARP_API_PORT` | `11001` | API 端口 |
| `DATA_DIR` | `data/warp_api` | 数据目录 |

---

## 8. 网络拓扑

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

## 9. 测试

```bash
# 单元测试
python -m pytest tests/warp_api/test_warp_api.py -v -m "not integration"

# 集成测试（需要 WARP 已连接 + 代理已启动）
cfwp start
python -m pytest tests/warp_api/test_warp_api.py -v -m integration
cfwp stop

# 全部测试
cfwp start
python -m pytest tests/warp_api/test_warp_api.py -v
cfwp stop
```

---

## 10. 已知问题与限制

1. **仅支持 IPv4**：WARP 接口只有 IPv4 地址，代理会拒绝 IPv6 目标并返回错误
2. **需要 root 权限**：`SO_BINDTODEVICE` 需要 `CAP_NET_RAW`
3. **Tailscale 修复非持久化**：nftables 和 ip rule 修复在重启后丢失，需重新运行 `cfwp fix` 或 `cfwp start`（会自动修复）
4. **WARP Include 模式**：当前 WARP 配置为 Include 模式（只代理特定范围），不是全局代理。代理通过 `SO_BINDTODEVICE` 强制走隧道
