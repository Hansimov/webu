# cfwp — 环境搭建指南

---

## 1. 前提条件

- Cloudflare WARP 已安装并注册
- Python 3.11+, conda `ai` 环境
- `webu` 包已 editable install (`pip install -e .`)

---

## 2. 安装 Cloudflare WARP

```bash
# Debian/Ubuntu
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg \
  | sudo gpg --yes --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" \
  | sudo tee /etc/apt/sources.list.d/cloudflare-client.list
sudo apt update && sudo apt install cloudflare-warp
```

```bash
# 注册
warp-cli registration new

# 连接
warp-cli connect

# 状态 — 应显示 Connected
warp-cli status
```

---

## 3. 权限配置 (SUDOPASS)

代理需要 root 权限（`SO_BINDTODEVICE`），使用 `SUDOPASS` 环境变量实现免交互提权。

在 shell 配置文件（`~/.bashrc` 或 `~/.zshrc`）中添加：

```bash
export SUDOPASS="your_sudo_password"
```

所有需要 sudo 的操作（启动代理、修复网络、停止服务）都会自动使用此变量。

---

## 4. 启动服务

```bash
# 启动代理 + 管理 API（后台运行）
cfwp start

# 验证
cfwp status
curl --proxy http://127.0.0.1:11000 http://ifconfig.me/ip
```

`cfwp start` 启动时自动完成以下网络修复（幂等，可重复执行）：

| 修复项 | 内容 |
|--------|------|
| nftables Tailscale 例外 | 防止 Tailscale 流量被 WARP DROP |
| ip rule 优先级 | Tailscale 路由表在 WARP 之前查找 |
| ip -6 rule ndppd 保护 | 随机 IPv6 出口流量走 main 表 |
| resolvectl domain `~.` | **修复 WARP DNS 劫持**，让 ISP DNS 优先返回 AAAA 记录 |

---

## 5. 数据目录

```
data/warp_api/
├── server.log    # 服务日志
└── server.pid    # 服务 PID 文件
```

---

## 6. 测试

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

*文档更新日期：2026-03-05*（cfwp start 自动修复列表）
