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
        client.store_screenshot(path)
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

    # 重置工具为 none，避免影响后续场景（Deep Research 会彻底改变 UI）
    try:
        client.set_tool("none")
        time.sleep(0.5)
        client.new_chat()
        time.sleep(1)
        # 验证工具已被重置
        current_tool = client.get_tool().get("tool", "")
        check(current_tool == "none", f"工具已重置为 none (当前: {current_tool})")
    except Exception as e:
        print(f"  ⚠ 重置工具失败: {e}")
        # 强制 new_chat 兜底
        try:
            client.new_chat()
            time.sleep(1)
        except Exception:
            pass

    return all(results)


def scenario_multi_turn(client):
    """场景3: 多轮对话"""
    section("场景3: 多轮对话")
    results = []

    # 新建聊天，确保干净状态
    client.new_chat()
    time.sleep(1)

    # 确保处于快速模式、无工具（减少等待时间，避免 Deep Research 等特殊 UI）
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


def scenario_screenshot_store_download(client):
    """场景7: 截图存储与下载"""
    section("场景7: 截图存储/下载")
    results = []
    import tempfile

    # 7a. 服务器端存储截图
    print("\n  → 7a. store_screenshot")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "store_test.png")
        r = client.store_screenshot(path)
        ok = r.get("status") == "ok"
        exists = os.path.exists(r.get("path", ""))
        results.append(ok and exists)
        check(ok and exists, f"store_screenshot → {r.get('path', 'N/A')}")

    # 7b. 下载截图到本地
    print("\n  → 7b. download_screenshot")
    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = os.path.join(tmpdir, "download_test.png")
        result_path = client.download_screenshot(local_path)
        exists = os.path.exists(local_path)
        size = os.path.getsize(local_path) if exists else 0
        ok = exists and size > 1000
        results.append(ok)
        check(ok, f"download_screenshot → {local_path} ({size} bytes)")

    return all(results)


def scenario_store_download_images(client):
    """场景8: 图片存储与下载（无图片场景）"""
    section("场景8: 图片存储/下载")
    results = []
    import tempfile

    # 先新建聊天（快速模式、无工具），发送文本消息确保无图片
    client.new_chat()
    time.sleep(1)
    client.set_mode("快速")
    time.sleep(0.5)
    client.send_message("Say 'hello'", wait_response=True)
    time.sleep(0.5)

    # 8a. store_images — 无图片时返回空
    print("\n  → 8a. store_images（无图片）")
    with tempfile.TemporaryDirectory() as tmpdir:
        r = client.store_images(output_dir=tmpdir, prefix="test")
        ok = r.get("status") == "ok"
        empty = r.get("image_count", -1) == 0
        results.append(ok and empty)
        check(ok and empty, f"store_images 无图片: count={r.get('image_count')}")

    # 8b. download_images — 无图片时返回空
    print("\n  → 8b. download_images（无图片）")
    with tempfile.TemporaryDirectory() as tmpdir:
        r = client.download_images(output_dir=tmpdir, prefix="test")
        ok = r.get("status") == "ok"
        empty = r.get("image_count", -1) == 0
        saved_empty = r.get("saved_count", -1) == 0
        results.append(ok and empty and saved_empty)
        check(
            ok and empty and saved_empty,
            f"download_images 无图片: count={r.get('image_count')}, saved={r.get('saved_count')}",
        )

    return all(results)


def scenario_chatdb_lifecycle(client):
    """场景9: 聊天数据库完整生命周期"""
    section("场景9: 聊天数据库")
    results = []

    # 9a. 创建聊天
    print("\n  → 9a. 创建聊天")
    r = client.chatdb_create(title="场景测试聊天")
    ok = r.get("status") == "ok"
    chat_id = r.get("chat_id", "")
    results.append(ok and len(chat_id) > 0)
    check(ok, f"chatdb_create → {chat_id}")

    if not chat_id:
        print("  ❌ 无法继续：创建聊天失败")
        return False

    try:
        # 9b. 添加消息
        print("\n  → 9b. 添加消息")
        m1 = client.chatdb_add_message(chat_id, role="user", content="Python 是什么？")
        ok1 = m1.get("status") == "ok" and m1.get("message_index") == 0
        results.append(ok1)
        check(ok1, f"添加用户消息 → index={m1.get('message_index')}")

        m2 = client.chatdb_add_message(
            chat_id, role="model", content="Python 是一种高级编程语言..."
        )
        ok2 = m2.get("status") == "ok" and m2.get("message_index") == 1
        results.append(ok2)
        check(ok2, f"添加模型消息 → index={m2.get('message_index')}")

        # 9c. 获取聊天
        print("\n  → 9c. 获取聊天详情")
        chat = client.chatdb_get(chat_id)
        has_msgs = len(chat.get("chat", {}).get("messages", [])) == 2
        results.append(has_msgs)
        check(
            has_msgs, f"聊天有 {len(chat.get('chat', {}).get('messages', []))} 条消息"
        )

        # 9d. 获取单条消息
        print("\n  → 9d. 获取单条消息")
        msg = client.chatdb_get_message(chat_id, 0)
        correct = msg.get("message", {}).get("content") == "Python 是什么？"
        results.append(correct)
        check(correct, f"消息内容: {msg.get('message', {}).get('content', '')[:30]}")

        # 9e. 更新消息
        print("\n  → 9e. 更新消息")
        client.chatdb_update_message(chat_id, 0, content="什么是 Python？")
        updated = client.chatdb_get_message(chat_id, 0)
        correct = updated.get("message", {}).get("content") == "什么是 Python？"
        results.append(correct)
        check(correct, f"更新后: {updated.get('message', {}).get('content', '')[:30]}")

        # 9f. 更新标题
        print("\n  → 9f. 更新标题")
        client.chatdb_update_title(chat_id, title="重命名后的聊天")
        chat2 = client.chatdb_get(chat_id)
        correct = chat2.get("chat", {}).get("title") == "重命名后的聊天"
        results.append(correct)
        check(correct, f"标题: {chat2.get('chat', {}).get('title')}")

        # 9g. 列出聊天
        print("\n  → 9g. 列出聊天")
        chats = client.chatdb_list()
        found = any(c.get("chat_id") == chat_id for c in chats.get("chats", []))
        results.append(found)
        check(found, f"列表中找到 {chat_id}")

        # 9h. 搜索
        print("\n  → 9h. 搜索聊天")
        search = client.chatdb_search(query="Python")
        has_results = len(search.get("results", [])) > 0
        results.append(has_results)
        check(has_results, f"搜索 'Python' 返回 {len(search.get('results', []))} 条")

        # 9i. 统计
        print("\n  → 9i. 数据库统计")
        stats = client.chatdb_stats()
        ok_stats = (
            stats.get("chat_count", 0) >= 1 and stats.get("total_messages", 0) >= 2
        )
        results.append(ok_stats)
        check(
            ok_stats,
            f"stats: {stats.get('chat_count')} 聊天, {stats.get('total_messages')} 消息",
        )

        # 9j. 删除消息
        print("\n  → 9j. 删除消息")
        client.chatdb_delete_message(chat_id, 1)
        msgs_after = client.chatdb_get_messages(chat_id)
        correct = len(msgs_after.get("messages", [])) == 1
        results.append(correct)
        check(correct, f"删除后剩余 {len(msgs_after.get('messages', []))} 条消息")

    finally:
        # 9k. 删除聊天
        print("\n  → 9k. 删除聊天")
        client.chatdb_delete(chat_id)
        chats_after = client.chatdb_list()
        not_found = all(
            c.get("chat_id") != chat_id for c in chats_after.get("chats", [])
        )
        results.append(not_found)
        check(not_found, "聊天已从列表中删除")

    return all(results)


def scenario_send_and_record(client):
    """场景10: 发送消息并记录到 ChatDB"""
    section("场景10: 发送并记录到 ChatDB")
    results = []

    # 新建聊天（快速模式、无工具）并发送
    client.new_chat()
    time.sleep(1)
    client.set_mode("快速")
    time.sleep(0.5)

    prompt = "Say exactly 'integration test ok'"
    print(f"\n  → 发送消息: '{prompt}'")
    r = client.send_message(prompt, wait_response=True)
    ok = r.get("status") == "ok"
    resp_text = r.get("response", {}).get("text", "")
    results.append(ok and len(resp_text) > 0)
    check(
        ok and len(resp_text) > 0, f"响应 ({len(resp_text)} chars): '{resp_text[:60]}'"
    )

    # 记录到 ChatDB
    create = client.chatdb_create(title="自动记录测试")
    chat_id = create.get("chat_id", "")
    results.append(len(chat_id) > 0)

    if chat_id:
        try:
            client.chatdb_add_message(chat_id, role="user", content=prompt)
            client.chatdb_add_message(chat_id, role="model", content=resp_text)

            # 验证
            chat = client.chatdb_get(chat_id)
            msgs = chat.get("chat", {}).get("messages", [])
            correct = (
                len(msgs) == 2
                and msgs[0]["role"] == "user"
                and msgs[1]["role"] == "model"
            )
            results.append(correct)
            check(correct, f"ChatDB 记录 {len(msgs)} 条消息")

            # 搜索验证
            search = client.chatdb_search(query="integration test")
            found = len(search.get("results", [])) > 0
            results.append(found)
            check(found, "搜索 'integration test' 能找到记录")
        finally:
            client.chatdb_delete(chat_id)

    ss(client, "send_and_record")
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
        "截图存储/下载": scenario_screenshot_store_download,
        "图片存储/下载": scenario_store_download_images,
        "聊天数据库": scenario_chatdb_lifecycle,
        "发送并记录": scenario_send_and_record,
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
