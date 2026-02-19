"""Gemini 模块交互式测试脚本 —— 连接已运行的浏览器。

前提: 先运行 launch_browser.py 保持浏览器运行。
本脚本通过 CDP 连接到已运行的 Chrome，执行测试步骤，不重启浏览器。

运行: python -m tests.gemini.test_interactive [step]

步骤:
  dom     - 深度 DOM 探索
  chat    - 新建对话 + Imagen + PRO 模式
  send    - 发送简单消息
  code    - 代码响应测试
  multi   - 多轮对话
  all     - 执行全部步骤（默认）
"""

import asyncio
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright
from tclogger import logger, logstr

from webu.gemini.agency import GeminiAgency
from webu.gemini.config import GeminiConfig
from webu.gemini.parser import GeminiResponseParser
from webu.gemini.constants import (
    GEMINI_URL,
    SEL_LOGIN_AVATAR,
    SEL_LOGIN_BUTTON,
    SEL_INPUT_AREA,
    SEL_SEND_BUTTON,
    SEL_NEW_CHAT_BUTTON,
    SEL_SIDEBAR_TOGGLE,
    SEL_RESPONSE_CONTAINER,
    SEL_RESPONSE_TEXT,
    SEL_LOADING_INDICATOR,
    SEL_STOP_BUTTON,
    SEL_TOOLS_BUTTON,
    SEL_IMAGE_GEN_OPTION,
    SEL_MODEL_SELECTOR,
)
from webu.gemini.errors import (
    GeminiError,
    GeminiLoginRequiredError,
    GeminiPageError,
)

SCREENSHOT_DIR = (
    Path(__file__).parent.parent.parent / ".chats" / "gemini" / "screenshots"
)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = (
    Path(__file__).parent.parent.parent / ".chats" / "gemini" / "browser_state.json"
)


async def shot(client: GeminiAgency, name: str) -> str:
    """截图并保存到 .chats/gemini/screenshots/，返回路径。"""
    ts = datetime.now().strftime("%H%M%S")
    path = str(SCREENSHOT_DIR / f"{ts}_{name}.png")
    await client.screenshot(path=path)
    logger.okay(f"  截图: {path}")
    return path


async def connect_to_running_browser() -> GeminiAgency:
    """连接到 launch_browser.py 启动的浏览器，返回 GeminiAgency。"""
    if not STATE_FILE.exists():
        raise RuntimeError(
            "浏览器未运行。请先执行: python -m tests.gemini.launch_browser"
        )

    state = json.loads(STATE_FILE.read_text())
    if not state.get("running"):
        raise RuntimeError("浏览器状态为非运行。请重启 launch_browser。")

    cdp_url = state["cdp_url"]
    logger.note(f"> 连接到已运行的浏览器: {cdp_url}")

    # 通过 CDP 连接 Playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp(cdp_url)

    contexts = browser.contexts
    if contexts and contexts[0].pages:
        page = contexts[0].pages[0]
    else:
        raise RuntimeError("浏览器没有打开的页面")

    logger.okay(f"  已连接: {page.url}")

    # 强制暗色主题
    await page.emulate_media(color_scheme="dark")

    # 构建 GeminiAgency（不启动新浏览器）
    config = GeminiConfig(config_path="configs/gemini.json")
    client = GeminiAgency.__new__(GeminiAgency)
    client.config = config
    client.browser = type(
        "FakeBrowser",
        (),
        {
            "page": page,
            "config": config,
            "screenshot": lambda self, path=None: page.screenshot(
                path=path, full_page=False
            ),
            "navigate_to_gemini": lambda self: _navigate(page),
            "get_page_info": lambda self: _page_info(page),
            "download_image_as_base64": lambda self, url: _dl_img(page, url),
        },
    )()
    client.parser = GeminiResponseParser()
    client.is_ready = True
    client._image_mode = False
    client._message_count = 0

    # 存储 pw 引用以便清理
    client._pw = pw
    client._browser_connection = browser

    return client


async def _navigate(page):
    await page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=60000)
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    return page


async def _page_info(page):
    try:
        return {
            "url": page.url,
            "title": await page.title(),
            "viewport": page.viewport_size,
        }
    except Exception as e:
        return {"error": str(e)}


async def _dl_img(page, url):
    # 简单代理 — 复用 GeminiBrowser 的逻辑
    from webu.gemini.browser import GeminiBrowser

    b = GeminiBrowser.__new__(GeminiBrowser)
    b.page = page
    return await GeminiBrowser.download_image_as_base64(b, url)


async def disconnect_client(client: GeminiAgency):
    """断开 Playwright 连接（不关闭浏览器）。"""
    try:
        if hasattr(client, "_browser_connection"):
            await client._browser_connection.close()
        if hasattr(client, "_pw"):
            await client._pw.stop()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
# 步骤 1: 页面信息
# ═══════════════════════════════════════════════════════════════


async def step_info(client: GeminiAgency):
    """显示页面基本信息和登录状态。"""
    logger.note("=" * 60)
    logger.note("步骤 1: 页面信息 & 登录检测")
    logger.note("=" * 60)

    info = await client.browser.get_page_info()
    logger.mesg(f"  URL:   {info.get('url', 'N/A')}")
    logger.mesg(f"  标题:  {info.get('title', 'N/A')}")

    status = await client.check_login_status()
    logger.mesg(f"  登录: {status}")
    await shot(client, "01_info")

    if not status["logged_in"]:
        logger.err("  ⚠ 未登录! 请在 VNC 中登录后再运行测试。")
        return False
    return True


# ═══════════════════════════════════════════════════════════════
# 步骤 3: DOM 选择器探索
# ═══════════════════════════════════════════════════════════════


async def step_explore_dom(client: GeminiAgency):
    """深度探索 Gemini 页面真实 DOM 结构，输出到文件供分析。"""
    logger.note("=" * 60)
    logger.note("步骤 3: 深度 DOM 探索")
    logger.note("=" * 60)

    page = client.page
    dump_path = SCREENSHOT_DIR / "dom_dump.txt"

    # 等待页面完全加载
    await asyncio.sleep(3)

    # 用 JS 一次性收集所有关键 DOM 信息
    dom_info = await page.evaluate(
        """() => {
        const result = {
            url: location.href,
            title: document.title,
            editables: [],
            buttons: [],
            textareas: [],
            inputs: [],
            customElements: [],
            ariaRoles: [],
            matElements: [],
        };

        // contenteditable 元素
        document.querySelectorAll('[contenteditable]').forEach((el, i) => {
            result.editables.push({
                idx: i,
                tag: el.tagName,
                cls: (el.className || '').substring(0, 120),
                role: el.getAttribute('role') || '',
                ariaLabel: el.getAttribute('aria-label') || '',
                contenteditable: el.getAttribute('contenteditable'),
                visible: el.offsetParent !== null || el.offsetWidth > 0,
                parentTag: el.parentElement?.tagName || '',
                parentCls: (el.parentElement?.className || '').substring(0, 80),
                grandparentTag: el.parentElement?.parentElement?.tagName || '',
                innerTextLen: (el.innerText || '').length,
                placeholder: el.getAttribute('placeholder') || el.getAttribute('data-placeholder') || '',
            });
        });

        // 所有 button 元素
        document.querySelectorAll('button').forEach((el, i) => {
            const visible = el.offsetParent !== null || el.offsetWidth > 0;
            if (!visible) return;
            result.buttons.push({
                idx: i,
                ariaLabel: el.getAttribute('aria-label') || '',
                matTooltip: el.getAttribute('mattooltip') || '',
                cls: (el.className || '').substring(0, 100),
                text: (el.textContent || '').trim().substring(0, 60),
                disabled: el.disabled,
                type: el.type || '',
            });
        });

        // textarea / input 元素
        document.querySelectorAll('textarea, input[type="text"], input:not([type])').forEach((el, i) => {
            result.textareas.push({
                idx: i,
                tag: el.tagName,
                cls: (el.className || '').substring(0, 80),
                ariaLabel: el.getAttribute('aria-label') || '',
                placeholder: el.placeholder || '',
                visible: el.offsetParent !== null || el.offsetWidth > 0,
            });
        });

        // 自定义元素 (Custom Elements)
        const customTags = new Set();
        document.querySelectorAll('*').forEach(el => {
            if (el.tagName.includes('-')) customTags.add(el.tagName.toLowerCase());
        });
        result.customElements = Array.from(customTags).sort();

        // role="textbox" 元素
        document.querySelectorAll('[role="textbox"]').forEach((el, i) => {
            result.ariaRoles.push({
                tag: el.tagName,
                cls: (el.className || '').substring(0, 100),
                ariaLabel: el.getAttribute('aria-label') || '',
                contenteditable: el.getAttribute('contenteditable'),
                visible: el.offsetParent !== null || el.offsetWidth > 0,
            });
        });

        // mat-* 元素（Angular Material）
        document.querySelectorAll('[class*="mat-"]').forEach((el, i) => {
            if (i > 30) return;
            const visible = el.offsetParent !== null || el.offsetWidth > 0;
            if (!visible) return;
            result.matElements.push({
                tag: el.tagName,
                cls: (el.className || '').substring(0, 120),
            });
        });

        return result;
    }"""
    )

    # 写入 dump 文件
    lines = []
    lines.append(f"=== Gemini DOM Dump ===")
    lines.append(f"URL: {dom_info['url']}")
    lines.append(f"Title: {dom_info['title']}")

    lines.append(f"\n--- Custom Elements ({len(dom_info['customElements'])}) ---")
    for tag in dom_info["customElements"]:
        lines.append(f"  <{tag}>")

    lines.append(f"\n--- contenteditable ({len(dom_info['editables'])}) ---")
    for e in dom_info["editables"]:
        lines.append(
            f"  #{e['idx']}: <{e['tag']}> cls='{e['cls']}' role='{e['role']}' "
            f"aria-label='{e['ariaLabel']}' visible={e['visible']} "
            f"parent=<{e['parentTag']}>.{e['parentCls']} placeholder='{e['placeholder']}'"
        )

    lines.append(f"\n--- role=textbox ({len(dom_info['ariaRoles'])}) ---")
    for r in dom_info["ariaRoles"]:
        lines.append(
            f"  <{r['tag']}> cls='{r['cls']}' aria-label='{r['ariaLabel']}' "
            f"contenteditable={r['contenteditable']} visible={r['visible']}"
        )

    lines.append(f"\n--- Visible Buttons ({len(dom_info['buttons'])}) ---")
    for b in dom_info["buttons"]:
        lines.append(
            f"  #{b['idx']}: aria-label='{b['ariaLabel']}' mattooltip='{b['matTooltip']}' "
            f"text='{b['text']}' cls='{b['cls']}' disabled={b['disabled']}"
        )

    lines.append(f"\n--- textarea/input ({len(dom_info['textareas'])}) ---")
    for t in dom_info["textareas"]:
        lines.append(
            f"  <{t['tag']}> cls='{t['cls']}' aria-label='{t['ariaLabel']}' "
            f"placeholder='{t['placeholder']}' visible={t['visible']}"
        )

    lines.append(f"\n--- mat-* visible ({len(dom_info['matElements'])}) ---")
    for m in dom_info["matElements"]:
        lines.append(f"  <{m['tag']}> cls='{m['cls']}'")

    dump_text = "\n".join(lines)
    dump_path.write_text(dump_text, encoding="utf-8")
    logger.okay(f"  DOM dump 已保存: {dump_path}")

    # 也输出关键信息到控制台
    logger.mesg(f"  Custom Elements: {len(dom_info['customElements'])}")
    for tag in dom_info["customElements"]:
        logger.mesg(f"    <{tag}>")

    logger.mesg(f"\n  contenteditable elements: {len(dom_info['editables'])}")
    for e in dom_info["editables"]:
        vis = "✓" if e["visible"] else "×"
        logger.mesg(
            f"    [{vis}] <{e['tag']}> role='{e['role']}' "
            f"aria='{e['ariaLabel']}' parent=<{e['parentTag']}>"
        )

    logger.mesg(f"\n  role=textbox: {len(dom_info['ariaRoles'])}")
    for r in dom_info["ariaRoles"]:
        vis = "✓" if r["visible"] else "×"
        logger.mesg(f"    [{vis}] <{r['tag']}> aria='{r['ariaLabel']}'")

    logger.mesg(f"\n  Visible buttons: {len(dom_info['buttons'])}")
    for b in dom_info["buttons"]:
        if b["ariaLabel"] or b["matTooltip"]:
            logger.mesg(
                f"    aria='{b['ariaLabel']}' tooltip='{b['matTooltip']}' text='{b['text']}'"
            )
        elif b["text"]:
            logger.mesg(f"    text='{b['text']}' cls='{b['cls'][:50]}'")

    # 测试已有选择器
    logger.mesg("\n  -- 选择器检验 --")
    selector_groups = {
        "LOGIN_AVATAR": SEL_LOGIN_AVATAR,
        "INPUT_AREA": SEL_INPUT_AREA,
        "SEND_BUTTON": SEL_SEND_BUTTON,
        "NEW_CHAT_BUTTON": SEL_NEW_CHAT_BUTTON,
        "SIDEBAR_TOGGLE": SEL_SIDEBAR_TOGGLE,
        "RESPONSE_CONTAINER": SEL_RESPONSE_CONTAINER,
    }
    results = {}
    for name, selector_str in selector_groups.items():
        found_any = False
        for sel in selector_str.split(","):
            sel = sel.strip()
            try:
                el = await page.query_selector(sel)
                if el:
                    vis = await el.is_visible()
                    status = "VISIBLE" if vis else "hidden"
                    logger.okay(f"  {name}: {status} -> {sel[:60]}")
                    found_any = True
                    if vis:
                        break
            except Exception:
                continue
        if not found_any:
            logger.warn(f"  {name}: NOT FOUND")
        results[name] = found_any

    await shot(client, "03_dom_explore")
    return results


# ═══════════════════════════════════════════════════════════════
# 步骤 3b: 新建对话 + Imagen + PRO 模式
# ═══════════════════════════════════════════════════════════════


async def step_chat_setup(client: GeminiAgency):
    """新建对话 → 选择图片生成工具 → 确保 PRO 模式。

    基于实际 DOM 探索结果重写:
    - 新建对话: a[aria-label*="发起新对话"] / CSS 选择器 / URL 导航
    - PRO: 检查 pillbox-btn 是否 disabled（disabled = 已是 PRO 用户）
    - Imagen: 零态卡片 button[aria-label*="制作图片"] / 工具抽屉
    - 模式: button[aria-label="打开模式选择器"] 显示当前模式文本
    """
    logger.note("=" * 60)
    logger.note("步骤 3b: 新建对话 + Imagen + PRO")
    logger.note("=" * 60)

    page = client.page

    # ── 1. 新建对话 ──────────────────────────────────────────
    logger.note("> 新建对话 ...")

    new_chat_ok = False
    # 先尝试 CSS 选择器
    new_chat_selectors = [s.strip() for s in SEL_NEW_CHAT_BUTTON.split(",")]
    for sel in new_chat_selectors:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                new_chat_ok = True
                logger.okay(f"  ✓ 新建对话 (CSS): {sel[:50]}")
                break
        except Exception:
            continue

    if not new_chat_ok:
        # 回退: 文本匹配
        for txt in ["New chat", "发起新对话", "新建对话"]:
            try:
                loc = page.locator(
                    f'button:has-text("{txt}"), a:has-text("{txt}")'
                ).first
                if await loc.is_visible(timeout=3000):
                    await loc.click()
                    new_chat_ok = True
                    logger.okay(f"  ✓ 新建对话 (text): '{txt}'")
                    break
            except Exception:
                continue

    if not new_chat_ok:
        # 最终回退: 导航
        logger.warn("  新建对话按钮未找到，通过 URL 导航")
        await page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        new_chat_ok = True
        logger.okay("  ✓ 新建对话 (navigation)")

    await asyncio.sleep(3)
    await shot(client, "03b_new_chat")

    # ── 2. 检查 PRO 状态 ────────────────────────────────────
    # 实际 DOM: PRO 按钮是 pillbox-btn, disabled=True 表示已是 PRO 用户
    logger.note("> 检查 PRO 状态 ...")

    pro_active = False
    pro_info = await page.evaluate(
        """() => {
        // 查找 PRO 按钮 — class 包含 pillbox-btn, 文本包含 PRO
        const btns = document.querySelectorAll('button');
        for (const btn of btns) {
            const text = (btn.textContent || '').trim();
            const cls = btn.className || '';
            if (text === 'PRO' && cls.includes('pillbox')) {
                return {
                    found: true,
                    disabled: btn.disabled,
                    text: text,
                    cls: cls.substring(0, 80),
                };
            }
        }
        return {found: false};
    }"""
    )

    if pro_info.get("found"):
        if pro_info.get("disabled"):
            # disabled = 已是 PRO 用户（按钮是徽章，不可点击）
            pro_active = True
            logger.okay("  ✓ 已是 PRO 用户（PRO 按钮为 disabled 徽章）")
        else:
            # 可点击 = 需要升级，尝试点击
            logger.mesg("  PRO 按钮可点击，尝试选择 ...")
            try:
                btn = await page.query_selector("button.pillbox-btn")
                if btn:
                    await btn.click()
                    await asyncio.sleep(2)
                    pro_active = True
                    logger.okay("  ✓ 已点击 PRO 按钮")
            except Exception as e:
                logger.warn(f"  点击 PRO 按钮失败: {e}")
    else:
        logger.warn("  PRO 按钮未找到")

    await shot(client, "03b_pro")

    # ── 3. 检查模式 → 切换为 Pro ──────────────────────────
    logger.note("> 检查/切换模式 → Pro ...")
    current_mode = await _ensure_pro_mode(page)

    await shot(client, "03b_mode")

    # ── 4. 检查 Imagen / 图片生成 ──────────────────────────
    logger.note("> 检查图片生成 ...")

    imagen_active = False

    # 方案 A: 零态卡片 — 新对话首页会显示 "🍌 制作图片" 卡片
    try:
        card = await page.query_selector('button[aria-label*="制作图片"]')
        if card and await card.is_visible():
            logger.mesg("  找到零态卡片「制作图片」，点击 ...")
            await card.click()
            await asyncio.sleep(2)
            imagen_active = True
            client._image_mode = True
            logger.okay("  ✓ 已点击「制作图片」零态卡片")
            await shot(client, "03b_imagen_card")
        else:
            logger.mesg("  零态卡片不可见，尝试工具抽屉 ...")
    except Exception as e:
        logger.warn(f"  零态卡片点击失败: {e}")

    if not imagen_active:
        # 方案 B: 工具抽屉
        try:
            tools_btn = await page.query_selector(
                'button[aria-label="工具"], button[aria-label*="Tools" i]'
            )
            if tools_btn and await tools_btn.is_visible():
                await tools_btn.click()
                await asyncio.sleep(1)
                await shot(client, "03b_tools_open")

                # 探索工具抽屉内容
                drawer_info = await page.evaluate(
                    """() => {
                    const drawer = document.querySelector('toolbox-drawer');
                    if (!drawer) return {found: false};
                    const items = [];
                    drawer.querySelectorAll('button, [role="menuitem"], [role="option"], mat-action-list *').forEach(el => {
                        const text = (el.textContent || '').trim();
                        const label = el.getAttribute('aria-label') || '';
                        const visible = el.offsetParent !== null;
                        if (text && visible) {
                            items.push({text: text.substring(0, 60), label, tag: el.tagName});
                        }
                    });
                    return {found: true, items};
                }"""
                )

                if drawer_info.get("found"):
                    logger.mesg(
                        f"  工具抽屉内容 ({len(drawer_info.get('items', []))} items):"
                    )
                    for item in drawer_info.get("items", []):
                        logger.mesg(
                            f"    [{item['tag']}] text='{item['text']}' label='{item['label']}'"
                        )

                    # 查找图片生成相关
                    for item in drawer_info.get("items", []):
                        t = (item["text"] + item["label"]).lower()
                        if any(k in t for k in ["image", "imagen", "图片", "制作图片"]):
                            logger.mesg(f"  找到图片选项: {item['text']}")
                            # 尝试点击
                            loc = page.locator(
                                f'toolbox-drawer button:has-text("{item["text"][:20]}")'
                            ).first
                            try:
                                await loc.click(timeout=3000)
                                imagen_active = True
                                client._image_mode = True
                                logger.okay(f"  ✓ 打开 Imagen: {item['text']}")
                            except Exception as e2:
                                logger.warn(f"  点击失败: {e2}")
                            break
                else:
                    logger.warn("  工具抽屉 <toolbox-drawer> 未找到")

                # 关闭工具抽屉（如果还开着且没选中什么）
                if not imagen_active:
                    try:
                        await tools_btn.click()
                        await asyncio.sleep(0.5)
                    except Exception:
                        pass
            else:
                logger.warn("  工具按钮不可见")
        except Exception as e:
            logger.warn(f"  工具抽屉操作失败: {e}")

    if not imagen_active:
        logger.warn("  × 图片生成未启用（可能需要在 prompt 中指定）")

    await shot(client, "03b_final")

    result = {
        "new_chat": new_chat_ok,
        "pro": pro_active,
        "mode": current_mode,
        "imagen": imagen_active,
    }
    logger.okay(f"  结果: {result}")
    return result


# ═══════════════════════════════════════════════════════════════
# 步骤 4: 图片生成测试
# ═══════════════════════════════════════════════════════════════


async def _ensure_pro_mode(page) -> str:
    """检查并确保当前为 Pro 模式，返回最终模式名。"""
    mode_info = await page.evaluate(
        """() => {
        const btn = document.querySelector('button[aria-label*="模式选择器"], button[aria-label*="mode selector" i], button.input-area-switch');
        if (!btn) return {found: false};
        return {found: true, text: (btn.textContent || '').trim()};
    }"""
    )

    if not mode_info.get("found"):
        logger.warn("  模式选择器未找到")
        return "unknown"

    current = mode_info["text"]
    if any(k in current.lower() for k in ["pro", "深度"]):
        logger.okay(f"  ✓ 已是 Pro 模式: {current}")
        return current

    logger.mesg(f"  当前模式「{current}」→ 切换到 Pro ...")
    mode_btn = await page.query_selector(
        'button[aria-label*="模式选择器"], button[aria-label*="mode selector" i], button.input-area-switch'
    )
    if not mode_btn or not await mode_btn.is_visible():
        logger.warn("  模式按钮不可见")
        return current

    await mode_btn.click()
    await asyncio.sleep(1.5)

    # 在 bard-mode-switcher 或 overlay 中找 Pro
    for base in ["bard-mode-switcher", ".cdk-overlay-pane"]:
        try:
            loc = page.locator(f"{base} button").filter(has_text="Pro").first
            if await loc.is_visible(timeout=2000):
                await loc.click()
                await asyncio.sleep(1.5)
                # 验证切换结果
                new_info = await page.evaluate(
                    """() => {
                    const btn = document.querySelector('button[aria-label*="模式选择器"], button[aria-label*="mode selector" i], button.input-area-switch');
                    return btn ? (btn.textContent || '').trim() : '';
                }"""
                )
                logger.okay(f"  ✓ 模式已切换: {new_info}")
                return new_info
        except Exception:
            continue

    logger.warn("  Pro 选项未找到，Escape 关闭菜单")
    await page.keyboard.press("Escape")
    return current


async def step_send_image(client: GeminiAgency, new_chat: bool = False):
    """发送图片生成请求，验证 Imagen 完整流程。

    Args:
        new_chat: 是否先新建对话（默认 False，复用当前对话）
    """
    logger.note("=" * 60)
    logger.note("步骤 4: 图片生成测试")
    logger.note("=" * 60)

    page = client.page

    try:
        # ── 4.1 可选新建对话 ──────────────────────────────────
        if new_chat:
            logger.note("> 4.1 新建对话 ...")
            await client.new_chat()
            await asyncio.sleep(2)
            await shot(client, "04a_new_chat")
        else:
            logger.mesg("> 4.1 复用当前对话")

        # ── 4.2 确保 Pro 模式 ─────────────────────────────────
        logger.note("> 4.2 确保 Pro 模式 ...")
        current_mode = await _ensure_pro_mode(page)
        await shot(client, "04a_mode")

        # ── 4.2b 选择图片生成工具 ─────────────────────────────
        logger.note("> 4.2b 选择图片生成工具 ...")
        imagen_ok = False

        # 方案 A: 零态卡片（新对话首页）
        try:
            card = await page.query_selector('button[aria-label*="制作图片"]')
            if card and await card.is_visible():
                await card.click()
                await asyncio.sleep(2)
                imagen_ok = True
                logger.okay("  ✓ 已点击零态卡片「制作图片」")
        except Exception:
            pass

        if not imagen_ok:
            # 方案 B: 工具抽屉
            try:
                tools_btn = await page.query_selector(
                    'button[aria-label="工具"], button[aria-label*="Tools" i]'
                )
                if tools_btn and await tools_btn.is_visible():
                    await tools_btn.click()
                    await asyncio.sleep(1)
                    # 查找图片生成选项
                    drawer_items = await page.evaluate(
                        """() => {
                        const drawer = document.querySelector('toolbox-drawer');
                        if (!drawer) return [];
                        return Array.from(drawer.querySelectorAll('button, [role="menuitem"]'))
                            .filter(el => el.offsetParent !== null)
                            .map(el => ({text: (el.textContent||'').trim().substring(0,40), label: el.getAttribute('aria-label')||''}));
                    }"""
                    )
                    logger.mesg(f"  工具抽屉: {[i['text'] for i in drawer_items]}")

                    for item in drawer_items:
                        t = (item["text"] + item["label"]).lower()
                        if any(k in t for k in ["image", "imagen", "图片"]):
                            loc = (
                                page.locator("toolbox-drawer button")
                                .filter(has_text=item["text"][:15])
                                .first
                            )
                            try:
                                await loc.click(timeout=3000)
                                imagen_ok = True
                                logger.okay(f"  ✓ 选择工具: {item['text']}")
                            except Exception:
                                pass
                            break

                    if not imagen_ok:
                        # 关闭抽屉
                        await tools_btn.click()
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.warn(f"  工具抽屉操作失败: {e}")

        if not imagen_ok:
            logger.mesg("  图片生成工具未显式选择，将通过 prompt 直接请求")

        await shot(client, "04a_imagen")

        # ── 4.3 发送图片生成请求 ──────────────────────────────
        msg = "Generate an image of a cute orange cat sitting on a bookshelf, digital art style"
        logger.note("> 4.3 发送图片生成请求 ...")
        logger.mesg(f"  Prompt: {msg}")

        # 输入文本
        await client._type_message(msg)
        await asyncio.sleep(0.5)
        await shot(client, "04b_typed")

        # 发送
        await client._submit_message()
        logger.okay("  ✓ 已发送")

        # ── 4.4 等待响应 ─────────────────────────────────────
        logger.note("> 4.4 等待图片生成响应 (最长 180s) ...")
        timeout_ms = 180000

        response_html = await client._wait_for_response(timeout=timeout_ms)
        await shot(client, "04c_response")

        if not response_html:
            logger.err("  × 未收到响应")
            return None

        logger.okay(f"  ✓ 收到响应 HTML ({len(response_html)} chars)")

        # ── 4.5 提取图片元素 ─────────────────────────────────
        logger.note("> 4.5 提取图片 ...")

        # 先手动检查容器和图片（调试）
        debug_info = await page.evaluate(
            """() => {
            const sel = 'message-content, model-response, .response-container, .model-response-text';
            const containers = document.querySelectorAll(sel);
            const result = {container_count: containers.length, containers: []};
            containers.forEach((c, i) => {
                const imgs = c.querySelectorAll('img');
                result.containers.push({
                    idx: i,
                    tag: c.tagName,
                    cls: (c.className || '').substring(0, 60),
                    img_count: imgs.length,
                    imgs: Array.from(imgs).map(img => ({
                        src: (img.src || '').substring(0, 80),
                        w: img.naturalWidth,
                        h: img.naturalHeight,
                        complete: img.complete,
                        cls: (img.className || '').substring(0, 40),
                    })),
                });
            });
            return result;
        }"""
        )
        logger.mesg(f"  [debug] 容器数: {debug_info['container_count']}")
        for c in debug_info.get("containers", []):
            logger.mesg(f"    [{c['idx']}] <{c['tag']}> imgs={c['img_count']}")
            for img in c.get("imgs", []):
                logger.mesg(
                    f"      {img['w']}x{img['h']} complete={img['complete']} src={img['src'][:60]}"
                )

        images_data = await client._extract_images(download_base64=True)
        logger.mesg(f"  提取到 {len(images_data) if images_data else 0} 个图片元素")

        if images_data:
            for i, img in enumerate(images_data):
                logger.mesg(
                    f"    图片#{i}: src={img.get('src', '')[:80]}... "
                    f"size={img.get('width', '?')}x{img.get('height', '?')}"
                )

        # ── 4.6 解析响应 ─────────────────────────────────────
        logger.note("> 4.6 解析响应 ...")
        response = client.parser.parse(
            html_content=response_html,
            image_data_list=images_data or None,
        )

        # 回填 base64 数据
        if images_data and response.images:
            for img_resp in response.images:
                for img_data in images_data:
                    if img_data.get("src") == img_resp.url and img_data.get(
                        "base64_data"
                    ):
                        img_resp.base64_data = img_data["base64_data"]
                        img_resp.mime_type = img_data.get(
                            "mime_type", img_resp.mime_type
                        )

        logger.okay(f"  文本 ({len(response.text)} ch): {response.text[:300]}")
        logger.mesg(
            f"  Markdown ({len(response.markdown)} ch): {response.markdown[:300]}"
        )
        logger.mesg(f"  图片数量: {len(response.images)}")
        logger.mesg(f"  代码块数: {len(response.code_blocks)}")
        logger.mesg(f"  是否错误: {response.is_error}")

        if response.images:
            for i, img in enumerate(response.images):
                has_b64 = f"✓ ({len(img.base64_data)}B)" if img.base64_data else "×"
                logger.okay(
                    f"  图片#{i}: {img.width}x{img.height} "
                    f"mime={img.mime_type} base64={has_b64} "
                    f"url={img.url[:80]}"
                )
                if img.alt:
                    logger.mesg(f"    alt: {img.alt[:100]}")
        else:
            logger.warn("  × 未解析到图片，检查 DOM ...")

        if response.is_error:
            logger.err(f"  错误信息: {response.error_message}")

        # ── 4.7 响应 DOM 结构（调试）─────────────────────────
        logger.note("> 4.7 响应 DOM 结构 ...")
        resp_dom = await page.evaluate(
            """() => {
            const containers = document.querySelectorAll('message-content, model-response, .response-container');
            if (containers.length === 0) return {found: false};
            const last = containers[containers.length - 1];
            const imgs = last.querySelectorAll('img');
            const result = {
                found: true,
                containerTag: last.tagName,
                containerCls: (last.className || '').substring(0, 100),
                innerHTML_len: last.innerHTML.length,
                innerText_preview: (last.innerText || '').substring(0, 300),
                img_count: imgs.length,
                imgs: [],
                children_tags: [],
            };
            for (let i = 0; i < Math.min(last.children.length, 20); i++) {
                const child = last.children[i];
                result.children_tags.push({
                    tag: child.tagName,
                    cls: (child.className || '').substring(0, 60),
                    text_len: (child.innerText || '').length,
                });
            }
            imgs.forEach((img, i) => {
                if (i >= 10) return;
                result.imgs.push({
                    src: (img.src || '').substring(0, 120),
                    alt: img.alt || '',
                    width: img.naturalWidth || img.width,
                    height: img.naturalHeight || img.height,
                    cls: (img.className || '').substring(0, 60),
                    visible: img.offsetParent !== null,
                    complete: img.complete,
                });
            });
            return result;
        }"""
        )

        if resp_dom.get("found"):
            logger.mesg(
                f"  容器: <{resp_dom['containerTag']}> cls='{resp_dom.get('containerCls', '')}'"
            )
            logger.mesg(f"  HTML: {resp_dom['innerHTML_len']} chars")
            if resp_dom.get("innerText_preview"):
                logger.mesg(f"  文本预览: {resp_dom['innerText_preview'][:200]}")
            logger.mesg(f"  子元素:")
            for child in resp_dom.get("children_tags", []):
                logger.mesg(
                    f"    <{child['tag']}> cls='{child['cls']}' text={child['text_len']}ch"
                )
            logger.mesg(f"  图片 ({resp_dom['img_count']}):")
            for img in resp_dom.get("imgs", []):
                vis = "✓" if img["visible"] else "×"
                comp = "loaded" if img.get("complete") else "loading"
                logger.mesg(
                    f"    [{vis}] {img['width']}x{img['height']} {comp} "
                    f"cls='{img['cls']}' src={img['src'][:80]}"
                )
        else:
            logger.warn("  × 未找到响应容器")

        await shot(client, "04d_final")
        client._message_count += 1
        return response

    except GeminiLoginRequiredError as e:
        logger.err(f"  需要登录: {e}")
        await shot(client, "04_login_required")
    except GeminiPageError as e:
        logger.err(f"  页面错误: {e}")
        traceback.print_exc()
        await shot(client, "04_page_error")
    except GeminiError as e:
        logger.err(f"  Gemini 错误: {e}")
        traceback.print_exc()
        await shot(client, "04_error")
    except Exception as e:
        logger.err(f"  意外错误: {type(e).__name__}: {e}")
        traceback.print_exc()
        await shot(client, "04_unexpected")
    return None


# ═══════════════════════════════════════════════════════════════
# 步骤 4b: 发送简单文本消息
# ═══════════════════════════════════════════════════════════════


async def step_send_simple(client: GeminiAgency):
    """发送一条简单文本消息，验证完整流程。"""
    logger.note("=" * 60)
    logger.note("步骤 4: 发送简单消息")
    logger.note("=" * 60)

    page = client.page

    try:
        # 先探索发送按钮
        logger.note("> 探索输入区域和发送按钮 ...")
        input_send_info = await page.evaluate(
            """() => {
            const result = {input: null, send_buttons: [], all_nearby_buttons: []};

            // 查找输入框
            const editors = document.querySelectorAll(
                'rich-textarea div.ql-editor[contenteditable="true"], ' +
                'div.ql-editor[contenteditable="true"], ' +
                '[contenteditable="true"]'
            );
            for (const el of editors) {
                if (el.offsetParent !== null || el.offsetWidth > 0) {
                    result.input = {
                        tag: el.tagName,
                        cls: (el.className || '').substring(0, 80),
                        role: el.getAttribute('role') || '',
                        text: (el.innerText || '').trim().substring(0, 50),
                        rect: el.getBoundingClientRect(),
                    };
                    break;
                }
            }

            // 查找所有可能的发送按钮
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.offsetParent === null && btn.offsetWidth === 0) continue;
                const label = btn.getAttribute('aria-label') || '';
                const tooltip = btn.getAttribute('mattooltip') || '';
                const text = (btn.textContent || '').trim();
                const cls = btn.className || '';

                // 发送相关
                const lowerAll = (label + tooltip + text).toLowerCase();
                if (lowerAll.includes('send') || lowerAll.includes('发送') ||
                    lowerAll.includes('submit') || lowerAll.includes('提交')) {
                    result.send_buttons.push({
                        label, tooltip, text: text.substring(0, 40),
                        cls: cls.substring(0, 60),
                        disabled: btn.disabled,
                        rect: btn.getBoundingClientRect(),
                    });
                }

                // 输入框附近的按钮
                const parent = btn.closest('.input-area-container, rich-textarea, .chat-input, [class*="input-area"]');
                if (parent) {
                    result.all_nearby_buttons.push({
                        label, tooltip, text: text.substring(0, 30),
                        cls: cls.substring(0, 60),
                        disabled: btn.disabled,
                    });
                }
            }
            return result;
        }"""
        )

        logger.mesg(f"  输入框: {input_send_info.get('input')}")
        logger.mesg(f"  发送按钮: {len(input_send_info.get('send_buttons', []))}")
        for btn in input_send_info.get("send_buttons", []):
            logger.mesg(
                f"    label='{btn['label']}' tooltip='{btn['tooltip']}' text='{btn['text']}' disabled={btn['disabled']}"
            )
        logger.mesg(
            f"  输入区附近按钮: {len(input_send_info.get('all_nearby_buttons', []))}"
        )
        for btn in input_send_info.get("all_nearby_buttons", []):
            logger.mesg(
                f"    label='{btn['label']}' tooltip='{btn['tooltip']}' text='{btn['text']}'"
            )

        # 新建会话
        await client.new_chat()
        await asyncio.sleep(2)
        await shot(client, "04a_new_chat")

        msg = "Hello! Reply with exactly: 'Test successful. Gemini is working.'"
        logger.mesg(f"  发送: {msg}")
        response = await client.send_message(msg, download_images=False)

        await shot(client, "04b_response")

        logger.okay(f"  文本 ({len(response.text)} ch): {response.text[:200]}")
        logger.mesg(f"  MD   ({len(response.markdown)} ch): {response.markdown[:200]}")
        logger.mesg(f"  代码块: {len(response.code_blocks)}")
        logger.mesg(f"  图片: {len(response.images)}")
        logger.mesg(f"  错误: {response.is_error}")

        # 如果文本为空但有 raw_html，输出调试信息
        if not response.text and response.raw_html:
            logger.warn(f"  ⚠ 文本为空! raw_html 长度: {len(response.raw_html)}")
            logger.mesg(f"  raw_html 前 500 字符:")
            logger.mesg(f"  {response.raw_html[:500]}")
            logger.mesg(f"  raw_html 后 500 字符:")
            logger.mesg(f"  {response.raw_html[-500:]}")

            # 用 JS 直接检查响应容器的 innerText
            resp_text = await page.evaluate(
                """() => {
                const containers = document.querySelectorAll(
                    'message-content, model-response, .response-container'
                );
                const results = [];
                containers.forEach((c, i) => {
                    const inner = (c.innerText || '').trim();
                    results.push({
                        idx: i,
                        tag: c.tagName,
                        cls: (c.className || '').substring(0, 60),
                        innerTextLen: inner.length,
                        innerTextPreview: inner.substring(0, 200),
                        innerHTMLLen: c.innerHTML.length,
                        childCount: c.children.length,
                        firstChildTag: c.children[0] ? c.children[0].tagName : 'none',
                    });
                });
                return results;
            }"""
            )
            logger.mesg(f"  响应容器直接检查:")
            for r in resp_text:
                logger.mesg(
                    f"    [{r['idx']}] <{r['tag']}> cls='{r['cls']}' "
                    f"innerText={r['innerTextLen']}ch html={r['innerHTMLLen']}ch "
                    f"children={r['childCount']} firstChild=<{r['firstChildTag']}>"
                )
                if r["innerTextPreview"]:
                    logger.mesg(f"      text: {r['innerTextPreview'][:150]}")

        if response.is_error:
            logger.err(f"  错误信息: {response.error_message}")
        return response

    except GeminiLoginRequiredError as e:
        logger.err(f"  需要登录: {e}")
        await shot(client, "04_login_required")
    except GeminiPageError as e:
        logger.err(f"  页面错误: {e}")
        traceback.print_exc()
        await shot(client, "04_page_error")
    except GeminiError as e:
        logger.err(f"  Gemini 错误: {e}")
        traceback.print_exc()
        await shot(client, "04_error")
    except Exception as e:
        logger.err(f"  意外错误: {type(e).__name__}: {e}")
        traceback.print_exc()
        await shot(client, "04_unexpected")
    return None


# ═══════════════════════════════════════════════════════════════
# 步骤 5: 代码响应测试
# ═══════════════════════════════════════════════════════════════


async def step_send_code(client: GeminiAgency):
    """发送需要代码回复的消息，验证代码块解析。"""
    logger.note("=" * 60)
    logger.note("步骤 5: 代码响应")
    logger.note("=" * 60)

    try:
        msg = (
            "Write a Python function to calculate fibonacci(n). Keep it under 10 lines."
        )
        logger.mesg(f"  发送: {msg}")
        response = await client.send_message(msg, download_images=False)
        await shot(client, "05_code_response")

        logger.okay(f"  文本长度: {len(response.text)}")
        logger.mesg(f"  代码块数: {len(response.code_blocks)}")
        for i, cb in enumerate(response.code_blocks):
            logger.mesg(
                f"    代码块#{i}: lang={cb.language} lines={len(cb.code.splitlines())}"
            )
            for line in cb.code.splitlines()[:5]:
                logger.mesg(f"      {line}")

        if "```" in response.markdown:
            logger.okay("  Markdown 包含代码块标记")
        else:
            logger.warn("  Markdown 未包含代码块标记")

        return response

    except Exception as e:
        logger.err(f"  错误: {type(e).__name__}: {e}")
        await shot(client, "05_error")
    return None


# ═══════════════════════════════════════════════════════════════
# 步骤 6: 多轮对话
# ═══════════════════════════════════════════════════════════════


async def step_multi_turn(client: GeminiAgency):
    """在同一会话中发送跟进消息。"""
    logger.note("=" * 60)
    logger.note("步骤 6: 多轮对话")
    logger.note("=" * 60)

    try:
        msg = "Now add error handling and type hints to that function."
        logger.mesg(f"  发送: {msg}")
        response = await client.send_message(msg, download_images=False)
        await shot(client, "06_multi_turn")

        logger.okay(f"  文本长度: {len(response.text)}")
        logger.mesg(f"  代码块数: {len(response.code_blocks)}")
        logger.mesg(f"  消息计数: {client._message_count}")
        return response

    except Exception as e:
        logger.err(f"  错误: {type(e).__name__}: {e}")
        await shot(client, "06_error")
    return None


# ═══════════════════════════════════════════════════════════════
# 步骤 7: 完整状态汇报
# ═══════════════════════════════════════════════════════════════


async def step_status(client: GeminiAgency):
    """获取并打印客户端完整状态。"""
    logger.note("=" * 60)
    logger.note("步骤 7: 状态汇报")
    logger.note("=" * 60)

    status = await client.browser_status()
    for k, v in status.items():
        logger.mesg(f"  {k}: {v}")
    await shot(client, "07_status")
    return status


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

STEPS = {
    "dom": "step_explore_dom",
    "chat": "step_chat_setup",
    "image": "step_send_image",
    "send": "step_send_simple",
    "code": "step_send_code",
    "multi": "step_multi_turn",
    "status": "step_status",
}


async def main():
    # 解析命令行参数
    # 用法: python -m tests.gemini.test_interactive [step] [new]
    # step: dom, chat, image, send, code, multi, status, all
    # new:  加上 "new" 参数则新建对话（仅对 image/send 等有效）
    args = sys.argv[1:] if len(sys.argv) > 1 else ["all"]
    step_name = args[0].lower()
    want_new_chat = "new" in [a.lower() for a in args[1:]]

    logger.note("=" * 60)
    logger.note(f"  Gemini 交互式测试 (步骤: {step_name})")
    logger.note("=" * 60)
    logger.mesg(f"  截图目录: {SCREENSHOT_DIR}")

    client = await connect_to_running_browser()

    try:
        # 1. 页面信息 & 登录检测
        if not await step_info(client):
            return

        if step_name == "dom":
            await step_explore_dom(client)

        elif step_name == "chat":
            await step_chat_setup(client)

        elif step_name == "image":
            await step_send_image(client, new_chat=want_new_chat)

        elif step_name == "send":
            await step_send_simple(client)

        elif step_name == "code":
            await step_send_code(client)

        elif step_name == "multi":
            await step_multi_turn(client)

        elif step_name == "status":
            await step_status(client)

        elif step_name == "all":
            # 全部步骤
            await step_explore_dom(client)
            setup = await step_chat_setup(client)
            r_img = await step_send_image(client)
            r1 = await step_send_simple(client)
            if r1:
                await step_send_code(client)
                await step_multi_turn(client)
            await step_status(client)
        else:
            logger.err(f"未知步骤: {step_name}")
            logger.mesg(f"  可用: {', '.join(STEPS.keys())}, all")
            return

        logger.note("=" * 60)
        logger.okay("完成!")
        logger.note("=" * 60)

    except Exception as e:
        logger.err(f"测试出错: {type(e).__name__}: {e}")
        traceback.print_exc()
        try:
            await shot(client, "error_final")
        except Exception:
            pass
    finally:
        await disconnect_client(client)


if __name__ == "__main__":
    asyncio.run(main())
