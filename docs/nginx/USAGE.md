# wngx 常用命令

本文整理 `webu.nginx` 模块的常见命令，以及远端 nginx/openresty 站点配置的推荐操作顺序。

## 1. 本地渲染站点配置

渲染一个 HTTP 站点：

```bash
wngx render-reverse-proxy \
  --server-name public.docs.invalid \
  --upstream-url http://127.0.0.1:32002 \
  --listen-http
```

渲染一个同时监听 HTTP + HTTPS 的站点：

```bash
wngx render-reverse-proxy \
  --server-name public.docs.invalid \
  --server-name www.public.docs.invalid \
  --upstream-url http://127.0.0.1:32002 \
  --listen-http \
  --listen-https \
  --redirect-https \
  --ssl-certificate /etc/letsencrypt/live/public.docs.invalid/fullchain.pem \
  --ssl-certificate-key /etc/letsencrypt/live/public.docs.invalid/privkey.pem
```

## 2. 上传并应用远端站点

应用到远端默认 nginx 目录：

```bash
wngx remote-site-apply \
  --host-name edge-relay-01 \
  --site-name public-docs \
  --server-name public.docs.invalid \
  --upstream-url http://127.0.0.1:32002 \
  --listen-http
```

如果远端是容器内的 openresty，显式传入测试和 reload 命令：

```bash
wngx remote-site-apply \
  --host-name edge-relay-01 \
  --site-name public-docs \
  --server-name public.docs.invalid \
  --upstream-url http://127.0.0.1:32002 \
  --listen-http \
  --remote-conf-dir /opt/openresty/conf/conf.d \
  --test-command "docker exec openresty nginx -t" \
  --reload-command "docker exec openresty nginx -s reload"
```

如果站点前端资源使用带 hash 的 `/assets/` 文件名，可以在中继上开启静态资源缓存，降低 origin 和回程隧道的重复传输：

```bash
wngx remote-site-apply \
  --host-name edge-relay-01 \
  --site-name public-docs \
  --server-name public.docs.invalid \
  --upstream-url http://127.0.0.1:32002 \
  --listen-http \
  --enable-static-cache \
  --static-cache-zone public_docs_assets \
  --static-cache-path /tmp/webu-nginx-cache-public-docs
```

开启后，`/assets/` 和 `/icons/` 会在远端 nginx/openresty 上使用 `proxy_cache`，并向客户端返回长期 `Cache-Control`。只应对指纹化或可接受长缓存的静态资源启用该选项。

## 3. 查看远端配置

```bash
wngx remote-site-show \
  --host-name edge-relay-01 \
  --site-name public-docs
```

## 4. 停用远端站点

```bash
wngx remote-site-disable \
  --host-name edge-relay-01 \
  --site-name public-docs
```

如果远端不是标准 nginx 命令，同样可以覆盖测试和 reload：

```bash
wngx remote-site-disable \
  --host-name edge-relay-01 \
  --site-name public-docs \
  --remote-conf-dir /opt/openresty/conf/conf.d \
  --test-command "docker exec openresty nginx -t" \
  --reload-command "docker exec openresty nginx -s reload"
```

## 5. 推荐调试顺序

1. 先本地 `render-reverse-proxy`，确认配置块长什么样。
2. 再 `remote-site-apply`，让远端先跑 `nginx -t`；如果校验失败，`wngx` 会尝试回滚到旧配置。
3. 应用后立即 `remote-site-show`，确认远端实际生效的内容。
4. 如果只是想快速撤销，优先 `remote-site-disable`，不要手工 SSH 上去直接删文件。
