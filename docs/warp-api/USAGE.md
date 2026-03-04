# cfwp — 使用指南

---

## 1. CLI 命令

```
cfwp — Cloudflare WARP 代理管理工具

cfwp start [--proxy-port 11000] [--api-port 11001]
    启动 WARP 代理 + 管理 API（后台运行，自动修复 Tailscale 兼容性）

cfwp stop
    停止服务

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

## 2. 代理使用

代理端口：`11000`，支持以下三种方式：

### SOCKS5

```bash
curl --socks5-hostname 127.0.0.1:11000 https://ifconfig.me/ip
```

### HTTP 代理（HTTPS 目标）

```bash
curl --proxy http://127.0.0.1:11000 https://ifconfig.me/ip
```

### HTTP 代理（HTTP 目标）

```bash
curl --proxy http://127.0.0.1:11000 http://ifconfig.me/ip
```

### Python 中使用

```python
import requests

proxies = {"http": "socks5h://127.0.0.1:11000", "https": "socks5h://127.0.0.1:11000"}
r = requests.get("https://ifconfig.me/ip", proxies=proxies)
print(r.text)

# 或 HTTP 代理
proxies = {"http": "http://127.0.0.1:11000", "https": "http://127.0.0.1:11000"}
r = requests.get("http://ifconfig.me/ip", proxies=proxies)
print(r.text)
```

---

## 3. 管理 API

API 端口：`11001`，文档：`http://127.0.0.1:11001/docs`

```bash
# 健康检查
curl http://127.0.0.1:11001/health

# WARP 状态
curl http://127.0.0.1:11001/warp/status

# IP 信息
curl http://127.0.0.1:11001/warp/ip

# 代理统计
curl http://127.0.0.1:11001/proxy/stats

# 连接/断开 WARP
curl -X POST http://127.0.0.1:11001/warp/connect
curl -X POST http://127.0.0.1:11001/warp/disconnect
```

---

## 4. 典型工作流

```bash
# 首次使用
export SUDOPASS="your_password"   # 添加到 ~/.zshrc
cfwp start                        # 启动（自动修复 Tailscale 兼容性）

# 日常使用
cfwp status                       # 查看状态
cfwp ip                           # 检查 IP
cfwp logs -f                      # 跟踪日志

# 验证代理
curl --proxy http://127.0.0.1:11000 http://ifconfig.me/ip   # 应显示 WARP 出口 IP
curl http://ifconfig.me/ip                                    # 应显示直连 IP

# 重启
cfwp restart

# 停止
cfwp stop
```

---

*文档更新日期：2026-03-05*
