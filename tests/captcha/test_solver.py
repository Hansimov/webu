"""测试 CAPTCHA 网格检测、标注、VLM 解题全流程。

使用 debugs/captcha-samples/ 下的样本图片进行测试。
步骤：
  1. GridAnnotator: 检测网格 → 标注编号 → 保存结果
  2. CaptchaSolver: 标注图 + prompt → 调用 VLM → 解析回答
  3. 对比 ground truth 验证正确率
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from webu.captcha.solver import GridAnnotator, CaptchaSolver

SAMPLES_DIR = Path("debugs/captcha-samples")
OUTPUT_DIR = Path("debugs/captcha-samples/annotated")

# Ground truth: 正确答案
GROUND_TRUTH = {
    "boats":          {"grid": (3, 3), "cells": [2, 5, 7]},
    "crosswalks":     {"grid": (3, 3), "cells": [1, 2, 7]},
    "traffic-lights": {"grid": (4, 4), "cells": [2, 3, 4]},
}

# 每个样本对应的任务文本
TASK_MAP = {
    "boats":          "Select all images with boats",
    "crosswalks":     "Select all images with crosswalks",
    "traffic-lights": "Select all images with traffic lights",
}


def test_grid_annotator():
    """测试 GridAnnotator 对所有样本图片的网格检测与标注。"""
    print("=" * 60)
    print("Test: GridAnnotator")
    print("=" * 60)

    annotator = GridAnnotator(verbose=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    samples = sorted(SAMPLES_DIR.glob("*.jp*g")) + sorted(
        SAMPLES_DIR.glob("*.png")
    )
    # 排除非样本文件（如旧的标注输出）
    samples = [p for p in samples if p.stem in GROUND_TRUTH or p.stem not in ("last_annotated",)]
    samples = [p for p in samples if p.stem != "last_annotated"]
    if not samples:
        print(f"  No sample images found in {SAMPLES_DIR}")
        return

    grid_pass = True
    for img_path in samples:
        stem = img_path.stem
        print(f"\n--- {img_path.name} ---")
        # 自动检测网格
        result = annotator.annotate(str(img_path))
        print(f"  Grid: {result.rows}×{result.cols}")
        print(f"  Cells: {result.total_cells}")
        print(f"  Image size: {result.original_size}")
        print(f"  Cell rects (first 4): {result.cell_rects[:4]} ...")

        # 验证网格大小
        gt = GROUND_TRUTH.get(stem)
        if gt:
            expected_grid = gt["grid"]
            if result.grid_size == expected_grid:
                print(f"  ✓ Grid size correct: {result.grid_size}")
            else:
                print(f"  ✗ Grid size WRONG: got {result.grid_size}, expected {expected_grid}")
                grid_pass = False

        # 保存标注结果
        out_path = OUTPUT_DIR / f"{img_path.stem}_annotated.png"
        out_path.write_bytes(result.annotated_image)
        print(f"  Saved: {out_path}")

    if grid_pass:
        print("\n  ✓ All grid detections correct!")
    else:
        print("\n  ✗ Some grid detections FAILED!")


async def test_captcha_solver():
    """测试 CaptchaSolver 调用 VLM 解题，验证 ground truth。"""
    print("\n" + "=" * 60)
    print("Test: CaptchaSolver (VLM)")
    print("=" * 60)

    solver = CaptchaSolver(verbose=True)

    if not solver.endpoint:
        print("  × VLM endpoint not configured, skipping VLM test")
        print("  → Set endpoint in configs/captcha.json")
        return

    print(f"\n  Endpoint: {solver.endpoint}")

    samples = sorted(SAMPLES_DIR.glob("*.jp*g")) + sorted(
        SAMPLES_DIR.glob("*.png")
    )
    samples = [p for p in samples if p.stem in GROUND_TRUTH]

    all_correct = True
    for img_path in samples:
        stem = img_path.stem
        print(f"\n--- {img_path.name} ---")
        task_text = TASK_MAP.get(stem, None)

        indices = await solver.solve_from_file(
            str(img_path),
            task_text=task_text,
        )

        gt = GROUND_TRUTH.get(stem)
        if gt:
            expected = gt["cells"]
            if indices == expected:
                print(f"  ✓ VLM correct: {indices}")
            else:
                print(f"  ✗ VLM WRONG: got {indices}, expected {expected}")
                all_correct = False
        else:
            if indices:
                print(f"  ? VLM returned: {indices} (no ground truth)")
            else:
                print(f"  × No cells identified")

    if all_correct:
        print("\n  ✓ All VLM answers correct!")
    else:
        print("\n  ✗ Some VLM answers WRONG (may retry or refine prompt)")


async def test_response_parsing():
    """测试 VLM 响应解析逻辑。"""
    print("\n" + "=" * 60)
    print("Test: Response Parsing")
    print("=" * 60)

    solver = CaptchaSolver(verbose=False)

    test_cases = [
        # (input_text, max_index, expected)
        ('```json\n[1, 4, 7]\n```', 9, [1, 4, 7]),
        ('[2, 5, 8]', 9, [2, 5, 8]),
        ('选择格子 1, 3, 5', 9, [1, 3, 5]),
        ('应该选择第 2、6、9 个格子', 9, [2, 6, 9]),
        ('```json\n[1, 2, 5, 6, 9, 10]\n```', 16, [1, 2, 5, 6, 9, 10]),
        # 过滤超出范围的
        ('[1, 4, 15]', 9, [1, 4]),
        # 空结果
        ('没有符合条件的格子', 9, []),
        # 去重
        ('[1, 1, 3, 3]', 9, [1, 3]),
    ]

    all_pass = True
    for text, max_idx, expected in test_cases:
        result = solver._parse_response(text, max_idx)
        status = "✓" if result == expected else "×"
        if result != expected:
            all_pass = False
        print(
            f"  {status} parse({text[:40]:40s}, max={max_idx}) "
            f"→ {result}  (expected {expected})"
        )

    if all_pass:
        print("\n  All parsing tests passed!")
    else:
        print("\n  Some parsing tests FAILED!")


async def main():
    # 1. 测试网格标注
    test_grid_annotator()

    # 2. 测试响应解析
    await test_response_parsing()

    # 3. 测试 VLM 解题
    await test_captcha_solver()


if __name__ == "__main__":
    asyncio.run(main())
