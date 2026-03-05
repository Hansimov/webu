"""快速测试 SiliconFlow Thinking model — 确认不再卡死。"""

import json
import sys
from pathlib import Path
from tclogger import logger, logstr

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from webu.llms.client import LLMClient

LLM_CONFIG_PATH = PROJECT_ROOT / "configs" / "llms.json"


def test_thinking_model():
    logger.note("=" * 60)
    logger.note("Test: SiliconFlow Thinking model (timeout + error handling)")
    logger.note("=" * 60)

    with open(LLM_CONFIG_PATH) as f:
        configs = json.load(f)
    config = configs["sf_qwen3_vl_8b"]

    # Use Thinking variant
    thinking_model = "Qwen/Qwen3-VL-8B-Thinking"

    client = LLMClient(
        endpoint=config["endpoint"],
        api_key=config["api_key"],
        api_format=config.get("api_format", "openai"),
        model=thinking_model,
        timeout=120,  # 2 minutes — generous but won't hang forever
        verbose=True,
        verbose_user=True,
        verbose_assistant=True,
        verbose_content=True,
        verbose_think=True,
        verbose_usage=True,
        verbose_finish=True,
    )

    # Simple text test first (no image, quick)
    logger.mesg("\n[1] Simple text — stream=True")
    try:
        resp = client.chat(
            messages=[{"role": "user", "content": "What is 2+3? Answer briefly."}],
            stream=True,
            max_tokens=256,
            temperature=0.0,
        )
        logger.mesg(f"\n  Response length: {len(resp)}")
        logger.success("  ✓ Stream mode OK")
    except Exception as e:
        logger.err(f"  × Stream failed: {e}")

    logger.mesg("\n[2] Simple text — stream=False")
    try:
        resp = client.chat(
            messages=[{"role": "user", "content": "What is 3+5? Answer briefly."}],
            stream=False,
            max_tokens=256,
            temperature=0.0,
        )
        logger.mesg(f"\n  Response length: {len(resp)}")
        logger.success("  ✓ JSON mode OK")
    except Exception as e:
        logger.err(f"  × JSON failed: {e}")


if __name__ == "__main__":
    test_thinking_model()
