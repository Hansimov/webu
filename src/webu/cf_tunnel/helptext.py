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
        "6. 用 `dig example.com NS`、`dig +trace example.com A` 和实际业务 URL 做最终验证。",
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
        "- 重新生成文档：`cftn docs-sync`",
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
