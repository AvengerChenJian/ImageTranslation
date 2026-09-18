"""修复 OCR 吞掉的词间空格。

部分识别模型会把一行里的多个单词连成不带空格的串（如 PREMIUM ARABICA ->
PREMIUMARABICA），翻译 API 遇到这种串通常原样返回。这里利用真实像素：
文字区域的竖列投影里，词间留白明显宽于字间留白，据此把空格插回正确位置。
"""
from __future__ import annotations

import numpy as np

from .render import load_font


def _ink_bool(region_bgr: np.ndarray) -> np.ndarray:
    """提取区域内的文字像素（与"最常见像素值"差异大的即为字）。"""
    gray = region_bgr.mean(axis=2).astype(np.uint8)
    if gray.size == 0:
        return np.zeros(gray.shape, dtype=bool)
    # 众数近似为底色
    hist = np.bincount(gray.ravel(), minlength=256)
    bg = int(np.argmax(hist))
    diff = np.abs(gray.astype(np.int16) - bg).astype(np.uint8)
    threshold = max(28, int(0.35 * float(np.abs(gray.astype(np.int16) - bg).max())))
    return diff > threshold


def _column_gaps(mask: np.ndarray, min_gap: int) -> tuple[list[float], list[int]]:
    """返回内部空白段（中心 x、宽度），按 x 升序。"""
    cols = mask.any(axis=0)
    idx = np.flatnonzero(cols)
    if len(idx) < 4:
        return [], []
    left, right = int(idx[0]), int(idx[-1])
    centers: list[float] = []
    widths: list[int] = []
    i = left
    while i < right:
        if cols[i]:
            i += 1
            continue
        j = i
        while j < right and not cols[j]:
            j += 1
        width = j - i
        centers.append((i + j - 1) / 2.0)
        widths.append(width)
        i = j
    return centers, widths


def recover_spaces(
    img_bgr: np.ndarray,
    rect: tuple[int, int, int, int],
    text: str,
    lang_code: str,
    font_size: int,
) -> str:
    """把丢失的空格补回。无法判断时原样返回。"""
    text = (text or "").strip()
    if not text or " " in text or len(text) < 4:
        return text
    if not any(("a" <= c <= "z") or ("A" <= c <= "Z") for c in text):
        return text

    h_img, w_img = img_bgr.shape[:2]
    x, y, rw, rh = rect
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w_img, x + rw), min(h_img, y + rh)
    if x1 - x0 < 8 or y1 - y0 < 6:
        return text
    region = img_bgr[y0:y1, x0:x1]

    mask = _ink_bool(region)
    rows = np.flatnonzero(mask.any(axis=1))
    cols_idx = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0 or cols_idx.size < 4:
        return text
    cap_h = int(rows[-1] - rows[0] + 1)
    left, right = int(cols_idx[0]), int(cols_idx[-1])
    if cap_h < 6 or right - left < 8:
        return text

    centers, gap_w = _column_gaps(mask, 1)
    if len(centers) < 2:
        return text

    # 实测：词间隙约为最大字间隙的 2 倍以上，据此自适应筛选
    biggest = max(gap_w)
    runner_up = sorted(gap_w)[-2]
    keep = max(max(3, int(0.30 * cap_h)), int(0.62 * biggest))
    # 没有明显离群的宽空隙 -> 大概率本来就是一个词，不要乱切
    if biggest < max(max(4, int(0.30 * cap_h)), 1.5 * runner_up):
        return text
    gaps = [c for c, w in zip(centers, gap_w) if w >= keep]
    if not gaps:
        return text

    # 用同字号渲染该串，按整体缩放对齐到真实墨迹宽度，再找最近的字符边界
    font = load_font(lang_code, max(8, int(font_size)))
    widths = [float(font.getlength(c)) for c in text]
    total = sum(widths)
    actual = right - left
    if total <= 0 or actual <= 0:
        return text
    scale = actual / total

    boundaries: list[float] = []
    acc = 0.0
    for w in widths[:-1]:
        acc += w
        boundaries.append(left + acc * scale)

    cuts: list[int] = []
    for g in gaps:
        k = int(np.argmin([abs(b - g) for b in boundaries]))
        pos = k + 1
        if pos not in cuts and (not cuts or pos > cuts[-1]):
            cuts.append(pos)
    if not cuts:
        return text

    out: list[str] = []
    prev = 0
    for pos in cuts:
        out.append(text[prev:pos])
        prev = pos
    out.append(text[prev:])
    parts = [p for p in out if p]
    # 切出单字母碎片说明阈值不合适，放弃本次修复
    if len(parts) < 2 or min(len(p) for p in parts) < 2:
        return text
    return " ".join(parts)
