# Ali Email 配置

`ali_email` 是 Alibaba Cloud DirectMail 的本地辅助模块，用于账号注册、忘记密码等事务邮件发信。命令行入口是 `alem`。

## 前提

1. 在阿里云域名控制台搜索 "邮件推送"，开通 DirectMail/邮件推送服务。
2. 准备 RAM AccessKey，只授予本项目需要的 DirectMail 权限。
3. 发信域名已经托管在可编辑 DNS 的平台上。
4. 安装可选 SDK 依赖：

```bash
pip install -e '.[ali-email]'
```

建议 RAM 策略至少包含：

```text
dm:CreateDomain
dm:CheckDomain
dm:DescDomain
dm:QueryDomainByParam
dm:CreateMailAddress
dm:QueryMailAddressByParam
dm:SingleSendMail
```

如果只运行线上发信，不做初始化，可以只保留查询和 `dm:SingleSendMail`。

## 本地配置

```bash
alem config-init
```

编辑忽略提交的 `configs/ali_email.json`：

```json
{
  "region_id": "cn-hangzhou",
  "endpoint": "dm.aliyuncs.com",
  "sender_account_name": "register@example.com",
  "sender_alias": "Account",
  "reply_to_address": false,
  "address_type": 1,
  "tag_name": "account-verification",
  "aliyun_access_id": "",
  "aliyun_access_secret": ""
}
```

AccessKey 不要写入文档、测试输出或 git。字段为空时，模块会尝试从本地 `ali_esa.json` 或 `cf_tunnel.json` 回退读取同名凭据。

其他进程调用 `ali_email` 时，需要让进程能找到 `webu` 配置：

```bash
export WEBU_PROJECT_ROOT=/home/asimov/repos/webu
export WEBU_CONFIG_DIR=/home/asimov/repos/webu/configs
export XXXX_ACCOUNT_EMAIL_PROVIDER=ali_email
```

## 发信域名

创建 DirectMail 发信域名：

```bash
alem domain-create --domain-name example.com
alem domain-list --keyword example.com
```

查看需要配置的 DNS 记录：

```bash
alem domain-desc --domain-id <domain-id>
```

通常需要配置：

```text
MX     example.com                         mx01.dm.aliyun.com.         priority 10
TXT    example.com                         v=spf1 include:spf1.dm.aliyun.com -all
TXT    aliyun-cn-hangzhou._domainkey       v=DKIM1; k=rsa; p=<DKIM_PUBLIC_KEY>
TXT    _dmarc                              v=DMARC1;p=none;rua=mailto:dmarc_report@service.aliyun.com
CNAME  dmtrace                             tracedm.aliyuncs.com.
```

如果域名由 `ali_esa` 管理，可用类似命令写入记录：

```bash
aesa site-record-apply --site-name example.com --record-name example.com --record-type MX --data-value mx01.dm.aliyun.com --priority 10 --proxied false --ttl 60 --comment 'DirectMail MX'
aesa site-record-apply --site-name example.com --record-name example.com --record-type TXT --data-value 'v=spf1 include:spf1.dm.aliyun.com -all' --proxied false --ttl 60 --comment 'DirectMail SPF'
aesa site-record-apply --site-name example.com --record-name aliyun-cn-hangzhou._domainkey.example.com --record-type TXT --data-value 'v=DKIM1; k=rsa; p=<DKIM_PUBLIC_KEY>' --proxied false --ttl 60 --comment 'DirectMail DKIM'
aesa site-record-apply --site-name example.com --record-name _dmarc.example.com --record-type TXT --data-value 'v=DMARC1;p=none;rua=mailto:dmarc_report@service.aliyun.com' --proxied false --ttl 60 --comment 'DirectMail DMARC'
aesa site-record-apply --site-name example.com --record-name dmtrace.example.com --record-type CNAME --data-value tracedm.aliyuncs.com --proxied false --ttl 60 --comment 'DirectMail trace'
```

DNS 生效后触发校验并查看状态：

```bash
alem domain-check --domain-id <domain-id>
alem domain-desc --domain-id <domain-id>
```

`DomainStatus`、`SpfAuthStatus`、`DkimAuthStatus`、`MxAuthStatus`、`DmarcAuthStatus`、`CnameAuthStatus` 为 `0` 时，域名侧校验通过。

## 发信地址

创建事务邮件发信地址：

```bash
alem create-sender --account-name register@example.com --sendtype trigger
alem sender-list --keyword register@example.com --sendtype trigger
```

`AccountStatus=0` 且 `DomainStatus=0` 后再发信。新建地址有短暂生效延迟，刚创建后立刻调用 `send-code` 可能返回 `InvalidMailAddress.NotFound`，等待几十秒后重试即可。

## 发信验证

```bash
alem config-check
alem send-code --to user@example.net --code 123456 --purpose register --product-name Account
```

成功时返回 DirectMail `EnvId` 和 `RequestId`。生产日志中只记录请求 ID，不记录验证码、完整邮件正文或 AccessKey。

## 参考

- DirectMail `SingleSendMail`：https://help.aliyun.com/zh/direct-mail/api-dm-2015-11-23-singlesendmail
- DirectMail 域名配置 FAQ：https://www.alibabacloud.com/help/en/direct-mail/domain-name-configuration-faqs/
- DirectMail `DescDomain`：https://www.alibabacloud.com/help/en/direct-mail/api-dm-2015-11-23-descdomain
- DKIM 配置说明：https://www.alibabacloud.com/help/en/direct-mail/what-is-dkim-and-how-to-configure-dkim-records
