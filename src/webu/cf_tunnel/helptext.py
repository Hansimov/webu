from __future__ import annotations

from pathlib import Path

from webu.clis import add_examples_epilog, root_epilog
from webu.runtime_settings.sensitive import assert_public_text_safe


USAGE_DOC_PATH = Path(__file__).resolve().parents[3] / "docs" / "cf-tunnel" / "USAGE.md"
CONFIGS_DOC_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "cf-tunnel" / "CONFIGS.md"
)


COMMAND_HELP = {
    "dns-migrate": {
        "summary": "把域名的 DNS 托管从阿里云切到 Cloudflare。",
        "examples": [
            "cftn dns-migrate example.com --cf-token-mode auto",
            "cftn dns-migrate example.com --cf-token-mode manual --save-config",
        ],
    },
    "tunnel-apply": {
        "summary": "为某个 domain_name/local_url 创建或更新 remote-managed tunnel。",
        "examples": [
            "cftn tunnel-apply --name app-example --install-service",
            "cftn tunnel-apply --all",
        ],
    },
    "tunnel-status": {
        "summary": "查看 tunnel 在 Cloudflare 控制面的状态和连接数。",
        "examples": [
            "cftn tunnel-status --name app-example",
        ],
    },
    "access-diagnose": {
        "summary": "诊断大陆访问慢、DNS 解析异常、证书异常或浏览器提示连接不安全的问题。",
        "examples": [
            "cftn access-diagnose --name app-example",
            "cftn access-diagnose --hostname app.example.com",
        ],
    },
    "page-audit": {
        "summary": "检查页面返回、mixed content、dev server 暴露和静态资源 4xx 问题。",
        "examples": [
            "cftn page-audit --name app-example",
            "cftn page-audit --hostname app.example.com --path /",
        ],
    },
    "edge-trace": {
        "summary": "追踪当前命中的 Cloudflare 边缘 IP、colo 和 trace 信息，辅助大陆访问与优选 IP 评估。",
        "examples": [
            "cftn edge-trace --name app-example",
            "cftn edge-trace --hostname app.example.com --path /cdn-cgi/trace",
        ],
    },
    "client-override-plan": {
        "summary": "导出面向特定用户群的客户端 hosts/本地 DNS 优选 IP 实验计划。",
        "examples": [
            "cftn client-override-plan --name app-example --prefer-family ipv4",
            "cftn client-override-plan --hostname app.example.com --prefer-family any --max-candidates 3",
        ],
    },
    "client-canary-bundle": {
        "summary": "生成跨桌面和移动端的 canary 测试包、平台指引和灰度步骤。",
        "examples": [
            "cftn client-canary-bundle --name app-example --prefer-family ipv4",
        ],
    },
    "client-report-template": {
        "summary": "输出客户端回传结果模板，用于按地区、运营商和平台收集实验结果。",
        "examples": [
            "cftn client-report-template --name app-example --prefer-family ipv4",
        ],
    },
    "client-report-summary": {
        "summary": "汇总客户端回传结果，按运营商和平台筛选更稳的优选 IP。",
        "examples": [
            "cftn client-report-summary reports/client-canary.json",
        ],
    },
    "config-check": {
        "summary": "校验 configs/cf_tunnel.json 的结构。",
        "examples": ["cftn config-check"],
    },
    "config-init": {
        "summary": "生成最小配置骨架。",
        "examples": ["cftn config-init", "cftn config-init --force"],
    },
    "config-schema": {
        "summary": "打印 cf_tunnel 的共享 schema。",
        "examples": ["cftn config-schema"],
    },
    "docs-sync": {
        "summary": "重写 docs/cf-tunnel/USAGE.md 和 CONFIGS.md。",
        "examples": ["cftn docs-sync"],
    },
    "token-ensure": {
        "summary": "确保存在可用的 Cloudflare 工作 token，可自动创建或手动输入。",
        "examples": [
            "cftn token-ensure --zone-name example.com --cf-token-mode auto",
            "cftn token-ensure --zone-name example.com --cf-token-mode manual",
        ],
    },
}


def root_description() -> str:
    return "Manage Cloudflare remote-managed tunnels and Aliyun registrar DNS migration from the command line."


def root_help_epilog() -> str:
    return assert_public_text_safe(
        root_epilog(
            quick_start=[
                "cftn config-init",
                "cftn dns-migrate example.com --cf-token-mode auto",
                "cftn tunnel-apply --name app-example --install-service",
            ],
            examples=[
                "cftn token-ensure --zone-name example.com --cf-token-mode auto",
                "cftn tunnel-status --name app-example",
                "cftn access-diagnose --name app-example",
                "cftn page-audit --name app-example",
                "cftn client-override-plan --name app-example --prefer-family ipv4",
                "cftn client-canary-bundle --name app-example --prefer-family ipv4",
            ],
        )
    )


def command_epilog(command_name: str) -> str:
    return assert_public_text_safe(
        add_examples_epilog(COMMAND_HELP.get(command_name, {}).get("examples", []))
    )


def render_usage_markdown() -> str:
    lines = [
        "# cftn Usage",
        "",
        root_description(),
        "",
        "## Recommended Workflow",
        "",
        "1. 先检查配置结构是否完整：`cftn config-check`。",
        "2. 如果还没有工作 token，先生成或确认 token：`cftn token-ensure --zone-name example.com --cf-token-mode auto --save-config`。",
        "3. 迁移注册商 DNS 到 Cloudflare：`cftn dns-migrate example.com --cf-token-mode auto --save-config`。",
        "4. 用 tunnel 配置把域名入口指向本地服务：`cftn tunnel-apply --name app-example --install-service --save-config`。",
        "5. 检查 tunnel 控制面状态和连接：`cftn tunnel-status --name app-example`。",
        "6. 如果大陆访问慢、必须挂代理或浏览器提示连接不安全，运行：`cftn access-diagnose --name app-example`。",
        "7. 如果页面本身异常、空白、资源报错或疑似 mixed content，运行：`cftn page-audit --name app-example`。",
        "8. 如果要继续判断当前网络命中的 Cloudflare 边缘、colo 和是否适合做客户端侧优选实验，运行：`cftn edge-trace --name app-example`。",
        "9. 如果要把结果转成定向用户可执行的 hosts/本地 DNS 实验包，运行：`cftn client-override-plan --name app-example --prefer-family ipv4`。",
        "10. 如果要覆盖桌面和移动端灰度，生成 canary 测试包：`cftn client-canary-bundle --name app-example --prefer-family ipv4`。",
        "11. 收集客户端结果后，汇总各地区/运营商/平台表现：`cftn client-report-summary reports/client-canary.json`。",
        "12. 用 `dig example.com NS`、`dig +trace example.com A` 和实际业务 URL 做最终验证。",
        "",
        "## Common Commands",
        "",
        "- 初始化空白配置：`cftn config-init --force`",
        "- 查看配置 schema：`cftn config-schema`",
        "- 自动创建或确认工作 token：`cftn token-ensure --zone-name example.com --cf-token-mode auto --save-config`",
        "- 迁移 zone 到 Cloudflare：`cftn dns-migrate example.com --cf-token-mode auto --save-config`",
        "- 应用单个 tunnel：`cftn tunnel-apply --name app-example --install-service --save-config`",
        "- 批量应用所有 tunnel：`cftn tunnel-apply --all --install-service --save-config`",
        "- 查看 tunnel 实时状态：`cftn tunnel-status --name app-example`",
        "- 诊断 DNS 污染、TLS 异常和大陆访问问题：`cftn access-diagnose --name app-example`",
        "- 审计页面内容、mixed content 和 dev server 暴露：`cftn page-audit --name app-example`",
        "- 查看当前命中的 Cloudflare 边缘与 colo：`cftn edge-trace --name app-example`",
        "- 导出特定用户群的客户端优选 IP 实验计划：`cftn client-override-plan --name app-example --prefer-family ipv4`",
        "- 生成多端 canary 测试包：`cftn client-canary-bundle --name app-example --prefer-family ipv4`",
        "- 生成客户端回传模板：`cftn client-report-template --name app-example --prefer-family ipv4`",
        "- 汇总地区/运营商/平台结果：`cftn client-report-summary reports/client-canary.json`",
        "- 重新生成文档：`cftn docs-sync`",
        "",
        "## Mainland Access Notes",
        "",
        "- 社区里常说的“优选 Cloudflare IP”主要适用于直接测试 Cloudflare CDN Anycast IP，或者本地 hosts/自建 DNS 的加速实验。",
        "- 对于 Cloudflare Tunnel 的访客入口，不应该把业务 hostname 改成手选 A 记录 IP；Tunnel 依赖 Cloudflare 托管的代理链路和证书匹配，强行固定 IP 很容易引入证书错误、路由漂移或直接失效。",
        "- `cftn edge-trace` 适合先看当前网络到底打到了哪些 Cloudflare 边缘、返回了什么 colo，再决定是否值得做客户端侧 hosts/本地 DNS 实验。",
        "- `cftn client-override-plan` 会把当前成功的 Cloudflare 边缘候选导出成 hosts 覆盖和验证命令，适合给小规模大陆用户灰度试验。",
        "- `cftn client-canary-bundle` 会把桌面端 hosts 覆盖、移动端本地 DNS 灰度方式、验证步骤和回传模板打包成一份结果。",
        "- 真正的优化目标应该是按运营商、地区、平台分别选出更稳的候选，而不是追求一个全国通吃的固定 IP。",
        "- 如果大陆用户必须稳定低延迟访问，通常需要额外的接入层，例如香港/日本/新加坡附近的反向代理入口，或者具备合规能力的大陆前置 CDN/加速层。",
        "- 如果 HTTPS 已经启用但浏览器仍提示不安全，除了 DNS 劫持命中错误 IP 之外，还要重点排查页面是否加载了 `http://` 资源或不安全表单。",
        "- 如果页面返回里出现 `@vite/client`、`@vite-plugin-checker-runtime`、`/.quasar/client-entry.js` 这类标记，往往说明你公开的是开发服务器而不是生产构建，这本身就容易带来资源错误、HMR websocket 异常和浏览器安全提示。",
        "",
        "## Optimization Principle",
        "",
        "- `cftn` 当前对国内多地、多运营商访问的优化，本质上不是修改 Cloudflare Tunnel 的公网入口架构，而是做 `测量 -> 小流量灰度 -> 分群选优 -> 快速回滚`。",
        "- Tunnel 仍然保持 Cloudflare 官方支持的 remote-managed 模式：业务域名继续走 Cloudflare 代理记录，源站仍然由 tunnel 转发到 `local_url`。",
        "- 优化动作发生在客户端侧。`cftn edge-trace` 先测当前网络实际命中的 Cloudflare 边缘 IP 与 `colo`，`client-override-plan` 再把可用候选导出成 hosts 或本地 DNS override 方案，供特定用户群做 canary。",
        "- 这样做的原因是 Cloudflare Anycast 命中结果高度依赖 `地区 + 运营商 + 平台 + 时间`。同一个 IP 对上海电信桌面端可能更好，对广东移动手机端可能更差，所以不能假设存在一个全国长期最优的固定 IP。",
        "- `client-report-summary` 的目标不是找一个全国统一答案，而是找出 `某运营商 / 某平台 / 某地区` 下更稳的候选，优先保证成功率，再比较 TTFB 和 `trace_colo` 稳定性。",
        "- 因为这套机制是客户端侧灰度，所以一旦候选退化，只需要撤销客户端 hosts 或本地 DNS override，不需要改动 tunnel 架构或做公开 DNS 紧急切换。",
        "",
        "## What Changes",
        "",
        "- `edge-trace`、`client-override-plan`、`client-canary-bundle`、`client-report-template`、`client-report-summary` 这组优化命令本身不会修改 Cloudflare zone、不会修改 tunnel ingress、也不会把业务 hostname 改成公开 A 记录。它们主要读取现有配置并输出诊断、候选和测试材料。",
        "- 它们默认也不会改写 `configs/cf_tunnel.json`。只有显式使用 `--save-config` 的命令，例如 `token-ensure`、`dns-migrate`、`tunnel-apply`，才会把 token、zone 状态或 tunnel 元数据写回本地配置。",
        "- 真正可能发生变更的地方主要有三类：一是客户端机器上的 hosts 文件；二是测试 Wi-Fi、路由器或设备上的本地 DNS override；三是 canary 结果文件，例如你自己保存的 JSON 报告。",
        "- 对 Cloudflare 控制面的正式变更仍然集中在 `dns-migrate` 和 `tunnel-apply`：前者会迁移权威 DNS 托管，后者会创建或更新 tunnel、CNAME/代理入口，并为对应 tunnel 安装或更新独立的本机 `cloudflared-tunnel-*.service`。国内优选流程不应该替代这些正式配置。",
        "- 如果你看到某个优化方案要求把 `app.example.com` 在 Cloudflare DNS 里直接改成固定 A/AAAA 记录，那不属于当前 `cftn` 推荐路径。对于 Tunnel 场景，这通常会破坏 Cloudflare 托管代理链路，带来证书、路由或可用性问题。",
        "- 推荐理解为：`cftn` 的国内访问优化默认改的是 `测试客户端的解析路径`，不是 `生产权威 DNS 的发布方式`。",
        "",
        "## Multi-region Optimization Workflow",
        "",
        "1. 先按测试人群拆分 cohort，不要把全国用户混成一组。至少按 `地区 + 运营商 + 平台` 分层，例如 `上海-电信-桌面`、`广东-移动-Android`、`北京-联通-iPhone`。",
        "2. 用 `cftn edge-trace --name app-example` 先确认当前网络下有哪些可用 Cloudflare 边缘候选，以及它们命中的 `colo`。这一步只负责发现候选，不负责定版。",
        "3. 用 `cftn client-override-plan --name app-example --prefer-family ipv4` 导出首批候选。对于大陆灰度，优先从 IPv4 开始；IPv6 只有在目标网络 IPv6 质量稳定时再单独测试。",
        "4. 用 `cftn client-canary-bundle --name app-example --prefer-family ipv4` 生成多端测试包。桌面端默认走 hosts 覆盖；Android 和 iOS 默认走测试 Wi-Fi 或路由器 DNS override，而不是要求普通手机直接改 hosts。",
        "5. 每个 cohort 一次只测一个候选 IP，不要在同一批用户里同时下发多个候选，否则回传结果会混淆。每组先做 3 到 10 人小灰度，确认成功率和 TTFB 再扩大。",
        "6. 让每个测试用户回传统一字段：`region`、`city`、`isp`、`platform`、`network_type`、`candidate_ip`、`success`、`ttfb_ms`、`trace_colo`、`trace_loc`、`cf_ray`。模板可由 `cftn client-report-template --name app-example --prefer-family ipv4` 生成。",
        "7. 汇总测试结果时，不要只看平均速度。优先看 `success_rate`，其次看 `avg_ttfb_ms`，再看 `trace_colo` 是否稳定。用 `cftn client-report-summary reports/client-canary.json` 按运营商和平台分别选优。",
        "8. 如果 `overall` 最优和某个运营商或平台的最优不一致，就不要强推一个全国统一候选。优先采用运营商专属或平台专属分发方案。",
        "9. 桌面和移动端必须分开验证。很多移动网络会走不同的 DNS、不同的 IPv6/IPv4 策略，桌面端表现好的候选在 Android/iPhone 上可能反而退化。",
        "10. 回滚要和灰度同样制度化。每个 cohort 都要保留一组正常 DNS 对照用户；一旦出现证书错误、超时或页面异常，立即删除客户端 hosts 或本地 DNS override，并用 `curl -I https://app.example.com --max-time 20` 或浏览器直接验证已恢复正常 DNS。",
        "",
        "## Suggested Rollout",
        "",
        "- 第 1 轮：每个运营商挑 1 个地区，每个平台挑少量 canary，目标是确认有没有明显更优的候选。",
        "- 第 2 轮：对第 1 轮胜出的候选做同运营商跨地区复测，判断是否可以升格成该运营商默认候选。",
        "- 第 3 轮：对桌面和移动分别固化分发规则，例如 `电信桌面 -> IP-A`、`移动 Android -> IP-B`。",
        "- 持续维护：Anycast 会漂移，优选结果不是永久有效。建议定期重新跑小规模 canary，并保留快速回滚通道。",
        "",
        "## Commands",
        "",
    ]
    for name, meta in COMMAND_HELP.items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append(f"- Summary: {meta['summary']}")
        lines.append("- Examples:")
        for item in meta["examples"]:
            lines.append(f"  - `{item}`")
        lines.append("")
    return assert_public_text_safe("\n".join(lines).rstrip() + "\n")
