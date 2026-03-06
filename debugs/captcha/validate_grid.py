"""验证改进后的网格检测算法。

算法核心：
  1. 用 Hough 检测强水平线 → 聚类
  2. 对 3×3 和 4×4 两种候选分别尝试：
     - 预期 cell 间距 = image_width / n
     - 在聚类中贪心匹配等距线序列（容差 15%）
  3. 选择匹配最好的候选

正确答案 (ground truth):
  boats.jpg        → 3×3, correct cells = [2, 5, 7]
  crosswalks.jpeg  → 3×3, correct cells = [1, 2, 7]
  traffic-lights.jpg → 4×4, correct cells = [2, 3, 4]
"""

import cv2
import numpy as np
from pathlib import Path

SAMPLES_DIR = Path("debugs/captcha-samples")
OUTPUT_DIR = Path("debugs/captcha")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SAMPLES = [
    ("boats", SAMPLES_DIR / "boats.jpg", 3),
    ("crosswalks", SAMPLES_DIR / "crosswalks.jpeg", 3),
    ("traffic-lights", SAMPLES_DIR / "traffic-lights.jpg", 4),
]


def find_horizontal_line_clusters(img: np.ndarray, merge_gap: int = 15) -> list[int]:
    """检测强水平线并聚类，返回 y 坐标列表。"""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    edges = cv2.Canny(gray, 100, 200)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=int(w * 0.5),
        minLineLength=int(w * 0.4),
        maxLineGap=10,
    )

    y_positions = []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)
            if angle < 5:
                y_positions.append((y1 + y2) // 2)

    y_positions.sort()

    # 聚类
    clusters = []
    for y in y_positions:
        if clusters and abs(y - clusters[-1]) < merge_gap:
            clusters[-1] = (clusters[-1] + y) // 2
        else:
            clusters.append(y)

    return clusters


def detect_grid_region(
    img: np.ndarray,
    tolerance: float = 0.15,
) -> tuple[int, int, int] | None:
    """检测网格区域。

    Returns:
        (grid_top_y, grid_bottom_y, grid_n) 或 None
    """
    h, w = img.shape[:2]
    clusters = find_horizontal_line_clusters(img)

    # 过滤掉顶部边框线 (y < 3% of h) 和底部边框线 (y > 97%)
    filtered = [y for y in clusters if h * 0.03 < y < h * 0.97]

    print(f"    Raw clusters: {clusters}")
    print(f"    Filtered:     {filtered}")

    best_score = float("inf")
    best_result = None

    for n in [3, 4]:
        expected_spacing = w / n

        # 从每个聚类开始，尝试贪心匹配 (n+1) 个等距点
        for start_idx in range(len(filtered)):
            matched = [filtered[start_idx]]

            for j in range(start_idx + 1, len(filtered)):
                expected_next = matched[-1] + expected_spacing
                if abs(filtered[j] - expected_next) < expected_spacing * tolerance:
                    matched.append(filtered[j])
                    if len(matched) == n + 1:
                        break

            if len(matched) == n + 1:
                spacings = [
                    matched[k + 1] - matched[k] for k in range(len(matched) - 1)
                ]
                avg_sp = sum(spacings) / len(spacings)
                # 分数 = 间距偏差 + cell 宽高比偏差
                spacing_score = sum(abs(s - avg_sp) for s in spacings)
                # cell 应该接近正方形
                cell_h = avg_sp
                cell_w = w / n
                aspect_score = abs(cell_h / cell_w - 1.0) * 100
                total_score = spacing_score + aspect_score

                if total_score < best_score:
                    best_score = total_score
                    best_result = (
                        matched[0],
                        matched[-1],
                        n,
                        matched,
                        spacings,
                        total_score,
                    )

    if best_result:
        top, bottom, n, matched, spacings, score = best_result
        print(
            f"    Best: {n}×{n}, lines={matched}, spacings={spacings}, score={score:.1f}"
        )
        return top, bottom, n

    # 回退：假设网格在底部正方形区域
    print("    FALLBACK: assuming bottom-square region, 3×3")
    return h - w, h, 3


def draw_grid(
    img: np.ndarray,
    grid_top: int,
    grid_bottom: int,
    grid_n: int,
) -> np.ndarray:
    """在图片上绘制网格和编号。"""
    vis = img.copy()
    h, w = img.shape[:2]
    grid_height = grid_bottom - grid_top
    cell_w = w / grid_n
    cell_h = grid_height / grid_n

    # 画 header/grid 分界线
    cv2.line(vis, (0, grid_top), (w, grid_top), (0, 0, 255), 2)

    cell_idx = 1
    for r in range(grid_n):
        for c in range(grid_n):
            x1 = int(c * cell_w)
            y1 = int(grid_top + r * cell_h)
            x2 = int((c + 1) * cell_w)
            y2 = int(grid_top + (r + 1) * cell_h)

            # 格子边框
            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 255), 2)

            # 编号
            label = str(cell_idx)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
            lx = x2 - tw - 8
            ly = y2 - 8
            cv2.rectangle(
                vis,
                (lx - 4, ly - th - 4),
                (lx + tw + 4, ly + 4),
                (255, 255, 255),
                cv2.FILLED,
            )
            cv2.putText(
                vis,
                label,
                (lx, ly),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
            cell_idx += 1

    return vis


def main():
    print("=" * 60)
    print("网格检测算法验证")
    print("=" * 60)

    for name, path, expected_n in SAMPLES:
        print(f"\n{'─'*60}")
        print(f"  {name}: expected {expected_n}×{expected_n}")

        if not path.exists():
            print(f"    SKIP: not found")
            continue

        img = cv2.imread(str(path))
        h, w = img.shape[:2]
        print(f"    Image: {w}×{h}")

        result = detect_grid_region(img)
        if result is None:
            print(f"    FAIL: could not detect grid")
            continue

        grid_top, grid_bottom, grid_n = result
        grid_h = grid_bottom - grid_top
        cell_w = w / grid_n
        cell_h = grid_h / grid_n

        match = "✓" if grid_n == expected_n else "✗"
        print(f"    Result: {grid_n}×{grid_n} {match}")
        print(f"    Grid: y=[{grid_top}, {grid_bottom}], h={grid_h}")
        print(f"    Cell: {cell_w:.1f}×{cell_h:.1f}, aspect={cell_h/cell_w:.3f}")

        # 保存标注图
        vis = draw_grid(img, grid_top, grid_bottom, grid_n)
        out_path = OUTPUT_DIR / f"validated_{name}_{grid_n}x{grid_n}.png"
        cv2.imwrite(str(out_path), vis)
        print(f"    Saved: {out_path}")

    print(f"\n{'='*60}")
    print("Done.")


if __name__ == "__main__":
    main()
