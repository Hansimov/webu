# CF Email 使用

解析入站邮件：

```python
from webu.cf_email import extract_verification_codes, parse_email_message

parsed = parse_email_message(raw_mime)
codes = extract_verification_codes(raw_mime)
```

常用命令：

```bash
cfem config-check
cfem plan
cfem worker-script
cfem worker-deploy --dry-run
cfem worker-deploy
cfem ensure-worker-rule
cfem parse .playwright/cf-email-inbound.eml
cfem extract-code .playwright/cf-email-inbound.eml
```

Worker 脚本会读取 Cloudflare Email Routing 的 `message.raw`，把原始 MIME 和基础元数据 POST 到 `webhook_url`。接收端必须校验 `x-webhook-secret`，并避免长期保存完整 raw MIME。

如果配置了 `forward_to`，同一个 Worker 还会调用 `message.forward()` 把邮件转发到已验证的目标邮箱。`forward_to` 会作为 Worker secret `FORWARD_TO` 写入，适合需要人工查看完整邮件正文的场景。

`webhook_required=true` 时，webhook 不可达会让 Worker 处理失败，适合自动化解析需要强一致观测的场景。人工转发优先的调试地址可以设置为 `false`，让 webhook 失败只进入 Worker 日志。

运行注意事项：

- 真实收信时，`webhook_url` 必须能被 Cloudflare Worker 访问；本机 `127.0.0.1` 需要通过 cloudflared tunnel 或正式公网入口暴露。
- Cloudflare Dashboard 的 Activity Log 只能用于看路由结果、认证状态和投递信息；需要查看邮件正文时，请使用 `forward_to` 或把 raw MIME 写入受控存储/内部 webhook。
- 本地接收端建议使用 `14567` 这类大于 `10000` 的端口。
- 不要在早期测试把 catch-all 规则指向 Worker，优先使用单独地址。
- Worker secret 使用 `cfem worker-deploy` 写入，不要写进 Worker 源码。
- 如果只是查看解析能力，可把 `.eml` 文件直接传给 `cfem parse` 或 `cfem extract-code`。
- `.eml`、webhook jsonl、验证码和完整收件人列表都属于敏感调试产物，只能放在 `.playwright/` 这类忽略提交的本地目录中，测试完成后删除。
