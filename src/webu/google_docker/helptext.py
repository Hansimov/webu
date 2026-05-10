from __future__ import annotations

from pathlib import Path

from webu.runtime_settings import DEFAULT_GOOGLE_API_PORT, DEFAULT_GOOGLE_HUB_PORT
from webu.runtime_settings.sensitive import assert_public_text_safe


USAGE_DOC_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "google-docker" / "USAGE.md"
)
SETUP_DOC_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "google-docker" / "SETUP.md"
)
HINTS_DOC_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "google-docker" / "HINTS.md"
)

OVERVIEW_SECTIONS = [
    (
        "当前稳定路径",
        [
            "Google 搜索稳定方案以真实 Chrome、headless=false、Xvfb 兜底显示为默认前提。",
            "本地代理正常但自动化浏览器触发 captcha 时，优先排查浏览器指纹和运行模式，不要先怀疑代理本身。",
            "当远端运行时变量、浏览器模式或 bootstrap 资料发生变化时，HF 同步后优先执行 factory restart，再等待所有 Space 回到 RUNNING。",
            "如果 HF mirror 在上传或建仓阶段出现 SSL EOF，发布和压缩历史应临时切回官方 huggingface.co 端点。",
        ],
    ),
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
            "ggdk api-docker-up --mount-configs --replace",
            "ggdk hub-docker-up --mount-configs --replace",
            "gghb check",
            'gghb benchmark --query "OpenAI news" --requests 24 --concurrency 6',
            "ggdk hf-release",
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
        "examples": [
            f"python -m webu.google_docker serve --host 0.0.0.0 --port {DEFAULT_GOOGLE_API_PORT}"
        ],
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
    "api-docker-up": {
        "summary": "按默认建议完成本地 build + run。",
        "examples": [
            "ggdk api-docker-up",
            "ggdk api-docker-up --skip-build",
            "ggdk api-docker-up --proxy-mode disabled",
        ],
    },
    "docker-check": {
        "summary": "检查本地容器状态、服务健康和同端口冲突提示。",
        "examples": [
            "ggdk docker-check",
            f"ggdk docker-check --port {DEFAULT_GOOGLE_API_PORT}",
        ],
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
            f"ggdk hub-docker-up --skip-build --port {DEFAULT_GOOGLE_HUB_PORT}",
        ],
    },
    "hub-docker-down": {
        "summary": "停止并删除本地 hub Docker 容器。",
        "examples": ["ggdk hub-docker-down"],
    },
    "hub-docker-logs": {
        "summary": "查看本地 hub Docker 日志。",
        "examples": [
            "ggdk hub-docker-logs --follow",
            "ggdk hub-docker-logs --lines 50",
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
        "examples": [
            "ggdk hf-sync-all",
            "ggdk hf-sync-all --restart --factory",
            "ggdk hf-sync-all --max-workers 4",
        ],
    },
    "hf-release": {
        "summary": "一键执行 HF 同步、等待 RUNNING、真实审计，并可选批量压缩历史。",
        "examples": [
            "ggdk hf-release",
            "ggdk hf-release --format both --output data/debug/google_hub_all_audit_release.json",
            "ggdk hf-release --squash",
            "HF_ENDPOINT=https://huggingface.co WEBU_HF_CONTROL_ENDPOINT=https://huggingface.co ggdk hf-release",
        ],
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
        "summary": "读取远端默认首页；HF Space 默认展示运行面板。",
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
    "hf-super-squash-all": {
        "summary": "并行压缩所有启用 HF Spaces 的提交历史。",
        "examples": [
            "ggdk hf-super-squash-all",
            "ggdk hf-super-squash-all --max-workers 4",
        ],
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
    "docker-build",
    "docker-run",
    "api-docker-up",
    "docker-check",
    "docker-logs",
    "docker-down",
    "hub-docker-up",
    "hub-docker-down",
    "hub-docker-logs",
    "hf-create-space",
    "hf-url",
    "hf-sync",
    "hf-sync-all",
    "hf-release",
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
    "hf-super-squash-all",
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
    lines.append("  ggdk api-docker-up --mount-configs --replace")
    lines.append("  ggdk hub-docker-up --mount-configs --replace")
    lines.append("  gghb check")
    lines.append("  ggdk hf-release")
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
    lines.append(
        "5. 初始化多实例 hub 配置：先运行 `ggdk config-init --name google_hub`。"
    )
    lines.append("6. 本地 hub 的检查、查询和 benchmark 统一改用 `gghb`。")
    lines.append("7. HF 远端发布优先用 `ggdk hf-release`，不要再手工拼 sync、restart、audit。")
    lines.append("8. 如果改了 headless、Chrome 通道、bootstrap 或运行时环境变量，优先保留 `--factory`。")
    lines.append("9. 配置有疑问时，先运行 `ggdk config-check`。")
    lines.append("10. 修改帮助源或 schema 后，运行 `ggdk docs-sync` 更新文档。")
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
        "ggdk api-docker-up --mount-configs --replace",
        "ggdk hub-docker-up --mount-configs --replace",
        "gghb check",
        'gghb benchmark --query "OpenAI news" --requests 24 --concurrency 6',
        "```",
        "",
        "其中 `ggdk` 负责容器生命周期，`gghb` 负责 hub 本身的检查、查询和 benchmark。",
        "",
        "## 3. 同步到 HF Space",
        "",
        "```bash",
        "ggdk hf-create-space --space owner/space2 --exist-ok",
        "ggdk hf-release",
        "```",
        "",
        "如果想手动拆分执行，推荐顺序是：",
        "",
        "```bash",
        "ggdk hf-sync-all --restart --factory",
        "ggdk hf-status --space owner/space1",
        "ggdk hf-status --space owner/space2",
        "gghb audit --target all --format both --output data/debug/google_hub_all_audit_manual.json",
        "ggdk hf-super-squash-all",
        "```",
        "",
        "如果想拿到更完整的诊断信息，用：",
        "",
        "```bash",
        "ggdk hf-doctor --space owner/space1 --check-auth",
        "ggdk hf-doctor --space owner/space2 --check-auth",
        "```",
        "",
        "注意：",
        "",
        "1. 单纯 `--restart` 不一定会立刻反映新的浏览器模式或环境变量；涉及这类变化时，应优先 `--factory`。",
        "2. 验证通过后再做 `hf-super-squash-all`，不要在排障中途先压缩历史。",
        "3. 审计报告建议固定输出到 `data/debug/`，方便回溯每次发布状态。",
        "4. 如果 `hf-sync` 或 `hf-release` 在 HF mirror 上遇到 SSL EOF，可临时用 `HF_ENDPOINT=https://huggingface.co WEBU_HF_CONTROL_ENDPOINT=https://huggingface.co` 切回官方端点。",
        "",
        "## 4. 常见临时覆盖",
        "",
        "1. 切换 Space：为相关命令追加 `--space owner/other-space`。",
        "2. 切换管理 token：追加 `--admin-token ...`。",
        "3. 切换搜索 token：对 `hf-search` 追加 `--api-token ...`。",
        "4. 本地 hub 直接调试：使用 `gghb serve` 或 `gghb search`。",
        "5. 修改共享说明源后，执行 `ggdk docs-sync`。",
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
        "1. 单实例 google_api 用 `ggsc`；hub 本身用 `gghb`；容器和 HF 部署用 `ggdk`。",
        "2. Docker 本地联调用 `ggdk api-docker-up`、`ggdk hub-docker-up`、`gghb check`。",
        "3. Space 仓库排查用 `ggdk hf-files --space owner/space1 --prefix bootstrap/`。",
        "4. 配置排查用 `ggdk config-init` 和 `ggdk config-check`。",
        "",
        "## 常见排查动作",
        "",
        "```bash",
        "gghb check",
        "gghb backends",
        "ggdk hf-release --format both",
        'gghb benchmark --query "OpenAI news" --requests 12 --concurrency 4',
        "ggdk hf-logs --space owner/space1 --lines 80",
        "ggdk hf-files --space owner/space2 --prefix bootstrap/",
        "```",
        "",
        "## 推荐诊断顺序",
        "",
        "1. `ggdk config-init --name google_hub` 或 `ggdk config-check`",
        "2. `gghb check`",
        '3. `gghb benchmark --query "OpenAI news" --requests 12 --concurrency 4`',
        "4. `ggdk hf-release --format both --output data/debug/google_hub_all_audit_latest.json`",
        "5. `ggdk hf-doctor --space owner/space1 --check-auth`",
        "6. `ggdk hf-doctor --space owner/space2 --check-auth`",
        "",
        "## 最新经验",
        "",
        "1. 对 Google 来说，真实 Chrome + headed + 虚拟显示比继续伪造 UA 更关键；后者不足以解决 captcha。",
        "2. HF Space 更新浏览器相关环境变量后，需要把验证重点放在 `/admin/runtime` 和真实搜索审计，而不是只看构建成功。",
        "3. 普通 restart 适合代码热更新；factory restart 更适合运行时变量、浏览器模式、bootstrap 资料发生变化后的验收。",
        "4. 批量 super squash 放到验收通过之后做，既能保留排障期间的提交证据，也能在稳定后收敛历史。",
        "5. HF mirror 适合日常访问，但一旦 `/api/repos/create` 或上传阶段出现 SSL EOF，发布链路应直接切回官方 `huggingface.co`。",
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
