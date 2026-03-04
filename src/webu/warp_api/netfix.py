"""网络修复工具 — 解决 Cloudflare WARP 与 Tailscale 的共存冲突。

问题：
  WARP 在 nftables 的 `inet cloudflare-warp` 表中对 100.96.0.0/12 范围
  设置了 drop 规则（输入和输出方向）。Tailscale 的 MagicDNS 服务位于
  100.100.100.100，恰好落在这个范围内，导致 DNS 查询被丢弃。
  同时，WARP 的 ip rule (priority 5209) 优先级高于 Tailscale 的
  (priority 5270)，导致路由表查找顺序不正确。

修复：
  1. 在 WARP nftables 的 drop 规则之前插入 Tailscale 接口的 accept 规则
  2. 添加优先级更高的 ip rule 使 Tailscale 路由表先于 WARP 被查询
"""

import os
import subprocess

from tclogger import logger, logstr


TAILSCALE_INTERFACE = "tailscale0"
WARP_NFT_TABLE = "inet cloudflare-warp"

# Tailscale 路由表号
TAILSCALE_TABLE = 52

# WARP ip rule 优先级 (5209)，我们在它之前添加 Tailscale 规则
TAILSCALE_RULE_PRIORITY = 5200


def _sudo_run(cmd: list[str], check: bool = False) -> tuple[int, str]:
    """运行需要 sudo 的命令，自动使用 SUDOPASS 提权。"""
    sudopass = os.environ.get("SUDOPASS", "")
    full_cmd = ["sudo"] + (["-S"] if sudopass else []) + cmd

    result = subprocess.run(
        full_cmd,
        input=(sudopass + "\n").encode() if sudopass else None,
        capture_output=True,
        timeout=15,
    )
    return result.returncode, result.stdout.decode(errors="replace").strip()


def _run(cmd: str, check: bool = False) -> tuple[int, str]:
    """运行系统命令。"""
    result = subprocess.run(
        cmd.split(),
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip()


def _nft_run(cmd: str) -> tuple[int, str]:
    """运行 nft 命令（通过 SUDOPASS 提权）。"""
    return _sudo_run(["nft"] + cmd.split())


def _get_nft_handle(chain: str, pattern: str) -> int | None:
    """获取 nftables 规则的 handle 编号。"""
    rc, out = _nft_run(f"-a list chain {WARP_NFT_TABLE} {chain}")
    if rc != 0:
        return None
    for line in out.splitlines():
        if pattern in line:
            parts = line.strip().split("# handle ")
            if len(parts) == 2:
                return int(parts[1])
    return None


def _has_nft_rule(chain: str, pattern: str) -> bool:
    """检查 nftables 规则是否已存在。"""
    rc, out = _nft_run(f"list chain {WARP_NFT_TABLE} {chain}")
    if rc != 0:
        return False
    return pattern in out


def _has_ip_rule(priority: int, table: int) -> bool:
    """检查 ip rule 是否已存在。"""
    rc, out = _run("ip rule show")
    return f"{priority}:" in out and f"lookup {table}" in out


# ═══════════════════════════════════════════════════════════════
# 公共接口
# ═══════════════════════════════════════════════════════════════


def fix_tailscale_compat() -> dict:
    """修复 WARP 与 Tailscale 的兼容性问题。

    Returns:
        dict: {"nft_input": bool, "nft_output": bool, "ip_rule": bool}
              各项是否进行了修复（True = 本次添加，False = 已存在或不需要）
    """
    result = {"nft_input": False, "nft_output": False, "ip_rule": False}

    # 检查 WARP nftables 表是否存在
    rc, _ = _nft_run(f"list table {WARP_NFT_TABLE}")
    if rc != 0:
        logger.mesg("  WARP nftables table not found — skipping nft fixes")
        return result

    ts_accept = f'iifname "{TAILSCALE_INTERFACE}" accept'

    # ── 修复 input 链 ────────────────────────────────────────
    if _has_nft_rule("input", ts_accept):
        logger.mesg("  nft input: Tailscale exception already exists")
    else:
        handle = _get_nft_handle("input", "100.96.0.0/12 drop")
        if handle:
            rc, _ = _nft_run(
                f'insert rule {WARP_NFT_TABLE} input handle {handle} '
                f'iifname "{TAILSCALE_INTERFACE}" accept'
            )
            if rc == 0:
                result["nft_input"] = True
                logger.okay(f"  ✓ nft input: added Tailscale exception (before handle {handle})")
            else:
                logger.warn(f"  × nft input: failed to insert rule")
        else:
            logger.mesg("  nft input: no 100.96.0.0/12 drop rule found")

    # ── 修复 output 链 ───────────────────────────────────────
    ts_out_accept = f'oifname "{TAILSCALE_INTERFACE}" accept'
    if _has_nft_rule("output", ts_out_accept):
        logger.mesg("  nft output: Tailscale exception already exists")
    else:
        handle = _get_nft_handle("output", "100.96.0.0/12 drop")
        if handle:
            rc, _ = _nft_run(
                f'insert rule {WARP_NFT_TABLE} output handle {handle} '
                f'oifname "{TAILSCALE_INTERFACE}" accept'
            )
            if rc == 0:
                result["nft_output"] = True
                logger.okay(f"  ✓ nft output: added Tailscale exception (before handle {handle})")
            else:
                logger.warn(f"  × nft output: failed to insert rule")
        else:
            logger.mesg("  nft output: no 100.96.0.0/12 drop rule found")

    # ── 修复 ip rule 优先级 ──────────────────────────────────
    if _has_ip_rule(TAILSCALE_RULE_PRIORITY, TAILSCALE_TABLE):
        logger.mesg(f"  ip rule: Tailscale priority {TAILSCALE_RULE_PRIORITY} already exists")
    else:
        rc, _ = _sudo_run(
            ["ip", "rule", "add", "priority", str(TAILSCALE_RULE_PRIORITY),
             "lookup", str(TAILSCALE_TABLE)]
        )
        if rc == 0:
            result["ip_rule"] = True
            logger.okay(
                f"  ✓ ip rule: added lookup {TAILSCALE_TABLE} at priority {TAILSCALE_RULE_PRIORITY}"
            )
        else:
            logger.warn(f"  × ip rule: failed to add rule")

    return result


def check_tailscale_compat() -> dict:
    """检查 Tailscale 兼容性状态（不做修改）。"""
    ts_accept_in = f'iifname "{TAILSCALE_INTERFACE}" accept'
    ts_accept_out = f'oifname "{TAILSCALE_INTERFACE}" accept'

    return {
        "nft_table_exists": _nft_run(f"list table {WARP_NFT_TABLE}")[0] == 0,
        "nft_input_ok": _has_nft_rule("input", ts_accept_in),
        "nft_output_ok": _has_nft_rule("output", ts_accept_out),
        "ip_rule_ok": _has_ip_rule(TAILSCALE_RULE_PRIORITY, TAILSCALE_TABLE),
    }
