"""网络修复工具 — 解决 Cloudflare WARP 与 Tailscale / IPv6 ndppd 的共存冲突。

问题：
  1. WARP 在 nftables 的 `inet cloudflare-warp` 表中对 100.96.0.0/12 范围
     设置了 drop 规则。Tailscale 的 MagicDNS (100.100.100.100) 落在此范围内。
     同时 WARP 的 ip rule (priority 5209) 优先级高于 Tailscale (priority 5270)。

  2. WARP 将全局 DNS 设为 127.0.2.2/127.0.2.3（Cloudflare DOH 代理），配合
     routing domain ~.（catch-all），导致所有 DNS 查询走 Cloudflare DNS。
     Cloudflare DNS 不返回中国 CDN 域名（如 api.bilibili.com）的 AAAA 记录，
     使得 IPv6Session（force_ipv6）无法解析目标地址。

  3. WARP 的 ip -6 rule (priority 5209) 可能捕获 ndppd 前缀的 IPv6 出口流量。

修复：
  1. 在 WARP nftables drop 规则前插入 Tailscale 接口 accept 规则
  2. 添加优先级更高的 ip rule 使 Tailscale 路由表先于 WARP 被查询
  3. 在物理网口上设置 routing domain ~. 使 ISP DNS 优先于 WARP DNS
  4. 添加 ip -6 rule 保护 ndppd 前缀流量走 main 表
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


# ═══════════════════════════════════════════════════════════════
# IPv6 ndppd 路由保护
# ═══════════════════════════════════════════════════════════════

# WARP ip -6 rule (priority 5209) 将所有未标记的 IPv6 流量送入 table 65743。
# 通常 table 65743 只有 WARP 专用路由，正常 IPv6 流量会 fall-through。
# 但 WARP 重连/配置变更时可能临时添加默认路由，导致 ndppd 随机 IPv6 出口流量
# 被捕获并送入 CloudflareWARP 接口，被 nftables tun 链 reject。
# 解决：在 WARP 规则之前插入 ip -6 rule，确保 ndppd 前缀流量永远走 main 表。

IPV6_PROTECT_PRIORITY = 5200


def _get_ipv6_global_prefix() -> tuple[str, str, int] | None:
    """检测全局 IPv6 前缀（跳过 CloudflareWARP 接口）。

    Returns:
        (prefix, interface, prefix_bits) 如 ("2408:820c:685a:f860", "enp100s0f1", 64)
        或 None。
    """
    try:
        from ..ipv6.route import IPv6Prefixer

        prefixer = IPv6Prefixer()
        return prefixer.prefix, prefixer.netint, prefixer.prefix_bits
    except Exception:
        return None


def _has_ip6_rule(priority: int, keyword: str) -> bool:
    """检查 ip -6 rule 是否已存在。"""
    rc, out = _run("ip -6 rule show")
    return f"{priority}:" in out and keyword in out


def fix_ipv6_routing() -> dict:
    """保护 IPv6 ndppd 出口流量不被 WARP 路由表捕获。

    添加:
        ip -6 rule add priority 5200 from <prefix>::/<bits> lookup main

    Returns:
        dict: {"ipv6_rule": bool} — 是否本次添加了规则
    """
    result = {"ipv6_rule": False}

    prefix_info = _get_ipv6_global_prefix()
    if prefix_info is None:
        logger.mesg("  IPv6: no global prefix detected — skipping")
        return result

    prefix, netint, prefix_bits = prefix_info
    prefix_cidr = f"{prefix}::/{prefix_bits}"

    if _has_ip6_rule(IPV6_PROTECT_PRIORITY, prefix_cidr):
        logger.mesg(
            f"  IPv6: rule for {prefix_cidr} already exists "
            f"at priority {IPV6_PROTECT_PRIORITY}"
        )
    else:
        rc, _ = _sudo_run(
            [
                "ip", "-6", "rule", "add",
                "priority", str(IPV6_PROTECT_PRIORITY),
                "from", prefix_cidr,
                "lookup", "main",
            ]
        )
        if rc == 0:
            result["ipv6_rule"] = True
            logger.okay(
                f"  ✓ IPv6: added rule from {prefix_cidr} lookup main "
                f"at priority {IPV6_PROTECT_PRIORITY}"
            )
        else:
            logger.warn(f"  × IPv6: failed to add rule for {prefix_cidr}")

    return result


# ═══════════════════════════════════════════════════════════════
# DNS 修复 — 恢复 ISP DNS 优先级
# ═══════════════════════════════════════════════════════════════

# WARP 将全局 DNS 设为 127.0.2.2/127.0.2.3（Cloudflare DOH 代理），
# 配合 routing domain ~.（catch-all），劫持了所有 DNS 查询。
# Cloudflare DNS 不返回中国 CDN 域名（如 bilibili）的 AAAA 记录，
# 导致 IPv6Session (force_ipv6) 无法解析目标地址。
# 修复：在物理网口上设置 routing domain ~.，使 ISP DNS 优先于 WARP DNS。


def _get_resolvectl_domain(interface: str) -> str:
    """获取接口当前的 DNS routing domain 配置。"""
    rc, out = _run(f"resolvectl domain {interface}")
    if rc != 0:
        return ""
    # 输出格式: "Link 4 (enp100s0f1): ~."
    for line in out.splitlines():
        if interface in line and "~." in line:
            return "~."
    return ""


def fix_dns_routing() -> dict:
    """修复 WARP DNS 劫持：在物理网口设置 routing domain ~. 使 ISP DNS 优先。

    执行:
        resolvectl domain <netint> ~.

    Returns:
        dict: {"dns_fix": bool} — 是否本次进行了修复
    """
    result = {"dns_fix": False}

    prefix_info = _get_ipv6_global_prefix()
    if prefix_info is None:
        logger.mesg("  DNS: no network interface detected — skipping")
        return result

    _, netint, _ = prefix_info

    # 检查是否已设置
    if _get_resolvectl_domain(netint) == "~.":
        logger.mesg(f"  DNS: {netint} already has routing domain ~.")
        return result

    # 设置 routing domain ~.
    rc, _ = _sudo_run(["resolvectl", "domain", netint, "~."])
    if rc == 0:
        result["dns_fix"] = True
        logger.okay(f"  ✓ DNS: set {netint} routing domain to ~. (ISP DNS priority)")
    else:
        logger.warn(f"  × DNS: failed to set routing domain on {netint}")

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
