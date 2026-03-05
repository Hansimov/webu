"""快速诊断 qvl_machine 服务。

用法:
  python debugs/llms/test_vlm_diag.py [config_key]
  python debugs/llms/test_vlm_diag.py ai_qwen3_vl_8b
"""

import base64
import json
import requests
import sys
from pathlib import Path
from tclogger import logger, logstr

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LLM_CONFIG_PATH = PROJECT_ROOT / "configs" / "llms.json"
DEFAULT_CONFIG_KEY = "ai_qwen3_vl_8b"


def load_base_url(config_key: str) -> str:
    """从 configs/llms.json 读取 endpoint 并提取 base URL。"""
    with open(LLM_CONFIG_PATH) as f:
        all_configs = json.load(f)
    if config_key not in all_configs:
        raise KeyError(
            f"Config key '{config_key}' not found. "
            f"Available: {list(all_configs.keys())}"
        )
    endpoint = all_configs[config_key].get("endpoint", "")
    # 从 .../v1/chat/completions 推导 base_url
    for suffix in ["/v1/chat/completions", "/chat/completions"]:
        if endpoint.endswith(suffix):
            return endpoint[: -len(suffix)].rstrip("/")
    return endpoint.rstrip("/")


def check_health(base: str):
    logger.note("[1] Health check")
    try:
        resp = requests.get(f"{base}/health", timeout=10)
        logger.mesg(f"  Status: {resp.status_code}")
        logger.mesg(f"  Body:   {resp.text[:200]}")
    except Exception as e:
        logger.err(f"  × {e}")


def check_info(base: str):
    logger.note("[2] Info")
    try:
        resp = requests.get(f"{base}/info", timeout=10)
        logger.mesg(f"  Status: {resp.status_code}")
        data = resp.json()
        logger.mesg(f"  Available models: {data.get('available_models', [])}")
        for inst in data.get("instances", []):
            logger.mesg(
                f"    - {inst.get('model_label', '?')}: "
                f"{inst.get('endpoint', '?')} "
                f"healthy={inst.get('healthy', '?')}"
            )
    except Exception as e:
        logger.err(f"  × {e}")


def check_simple_text(base: str):
    logger.note("[3] Simple text chat")
    try:
        resp = requests.post(
            f"{base}/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Say hello in 5 words"}],
                "max_tokens": 32,
                "stream": False,
            },
            timeout=30,
        )
        logger.mesg(f"  Status: {resp.status_code}")
        logger.mesg(f"  Body:   {resp.text[:300]}")
    except Exception as e:
        logger.err(f"  × {e}")


def check_simple_text_stream(base: str):
    logger.note("[4] Simple text chat (stream)")
    try:
        resp = requests.post(
            f"{base}/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Say hello in 5 words"}],
                "max_tokens": 32,
                "stream": True,
            },
            stream=True,
            timeout=30,
        )
        logger.mesg(f"  Status: {resp.status_code}")
        line_count = 0
        for line in resp.iter_lines():
            text = line.decode("utf-8")
            if text.strip():
                logger.mesg(f"  [{line_count}] {text[:150]}")
                line_count += 1
                if line_count >= 10:
                    logger.mesg("  ... (truncated)")
                    break
    except Exception as e:
        logger.err(f"  × {e}")


def check_vlm_small(base: str):
    """用极小图片测试 VLM。"""
    logger.note("[5] VLM with tiny image")
    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
        b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
        b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    b64 = base64.b64encode(tiny_png).decode()
    data_url = f"data:image/png;base64,{b64}"

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": "What color is this pixel?"},
            ],
        }
    ]

    try:
        resp = requests.post(
            f"{base}/v1/chat/completions",
            json={
                "messages": messages,
                "max_tokens": 64,
                "stream": False,
            },
            timeout=60,
        )
        logger.mesg(f"  Status: {resp.status_code}")
        logger.mesg(f"  Body:   {resp.text[:500]}")
    except Exception as e:
        logger.err(f"  × {e}")


if __name__ == "__main__":
    config_key = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG_KEY
    base = load_base_url(config_key)
    logger.note(f"Diagnosing: {logstr.file(config_key)} → {base}")
    print()
    check_health(base)
    check_info(base)
    check_simple_text(base)
    check_simple_text_stream(base)
    check_vlm_small(base)
