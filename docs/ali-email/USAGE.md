# Ali Email 使用

业务代码通过 `send_verification_code()` 发送验证码：

```python
from webu.ali_email import send_verification_code

send_verification_code(
    to_address="user@example.net",
    code="123456",
    purpose="register",
    product_name="Account",
)
```

该函数会生成 text/html 两种正文，并调用 DirectMail `SingleSendMail`。

常用命令：

```bash
alem config-check
alem domain-list --keyword example.com
alem sender-list --keyword register@example.com --sendtype trigger
alem send-code --to user@example.net --code 123456 --dry-run
```

运行注意事项：

- 命令行入口统一使用 `alem`。
- `sender_account_name` 必须是 DirectMail 已创建且状态正常的发信地址。
- `address_type` 对普通发信地址使用 `1`。
- `reply_to_address=true` 只适用于 DirectMail 控制台里已验证通过的回信地址。
- `blbl-account` 使用该模块时，进程环境要包含 `WEBU_PROJECT_ROOT`/`WEBU_CONFIG_DIR`，否则会找不到本地配置。
- 不要在生产日志打印验证码、邮件全文、AccessKey 或完整收件人列表。
