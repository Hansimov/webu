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

运行注意事项：

- 真实收信时，`webhook_url` 必须能被 Cloudflare Worker 访问；本机 `127.0.0.1` 需要通过 cloudflared tunnel 或正式公网入口暴露。
- 本地接收端建议使用 `14567` 这类大于 `10000` 的端口。
- 不要在早期测试把 catch-all 规则指向 Worker，优先使用单独地址。
- Worker secret 使用 `cfem worker-deploy` 写入，不要写进 Worker 源码。
- 如果只是查看解析能力，可把 `.eml` 文件直接传给 `cfem parse` 或 `cfem extract-code`。
- `.eml`、webhook jsonl、验证码和完整收件人列表都属于敏感调试产物，只能放在 `.playwright/` 这类忽略提交的本地目录中，测试完成后删除。
