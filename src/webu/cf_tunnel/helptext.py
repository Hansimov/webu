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
        "9. 用 `dig example.com NS`、`dig +trace example.com A` 和实际业务 URL 做最终验证。",
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
        "- 重新生成文档：`cftn docs-sync`",
        "",
        "## Mainland Access Notes",
        "",
        "- 社区里常说的“优选 Cloudflare IP”主要适用于直接测试 Cloudflare CDN Anycast IP，或者本地 hosts/自建 DNS 的加速实验。",
        "- 对于 Cloudflare Tunnel 的访客入口，不应该把业务 hostname 改成手选 A 记录 IP；Tunnel 依赖 Cloudflare 托管的代理链路和证书匹配，强行固定 IP 很容易引入证书错误、路由漂移或直接失效。",
        "- `cftn edge-trace` 适合先看当前网络到底打到了哪些 Cloudflare 边缘、返回了什么 colo，再决定是否值得做客户端侧 hosts/本地 DNS 实验。",
        "- 如果大陆用户必须稳定低延迟访问，通常需要额外的接入层，例如香港/日本/新加坡附近的反向代理入口，或者具备合规能力的大陆前置 CDN/加速层。",
        "- 如果 HTTPS 已经启用但浏览器仍提示不安全，除了 DNS 劫持命中错误 IP 之外，还要重点排查页面是否加载了 `http://` 资源或不安全表单。",
        "- 如果页面返回里出现 `@vite/client`、`@vite-plugin-checker-runtime`、`/.quasar/client-entry.js` 这类标记，往往说明你公开的是开发服务器而不是生产构建，这本身就容易带来资源错误、HMR websocket 异常和浏览器安全提示。",
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
