"""分析 reCAPTCHA 样本图片的网格边界。

目的：
  1. 找到标题区域与网格区域的分界线
  2. 确定网格的真实起始位置和大小
  3. 验证格子编号与实际内容的对应关系

输出：
  - 每张样本图片的分析结果（控制台 + 标注图片）
  - 标注图片保存在 debugs/captcha/ 目录
"""

import cv2
import numpy as np
from pathlib import Path

SAMPLES_DIR = Path("debugs/captcha-samples")
OUTPUT_DIR = Path("debugs/captcha")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SAMPLES = {
    "boats": SAMPLES_DIR / "boats.jpg",
    "crosswalks": SAMPLES_DIR / "crosswalks.jpeg",
    "traffic-lights": SAMPLES_DIR / "traffic-lights.jpg",
}


def analyze_one(name: str, path: Path) -> dict:
    """分析一张样本图片的网格结构。"""
    img = cv2.imread(str(path))
    if img is None:
        print(f"  ERROR: Cannot read {path}")
        return {}

    h, w = img.shape[:2]
    print(f"\n{'='*60}")
    print(f"  {name}: {w}×{h} (ratio w/h = {w/h:.3f})")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # ── 方法 1: 简单假设 ──
    # reCAPTCHA 的网格区域通常是正方形，宽度 = 图片宽度
    # 标题区域在顶部，高度 = total_h - w
    grid_top_simple = h - w
    print(f"\n  [方法1] 假设网格为底部正方形:")
    print(f"    header_height = {grid_top_simple}")
    print(f"    grid area: y=[{grid_top_simple}, {h}], size={w}×{w}")

    # ── 方法 2: 水平边缘投影 ──
    # 在标题和网格之间通常有一条强水平线
    edges = cv2.Canny(gray, 50, 150)
    h_proj = np.sum(edges, axis=1).astype(float)

    # 归一化
    if h_proj.max() > 0:
        h_proj_norm = h_proj / h_proj.max()
    else:
        h_proj_norm = h_proj

    # 在 y=[h*0.15, h*0.5] 范围内找最强水平线
    # 这是标题区域大致范围
    search_start = int(h * 0.15)
    search_end = int(h * 0.5)
    search_region = h_proj_norm[search_start:search_end]

    if len(search_region) > 0:
        peak_idx = np.argmax(search_region)
        peak_y = search_start + peak_idx
        peak_val = h_proj_norm[peak_y]
        print(f"\n  [方法2] 水平边缘投影:")
        print(f"    搜索范围: y=[{search_start}, {search_end}]")
        print(f"    最强水平边缘: y={peak_y} (strength={peak_val:.3f})")

    # ── 方法 3: 色差检测 ──
    # 标题区域通常是深蓝色背景，网格区域是照片
    # 检测每行的颜色方差（标题区域方差低，照片区域方差高）
    row_var = np.array([np.var(gray[y, :]) for y in range(h)])
    if row_var.max() > 0:
        row_var_norm = row_var / row_var.max()
    else:
        row_var_norm = row_var

    # 找到方差从低到高的跳变点
    # 标题区域颜色均匀（低方差），网格区域图片丰富（高方差）
    # 用滑窗平滑
    kernel_size = 11
    row_var_smooth = np.convolve(
        row_var_norm, np.ones(kernel_size) / kernel_size, mode="same"
    )

    # 在 search 范围内找到方差阶跃
    search_var = row_var_smooth[search_start:search_end]
    if len(search_var) > 0:
        # 计算差分
        diff = np.diff(search_var)
        jump_idx = np.argmax(diff)
        jump_y = search_start + jump_idx
        jump_val = diff[jump_idx]
        print(f"\n  [方法3] 色差跳变检测:")
        print(f"    最大方差跳变: y={jump_y} (delta={jump_val:.4f})")

    # ── 方法 4: 检测水平长线 (Hough) ──
    # 网格边界是跨越整个图片宽度的水平线
    line_edges = cv2.Canny(gray, 100, 200)
    lines = cv2.HoughLinesP(
        line_edges,
        rho=1,
        theta=np.pi / 180,
        threshold=int(w * 0.6),  # 至少 60% 宽度
        minLineLength=int(w * 0.5),
        maxLineGap=10,
    )

    h_lines_found = []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)
            if angle < 5:  # 近似水平
                h_lines_found.append((y1 + y2) // 2)

    h_lines_found.sort()
    print(f"\n  [方法4] Hough 水平长线检测:")
    print(f"    找到 {len(h_lines_found)} 条水平线")
    for i, y_pos in enumerate(h_lines_found):
        region = "header" if y_pos < h * 0.4 else "grid"
        print(f"    线 {i}: y={y_pos} ({region}区域)")

    # ── 综合分析 ──
    # 找标题/网格分界线的最佳猜测
    candidates = [grid_top_simple]
    if h_lines_found:
        # 找最接近 grid_top_simple 的水平线
        for yl in h_lines_found:
            if abs(yl - grid_top_simple) < h * 0.1:
                candidates.append(yl)

    best_grid_top = int(np.median(candidates))
    print(f"\n  [综合] 网格顶部位置: y={best_grid_top}")

    # ── 绘制分析图 ──
    vis = img.copy()

    # 画分界线（红色粗线）
    cv2.line(vis, (0, best_grid_top), (w, best_grid_top), (0, 0, 255), 3)
    cv2.putText(
        vis,
        f"grid top: y={best_grid_top}",
        (10, best_grid_top - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 255),
        2,
    )

    # 画所有检测到的水平线（绿色细线）
    for yl in h_lines_found:
        cv2.line(vis, (0, yl), (w, yl), (0, 255, 0), 1)

    # 画 "方法1" 分界线（蓝色虚线）
    for x in range(0, w, 10):
        cv2.line(vis, (x, grid_top_simple), (x + 5, grid_top_simple), (255, 0, 0), 2)

    # 假设 3x3 网格（先通用分析）
    for grid_n in [3, 4]:
        vis_grid = img.copy()
        grid_h = h - best_grid_top
        cell_w_px = w / grid_n
        cell_h_px = grid_h / grid_n

        cv2.line(vis_grid, (0, best_grid_top), (w, best_grid_top), (0, 0, 255), 2)

        cell_idx = 1
        for r in range(grid_n):
            for c in range(grid_n):
                x1 = int(c * cell_w_px)
                y1 = int(best_grid_top + r * cell_h_px)
                x2 = int((c + 1) * cell_w_px)
                y2 = int(best_grid_top + (r + 1) * cell_h_px)

                # 画格子边框（黄色）
                cv2.rectangle(vis_grid, (x1, y1), (x2, y2), (0, 255, 255), 2)

                # 标注编号（红色，右下角）
                label = str(cell_idx)
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
                lx = x2 - tw - 8
                ly = y2 - 8
                cv2.rectangle(
                    vis_grid,
                    (lx - 4, ly - th - 4),
                    (lx + tw + 4, ly + 4),
                    (255, 255, 255),
                    cv2.FILLED,
                )
                cv2.putText(
                    vis_grid,
                    label,
                    (lx, ly),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.9,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
                cell_idx += 1

        out_path = OUTPUT_DIR / f"grid_analysis_{name}_{grid_n}x{grid_n}.png"
        cv2.imwrite(str(out_path), vis_grid)
        print(f"  Saved: {out_path}")

    # 保存分析图
    out_analysis = OUTPUT_DIR / f"grid_analysis_{name}_lines.png"
    cv2.imwrite(str(out_analysis), vis)
    print(f"  Saved: {out_analysis}")

    # ── 保存投影图 ──
    proj_h = 200
    proj_img = np.zeros((proj_h, w, 3), dtype=np.uint8)
    for x in range(w):
        if x < len(h_proj_norm):
            bar_h = int(h_proj_norm[x] * proj_h)
            cv2.line(proj_img, (x, proj_h), (x, proj_h - bar_h), (0, 255, 0), 1)
    for x in range(w):
        if x < len(row_var_smooth):
            bar_h = int(row_var_smooth[x] * proj_h)
            cv2.line(proj_img, (x, proj_h), (x, proj_h - bar_h), (0, 0, 255), 1)

    # 注意：这里把 y 轴映射为 x 轴来可视化
    # 重新做：把行方差画成横向图
    proj_img2 = np.zeros((h, 300, 3), dtype=np.uint8)
    for y in range(h):
        # 边缘投影（绿色）
        bar_w = int(h_proj_norm[y] * 150)
        cv2.line(proj_img2, (0, y), (bar_w, y), (0, 255, 0), 1)
        # 方差（红色）
        bar_w2 = int(row_var_smooth[y] * 150) + 150
        cv2.line(proj_img2, (150, y), (bar_w2, y), (0, 0, 255), 1)

    # 画分界线
    cv2.line(proj_img2, (0, best_grid_top), (300, best_grid_top), (0, 255, 255), 2)

    out_proj = OUTPUT_DIR / f"grid_analysis_{name}_projection.png"
    cv2.imwrite(str(out_proj), proj_img2)
    print(f"  Saved: {out_proj}")

    return {
        "name": name,
        "size": (w, h),
        "grid_top": best_grid_top,
        "h_lines": h_lines_found,
    }


def main():
    print("reCAPTCHA 样本图片网格边界分析")
    print("=" * 60)

    results = {}
    for name, path in SAMPLES.items():
        if path.exists():
            results[name] = analyze_one(name, path)
        else:
            print(f"\n  SKIP: {path} not found")

    print(f"\n\n{'='*60}")
    print("汇总:")
    for name, info in results.items():
        if info:
            w, h = info["size"]
            gt = info["grid_top"]
            print(
                f"  {name}: {w}×{h}, grid_top={gt}, "
                f"header={gt}px ({gt/h*100:.1f}%), "
                f"grid={h-gt}px ({(h-gt)/h*100:.1f}%)"
            )


if __name__ == "__main__":
    main()
