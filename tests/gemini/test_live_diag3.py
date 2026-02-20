"""诊断思考模式响应结构和多行输入问题。"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.webu.gemini.client import GeminiClient, GeminiClientConfig

config = GeminiClientConfig(host="127.0.0.1", port=30002, timeout=300)
client = GeminiClient(config)


def evaluate(js):
    import requests

    r = requests.post(f"{config.base_url}/evaluate", json={"js": js}, timeout=30)
    return r.json()


def pp(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


print("=" * 60)
print("  诊断1: 当前页面 model-response 结构")
print("=" * 60)

result = evaluate(
    """(() => {
  const mrs = document.querySelectorAll('model-response');
  return Array.from(mrs).map((mr, i) => {
    const mc = mr.querySelector('message-content');
    const text = (mc ? mc.innerText : mr.innerText || '').substring(0, 100);
    return {index: i, has_mc: !!mc, text_preview: text};
  });
})()"""
)
pp(result)


print("\n" + "=" * 60)
print("  诊断2: 发送一条思考模式消息并检查响应结构")
print("=" * 60)

# 新建聊天
client.new_chat()
time.sleep(1)

# 切换到思考模式
r = client.set_mode("思考")
print(f"set_mode(思考): {r}")
time.sleep(0.5)

# 设置输入
client.set_input("1+1=?")
time.sleep(0.3)

# 检查发送前的 model-response 数量
before = evaluate(
    """(() => {
  return document.querySelectorAll('model-response').length;
})()"""
)
print(f"发送前 model-response 数量: {before}")

# 发送（不等待响应）
print("\n发送中(不等待)...")
r = client.send_input(wait_response=False)
print(f"send_input: {r}")

# 轮询检查响应
for i in range(60):
    time.sleep(2)
    result = evaluate(
        """(() => {
      const mrs = document.querySelectorAll('model-response');
      const last = mrs[mrs.length - 1];
      if (!last) return {count: 0};
      
      const mc = last.querySelector('message-content');
      const loading = document.querySelector('.loading-indicator-container, mat-progress-bar, .response-loading');
      const stopBtn = document.querySelector('button[aria-label*="Stop" i], button[aria-label*="停止" i]');
      const thinkingEl = last.querySelector('.thinking-content, thinking-content, .thought-summary, .thought-text, [class*="thinking"], [class*="thought"]');
      
      return {
        count: mrs.length,
        has_mc: !!mc,
        mc_len: mc ? mc.innerHTML.length : 0,
        mc_text: mc ? mc.innerText.substring(0, 150) : '',
        has_loading: !!loading && loading.offsetParent !== null,
        has_stop: !!stopBtn && stopBtn.offsetParent !== null,
        has_thinking: !!thinkingEl,
        thinking_text: thinkingEl ? thinkingEl.innerText.substring(0, 100) : '',
        last_html_snippet: last.innerHTML.substring(0, 300),
      };
    })()"""
    )
    r = result.get("result", {})
    print(
        f"  [{i*2:3d}s] mrs={r.get('count')}, mc_len={r.get('mc_len', 0)}, "
        f"loading={r.get('has_loading')}, stop={r.get('has_stop')}, "
        f"thinking={r.get('has_thinking')}, mc_text={r.get('mc_text', '')[:50]}"
    )

    # 如果有内容且没有loading/stop，可能已完成
    if r.get("mc_len", 0) > 10 and not r.get("has_loading") and not r.get("has_stop"):
        print("\n  → 响应似乎已完成")
        print(f"  mc_text: {r.get('mc_text', '')[:200]}")
        print(f"  thinking_text: {r.get('thinking_text', '')[:200]}")
        print(f"  html_snippet: {r.get('last_html_snippet', '')[:300]}")
        break

# 截图
client.store_screenshot("data/debug/scenarios/diag3_think_response.png")


print("\n\n" + "=" * 60)
print("  诊断3: 多行输入检查")
print("=" * 60)

client.new_chat()
time.sleep(1)
client.set_mode("快速")
time.sleep(0.5)

# 通过 JS 方式检查 _type_message 对 \n 的处理
multiline_text = "第一行\\n第二行\\n第三行"
client.set_input("第一行\n第二行\n第三行")
time.sleep(0.5)

result = evaluate(
    """(() => {
  const editors = document.querySelectorAll('.ql-editor[contenteditable="true"], div[contenteditable="true"][role="textbox"], rich-textarea [contenteditable="true"]');
  for (const ed of editors) {
    if (ed.offsetParent !== null || ed.offsetWidth > 0) {
      return {
        innerHTML: ed.innerHTML,
        innerText: ed.innerText,
        textContent: ed.textContent,
        childNodes: Array.from(ed.childNodes).map(n => ({
          tag: n.tagName || '#text',
          text: (n.textContent || '').substring(0, 30)
        }))
      };
    }
  }
  return {error: 'no visible editor found'};
})()"""
)
print("\n输入框 DOM 结构:")
pp(result)

# 用 get_input 读取
gi = client.get_input()
print(f"\nget_input(): '{gi.get('text', '')}'")

client.close()
print("\n诊断完成。")
