from __future__ import annotations

from pathlib import Path

from webu.runtime_settings.sensitive import assert_public_text_safe


USAGE_DOC_PATH = Path(__file__).resolve().parents[3] / "docs" / "google-docker" / "USAGE.md"
SETUP_DOC_PATH = Path(__file__).resolve().parents[3] / "docs" / "google-docker" / "SETUP.md"
HINTS_DOC_PATH = Path(__file__).resolve().parents[3] / "docs" / "google-docker" / "HINTS.md"

OVERVIEW_SECTIONS = [
    (
        "默认行为",
        [
            "默认 Space：取 configs/hf_spaces.json 中的第一个 space。",
            "默认 HF 服务地址：从 google_api.json 和 hf_spaces.json 自动解析。",
            "默认搜索 token：取 google_api.json 中 hf-space 项的 api_token。",
            "默认管理 token：取 google_docker.json 中的 admin_token。",
            "因此日常使用通常不再需要手写 jq、python heredoc 或 curl。",
        ],
    ),
    (
        "推荐最短路径",
        [
            "ggdk hub-docker-up --mount-configs --replace",
            "ggdk hub-check",
            "ggdk hf-sync-all",
            "ggdk hub-search \"OpenAI news\"",
        ],
    ),
]
COMMAND_HELP = {
    "print-config": {
        "summary": "查看当前解析后的运行时配置。",
        "examples": ["ggdk print-config"],
    },
    "serve": {
        "summary": "以前台方式直接启动 google_docker 服务。",
        "examples": ["python -m webu.google_docker serve --host 0.0.0.0 --port 18200"],
    },
    "hub-serve": {
        "summary": "以前台方式直接启动中心化 google_hub 服务。",
        "examples": ["python -m webu.google_docker hub-serve --host 0.0.0.0 --port 18100"],
    },
    "docker-build": {
        "summary": "构建本地 Docker 镜像。",
        "examples": ["ggdk docker-build", "ggdk docker-build --no-cache"],
    },
    "docker-run": {
        "summary": "手动运行本地 Docker 容器。",
        "examples": [
            "ggdk docker-run --bind-source --mount-configs --replace",
            "ggdk docker-run --proxy-mode disabled --replace",
        ],
    },
    "docker-up": {
        "summary": "按默认建议完成本地 build + run。",
        "examples": [
            "ggdk docker-up",
            "ggdk docker-up --skip-build",
            "ggdk docker-up --proxy-mode disabled",
        ],
    },
    "docker-check": {
        "summary": "检查本地容器状态、服务健康和同端口冲突提示。",
        "examples": ["ggdk docker-check", "ggdk docker-check --port 18200"],
    },
    "docker-logs": {
        "summary": "查看本地 Docker 日志。",
        "examples": ["ggdk docker-logs --follow", "ggdk docker-logs --lines 50"],
    },
    "docker-stop": {
        "summary": "停止并删除指定 Docker 容器。",
        "examples": ["ggdk docker-stop", "ggdk docker-stop --name webu-google-api"],
    },
    "docker-down": {
        "summary": "停止并删除本地 Docker 容器。",
        "examples": ["ggdk docker-down"],
    },
    "hub-docker-up": {
        "summary": "构建并启动本地 hub Docker 服务。",
        "examples": [
            "ggdk hub-docker-up --mount-configs --replace",
            "ggdk hub-docker-up --skip-build --port 18100",
        ],
    },
    "hub-docker-down": {
        "summary": "停止并删除本地 hub Docker 容器。",
        "examples": ["ggdk hub-docker-down"],
    },
    "hub-check": {
        "summary": "检查本地 hub 服务和所有后端状态。",
        "examples": ["ggdk hub-check", "ggdk hub-check --port 18100"],
    },
    "hub-backends": {
        "summary": "列出 hub 当前维护的后端状态和指标。",
        "examples": ["ggdk hub-backends"],
    },
    "hub-search": {
        "summary": "通过中心化 hub 路由搜索请求。",
        "examples": [
            'ggdk hub-search "OpenAI news"',
            'ggdk hub-search "OpenAI news" --num 20',
        ],
    },
    "hf-url": {
        "summary": "打印当前解析出的 HF 服务地址。",
        "examples": ["ggdk hf-url"],
    },
    "hf-create-space": {
        "summary": "创建新的 HF Docker Space。",
        "examples": ["ggdk hf-create-space --space owner/space2 --exist-ok"],
    },
    "hf-sync": {
        "summary": "同步当前代码到默认 HF Space。",
        "examples": [
            "ggdk hf-sync",
            "ggdk hf-sync --restart --factory",
            "ggdk hf-sync --space owner/other-space",
        ],
    },
    "hf-sync-all": {
        "summary": "并行把当前代码同步到所有启用的 HF Spaces。",
        "examples": ["ggdk hf-sync-all", "ggdk hf-sync-all --restart", "ggdk hf-sync-all --max-workers 4"],
    },
    "hf-status": {
        "summary": "查看 HF Space 运行状态。",
        "examples": ["ggdk hf-status"],
    },
    "hf-logs": {
        "summary": "读取远端服务日志。",
        "examples": ["ggdk hf-logs", "ggdk hf-logs --lines 80"],
    },
    "hf-runtime": {
        "summary": "读取远端 /admin/runtime。",
        "examples": ["ggdk hf-runtime"],
    },
    "hf-health": {
        "summary": "读取远端 /health。",
        "examples": ["ggdk hf-health"],
    },
    "hf-home": {
        "summary": "读取远端隐藏首页。",
        "examples": ["ggdk hf-home"],
    },
    "hf-search": {
        "summary": "向远端 /search 发起请求。",
        "examples": [
            'ggdk hf-search "OpenAI news"',
            'ggdk hf-search "OpenAI news" --num 10',
            'ggdk hf-search "OpenAI news" --no-auth',
        ],
    },
    "hf-check": {
        "summary": "聚合远端状态、健康检查、运行时和匿名鉴权检查。",
        "examples": ["ggdk hf-check", "ggdk hf-check --check-auth"],
    },
    "hf-doctor": {
        "summary": "输出更完整的远端诊断信息，包括 bootstrap 文件、提交数和日志摘要。",
        "examples": ["ggdk hf-doctor", "ggdk hf-doctor --check-auth --lines 80"],
    },
    "hf-files": {
        "summary": "列出远端仓库文件。",
        "examples": ["ggdk hf-files", "ggdk hf-files --prefix bootstrap/"],
    },
    "hf-commit-count": {
        "summary": "查看远端提交数量。",
        "examples": ["ggdk hf-commit-count"],
    },
    "hf-restart": {
        "summary": "请求重启远端 Space。",
        "examples": ["ggdk hf-restart", "ggdk hf-restart --factory"],
    },
    "hf-super-squash": {
        "summary": "压缩远端提交历史。",
        "examples": ["ggdk hf-super-squash"],
    },
    "docs-sync": {
        "summary": "用共享说明源重写 docs/google-docker 下的主要文档。",
        "examples": ["ggdk docs-sync"],
    },
    "config-check": {
        "summary": "按共享 schema 校验本地 configs/*.json。",
        "examples": ["ggdk config-check", "ggdk config-check --name google_api"],
    },
    "config-init": {
        "summary": "按共享 schema 生成最小配置骨架。",
        "examples": ["ggdk config-init", "ggdk config-init --name google_api --force"],
    },
    "config-schema": {
        "summary": "打印某个配置文件对应的 schema。",
        "examples": ["ggdk config-schema google_api", "ggdk config-schema llms"],
    },
}


COMMAND_ORDER = [
    "print-config",
    "hub-serve",
    "docker-build",
    "docker-run",
    "docker-up",
    "docker-check",
    "docker-logs",
    "docker-down",
    "hub-docker-up",
    "hub-docker-down",
    "hub-check",
    "hub-backends",
    "hub-search",
    "hf-create-space",
    "hf-url",
    "hf-sync",
    "hf-sync-all",
    "hf-status",
    "hf-health",
    "hf-home",
    "hf-runtime",
    "hf-search",
    "hf-check",
    "hf-doctor",
    "hf-logs",
    "hf-files",
    "hf-commit-count",
    "hf-restart",
    "hf-super-squash",
    "config-check",
    "config-init",
    "config-schema",
    "docs-sync",
]


def _render_examples(examples: list[str], bullet: str) -> str:
    return "\n".join(f"{bullet}{example}" for example in examples)


def root_description() -> str:
    return "Manage dockerized WebU google_api deployments with shared defaults from local configs."


def root_epilog() -> str:
    lines = ["Quick Start:"]
    for _, items in OVERVIEW_SECTIONS:
        if items and items[0].startswith("ggdk"):
            lines.extend(f"  {item}" for item in items)
            break
    lines.append("")
    lines.append("Examples:")
    lines.append("  ggdk hub-check")
    lines.append("  ggdk hub-docker-up --mount-configs --replace")
    lines.append("  ggdk hf-sync-all")
    return assert_public_text_safe("\n".join(lines))


def command_description(command_name: str) -> str:
    item = COMMAND_HELP.get(command_name)
    return item["summary"] if item else ""


def command_epilog(command_name: str) -> str:
    item = COMMAND_HELP.get(command_name)
    if not item:
        return ""
    lines = ["Examples:"]
    lines.extend(f"  {example}" for example in item.get("examples", []))
    return assert_public_text_safe("\n".join(lines))


def render_usage_markdown() -> str:
    lines = [
        "# 使用说明",
        "",
        "> 本文档由 `ggdk docs-sync` 从共享帮助源自动生成。",
        "",
    ]
    for title, items in OVERVIEW_SECTIONS:
        lines.append(f"## {title}")
        lines.append("")
        for index, item in enumerate(items, start=1):
            if item.startswith("ggdk"):
                lines.append("```bash")
                lines.append(item)
                lines.append("```")
            else:
                lines.append(f"{index}. {item}")
        lines.append("")

    lines.append("## 命令速查")
    lines.append("")
    for command_name in COMMAND_ORDER:
        item = COMMAND_HELP[command_name]
        lines.append(f"### `{command_name}`")
        lines.append("")
        lines.append(item["summary"])
        lines.append("")
        lines.append("```bash")
        lines.extend(item["examples"])
        lines.append("```")
        lines.append("")

    lines.append("## 覆盖默认值")
    lines.append("")
    lines.append("1. 操作非默认 Space：加 `--space owner/other-space`。")
    lines.append("2. 临时覆盖管理 token：加 `--admin-token ...`。")
    lines.append("3. 临时覆盖搜索 token：加 `--api-token ...`。")
    lines.append("4. 验证匿名行为：对 `hf-search` 使用 `--no-auth`。")
    lines.append("5. 初始化多实例 hub 配置：先运行 `ggdk config-init --name google_hub`。")
    lines.append("6. 配置有疑问时，先运行 `ggdk config-check`。")
    lines.append("7. 修改帮助源或 schema 后，运行 `ggdk docs-sync` 更新文档。")
    lines.append("")
    return "\n".join(lines)


def render_setup_markdown() -> str:
    lines = [
        "# 部署步骤",
        "",
        "> 本文档由 `ggdk docs-sync` 从共享帮助源自动生成。",
        "",
        "## 1. 先准备最小配置",
        "",
        "必须先准备以下文件：",
        "",
        "1. `configs/hf_spaces.json`",
        "2. `configs/google_api.json`",
        "3. `configs/google_docker.json`",
        "4. `configs/google_hub.json`",
        "",
        "如果要启用验证码 VLM 或本地代理，再额外维护 `configs/captcha.json`、`configs/llms.json`、`configs/proxies.json`。",
        "",
        "配置写完后，先跑一次校验：",
        "",
        "```bash",
        "ggdk config-init --name google_hub",
        "ggdk config-check",
        "```",
        "",
        "## 2. 本地中心服务启动",
        "",
        "```bash",
        "ggdk hub-docker-up --mount-configs --replace",
        "ggdk hub-check",
        "```",
        "",
        "如果你还保留单实例 google_api，本地 hub 会把它当成一个后端节点统一调度。",
        "",
        "## 3. 同步到 HF Space",
        "",
        "```bash",
        "ggdk hf-create-space --space owner/space2 --exist-ok",
        "ggdk hf-sync-all --restart",
        "```",
        "",
        "如果想拿到更完整的诊断信息，用：",
        "",
        "```bash",
        "ggdk hf-doctor --space owner/space1 --check-auth",
        "ggdk hf-doctor --space owner/space2 --check-auth",
        "```",
        "",
        "## 4. 常见临时覆盖",
        "",
        "1. 切换 Space：为相关命令追加 `--space owner/other-space`。",
        "2. 切换管理 token：追加 `--admin-token ...`。",
        "3. 切换搜索 token：对 `hf-search` 追加 `--api-token ...`。",
        "4. 修改共享说明源后，执行 `ggdk docs-sync`。",
        "",
    ]
    return assert_public_text_safe("\n".join(lines))


def render_hints_markdown() -> str:
    lines = [
        "# 使用提示",
        "",
        "> 本文档由 `ggdk docs-sync` 从共享帮助源自动生成。",
        "",
        "## 先用命令，不要先拼 shell",
        "",
        "优先顺序：",
        "",
        "1. 状态检查优先用 `ggdk hub-check` 或 `ggdk hub-backends`。",
        "2. Docker 本地联调用 `ggdk hub-docker-up`、`ggdk hub-check`、`ggdk hub-docker-down`。",
        "3. Space 仓库排查用 `ggdk hf-files --space owner/space1 --prefix bootstrap/`。",
        "4. 配置排查用 `ggdk config-init` 和 `ggdk config-check`。",
        "",
        "## 常见排查动作",
        "",
        "```bash",
        "ggdk hub-check",
        "ggdk hub-backends",
        "ggdk hf-logs --space owner/space1 --lines 80",
        "ggdk hf-files --space owner/space2 --prefix bootstrap/",
        "```",
        "",
        "## 推荐诊断顺序",
        "",
        "1. `ggdk config-init --name google_hub` 或 `ggdk config-check`",
        "2. `ggdk hub-check`",
        "3. `ggdk hf-doctor --space owner/space1 --check-auth`",
        "4. `ggdk hf-doctor --space owner/space2 --check-auth`",
        "",
        "## 文档维护原则",
        "",
        "1. `USAGE.md`、`SETUP.md`、`HINTS.md`、`CONFIGS.md` 都由生成器维护。",
        "2. 命令帮助和文档示例要共用同一份说明源。",
        "3. 配置模板和约束要共用同一份 schema 源。",
        "",
    ]
    lines.append("")
    return assert_public_text_safe("\n".join(lines))