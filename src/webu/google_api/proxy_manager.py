"""代理管理器 — 基于固定代理列表的健康检查、负载均衡和自动故障转移。

取代旧的基于 MongoDB 代理池的方案，专注于使用给定的代理列表：
- 主代理：socks5://127.0.0.1:11000 (Cloudflare WARP)
- 备用代理：http://127.0.0.1:11111, http://127.0.0.1:11119

功能：
- 周期性健康检查
- 自动故障转移：主代理不可用时，切换到备用代理
- 自动恢复：周期性检查主代理是否恢复，恢复后自动切回
- 使用报告反馈：搜索成功/失败时更新代理状态
"""

import asyncio
import random
import time

from dataclasses import dataclass, field
from enum import Enum
from tclogger import logger, logstr
from typing import Optional

import aiohttp
from aiohttp_socks import ProxyConnector


# ═══════════════════════════════════════════════════════════════
# 默认代理配置
# ═══════════════════════════════════════════════════════════════

DEFAULT_PROXIES = [
    {"url": "socks5://127.0.0.1:11000", "role": "primary", "name": "warp-socks5"},
    {"url": "http://127.0.0.1:11111", "role": "backup", "name": "backup-11111"},
    {"url": "http://127.0.0.1:11119", "role": "backup", "name": "backup-11119"},
]

# 健康检查间隔（秒）
HEALTH_CHECK_INTERVAL = 30

# 恢复检查间隔（秒）— 当主代理不可用时，多久检查一次是否恢复
RECOVERY_CHECK_INTERVAL = 15

# 健康检查超时（秒）
HEALTH_CHECK_TIMEOUT = 15

# 连续失败次数阈值 — 超过此次数标记为不健康
FAILURE_THRESHOLD = 3

# 健康检查端点
HEALTH_CHECK_URLS = [
    "https://www.google.com",
    "https://httpbin.org/ip",
    "https://ifconfig.me",
]


# ═══════════════════════════════════════════════════════════════
# 代理状态
# ═══════════════════════════════════════════════════════════════


class ProxyRole(str, Enum):
    PRIMARY = "primary"
    BACKUP = "backup"


@dataclass
class ProxyState:
    """单个代理的运行时状态。"""

    url: str
    name: str
    role: ProxyRole
    healthy: bool = True
    latency_ms: int = 0
    last_check_time: float = 0.0
    last_success_time: float = 0.0
    last_failure_time: float = 0.0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_successes: int = 0
    total_failures: int = 0

    @property
    def is_primary(self) -> bool:
        return self.role == ProxyRole.PRIMARY

    @property
    def success_rate(self) -> float:
        total = self.total_successes + self.total_failures
        if total == 0:
            return 1.0
        return self.total_successes / total

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "name": self.name,
            "role": self.role.value,
            "healthy": self.healthy,
            "latency_ms": self.latency_ms,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "success_rate": f"{self.success_rate:.1%}",
            "last_check": time.strftime(
                "%H:%M:%S", time.localtime(self.last_check_time)
            )
            if self.last_check_time
            else "never",
        }


# ═══════════════════════════════════════════════════════════════
# 健康检查
# ═══════════════════════════════════════════════════════════════


async def check_proxy_health(
    proxy_url: str,
    timeout_s: int = HEALTH_CHECK_TIMEOUT,
    check_url: str = None,
) -> tuple[bool, int, str]:
    """检查代理是否可用。

    通过代理发送 HTTP 请求到检测端点，验证连通性。

    Args:
        proxy_url: 代理 URL (e.g. "socks5://127.0.0.1:11000")
        timeout_s: 超时秒数
        check_url: 检测 URL（默认使用 Google）

    Returns:
        (is_healthy, latency_ms, error_message)
    """
    url = check_url or HEALTH_CHECK_URLS[0]
    timeout = aiohttp.ClientTimeout(total=timeout_s)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Encoding": "gzip, deflate",
    }

    try:
        is_socks = proxy_url.startswith("socks")
        if is_socks:
            connector = ProxyConnector.from_url(proxy_url)
            session = aiohttp.ClientSession(
                connector=connector, headers=headers, timeout=timeout,
            )
            kwargs = {"ssl": False}
        else:
            session = aiohttp.ClientSession(
                headers=headers, timeout=timeout,
            )
            kwargs = {"proxy": proxy_url, "ssl": False}

        async with session:
            start = time.time()
            async with session.get(url, **kwargs) as resp:
                await resp.read()
                elapsed_ms = int((time.time() - start) * 1000)

                # 任何 HTTP 响应都说明代理可达（包括 4xx）
                # 只要能连通目标就认为健康
                if resp.status < 500:
                    return True, elapsed_ms, ""
                else:
                    return False, elapsed_ms, f"HTTP {resp.status}"

    except asyncio.TimeoutError:
        return False, 0, "timeout"
    except aiohttp.ClientError as e:
        return False, 0, str(e)[:200]
    except Exception as e:
        return False, 0, str(e)[:200]


# ═══════════════════════════════════════════════════════════════
# ProxyManager
# ═══════════════════════════════════════════════════════════════


class ProxyManager:
    """固定代理列表管理器 — 健康检查 + 自动故障转移 + 自动恢复。

    使用流程：
    1. manager = ProxyManager(proxies=[...])
    2. await manager.start()  # 启动后台健康检查
    3. proxy_url = manager.get_proxy()  # 获取最佳可用代理
    4. manager.report_success(proxy_url) / manager.report_failure(proxy_url)
    5. await manager.stop()  # 停止

    故障转移逻辑：
    - 优先使用健康的主代理
    - 主代理不可用时，轮换使用健康的备用代理
    - 后台定期检查主代理是否恢复，恢复后自动切回
    """

    def __init__(
        self,
        proxies: list[dict] = None,
        check_interval: int = HEALTH_CHECK_INTERVAL,
        recovery_interval: int = RECOVERY_CHECK_INTERVAL,
        failure_threshold: int = FAILURE_THRESHOLD,
        verbose: bool = True,
    ):
        self.verbose = verbose
        self.check_interval = check_interval
        self.recovery_interval = recovery_interval
        self.failure_threshold = failure_threshold

        # 初始化代理状态
        proxy_configs = proxies or DEFAULT_PROXIES
        self._proxies: list[ProxyState] = []
        for cfg in proxy_configs:
            role = ProxyRole(cfg.get("role", "backup"))
            self._proxies.append(
                ProxyState(
                    url=cfg["url"],
                    name=cfg.get("name", cfg["url"]),
                    role=role,
                )
            )

        # 用于轮换备用代理的索引
        self._backup_index = 0

        # 后台任务
        self._check_task: Optional[asyncio.Task] = None
        self._running = False

    # ── 生命周期 ──────────────────────────────────────────────

    async def start(self):
        """启动代理管理器：执行初始健康检查 + 启动后台检查循环。"""
        if self._running:
            return

        logger.note("> Starting ProxyManager ...")

        # 初始健康检查（全部代理）
        await self._check_all()

        # 启动后台检查循环
        self._running = True
        self._check_task = asyncio.create_task(self._health_check_loop())

        healthy_count = sum(1 for p in self._proxies if p.healthy)
        logger.okay(
            f"  ✓ ProxyManager started: "
            f"{logstr.mesg(len(self._proxies))} proxies, "
            f"{logstr.mesg(healthy_count)} healthy"
        )

    async def stop(self):
        """停止代理管理器。"""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
            self._check_task = None
        logger.note("> ProxyManager stopped")

    # ── 代理选取 ──────────────────────────────────────────────

    def get_proxy(self) -> Optional[str]:
        """获取最佳可用代理 URL。

        优先级：
        1. 健康的主代理
        2. 健康的备用代理（轮换）
        3. 最近失败次数最少的代理（降级）

        Returns:
            代理 URL 字符串，或 None（无可用代理）
        """
        # 优先：健康的主代理
        for p in self._proxies:
            if p.is_primary and p.healthy:
                return p.url

        # 其次：健康的备用代理（轮换）
        healthy_backups = [p for p in self._proxies if not p.is_primary and p.healthy]
        if healthy_backups:
            idx = self._backup_index % len(healthy_backups)
            self._backup_index += 1
            selected = healthy_backups[idx]
            if self.verbose:
                logger.mesg(
                    f"  ↪ Primary unavailable, using backup: "
                    f"{logstr.mesg(selected.name)}"
                )
            return selected.url

        # 降级：所有代理都不健康，选失败次数最少的
        all_sorted = sorted(self._proxies, key=lambda p: p.consecutive_failures)
        if all_sorted:
            selected = all_sorted[0]
            if self.verbose:
                logger.warn(
                    f"  ⚠ All proxies unhealthy, degraded to: "
                    f"{logstr.mesg(selected.name)} "
                    f"(failures: {selected.consecutive_failures})"
                )
            return selected.url

        return None

    def get_all_proxies(self) -> list[str]:
        """获取所有健康代理的 URL 列表。"""
        return [p.url for p in self._proxies if p.healthy]

    # ── 使用反馈 ──────────────────────────────────────────────

    def report_success(self, proxy_url: str):
        """报告代理使用成功。"""
        state = self._find_proxy(proxy_url)
        if not state:
            return
        state.consecutive_failures = 0
        state.consecutive_successes += 1
        state.total_successes += 1
        state.last_success_time = time.time()
        if not state.healthy:
            state.healthy = True
            if self.verbose:
                logger.okay(f"  ✓ Proxy recovered: {logstr.mesg(state.name)}")

    def report_failure(self, proxy_url: str):
        """报告代理使用失败。"""
        state = self._find_proxy(proxy_url)
        if not state:
            return
        state.consecutive_failures += 1
        state.consecutive_successes = 0
        state.total_failures += 1
        state.last_failure_time = time.time()

        if (
            state.healthy
            and state.consecutive_failures >= self.failure_threshold
        ):
            state.healthy = False
            if self.verbose:
                logger.warn(
                    f"  × Proxy marked unhealthy: {logstr.mesg(state.name)} "
                    f"({state.consecutive_failures} consecutive failures)"
                )

    # ── 统计 ──────────────────────────────────────────────────

    def stats(self) -> dict:
        """获取代理管理器统计信息。"""
        total = len(self._proxies)
        healthy = sum(1 for p in self._proxies if p.healthy)
        primary_healthy = any(
            p.healthy for p in self._proxies if p.is_primary
        )
        return {
            "total_proxies": total,
            "healthy_proxies": healthy,
            "unhealthy_proxies": total - healthy,
            "primary_healthy": primary_healthy,
            "using_primary": primary_healthy,
            "proxies": [p.to_dict() for p in self._proxies],
        }

    # ── 内部方法 ──────────────────────────────────────────────

    def _find_proxy(self, url: str) -> Optional[ProxyState]:
        """根据 URL 查找代理状态。"""
        for p in self._proxies:
            if p.url == url:
                return p
        return None

    async def _check_all(self):
        """对所有代理执行健康检查。"""
        tasks = []
        for proxy in self._proxies:
            tasks.append(self._check_single(proxy))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_single(self, proxy: ProxyState):
        """对单个代理执行健康检查。"""
        healthy, latency_ms, error = await check_proxy_health(proxy.url)
        proxy.last_check_time = time.time()
        proxy.latency_ms = latency_ms

        was_healthy = proxy.healthy
        if healthy:
            proxy.healthy = True
            proxy.consecutive_failures = 0
            if not was_healthy and self.verbose:
                logger.okay(
                    f"  ✓ Proxy recovered: {logstr.mesg(proxy.name)} "
                    f"({latency_ms}ms)"
                )
        else:
            proxy.consecutive_failures += 1
            if proxy.consecutive_failures >= self.failure_threshold:
                proxy.healthy = False
            if self.verbose and not was_healthy:
                logger.mesg(
                    f"  · Proxy still down: {logstr.mesg(proxy.name)} — {error}"
                )
            elif self.verbose and proxy.consecutive_failures == 1:
                logger.warn(
                    f"  ⚠ Proxy check failed: {logstr.mesg(proxy.name)} — {error}"
                )

    async def _health_check_loop(self):
        """后台健康检查循环。

        - 每 check_interval 秒检查所有代理
        - 如果主代理不健康，每 recovery_interval 秒额外检查主代理
        """
        try:
            while self._running:
                # 等待到下一次检查
                primary_healthy = any(
                    p.healthy for p in self._proxies if p.is_primary
                )
                interval = (
                    self.recovery_interval
                    if not primary_healthy
                    else self.check_interval
                )
                await asyncio.sleep(interval)

                if not self._running:
                    break

                # 执行健康检查
                if not primary_healthy:
                    # 主代理不健康，只检查主代理（快速恢复检测）
                    primary_proxies = [
                        p for p in self._proxies if p.is_primary
                    ]
                    for p in primary_proxies:
                        await self._check_single(p)
                    # 如果主代理恢复了，标志性地检查一下备用代理
                    if any(pp.healthy for pp in primary_proxies):
                        logger.okay(
                            "  ✓ Primary proxy recovered! "
                            "Switching back to primary."
                        )
                else:
                    # 常规全量检查
                    await self._check_all()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.err(f"  × Health check loop error: {e}")
