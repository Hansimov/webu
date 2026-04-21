# wssh 常用命令

本文整理 `webu.ssh` 模块的常见命令，以及远端主机和 SSH 隧道的推荐操作顺序。

## 1. 初始化和校验配置

生成模板：

```bash
wssh config-init
```

校验配置：

```bash
wssh config-check
```

打印 schema：

```bash
wssh config-schema
```

## 2. 管理主机

列出当前主机：

```bash
wssh host-list
```

创建或更新一个私钥登录主机：

```bash
wssh host-upsert \
  --name edge-relay-01 \
  --hostname relay.docs.invalid \
  --username root \
  --identity-file /home/example/.ssh/id_ed25519 \
  --save-config
```

创建或更新一个密码登录主机：

```bash
wssh host-upsert \
  --name edge-relay-01 \
  --ip 198.51.100.24 \
  --username root \
  --password replace-me \
  --save-config
```

探测 SSH 是否可用：

```bash
wssh probe --name edge-relay-01
```

## 3. 执行命令和传文件

执行远端命令：

```bash
wssh exec --name edge-relay-01 --command-text "uname -a"
```

如果命令需要 TTY：

```bash
wssh exec --name edge-relay-01 --command-text "journalctl -u nginx -n 20" --allocate-tty
```

上传文件：

```bash
wssh copy-to \
  --name edge-relay-01 \
  --local-path ./debugs/example.txt \
  --remote-path /tmp/example.txt
```

下载文件：

```bash
wssh copy-from \
  --name edge-relay-01 \
  --remote-path /etc/os-release \
  --local-path ./debugs/os-release.txt
```

## 4. 管理隧道定义

列出当前隧道：

```bash
wssh tunnel-list
```

创建一个远程反向隧道：

```bash
wssh tunnel-upsert \
  --name example-remote-web \
  --host-name edge-relay-01 \
  --mode remote \
  --local-host 127.0.0.1 \
  --local-port 20002 \
  --remote-host 127.0.0.1 \
  --remote-port 32002 \
  --save-config
```

创建一个本地正向隧道：

```bash
wssh tunnel-upsert \
  --name example-local-admin \
  --host-name edge-relay-01 \
  --mode local \
  --local-host 127.0.0.1 \
  --local-port 39080 \
  --remote-host 127.0.0.1 \
  --remote-port 80 \
  --save-config
```

查看实际 SSH 命令：

```bash
wssh tunnel-command --name example-remote-web
```

## 5. 托管隧道为 systemd 服务

安装并启动系统级服务：

```bash
wssh tunnel-service-install --name example-remote-web
```

安装并启动 user systemd 服务：

```bash
wssh tunnel-service-install --name example-remote-web --user
```

查看服务状态：

```bash
wssh tunnel-service-status --name example-remote-web --user
```

查看最近日志：

```bash
wssh tunnel-service-logs --name example-remote-web --lines 100 --user
```

重启服务：

```bash
wssh tunnel-service-restart --name example-remote-web --user
```

停用服务：

```bash
wssh tunnel-service-disable --name example-remote-web --user
```

停用并删除 unit 文件：

```bash
wssh tunnel-service-disable --name example-remote-web --purge-unit-file --user
```

## 6. 推荐调试顺序

1. 先 `host-upsert` + `probe`，确认 SSH 本身通。
2. 再跑一次 `tunnel-command`，确认 `ssh -L/-R` 参数和端口方向正确。
3. 需要长期运行时，再切到 `tunnel-service-install`。
4. 出问题时优先看 `tunnel-service-status` 和 `tunnel-service-logs`，而不是盲目重复安装服务。