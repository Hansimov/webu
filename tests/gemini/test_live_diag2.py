"""诊断工具箱抽屉的实际 DOM 结构。"""

import json
import requests
import time

BASE = "http://127.0.0.1:30002"


def ev(js):
    return requests.post(f"{BASE}/evaluate", json={"js": js}, timeout=30).json()


def ss(label):
    requests.post(
        f"{BASE}/store_screenshot",
        json={"path": f"data/debug/diag2_{label}.png"},
        timeout=10,
    )
    print(f"  ss: data/debug/diag2_{label}.png")


def pp(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main():
    # Reset state
    requests.post(f"{BASE}/new_chat")
    time.sleep(2)
    ss("00_fresh")

    # Click the ACTUAL toolbox-drawer button
    print("\n=== Click toolbox-drawer-button ===")
    r = ev(
        """() => {
        const btn = document.querySelector('button.toolbox-drawer-button');
        if (!btn) return {error: 'no toolbox-drawer-button'};
        btn.click();
        return {clicked: true, ariaLabel: btn.getAttribute('aria-label'), cls: btn.className.substring(0, 200)};
    }"""
    )
    pp(r)
    time.sleep(1)
    ss("01_toolbox_opened")

    # Inspect CDK overlays and menus
    print("\n=== Inspect overlays/menus ===")
    r = ev(
        """() => {
        const items = [];
        
        // CDK overlays
        const overlays = document.querySelectorAll('.cdk-overlay-pane');
        for (const ol of overlays) {
            if (ol.offsetWidth === 0 && ol.offsetHeight === 0) continue;
            const buttons = ol.querySelectorAll('button, [role="menuitem"], [role="option"]');
            for (const btn of buttons) {
                if (btn.offsetParent !== null || btn.offsetWidth > 0) {
                    items.push({
                        source: 'cdk-overlay',
                        tag: btn.tagName,
                        text: (btn.textContent || '').trim().substring(0, 100),
                        ariaLabel: btn.getAttribute('aria-label') || '',
                        role: btn.getAttribute('role') || '',
                        cls: Array.from(btn.classList).join(' ').substring(0, 200)
                    });
                }
            }
        }
        
        // Menus
        const menus = document.querySelectorAll('[role="menu"]');
        for (const menu of menus) {
            if (menu.offsetParent === null && menu.offsetWidth === 0) continue;
            const btns = menu.querySelectorAll('button, [role="menuitem"]');
            for (const btn of btns) {
                items.push({
                    source: 'menu',
                    tag: btn.tagName,
                    text: (btn.textContent || '').trim().substring(0, 100),
                    ariaLabel: btn.getAttribute('aria-label') || '',
                    role: btn.getAttribute('role') || '',
                    cls: Array.from(btn.classList).join(' ').substring(0, 200)
                });
            }
        }
        
        return {overlayCount: overlays.length, menuCount: menus.length, items: items};
    }"""
    )
    pp(r)

    # Also check for toolbox-drawer-item elements specifically
    print("\n=== Toolbox-drawer items ===")
    r = ev(
        """() => {
        const items = [];
        
        // Look for elements with toolbox-drawer in class
        const all = document.querySelectorAll('[class*="toolbox-drawer-item"], [class*="toolbox-item"]');
        for (const el of all) {
            items.push({
                tag: el.tagName,
                text: (el.textContent || '').trim().substring(0, 100),
                ariaLabel: el.getAttribute('aria-label') || '',
                visible: el.offsetParent !== null || el.offsetWidth > 0,
                cls: Array.from(el.classList).join(' ').substring(0, 200),
                outerHTML: el.outerHTML.substring(0, 400)
            });
        }
        
        // Also look for mat-list-item or list items in any visible overlay
        const listItems = document.querySelectorAll('mat-list-item, mat-nav-list a, mat-action-list button, [class*="drawer-list"] *, [class*="tool-list"] *');
        for (const el of listItems) {
            if (el.offsetParent !== null || el.offsetWidth > 0) {
                items.push({
                    tag: el.tagName,
                    text: (el.textContent || '').trim().substring(0, 100),
                    cls: Array.from(el.classList).join(' ').substring(0, 200)
                });
            }
        }
        
        return items;
    }"""
    )
    pp(r)

    # Check bottom sheet / dialog
    print("\n=== Bottom sheets / dialogs ===")
    r = ev(
        """() => {
        const items = [];
        const containers = document.querySelectorAll(
            'mat-bottom-sheet-container, mat-dialog-container, ' +
            '[class*="bottom-sheet"], [class*="drawer-panel"], ' +
            '.cdk-overlay-container > .cdk-overlay-backdrop + .cdk-overlay-pane'
        );
        for (const c of containers) {
            items.push({
                tag: c.tagName,
                text: (c.textContent || '').trim().substring(0, 300),
                cls: Array.from(c.classList).join(' ').substring(0, 200),
                children: c.children.length,
                visible: c.offsetParent !== null || c.offsetWidth > 0
            });
        }
        return items;
    }"""
    )
    pp(r)

    # Close and try again with Escape
    print("\n=== Close with Escape ===")
    ev(
        """() => { document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); }"""
    )
    time.sleep(0.5)
    ss("02_after_escape")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
