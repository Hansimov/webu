# wfrp 常用命令

本文整理 `webu.frp` 模块的常见命令，以及远端 `frps` 和本地 `frpc` 的推荐操作顺序。

## 1. 初始化和校验配置

```bash
wfrp config-init
wfrp config-check
wfrp config-schema
```

## 2. 管理远端 frps

列出当前 server：

```bash
wfrp server-list
```

创建或更新一个远端 server：

```bash
wfrp server-upsert \
  --name edge-frps \
  --ssh-host-name edge-relay-01 \
  --bind-port 7000 \
  --proxy-bind-addr 127.0.0.1 \
  --auth-token replace-me \
  --remote-binary-path /opt/webu/frp/frps \
  --remote-config-path /opt/webu/frp/frps.toml \
  --save-config
```

查看生成的 `frps.toml`：

```bash
wfrp server-render --name edge-frps
```

上传配置并安装远端服务：

```bash
wfrp server-deploy --name edge-frps --install-service
```

查看远端服务状态：

```bash
wfrp server-status --name edge-frps
```

查看远端日志：

```bash
wfrp server-logs --name edge-frps --lines 100
```

重启远端服务：

```bash
wfrp server-restart --name edge-frps
```

停用远端服务：

```bash
wfrp server-disable --name edge-frps
```

删除远端 unit 文件：

```bash
wfrp server-disable --name edge-frps --purge-unit-file
```

## 3. 管理本地 frpc

列出当前 client：

```bash
wfrp client-list
```

创建或更新一个 client：

```bash
wfrp client-upsert \
  --name example-public-web \
  --server-name edge-frps \
  --local-host 127.0.0.1 \
  --local-port 20002 \
  --remote-port 32002 \
  --binary-path /opt/webu/frp/frpc \
  --save-config
```

查看生成的 `frpc.toml`：

```bash
wfrp client-render --name example-public-web
```

把 `frpc.toml` 写到磁盘：

```bash
wfrp client-prepare --name example-public-web
```

单次运行验证：

```bash
wfrp client-run-once --name example-public-web --timeout-seconds 15
```

## 4. 托管本地 frpc 为 systemd 服务

安装并启动服务：

```bash
wfrp client-service-install --name example-public-web
```

查看状态：

```bash
wfrp client-service-status --name example-public-web
```

查看日志：

```bash
wfrp client-service-logs --name example-public-web --lines 100
```

重启服务：

```bash
wfrp client-service-restart --name example-public-web
```

停用服务：

```bash
wfrp client-service-disable --name example-public-web
```

停用并删除 unit 文件：

```bash
wfrp client-service-disable --name example-public-web --purge-unit-file
```

## 5. 推荐调试顺序

1. 先检查 `wssh probe` 是否能连到远端主机。
2. 用 `server-render` 和 `client-render` 先确认 TOML 内容。
3. 再执行 `server-deploy --install-service`，确认远端 `frps` 起来。
4. 用 `client-run-once` 验证本地 `frpc` 能真正连上远端。
5. 最后才切到 `client-service-install`，让它长期运行。