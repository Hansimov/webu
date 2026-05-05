# nginx 模块配置指南

本文说明如何在 `webu` 项目中使用 `nginx` 模块，把远端 nginx/openresty 反向代理站点配置标准化为可渲染、可上传、可回滚的 CLI 流程。

## 模块定位

`webu.nginx` 当前不维护单独的 JSON 配置文件，而是提供一组面向远端主机的操作：

- 本地渲染反向代理站点配置。
- 通过 SSH 上传站点配置到远端主机。
- 在远端执行 `nginx -t` 和 reload。
- 查看或删除远端站点配置。

## 运行前提

- 在 `webu` 项目根目录执行命令。
- 当前 Python 环境里已经能导入 `webu`。
- 推荐直接使用已安装入口 `wngx`；如果当前环境还没有把入口脚本装到 `PATH`，可以临时改用：

```bash
python -m webu.nginx.cli
```

- `configs/ssh.json` 中已经存在可用的远端主机，因为 `wngx` 会通过 `wssh` 上传文件并执行远端命令。
- 远端已经安装 nginx 或 openresty，并且你知道它的站点目录、测试命令和 reload 命令。
- 如果要配置 HTTPS，需要提前准备好证书和私钥路径，或者至少知道远端 ACME challenge 根目录。

## 配置来源

`wngx` 没有自己的 `configs/nginx.json`。它主要依赖：

- `configs/ssh.json`：远端主机信息。
- 命令行参数：站点名、域名、upstream、远端站点目录、证书路径等。

这意味着 nginx 相关的公网域名、上游地址和证书路径同样属于敏感运行信息，不应直接硬编码进公开代码或文档。

## 常用参数说明

- `--host-name`：引用 `configs/ssh.json` 中的远端主机。
- `--site-name`：远端站点配置名，最终会渲染成 `<site-name>.conf`。
- `--server-name`：一个或多个域名，会写进 `server_name`。
- `--upstream-url`：反代上游地址，必须以 `http://` 或 `https://` 开头。
- `--remote-conf-dir`：远端站点目录，默认 `/etc/nginx/conf.d`。
- `--test-command`：远端配置校验命令，默认 `nginx -t`。
- `--reload-command`：远端 reload 命令，默认 `nginx -s reload`。
- `--listen-http` / `--listen-https`：控制是否生成 `80` / `443` server block。
- `--redirect-https`：当同时开启 HTTP + HTTPS 时，让 HTTP block 只做 `301` 跳转。
- `--ssl-certificate` / `--ssl-certificate-key`：HTTPS 证书路径。
- `--acme-root`：`/.well-known/acme-challenge/` 的根目录。
- `--enable-static-cache`：为 `/assets/` 和 `/icons/` 生成远端 `proxy_cache` 规则。
- `--static-cache-zone`：缓存 zone 名称，默认从站点名派生。
- `--static-cache-path`：远端缓存目录，默认 `/tmp/webu-nginx-cache`。
- `--static-cache-max-size` / `--static-cache-inactive`：远端缓存容量和 inactive 过期时间。
- `--static-cache-browser-max-age`：客户端 `Cache-Control max-age` 秒数，默认 `31536000`。

## 推荐配置流程

1. 先用 `wssh probe` 确认远端主机可达。
2. 用 `wngx render-reverse-proxy` 在本地预览渲染结果。
3. 确认 `server_name`、`upstream_url`、TLS 参数都正确。
4. 用 `wngx remote-site-apply` 上传并应用站点配置。
5. 用 `wngx remote-site-show` 回读远端最终文件。
6. 如果要回滚，用 `wngx remote-site-disable` 删除站点并 reload。

## 最小示例

渲染一个 HTTP 反代站点：

```bash
wngx render-reverse-proxy \
  --server-name public.docs.invalid \
  --upstream-url http://127.0.0.1:32002 \
  --listen-http
```

渲染一个带静态资源缓存的 HTTP 反代站点：

```bash
wngx render-reverse-proxy \
  --server-name public.docs.invalid \
  --upstream-url http://127.0.0.1:32002 \
  --listen-http \
  --enable-static-cache \
  --static-cache-zone public_docs_assets \
  --static-cache-path /tmp/webu-nginx-cache-public-docs
```

渲染并上传一个 HTTPS 站点：

```bash
wngx remote-site-apply \
  --host-name edge-relay-01 \
  --site-name public-docs \
  --server-name public.docs.invalid \
  --upstream-url http://127.0.0.1:32002 \
  --listen-http \
  --listen-https \
  --redirect-https \
  --ssl-certificate /etc/letsencrypt/live/public.docs.invalid/fullchain.pem \
  --ssl-certificate-key /etc/letsencrypt/live/public.docs.invalid/privkey.pem
```

## `--project-root` 与 `--config-dir`

所有 `wngx` 子命令都支持：

- `--project-root`：显式指定 `webu` 根目录。
- `--config-dir`：显式指定配置目录。

由于 `wngx` 依赖 `configs/ssh.json`，如果它是从外部 helper 或其他仓库调起的，建议总是带上这两个参数。
