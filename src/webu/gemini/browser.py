import asyncio
import os
import re
import signal
import socket
import subprocess
import threading

from pathlib import Path
from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)
from tclogger import logger, logstr, norm_path

from .config import GeminiConfig
from .constants import GEMINI_URL, GEMINI_NAVIGATION_TIMEOUT, GEMINI_CHROME_EXECUTABLE
from .constants import GEMINI_NOVNC_DIR
from .errors import GeminiBrowserError, GeminiNetworkError


# Chrome 默认用户数据目录
CHROME_USER_DATA_DIR = norm_path("~/.config/google-chrome")

# 内部端口偏移量：Chrome 绑定到 127.0.0.1 的该端口，
# TCP 代理将其暴露到 0.0.0.0 的配置端口。
_INTERNAL_PORT_OFFSET = 10

# 匹配 HTTP 请求中 Host 头的正则表达式。
# 预编译以提高性能，因为每个数据块都需要应用。
_RE_HOST_HEADER = re.compile(rb"(?i)\r\nHost:\s*[^\r\n]+")


def find_chrome_executable(configured_path: str = None) -> str:
    """查找可用的 Chrome/Chromium 可执行文件。

    优先级：配置路径 > 系统 google-chrome > 系统 chromium > Playwright 默认
    """
    candidates = []
    if configured_path:
        candidates.append(configured_path)
    candidates.extend(
        [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
        ]
    )
    for path in candidates:
        if Path(path).exists():
            return path
    return None


class _TCPProxy:
    """Chrome DevTools 的 TCP 代理，负责重写 Host 头和内部 URL。

    Chrome DevTools 会拒绝 Host 头不是 IP 地址或 'localhost' 的 HTTP 请求。
    此外，Chrome 返回的 JSON 响应中包含内部 WebSocket URL
    （如 ws://127.0.0.1:30011/devtools/...），需要重写以便远程客户端连接。

    该代理处理两个方向：
    - 客户端 → Chrome：重写所有 HTTP 请求的 Host 头（支持 keep-alive）
    - Chrome → 客户端：将内部地址重写为外部主机名:端口
    """

    def __init__(self, external_port: int, internal_port: int):
        self.external_port = external_port
        self.internal_port = internal_port
        self._hostname = socket.gethostname()
        self._loop = None
        self._server = None
        self._thread = None

        # 预计算替换字节串
        self._internal_addr = f"127.0.0.1:{internal_port}".encode()
        self._external_addr = f"{self._hostname}:{external_port}".encode()
        self._host_replacement = f"\r\nHost: 127.0.0.1:{internal_port}".encode()

    def _rewrite_request(self, data: bytes) -> bytes:
        """重写客户端到上游数据中的 Host 头。

        应用于每个数据块。对 WebSocket 二进制数据安全，因为
        正则模式 (\r\nHost: ...) 在二进制帧中几乎不可能出现。
        """
        return _RE_HOST_HEADER.sub(self._host_replacement, data)

    def _rewrite_response(self, data: bytes) -> bytes:
        """重写上游到客户端数据中的内部地址。

        将 Chrome DevTools JSON 响应中的 '127.0.0.1:{internal_port}'
        替换为 '{hostname}:{external_port}'。当地址重写导致响应体
        大小变化时，同时更新 Content-Length 头。
        """
        if self._internal_addr not in data:
            return data

        # 检查该数据块是否包含 HTTP 响应头
        header_end = data.find(b"\r\n\r\n")
        if header_end == -1:
            # 该数据块中没有头 —— 直接重写响应体
            return data.replace(self._internal_addr, self._external_addr)

        headers = data[: header_end + 4]  # 包含 \r\n\r\n
        body = data[header_end + 4 :]

        # 重写响应体中的地址
        new_body = body.replace(self._internal_addr, self._external_addr)

        # 如果 Content-Length 存在且响应体大小变化，则更新
        if len(new_body) != len(body):
            headers = re.sub(
                rb"(?i)\r\nContent-Length:\s*\d+",
                f"\r\nContent-Length: {len(new_body)}".encode(),
                headers,
            )

        # 同时重写头中的内部地址（罕见但可能存在）
        headers = headers.replace(self._internal_addr, self._external_addr)

        return headers + new_body

    async def _pipe(self, reader, writer, rewrite_fn=None):
        """将数据从 reader 传输到 writer，可选应用重写函数。"""
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                if rewrite_fn:
                    data = rewrite_fn(data)
                writer.write(data)
                await writer.drain()
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _handle_client(self, client_reader, client_writer):
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                "127.0.0.1", self.internal_port
            )
        except Exception:
            client_writer.close()
            return

        await asyncio.gather(
            self._pipe(client_reader, upstream_writer, self._rewrite_request),
            self._pipe(upstream_reader, client_writer, self._rewrite_response),
        )

    async def _run(self):
        self._server = await asyncio.start_server(
            self._handle_client, "0.0.0.0", self.external_port
        )
        async with self._server:
            await self._server.serve_forever()

    def start(self):
        def _thread_main():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._run())
            except asyncio.CancelledError:
                pass
            finally:
                self._loop.close()

        self._thread = threading.Thread(target=_thread_main, daemon=True)
        self._thread.start()

    def stop(self):
        if self._loop and self._server:
            self._loop.call_soon_threadsafe(self._server.close)
            # Cancel all remaining tasks in the proxy's event loop
            for task in asyncio.all_tasks(self._loop):
                self._loop.call_soon_threadsafe(task.cancel)
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None


class GeminiBrowser:
    """通过 CDP 管理 Gemini 自动化的浏览器实例。

    SSH/无头环境架构：
    1. 启动 Chrome 并配置 --remote-debugging-port（绑定到 127.0.0.1）
    2. 启动 TCP 代理将调试端口暴露到 0.0.0.0
    3. Playwright 通过 CDP 本地连接 Chrome
    4. 用户可通过 http://<服务器>:<端口> 远程访问 Chrome DevTools

    使用持久化 Chrome 配置文件保存登录状态。
    无 X 服务器时使用虚拟显示器（Xvfb）。
    """

    def __init__(self, config: GeminiConfig = None):
        self.config = config or GeminiConfig()
        self.playwright: Playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None
        self.is_started = False
        self.vdisplay = None
        self.chrome_process = None
        self._tcp_proxy: _TCPProxy = None
        self._websockify_process: subprocess.Popen = None

    def _ensure_display(self):
        """无 X 服务器时启动带 VNC 访问的虚拟显示器。

        使用 Xvnc (TigerVNC) 作为显示后端，而非 Xvfb，因为它
        同时提供虚拟 X 显示器和内置 VNC 服务器。远程用户
        可通过 VNC 客户端或 noVNC Web 界面查看和操作浏览器。
        """
        display = os.environ.get("DISPLAY", "")
        if display:
            logger.mesg(f"  使用现有显示器: {display}")
            return

        if self.config.headless:
            logger.mesg("  无头模式，无需显示器")
            return

        # 无显示器 —— 启动 Xvnc 虚拟显示器
        try:
            from pyvirtualdisplay import Display

            vnc_port = self.config.vnc_port
            self.vdisplay = Display(
                backend="xvnc",
                visible=False,
                size=(1920, 1080),
                rfbport=vnc_port,
                extra_args=[
                    "-SecurityTypes",
                    "None",  # 无需密码
                    "-localhost",
                    "no",  # 接受非本地连接
                ],
            )
            self.vdisplay.start()
            logger.okay(
                f"  ✓ Xvnc display started: {os.environ.get('DISPLAY', '')}"
                f" (VNC port: {vnc_port})"
            )
        except Exception as e:
            logger.warn(f"  × Failed to start Xvnc display: {e}")
            # 回退：尝试 Xvfb（无 VNC，但 Chrome 仍可运行）
            try:
                from pyvirtualdisplay import Display

                self.vdisplay = Display(visible=False, size=(1920, 1080))
                self.vdisplay.start()
                logger.okay(
                    f"  ✓ Xvfb display started (fallback, no VNC):"
                    f" {os.environ.get('DISPLAY', '')}"
                )
            except Exception as e2:
                logger.warn(f"  × Failed to start virtual display: {e2}")
                logger.warn("  Falling back to headless mode")
                self.config.config["headless"] = True

    def _start_novnc(self):
        """启动 websockify + noVNC 提供基于 Web 的 VNC 访问。

        websockify 将浏览器的 WebSocket 连接桥接到 VNC TCP 端口，
        同时提供 noVNC HTML/JS 查看器。
        """
        novnc_dir = norm_path(GEMINI_NOVNC_DIR)
        if not novnc_dir.exists() or not (novnc_dir / "vnc.html").exists():
            logger.warn(
                f"  × noVNC 未找到: {novnc_dir}。"
                "Web VNC 查看器已禁用，请使用 VNC 客户端。"
            )
            return

        vnc_port = self.config.vnc_port
        novnc_port = self.config.novnc_port

        try:
            self._websockify_process = subprocess.Popen(
                [
                    "websockify",
                    "--web",
                    str(novnc_dir),
                    str(novnc_port),
                    f"localhost:{vnc_port}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.okay(f"  ✓ noVNC Web 查看器已启动，端口: {novnc_port}")
        except FileNotFoundError:
            logger.warn("  × 未找到 websockify。请安装: pip install websockify")
        except Exception as e:
            logger.warn(f"  × 启动 noVNC 失败: {e}")

    def _stop_novnc(self):
        """停止 websockify/noVNC 进程。"""
        if self._websockify_process:
            try:
                self._websockify_process.terminate()
                self._websockify_process.wait(timeout=3)
                logger.mesg("  noVNC 已停止")
            except subprocess.TimeoutExpired:
                self._websockify_process.kill()
            except Exception as e:
                logger.warn(f"  × 停止 noVNC 出错: {e}")
            self._websockify_process = None

    def _stop_display(self):
        """停止虚拟显示器（如果已启动）。"""
        if self.vdisplay:
            try:
                self.vdisplay.stop()
                logger.mesg("  虚拟显示器已停止")
            except Exception as e:
                logger.warn(f"  × 停止虚拟显示器出错: {e}")
            self.vdisplay = None

    def _clear_browser_cache(self, user_data_dir: Path):
        """清理浏览器缓存数据，防止影响代理和网络连接。

        保留登录 Cookie、密码和偏好设置，只清理可能干扰代理的缓存文件：
        - HTTP 缓存、代码缓存、GPU 缓存
        - Service Worker（可能拦截网络请求）
        - HSTS/TransportSecurity 缓存（可能导致连接失败）
        - 网络预测数据
        """
        import shutil

        default_dir = user_data_dir / "Default"
        if not default_dir.exists():
            return

        # 需要清理的目录列表
        cache_dirs = [
            "Cache",
            "Code Cache",
            "Service Worker",
            "GPUCache",
            "DawnGraphiteCache",
            "DawnWebGPUCache",
            "blob_storage",
            "File System",
            "GCM Store",
        ]
        # 需要清理的文件列表
        cache_files = [
            "TransportSecurity",
            "Network Action Predictor",
            "Network Persistent State",
        ]

        cleared = []
        for dirname in cache_dirs:
            target = default_dir / dirname
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
                cleared.append(dirname)

        for filename in cache_files:
            target = default_dir / filename
            if target.exists():
                target.unlink(missing_ok=True)
                cleared.append(filename)

        # 也清理顶层的着色器缓存
        for dirname in ["GraphiteDawnCache", "GrShaderCache", "ShaderCache"]:
            target = user_data_dir / dirname
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
                cleared.append(dirname)

        if cleared:
            logger.mesg(f"  已清理浏览器缓存: {', '.join(cleared)}")

    def _launch_chrome_process(self) -> int:
        """启动 Chrome 进程并配置远程调试端口。

        Chrome 始终绑定到 127.0.0.1，因此使用内部端口并通过 TCP 代理
        将其暴露到 0.0.0.0。

        Returns:
            内部调试端口号。
        """
        chrome_path = find_chrome_executable(self.config.chrome_executable)
        if not chrome_path:
            raise GeminiBrowserError("找不到 Chrome 可执行文件")

        external_port = self.config.browser_port
        internal_port = external_port + _INTERNAL_PORT_OFFSET
        user_data_dir = norm_path(self.config.user_data_dir)
        user_data_dir.mkdir(parents=True, exist_ok=True)

        # 启动前清理可能影响代理/网络的缓存数据（保留登录 cookie）
        self._clear_browser_cache(user_data_dir)

        chrome_args = [
            chrome_path,
            f"--remote-debugging-port={internal_port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-component-update",
            "--disable-client-side-phishing-detection",
            "--remote-allow-origins=*",
        ]
        if self.config.proxy:
            chrome_args.append(f"--proxy-server={self.config.proxy}")
        if self.config.headless:
            chrome_args.append("--headless=new")

        logger.mesg(f"  Chrome executable: {logstr.file(chrome_path)}")
        logger.mesg(f"  User data dir: {logstr.file(str(user_data_dir))}")
        logger.mesg(f"  Internal debug port: {internal_port} (127.0.0.1)")

        self.chrome_process = subprocess.Popen(
            chrome_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Start TCP proxy: 0.0.0.0:external_port -> 127.0.0.1:internal_port
        self._tcp_proxy = _TCPProxy(external_port, internal_port)
        self._tcp_proxy.start()
        logger.mesg(f"  External debug port: {external_port} (0.0.0.0)")

        return internal_port

    def _stop_chrome_process(self):
        """停止 Chrome 进程和 TCP 代理。"""
        if self._tcp_proxy:
            try:
                self._tcp_proxy.stop()
                logger.mesg("  TCP 代理已停止")
            except Exception as e:
                logger.warn(f"  × 停止 TCP 代理出错: {e}")
            self._tcp_proxy = None

        if self.chrome_process:
            try:
                self.chrome_process.terminate()
                self.chrome_process.wait(timeout=5)
                logger.mesg("  Chrome 进程已终止")
            except subprocess.TimeoutExpired:
                self.chrome_process.kill()
                logger.mesg("  Chrome 进程已强制终止")
            except Exception as e:
                logger.warn(f"  × 停止 Chrome 出错: {e}")
            self.chrome_process = None

    async def start(self) -> "GeminiBrowser":
        """启动浏览器并通过 CDP 连接。"""
        if self.is_started:
            logger.mesg("  浏览器已启动")
            return self

        logger.note("> 启动 Gemini 浏览器 ...")
        self.config.log_config()

        # 确保显示器可用（必要时启动 Xvfb）
        self._ensure_display()

        try:
            # 启动 Chrome 并配置远程调试
            internal_port = self._launch_chrome_process()
            external_port = self.config.browser_port

            # 等待 Chrome 启动并开放调试端口
            await asyncio.sleep(2)

            # 启动 noVNC Web 查看器以便远程可视化访问
            self._start_novnc()

            # 通过 CDP 本地连接 Playwright 到运行中的 Chrome
            self.playwright = await async_playwright().start()
            cdp_url = f"http://127.0.0.1:{internal_port}"

            logger.mesg(f"  通过 CDP 连接 Playwright: {cdp_url}")
            self.browser = await self.playwright.chromium.connect_over_cdp(cdp_url)

            # 获取默认上下文和页面
            contexts = self.browser.contexts
            if contexts:
                self.context = contexts[0]
                if self.context.pages:
                    self.page = self.context.pages[0]
                else:
                    self.page = await self.context.new_page()
            else:
                self.context = await self.browser.new_context(
                    viewport={"width": 1400, "height": 900},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )
                self.page = await self.context.new_page()

            self.is_started = True
            hostname = socket.gethostname()
            novnc_port = self.config.novnc_port
            logger.okay("  ✓ 浏览器已启动")
            logger.note(
                f"  ℹ 远程浏览器访问:\n"
                f"    可视化:  http://{hostname}:{novnc_port}/vnc.html"
                f"?autoconnect=true&resize=remote\n"
                f"    DevTools: chrome://inspect → Configure → "
                f"'{hostname}:{external_port}'\n"
                f"    JSON API: http://{hostname}:{external_port}/json"
            )
            return self

        except Exception as e:
            logger.err(f"  × 启动浏览器失败: {e}")
            await self.stop()
            raise GeminiBrowserError(
                f"启动浏览器失败: {e}",
                details={
                    "proxy": self.config.proxy,
                    "user_data_dir": self.config.user_data_dir,
                },
            )

    async def stop(self):
        """关闭浏览器并清理资源。"""
        logger.note("> 停止 Gemini 浏览器 ...")
        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
            self.context = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            self.page = None
            self.is_started = False
            self._stop_chrome_process()
            self._stop_novnc()
            self._stop_display()
            logger.okay("  ✓ 浏览器已停止")
        except Exception as e:
            logger.warn(f"  × 停止浏览器出错: {e}")
            # 仍然尝试清理 Chrome 进程
            self._stop_chrome_process()
            self._stop_novnc()
            self._stop_display()

    async def navigate_to_gemini(self) -> Page:
        """导航到 Gemini 页面。"""
        if not self.is_started:
            await self.start()

        logger.note(f"> Navigating to: {logstr.mesg(GEMINI_URL)}")
        try:
            await self.page.goto(
                GEMINI_URL,
                wait_until="domcontentloaded",
                timeout=self.config.page_load_timeout,
            )
            # 等待页面完全可交互
            try:
                await self.page.wait_for_load_state(
                    "networkidle", timeout=GEMINI_NAVIGATION_TIMEOUT
                )
            except Exception:
                # networkidle 在动态页面上可能超时，继续执行
                pass

            # 处理 Google 同意页面重定向
            current_url = self.page.url
            if "consent.google.com" in current_url:
                logger.mesg("  处理同意页面 ...")
                # 尝试点击同意按钮继续
                agree_btns = await self.page.query_selector_all(
                    'button:has-text("I agree"), button:has-text("同意"), '
                    'button:has-text("Accept"), button:has-text("接受"), '
                    'button:has-text("Agree"), form[action*="consent"] button'
                )
                for btn in agree_btns:
                    if await btn.is_visible():
                        await btn.click()
                        logger.mesg("  已点击同意按钮")
                        await asyncio.sleep(3)
                        break
                # 等待重定向回 Gemini
                try:
                    await self.page.wait_for_url(
                        "**/gemini.google.com/**", timeout=15000
                    )
                except Exception:
                    pass

            title = await self.page.title()
            logger.okay(f"  ✓ Page loaded: {title}")
            logger.mesg(f"  URL: {self.page.url}")
            return self.page
        except Exception as e:
            error_msg = str(e)
            if "net::ERR_PROXY" in error_msg or "net::ERR_CONNECTION" in error_msg:
                raise GeminiNetworkError(
                    f"Failed to connect to Gemini. Check proxy settings.",
                    details={"proxy": self.config.proxy, "error": error_msg},
                )
            raise GeminiBrowserError(
                f"Failed to navigate to Gemini: {e}",
                details={"url": GEMINI_URL},
            )

    async def new_page(self) -> Page:
        """在浏览器上下文中创建新页面。"""
        if not self.is_started:
            await self.start()
        self.page = await self.context.new_page()
        return self.page

    async def screenshot(self, path: str = None) -> bytes:
        """对当前页面截图。"""
        if not self.page:
            raise GeminiBrowserError("没有活动页面可以截图。")
        screenshot_bytes = await self.page.screenshot(path=path, full_page=True)
        if path:
            logger.okay(f"  + 截图已保存: {path}")
        return screenshot_bytes

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
        return False
