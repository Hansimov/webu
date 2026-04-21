# ssh 模块配置指南

本文说明如何在 `webu` 项目中初始化 `ssh` 模块，并通过 `wssh` 管理远程主机、文件传输和可复用的 SSH 隧道。

## 模块定位

`webu.ssh` 负责三类事情：

- 维护 `configs/ssh.json` 中的远程主机清单。
- 用统一 CLI 执行 SSH 探测、远端命令和 `scp` 传输。
- 把常用端口转发定义固化成 systemd 服务，避免长期依赖手工开的终端。

本文中的主机名、路径和端口均为脱敏占位值，请替换成你自己的实际对象。

## 运行前提

- 在 `webu` 项目根目录执行命令。
- 当前 Python 环境里已经能导入 `webu`。
- 推荐直接使用已安装入口 `wssh`；如果当前环境还没有把入口脚本装到 `PATH`，可以临时改用：

```bash
python -m webu.ssh.cli
```

- 本机具备 `ssh` / `scp`。
- 如果主机使用密码登录而不是私钥登录，本机还需要 `sshpass`。
- 如果要把隧道托管为 user systemd 服务，需要本机 user systemd 可用；如果不确定，可先执行 `systemctl --user status` 检查。

## 配置文件

- 主配置文件：`configs/ssh.json`

`ssh.json` 属于本地运行时配置，不应提交真实主机名、IP、密码、私钥路径或隧道定义。

## 初始化配置

生成最小骨架：

```bash
wssh config-init
```

如果文件已经存在，需要显式覆盖：

```bash
wssh config-init --force
```

生成后立刻校验：

```bash
wssh config-check
```

如果需要检查完整 schema：

```bash
wssh config-schema
```

## 推荐字段说明

`hosts[]` 常用字段：

- `name`：本地主机标识，其他模块会通过它引用 SSH 主机。
- `ip` / `hostname`：远程主机地址；两者同时存在时优先使用 `hostname`。
- `port`：SSH 端口，默认 `22`。
- `username`：SSH 用户名。
- `password`：密码登录时使用；非空时 `wssh` 会走 `sshpass`。
- `identity_file`：私钥路径；如果设置了它，通常不再需要 `password`。
- `notes`：本地备注。

`tunnels[]` 常用字段：

- `name`：隧道标识，也是默认 systemd unit 名称的来源。
- `host_name`：引用 `hosts[]` 中的主机名。
- `mode`：`remote` 或 `local`，分别对应 `ssh -R` 和 `ssh -L`。
- `local_host` / `local_port`：本地侧监听地址和端口。
- `remote_host` / `remote_port`：远端侧监听地址和端口。
- `server_alive_interval_seconds` / `server_alive_count_max`：长期隧道保活参数。
- `service_name`：可选的 systemd unit 名称覆盖值。

## 推荐配置流程

1. 用 `wssh config-init` 生成 `configs/ssh.json`。
2. 用 `wssh host-upsert` 创建远端主机，而不是直接手工改 JSON。
3. 用 `wssh probe` 先验证 SSH 链路连通。
4. 如果需要文件同步或远端操作，再用 `wssh exec`、`wssh copy-to`、`wssh copy-from`。
5. 如果需要长期端口转发，用 `wssh tunnel-upsert` 定义隧道，再用 `wssh tunnel-command` 先核对命令。
6. 确认命令正确后，再用 `wssh tunnel-service-install` 安装 systemd 服务。

## 最小示例

创建一个远端主机：

```bash
wssh host-upsert \
  --name edge-relay-01 \
  --hostname relay.docs.invalid \
  --username root \
  --identity-file /home/example/.ssh/id_ed25519 \
  --save-config
```

创建一个远程反向隧道，把本地 `20002` 暴露到远端回环 `32002`：

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

## `--project-root` 与 `--config-dir`

所有 `wssh` 子命令都支持：

- `--project-root`：显式指定 `webu` 根目录。
- `--config-dir`：显式指定配置目录。

当你从外部仓库或 helper/runbook 调用 `wssh` 时，建议总是带上这两个参数，避免误读当前工作目录下的配置。