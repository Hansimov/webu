# 调试提示

## 环境注意点

本地工作站：

1. 本地代理地址只能写在 `configs/proxies.json`。
2. `google_api`、`gemini`、`proxy_api`、`searches` 都从这个文件读代理，不再从代码里取默认值。
3. 如果 `google_api.json` 中 `local` 服务的 `api_token` 为空，本地 `/search` 不做鉴权。

本地 Docker：

1. 如果要让容器看到本地代理配置，必须使用 `--mount-configs`。
2. Linux 上本机代理如果只监听 `127.0.0.1`，仍然需要 host networking 才能被容器访问。

远程服务器：

1. 除非该机器自己就有本地代理，否则不要复制 `configs/proxies.json`。
2. 建议显式设置 `WEBU_GOOGLE_PROXY_MODE=disabled`。
3. 如果要启用 `/search` 鉴权，推荐设置 `WEBU_GOOGLE_SERVICE_TYPE=remote-server`，并提供对应 token。

HF Space：

1. 首页只是伪装页，不能作为服务能力说明。
2. 搜索 token 和管理 token 都通过 HF secrets 注入，不依赖 bundle 内的本地配置文件。
3. 如果 HF 的 rebuild 控制接口不稳定，先 `hf-sync` 更新内容，再检查实际页面是否切换。
4. 新容器会优先使用 bundle 中打包的单文件加密 profile bootstrap；归档会用 search api_token 派生密钥加密，容器启动时自动解密恢复。如果本地 profile 本身已经过期或被 Google 判定异常，bootstrap 也不会神奇消除风控，只能降低冷启动概率。

## 常用调试命令

查看 Space 仓库文件：

```bash
ggdk hf-files
```

查看 Space 提交数量：

```bash
ggdk hf-commit-count
```

查看当前服务地址：

```bash
ggdk hf-url
```

读取远端日志：

```bash
ggdk hf-logs
```

查看管理运行时：

```bash
ggdk hf-runtime
```

验证远端搜索：

```bash
ggdk hf-search "OpenAI news"
```

## 常见状态

`PAUSED`
Space 还没被唤醒或还没开始新的运行实例。

`APP_STARTING`
镜像已经构建完成，应用正在启动。

`RUNNING_BUILDING`
旧实例还在服务，新实例正在切换。

`503` on restart endpoint
HF 控制面异常。先尝试不带重启的同步，再检查实际页面和状态。

## 仍然需要显式参数的情况

1. 你维护多个 Space，并且当前要操作的不是默认第一项。
2. 你要临时覆盖 `admin_token` 或 `api_token`。
3. 你要故意验证匿名访问失败，此时可用 `ggdk hf-search "query" --no-auth`。
