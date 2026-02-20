"""Gemini 实时测试脚本。

通过 GeminiClient 对正在运行的 Server 进行端到端测试，
每步截图保存到 data/debug/ 以便对照浏览器状态。

使用前请先启动服务器:
    python -m webu.gemini.run start

运行:
    python tests/gemini/test_live.py
"""

import json
import os
import sys
import time
import traceback

# 将项目根目录加入 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.webu.gemini.client import GeminiClient, GeminiClientConfig

# ── 工具函数 ────────────────────────────────────────────────

SCREENSHOT_DIR = "data/debug"
_step = 0


def step_screenshot(client: GeminiClient, label: str) -> str:
    """截图并保存，返回路径。"""
    global _step
    _step += 1
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    path = os.path.join(SCREENSHOT_DIR, f"{_step:02d}_{label}.png")
    try:
        result = client.store_screenshot(path)
        print(f"  📸 截图: {path}")
        return path
    except Exception as e:
        print(f"  ⚠ 截图失败: {e}")
        return ""


def pp(data):
    """Pretty-print JSON。"""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def run_test(name: str, func, *args, **kwargs):
    """运行单个测试并打印结果。"""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"{'='*60}")
    try:
        result = func(*args, **kwargs)
        print(f"✅ PASS: {name}")
        return result
    except Exception as e:
        print(f"❌ FAIL: {name}")
        traceback.print_exc()
        return None


# ══════════════════════════════════════════════════════════════
# 测试用例
# ══════════════════════════════════════════════════════════════


def test_health(client: GeminiClient):
    """测试健康检查。"""
    result = client.health()
    pp(result)
    assert result["status"] == "ok", f"health status not ok: {result}"
    assert result["version"] == "4.0.0", f"unexpected version: {result}"
    return result


def test_browser_status(client: GeminiClient):
    """测试浏览器状态。"""
    result = client.browser_status()
    pp(result)
    assert result["status"] == "ok", f"browser_status failed: {result}"
    data = result.get("data", {})
    assert "is_ready" in data, f"missing is_ready: {data}"
    step_screenshot(client, "browser_status")
    return result


def test_store_screenshot(client: GeminiClient):
    """测试服务器端截图保存。"""
    result = client.store_screenshot("data/debug/manual_screenshot.png")
    pp(result)
    assert result["status"] == "ok", f"store_screenshot failed: {result}"
    assert os.path.exists(
        result["path"]
    ), f"screenshot file not found: {result['path']}"
    return result


def test_download_screenshot(client: GeminiClient):
    """测试下载截图到本地。"""
    local_path = "data/debug/downloaded_screenshot.png"
    result = client.download_screenshot(local_path)
    assert (
        result == local_path
    ), f"download_screenshot returned unexpected path: {result}"
    assert os.path.exists(local_path), f"downloaded screenshot not found: {local_path}"
    size = os.path.getsize(local_path)
    assert size > 1000, f"downloaded screenshot too small: {size} bytes"
    print(f"  截图大小: {size} bytes")
    return result


def test_get_mode(client: GeminiClient):
    """测试获取模式。"""
    result = client.get_mode()
    pp(result)
    assert "mode" in result, f"missing mode: {result}"
    print(f"  当前模式: {result['mode']}")
    step_screenshot(client, "get_mode")
    return result


def test_get_tool(client: GeminiClient):
    """测试获取工具。"""
    result = client.get_tool()
    pp(result)
    assert "tool" in result, f"missing tool: {result}"
    print(f"  当前工具: {result['tool']}")
    return result


def test_get_input(client: GeminiClient):
    """测试获取输入框内容。"""
    result = client.get_input()
    pp(result)
    assert "text" in result, f"missing text: {result}"
    print(f"  输入框内容: '{result['text']}'")
    return result


def test_set_input(client: GeminiClient, text: str = "你好，这是一条测试消息"):
    """测试设置输入框内容。"""
    result = client.set_input(text)
    pp(result)
    assert result["status"] == "ok", f"set_input failed: {result}"

    # 验证输入框内容
    time.sleep(0.5)
    verify = client.get_input()
    actual = verify.get("text", "")
    print(f"  期望: '{text}'")
    print(f"  实际: '{actual}'")
    assert text[:10] in actual or len(actual) > 0, f"输入框内容验证失败: '{actual}'"

    step_screenshot(client, "set_input")
    return result


def test_add_input(client: GeminiClient, extra: str = " — 追加文本"):
    """测试追加输入框内容。"""
    before = client.get_input().get("text", "")
    print(f"  追加前: '{before}'")

    result = client.add_input(extra)
    pp(result)
    assert result["status"] == "ok", f"add_input failed: {result}"

    time.sleep(0.5)
    after = client.get_input().get("text", "")
    print(f"  追加后: '{after}'")

    step_screenshot(client, "add_input")
    return result


def test_clear_input(client: GeminiClient):
    """测试清空输入框。"""
    result = client.clear_input()
    pp(result)
    assert result["status"] == "ok", f"clear_input failed: {result}"

    time.sleep(0.5)
    verify = client.get_input()
    actual = verify.get("text", "")
    print(f"  清空后内容: '{actual}'")
    assert len(actual) == 0, f"输入框未清空: '{actual}'"

    step_screenshot(client, "clear_input")
    return result


def test_new_chat(client: GeminiClient):
    """测试新建聊天。"""
    result = client.new_chat()
    pp(result)
    assert result.get("status") == "ok", f"new_chat failed: {result}"

    time.sleep(1)
    step_screenshot(client, "new_chat")
    return result


def test_get_messages(client: GeminiClient):
    """测试获取消息列表。"""
    result = client.get_messages()
    pp(result)
    assert "messages" in result, f"missing messages: {result}"
    print(f"  消息数: {len(result['messages'])}")
    return result


def test_get_attachments(client: GeminiClient):
    """测试获取附件列表。"""
    result = client.get_attachments()
    pp(result)
    assert "attachments" in result, f"missing attachments: {result}"
    print(f"  附件数: {len(result['attachments'])}")
    return result


def test_set_mode(client: GeminiClient, mode: str):
    """测试设置模式。"""
    before = client.get_mode()
    print(f"  切换前模式: {before.get('mode')}")

    result = client.set_mode(mode)
    pp(result)
    assert result.get("status") == "ok", f"set_mode failed: {result}"

    time.sleep(1)
    after = client.get_mode()
    print(f"  切换后模式: {after.get('mode')}")

    step_screenshot(client, f"set_mode_{mode}")
    return result


def test_set_tool(client: GeminiClient, tool: str):
    """测试设置工具。"""
    before = client.get_tool()
    print(f"  切换前工具: {before.get('tool')}")

    result = client.set_tool(tool)
    pp(result)
    assert result.get("status") == "ok", f"set_tool failed: {result}"

    time.sleep(1)
    after = client.get_tool()
    print(f"  切换后工具: {after.get('tool')}")

    step_screenshot(client, f"set_tool_{tool}")
    return result


def test_send_message(client: GeminiClient, text: str = "你好"):
    """测试发送消息 (set_input + send_input)。"""
    # 先设置输入
    set_result = client.set_input(text)
    assert set_result["status"] == "ok", f"set_input failed: {set_result}"
    step_screenshot(client, "send_pre")

    # 发送并等待响应
    print(f"  发送消息: '{text}'")
    t0 = time.time()
    result = client.send_input(wait_response=True)
    elapsed = time.time() - t0
    print(f"  响应耗时: {elapsed:.1f}s")

    pp(result)
    assert result.get("status") == "ok", f"send_input failed: {result}"

    response = result.get("response", {})
    print(f"  响应文本长度: {len(response.get('text', ''))}")
    print(f"  响应前100字: {response.get('text', '')[:100]}")

    step_screenshot(client, "send_post")

    # 检查消息列表
    msgs = client.get_messages()
    print(f"  页面消息数: {len(msgs.get('messages', []))}")

    return result


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════


def main():
    global _step
    _step = 0

    config = GeminiClientConfig(host="127.0.0.1", port=30002, timeout=300)
    client = GeminiClient(config)

    print(f"\n{'#'*60}")
    print(f"# Gemini 实时端到端测试")
    print(f"# Server: {config.base_url}")
    print(f"{'#'*60}")

    results = {}

    # ── 第一组：只读检查 ──────────────────────────────────────
    results["health"] = run_test("健康检查", test_health, client)
    results["browser_status"] = run_test("浏览器状态", test_browser_status, client)
    results["store_screenshot"] = run_test("服务器截图", test_store_screenshot, client)
    results["download_screenshot"] = run_test(
        "下载截图", test_download_screenshot, client
    )
    results["get_mode"] = run_test("获取模式", test_get_mode, client)
    results["get_tool"] = run_test("获取工具", test_get_tool, client)
    results["get_input"] = run_test("获取输入框", test_get_input, client)
    results["get_messages"] = run_test("获取消息列表", test_get_messages, client)
    results["get_attachments"] = run_test("获取附件列表", test_get_attachments, client)

    # ── 第二组：输入框操作 ────────────────────────────────────
    results["set_input"] = run_test("设置输入框", test_set_input, client)
    results["add_input"] = run_test("追加输入框", test_add_input, client)
    results["clear_input"] = run_test("清空输入框", test_clear_input, client)

    # ── 第三组：聊天管理 ─────────────────────────────────────
    results["new_chat"] = run_test("新建聊天", test_new_chat, client)

    # ── 第四组：模式和工具 ───────────────────────────────────
    results["set_mode"] = run_test("设置模式 → 思考", test_set_mode, client, "思考")
    results["set_tool"] = run_test(
        "设置工具 → 生成图片", test_set_tool, client, "生成图片"
    )

    # ── 第五组：发送消息 ─────────────────────────────────────
    results["send_message"] = run_test("发送消息", test_send_message, client, "hi")

    # ── 汇总 ────────────────────────────────────────────────
    print(f"\n{'#'*60}")
    print(f"# 测试结果汇总")
    print(f"{'#'*60}")
    passed = sum(1 for v in results.values() if v is not None)
    total = len(results)
    print(f"  通过: {passed}/{total}")
    for name, result in results.items():
        status = "✅" if result is not None else "❌"
        print(f"  {status} {name}")

    client.close()
    print(f"\n截图目录: {os.path.abspath(SCREENSHOT_DIR)}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
