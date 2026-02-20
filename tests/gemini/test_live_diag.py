"""诊断 Gemini 页面 DOM 结构 — 通过 /evaluate 端点执行 JS。

用于调试 set_mode 和 set_tool 失败的根因：
1. 模式下拉菜单的实际 DOM 结构
2. 工具抽屉的实际 DOM 结构

使用:
    python tests/gemini/test_live_diag.py
"""

import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.webu.gemini.client import GeminiClient, GeminiClientConfig

BASE = "http://127.0.0.1:30002"


def evaluate(js: str) -> dict:
    """在 Gemini 页面中执行 JS 并返回结果。"""
    resp = requests.post(f"{BASE}/evaluate", json={"js": js}, timeout=30)
    return resp.json()


def pp(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def screenshot(label: str):
    requests.post(
        f"{BASE}/store_screenshot",
        json={"path": f"data/debug/diag_{label}.png"},
        timeout=10,
    )
    print(f"📸 data/debug/diag_{label}.png")


def main():
    print("=== 健康检查 ===")
    pp(requests.get(f"{BASE}/health").json())

    screenshot("00_initial")

    # ═══════════════════════════════════════════════════════════
    # 1. 模式选择器诊断
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("模式选择器诊断")
    print("=" * 60)

    # 1a. 查找模式选择器按钮
    print("\n--- 1a. 模式选择器按钮 ---")
    result = evaluate(
        """() => {
        const selectors = [
            'button[aria-label*="模式选择器"]',
            'button[aria-label*="mode selector" i]',
            'button.input-area-switch',
            'button[aria-label*="model" i]',
            'button[data-test-id="model-selector"]',
            'div[role="listbox"]'
        ];
        const found = [];
        for (const sel of selectors) {
            const els = document.querySelectorAll(sel);
            for (const el of els) {
                found.push({
                    selector: sel,
                    tag: el.tagName,
                    text: (el.textContent || '').trim().substring(0, 100),
                    ariaLabel: el.getAttribute('aria-label') || '',
                    visible: el.offsetParent !== null || el.offsetWidth > 0,
                    classList: Array.from(el.classList).join(' '),
                    outerHTML: el.outerHTML.substring(0, 300)
                });
            }
        }
        return found;
    }"""
    )
    pp(result)

    # 1b. 点击模式选择器并检查下拉内容
    print("\n--- 1b. 点击模式选择器 → 检查下拉 ---")
    result = evaluate(
        """() => {
        const btn = document.querySelector('button[aria-label*="模式选择器"]')
            || document.querySelector('button[aria-label*="mode selector" i]')
            || document.querySelector('button.input-area-switch');
        if (!btn) return { error: '未找到模式选择器按钮' };
        btn.click();
        return { clicked: true, text: btn.textContent.trim() };
    }"""
    )
    pp(result)

    time.sleep(1)
    screenshot("01_mode_dropdown_opened")

    # 1c. 检查下拉菜单中的选项
    print("\n--- 1c. 下拉菜单选项 ---")
    result = evaluate(
        """() => {
        const options = [];

        // 检查 role="option"
        const opts1 = document.querySelectorAll('[role="option"]');
        for (const el of opts1) {
            options.push({
                query: '[role="option"]',
                tag: el.tagName,
                text: (el.textContent || '').trim().substring(0, 100),
                visible: el.offsetParent !== null || el.offsetWidth > 0,
                ariaLabel: el.getAttribute('aria-label') || '',
                role: el.getAttribute('role') || '',
                classList: Array.from(el.classList).join(' '),
                outerHTML: el.outerHTML.substring(0, 400)
            });
        }

        // 检查 role="listbox" 的内容
        const listboxes = document.querySelectorAll('[role="listbox"]');
        for (const lb of listboxes) {
            const children = lb.children;
            for (const ch of children) {
                options.push({
                    query: '[role="listbox"] > child',
                    tag: ch.tagName,
                    text: (ch.textContent || '').trim().substring(0, 100),
                    visible: ch.offsetParent !== null || ch.offsetWidth > 0,
                    role: ch.getAttribute('role') || '',
                    classList: Array.from(ch.classList).join(' '),
                    outerHTML: ch.outerHTML.substring(0, 400)
                });
            }
        }

        // 检查 mat-option
        const matOpts = document.querySelectorAll('mat-option');
        for (const el of matOpts) {
            options.push({
                query: 'mat-option',
                tag: el.tagName,
                text: (el.textContent || '').trim().substring(0, 100),
                visible: el.offsetParent !== null || el.offsetWidth > 0,
                outerHTML: el.outerHTML.substring(0, 400)
            });
        }

        // 检查含 "思考" "快速" "Pro" 文本的所有可见元素
        const all = document.querySelectorAll('*');
        const keywords = ['思考', '快速', 'Pro', 'Flash', 'Think'];
        const textMatches = [];
        for (const el of all) {
            if (el.children.length > 3) continue;
            const t = (el.textContent || '').trim();
            if (t.length > 100) continue;
            for (const kw of keywords) {
                if (t.includes(kw) && el.offsetParent !== null) {
                    textMatches.push({
                        query: 'text:' + kw,
                        tag: el.tagName,
                        text: t.substring(0, 100),
                        visible: true,
                        role: el.getAttribute('role') || '',
                        classList: Array.from(el.classList).join(' '),
                        outerHTML: el.outerHTML.substring(0, 300)
                    });
                    break;
                }
            }
        }

        return { options, textMatches };
    }"""
    )
    pp(result)

    # 1d. 关闭下拉（按 Escape）
    print("\n--- 1d. 关闭下拉 ---")
    result = evaluate(
        """() => {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        return { escaped: true };
    }"""
    )
    time.sleep(0.5)

    # ═══════════════════════════════════════════════════════════
    # 2. 工具抽屉诊断
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("工具抽屉诊断")
    print("=" * 60)

    # 2a. 查找工具按钮
    print("\n--- 2a. 工具按钮 ---")
    result = evaluate(
        """() => {
        const selectors = [
            'button[aria-label*="Tools" i]',
            'button[aria-label*="工具"]'
        ];
        const found = [];
        for (const sel of selectors) {
            const els = document.querySelectorAll(sel);
            for (const el of els) {
                found.push({
                    selector: sel,
                    tag: el.tagName,
                    text: (el.textContent || '').trim().substring(0, 100),
                    ariaLabel: el.getAttribute('aria-label') || '',
                    visible: el.offsetParent !== null || el.offsetWidth > 0,
                    outerHTML: el.outerHTML.substring(0, 400)
                });
            }
        }
        return found;
    }"""
    )
    pp(result)

    # 2b. 点击工具按钮并检查抽屉内容
    print("\n--- 2b. 点击工具按钮 → 检查抽屉 ---")
    result = evaluate(
        """() => {
        const btn = document.querySelector('button[aria-label*="工具"]')
            || document.querySelector('button[aria-label*="Tools" i]');
        if (!btn) return { error: '未找到工具按钮' };
        btn.click();
        return { clicked: true, text: btn.textContent.trim() };
    }"""
    )
    pp(result)

    time.sleep(1)
    screenshot("02_tool_drawer_opened")

    # 2c. 检查工具抽屉中的所有可交互元素
    print("\n--- 2c. 工具抽屉内容 ---")
    result = evaluate(
        """() => {
        const items = [];

        // 查找 toolbox-drawer 内的元素
        const drawers = document.querySelectorAll('toolbox-drawer, [class*="toolbox"], [class*="tool-drawer"]');
        for (const drawer of drawers) {
            const buttons = drawer.querySelectorAll('button, [role="menuitem"], [role="option"]');
            for (const btn of buttons) {
                items.push({
                    source: 'drawer',
                    tag: btn.tagName,
                    text: (btn.textContent || '').trim().substring(0, 150),
                    ariaLabel: btn.getAttribute('aria-label') || '',
                    role: btn.getAttribute('role') || '',
                    visible: btn.offsetParent !== null || btn.offsetWidth > 0,
                    classList: Array.from(btn.classList).join(' '),
                    outerHTML: btn.outerHTML.substring(0, 400)
                });
            }
        }

        // 也查找包含 "生成图片" "Deep Research" "Canvas" 的可见元素
        const all = document.querySelectorAll('button, span, div, [role="menuitem"], [role="option"]');
        const keywords = ['生成图片', 'Deep Research', 'Canvas', '创作音乐', '制作图片'];
        for (const el of all) {
            const t = (el.textContent || '').trim();
            for (const kw of keywords) {
                if (t === kw && el.offsetParent !== null) {
                    items.push({
                        source: 'exact-text:' + kw,
                        tag: el.tagName,
                        text: t.substring(0, 150),
                        visible: true,
                        role: el.getAttribute('role') || '',
                        classList: Array.from(el.classList).join(' '),
                        outerHTML: el.outerHTML.substring(0, 400)
                    });
                }
            }
            if (t.includes('生成图片') && t !== '生成图片' && el.offsetParent !== null) {
                items.push({
                    source: 'substring-match:生成图片',
                    tag: el.tagName,
                    text: t.substring(0, 150),
                    exactMatch: t === '生成图片',
                    role: el.getAttribute('role') || '',
                    classList: Array.from(el.classList).join(' '),
                    outerHTML: el.outerHTML.substring(0, 400)
                });
            }
        }

        return items;
    }"""
    )
    pp(result)

    # 2d. 关闭工具抽屉
    print("\n--- 2d. 关闭工具抽屉 ---")
    evaluate(
        """() => {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        return true;
    }"""
    )
    time.sleep(0.5)
    screenshot("03_after_close")

    print("\n=== 诊断完成 ===")


if __name__ == "__main__":
    main()
