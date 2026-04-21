# frp 模块配置指南

本文说明如何在 `webu` 项目中初始化 `frp` 模块，并通过 `wfrp` 管理远端 `frps` 和本地 `frpc`。

## 模块定位

`webu.frp` 负责把 FRP 的几个关键动作统一到一个 CLI：

- 维护 `configs/frp.json` 中的 `frps` / `frpc` 定义。
- 渲染 `frps.toml` 和 `frpc.toml`。
- 通过 `webu.ssh` 把 `frps` 配置上传到远端 VPS。
- 把本地 `frpc` 托管成 systemd 服务。

## 运行前提

- 在 `webu` 项目根目录执行命令。
- 当前 Python 环境里已经能导入 `webu`。
- 推荐直接使用已安装入口 `wfrp`；如果当前环境还没有把入口脚本装到 `PATH`，可以临时改用：

```bash
python -m webu.frp.cli
```

- `configs/ssh.json` 中已经存在可用的远端主机，因为 `wfrp` 会通过 `wssh` 调用远程 SSH。
- 远端已经准备好 `frps` 二进制，或者你知道二进制最终应该被放到哪里。
- 本地已经准备好 `frpc` 二进制，或者会在 `configs/frp.json` 里显式指定它的路径。
- 如果要安装远端 `frps` 服务，远端需要 systemd；如果要安装本地 `frpc` 服务，本机需要 systemd。

## 配置文件

- 主配置文件：`configs/frp.json`
- 依赖的 SSH 主机配置：`configs/ssh.json`

`frp.json` 属于本地运行时配置，不应提交真实的远端主机名、token、二进制路径或端口规划。

## 初始化配置

生成最小骨架：

```bash
wfrp config-init
```

如果文件已经存在，需要显式覆盖：

```bash
wfrp config-init --force
```

校验配置：

```bash
wfrp config-check
```

打印 schema：

```bash
wfrp config-schema
```

## 推荐字段说明

`servers[]` 常用字段：

- `name`：本地 `frps` 标识。
- `ssh_host_name`：引用 `configs/ssh.json` 中的 SSH 主机名。
- `bind_port`：远端 `frps` 监听端口。
- `proxy_bind_addr`：远端 `frps` 的代理监听地址，通常保持 `127.0.0.1`。
- `auth_token`：`frps` / `frpc` 共用的认证 token。
- `remote_binary_path`：远端 `frps` 二进制路径。
- `remote_config_path`：远端 `frps.toml` 路径。
- `remote_service_name`：可选的远端 systemd unit 名称覆盖值。

`clients[]` 常用字段：

- `name`：本地 `frpc` 标识。
- `server_name`：引用 `servers[]` 中的 `frps` 名称。
- `server_addr`：可选的显式远端地址；留空时会回退读取 SSH 主机的 `hostname/ip`。
- `server_port`：远端 `frps` 端口。
- `auth_token`：可选的 client 级 token 覆盖值；留空时继承 server token。
- `local_host` / `local_port`：本地待暴露服务的地址和端口。
- `remote_port`：远端 `frps` 映射出来的端口。
- `binary_path`：本地 `frpc` 二进制路径。
- `config_path`：本地 `frpc.toml` 输出路径。
- `service_name`：可选的本地 systemd unit 名称覆盖值。

## 推荐配置流程

1. 先用 `wssh` 把远端主机配置好，并通过 `wssh probe` 验证 SSH 可用。
2. 用 `wfrp config-init` 生成 `configs/frp.json`。
3. 用 `wfrp server-upsert` 定义一个远端 `frps`。
4. 用 `wfrp client-upsert` 定义一个本地 `frpc`。
5. 用 `wfrp config-check` 校验 JSON。
6. 用 `wfrp server-render` / `client-render` 检查生成的 TOML。
7. 用 `wfrp server-deploy --install-service` 部署远端 `frps`。
8. 用 `wfrp client-prepare` 和 `client-run-once` 验证本地 `frpc`。
9. 确认链路无误后，再用 `wfrp client-service-install` 托管为 systemd 服务。

## 最小示例

创建一个远端 `frps`：

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

创建一个本地 `frpc`：

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

## `--project-root` 与 `--config-dir`

所有 `wfrp` 子命令都支持：

- `--project-root`：显式指定 `webu` 根目录。
- `--config-dir`：显式指定配置目录。

如果 `wfrp` 是从其他仓库、runbook 或 systemd helper 调起的，建议总是带上这两个参数，避免误用当前目录里的旧配置。