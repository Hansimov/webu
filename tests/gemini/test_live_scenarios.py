"""Gemini 全场景端到端测试。

覆盖:
1. 模式切换（快速→思考→Pro→快速）
2. 工具切换（生成图片→Canvas→无工具）
3. 多轮对话
4. 新建聊天后的状态重置
5. 输入框操作的边界情况（空、长文本、特殊字符）
6. get_messages 验证消息内容

使用:
    python tests/gemini/test_live_scenarios.py
"""

import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.webu.gemini.client import GeminiClient, GeminiClientConfig

SCREENSHOT_DIR = "data/debug/scenarios"
_step = 0


def ss(client, label):
    global _step
    _step += 1
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    path = os.path.join(SCREENSHOT_DIR, f"{_step:02d}_{label}.png")
    try:
        client.screenshot(path)
    except Exception:
        pass
    return path


def pp(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def check(condition, msg):
    if condition:
        print(f"  ✅ {msg}")
    else:
        print(f"  ❌ {msg}")
    return condition


# ══════════════════════════════════════════════════════════════
# 场景
# ══════════════════════════════════════════════════════════════


def scenario_mode_rotation(client):
    """场景1: 模式轮换 快速→思考→Pro→快速"""
    section("场景1: 模式轮换")
    results = []

    for mode in ["思考", "Pro", "快速"]:
        print(f"\n  → 切换到 {mode}")
        try:
            r = client.set_mode(mode)
            ok = r.get("status") == "ok"
            results.append(ok)
            check(ok, f"set_mode({mode}) 返回 ok")

            time.sleep(0.5)
            current = client.get_mode().get("mode", "")
            # 模式名可能有微小差异（如 mode-title 内有空格）
            match = mode in current or current in mode
            results.append(match)
            check(match, f"get_mode() = '{current}' (期望含 '{mode}')")
            ss(client, f"mode_{mode}")
        except Exception as e:
            print(f"  ❌ set_mode({mode}) 失败: {e}")
            results.append(False)
            ss(client, f"mode_{mode}_fail")

    return all(results)


def scenario_tool_rotation(client):
    """场景2: 工具轮换 生成图片→Canvas→Deep Research→取消"""
    section("场景2: 工具轮换")
    results = []

    # 先新建聊天确保干净状态
    client.new_chat()
    time.sleep(1)

    for tool in ["生成图片", "Canvas", "Deep Research"]:
        print(f"\n  → 选择工具 {tool}")
        try:
            r = client.set_tool(tool)
            ok = r.get("status") == "ok"
            results.append(ok)
            check(ok, f"set_tool({tool}) 返回 ok")

            time.sleep(0.5)
            current = client.get_tool().get("tool", "")
            check(current != "none", f"get_tool() = '{current}' (非 none)")
            ss(client, f"tool_{tool}")
        except Exception as e:
            print(f"  ❌ set_tool({tool}) 失败: {e}")
            results.append(False)
            ss(client, f"tool_{tool}_fail")

    return all(results)


def scenario_multi_turn(client):
    """场景3: 多轮对话"""
    section("场景3: 多轮对话")
    results = []

    # 新建聊天
    client.new_chat()
    time.sleep(1)

    # 确保处于快速模式（减少等待时间）
    client.set_mode("快速")
    time.sleep(0.5)

    # 第一轮
    print("\n  → 第1轮: 发送 'hello'")
    r1 = client.send_message("hello", wait_response=True)
    ok1 = r1.get("status") == "ok"
    resp1 = r1.get("response", {}).get("text", "")
    results.append(ok1 and len(resp1) > 0)
    check(ok1 and len(resp1) > 0, f"第1轮响应 ({len(resp1)} chars)")
    ss(client, "multi_turn_1")

    # 检查消息列表
    msgs = client.get_messages().get("messages", [])
    results.append(len(msgs) >= 2)
    check(len(msgs) >= 2, f"消息列表有 {len(msgs)} 条 (期望>=2)")

    # 第二轮
    print("\n  → 第2轮: 发送 '你叫什么名字'")
    r2 = client.send_message("你叫什么名字", wait_response=True)
    ok2 = r2.get("status") == "ok"
    resp2 = r2.get("response", {}).get("text", "")
    results.append(ok2 and len(resp2) > 0)
    check(ok2 and len(resp2) > 0, f"第2轮响应 ({len(resp2)} chars)")
    ss(client, "multi_turn_2")

    # 检查消息列表增长
    msgs2 = client.get_messages().get("messages", [])
    results.append(len(msgs2) >= 4)
    check(len(msgs2) >= 4, f"消息列表有 {len(msgs2)} 条 (期望>=4)")

    return all(results)


def scenario_new_chat_reset(client):
    """场景4: 新建聊天后状态重置"""
    section("场景4: 新建聊天重置")
    results = []

    # 先发送一条消息确保有内容
    client.send_message("test message for reset", wait_response=True)
    time.sleep(0.5)

    msgs_before = client.get_messages().get("messages", [])
    check(len(msgs_before) > 0, f"重置前有 {len(msgs_before)} 条消息")

    # 新建聊天
    r = client.new_chat()
    results.append(r.get("status") == "ok")
    check(r.get("status") == "ok", "new_chat() 返回 ok")
    time.sleep(1)

    # 验证消息列表已清空
    msgs_after = client.get_messages().get("messages", [])
    results.append(len(msgs_after) == 0)
    check(len(msgs_after) == 0, f"重置后有 {len(msgs_after)} 条消息 (期望 0)")

    # 验证输入框为空
    input_text = client.get_input().get("text", "")
    results.append(len(input_text) == 0)
    check(len(input_text) == 0, f"重置后输入框: '{input_text}' (期望空)")

    ss(client, "new_chat_reset")
    return all(results)


def scenario_input_edge_cases(client):
    """场景5: 输入框边界情况"""
    section("场景5: 输入框边界情况")
    results = []

    client.new_chat()
    time.sleep(1)

    # 5a. 空字符串
    print("\n  → 5a. 清空后 get_input")
    client.clear_input()
    time.sleep(0.3)
    text = client.get_input().get("text", "")
    results.append(len(text) == 0)
    check(len(text) == 0, f"清空后: '{text}'")

    # 5b. 特殊字符
    print("\n  → 5b. 特殊字符")
    special = "Hello <world> & \"quotes\" 'apostrophes' 中文 日本語 한국어"
    client.set_input(special)
    time.sleep(0.5)
    text = client.get_input().get("text", "")
    # 至少部分内容应该被保留
    has_content = len(text) > 10
    results.append(has_content)
    check(has_content, f"特殊字符输入: '{text[:50]}...'")
    ss(client, "input_special")

    # 5c. 多行文本
    print("\n  → 5c. 多行文本")
    multiline = "第一行\n第二行\n第三行"
    client.set_input(multiline)
    time.sleep(0.5)
    text = client.get_input().get("text", "")
    has_lines = "第一行" in text and "第三行" in text
    results.append(has_lines)
    check(has_lines, f"多行输入: '{text[:50]}'")
    ss(client, "input_multiline")

    # 5d. 连续设置
    print("\n  → 5d. 连续 set_input 覆盖")
    client.set_input("第一次")
    time.sleep(0.3)
    client.set_input("第二次")
    time.sleep(0.3)
    text = client.get_input().get("text", "")
    correct = "第二次" in text and "第一次" not in text
    results.append(correct)
    check(correct, f"连续覆盖: '{text}'")

    # 5e. add_input 追加
    print("\n  → 5e. add_input 多次追加")
    client.clear_input()
    time.sleep(0.3)
    client.set_input("A")
    time.sleep(0.2)
    client.add_input("B")
    time.sleep(0.2)
    client.add_input("C")
    time.sleep(0.3)
    text = client.get_input().get("text", "")
    has_all = "A" in text and "B" in text and "C" in text
    results.append(has_all)
    check(has_all, f"多次追加: '{text}'")
    ss(client, "input_append")

    client.clear_input()
    return all(results)


def scenario_mode_and_send(client):
    """场景6: 思考模式下发送消息"""
    section("场景6: 思考模式发送")
    results = []

    client.new_chat()
    time.sleep(1)

    # 切换到思考模式
    client.set_mode("思考")
    time.sleep(0.5)
    mode = client.get_mode().get("mode", "")
    results.append("思考" in mode)
    check("思考" in mode, f"当前模式: {mode}")

    # 发送消息
    print("\n  → 在思考模式下发送 '1+1=?'")
    r = client.send_message("1+1=?", wait_response=True)
    ok = r.get("status") == "ok"
    resp = r.get("response", {}).get("text", "")
    has_answer = ok and ("2" in resp)
    results.append(has_answer)
    check(has_answer, f"思考模式响应: '{resp[:80]}'")
    ss(client, "think_mode_send")

    # 切回快速模式
    client.set_mode("快速")
    time.sleep(0.5)

    return all(results)


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════


def main():
    global _step
    _step = 0

    config = GeminiClientConfig(host="127.0.0.1", port=30002, timeout=300)
    client = GeminiClient(config)

    print(f"\n{'#'*60}")
    print(f"# Gemini 全场景端到端测试")
    print(f"# Server: {config.base_url}")
    print(f"{'#'*60}")

    scenarios = {
        "模式轮换": scenario_mode_rotation,
        "工具轮换": scenario_tool_rotation,
        "多轮对话": scenario_multi_turn,
        "新建聊天重置": scenario_new_chat_reset,
        "输入框边界": scenario_input_edge_cases,
        "思考模式发送": scenario_mode_and_send,
    }

    results = {}
    for name, func in scenarios.items():
        try:
            results[name] = func(client)
        except Exception as e:
            print(f"\n  ❌ 场景异常: {e}")
            traceback.print_exc()
            results[name] = False
            ss(client, f"exception_{name}")

    # 汇总
    section("测试结果汇总")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\n  通过: {passed}/{total}")
    for name, ok in results.items():
        status = "✅" if ok else "❌"
        print(f"  {status} {name}")

    client.close()
    print(f"\n截图目录: {os.path.abspath(SCREENSHOT_DIR)}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
