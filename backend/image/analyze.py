"""分析单个文本框的前景色（文字色）、背景色与背景复杂程度。"""
from __future__ import annotations

import cv2
import numpy as np

from ..ocr.base import clamp_rect


def _ring_pixels(img: np.ndarray, rect: tuple[int, int, int, int], ratio: float = 0.35):
    """取文本框外扩一圈的像素，用于估计"真正的"背景色（不受文字污染）。"""
    h, w = img.shape[:2]
    x, y, rw, rh = rect
    pad_x = max(3, int(rw * ratio))
    pad_y = max(3, int(rh * ratio))
    ox0 = max(0, x - pad_x)
    oy0 = max(0, y - pad_y)
    ox1 = min(w, x + rw + pad_x)
    oy1 = min(h, y + rh + pad_y)
    outer = img[oy0:oy1, ox0:ox1]
    if outer.size == 0:
        return img.reshape(-1, 3)

    mask = np.ones(outer.shape[:2], dtype=bool)
    ix0 = max(0, x - ox0)
    iy0 = max(0, y - oy0)
    ix1 = min(outer.shape[1], x + rw - ox0)
    iy1 = min(outer.shape[0], y + rh - oy0)
    mask[iy0:iy1, ix0:ix1] = False
    pixels = outer[mask]
    if pixels.size == 0:
        pixels = outer.reshape(-1, 3)
    return pixels.reshape(-1, 3)


def _bgr(t) -> tuple[int, int, int]:
    return tuple(int(round(max(0, min(255, v)))) for v in t)


def detect_colors(
    img: np.ndarray, rect: tuple[int, int, int, int]
) -> tuple[tuple[int, int, int], tuple[int, int, int], bool]:
    """返回 (文字色 BGR, 背景色 BGR, 背景是否为近似纯色)。"""
    h, w = img.shape[:2]
    rect = clamp_rect(rect, w, h)
    x, y, rw, rh = rect
    region = img[y : y + rh, x : x + rw]

    ring = _ring_pixels(img, rect).astype(np.float32)
    bg_ring = np.median(ring, axis=0)
    bg_std = float(np.mean(np.std(ring, axis=0)))
    flat_bg = bg_std < 16.0

    if region.size == 0:
        return _bgr(bg_ring), _bgr(bg_ring), flat_bg

    pixels = region.reshape(-1, 3).astype(np.float32)
    if len(pixels) < 8:
        return _bgr(bg_ring), _bgr(bg_ring), flat_bg

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 8, 1.0)
    _, labels, centers = cv2.kmeans(pixels, 2, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.ravel(), minlength=2).astype(float)
    minority = int(np.argmin(counts))
    majority = int(np.argmax(counts))
    fg, bg = centers[minority], centers[majority]

    # 文字占比过高（粗体大字）时，改按"与外圈背景色的距离"判断
    if counts[minority] / counts.sum() > 0.45:
        dist = np.linalg.norm(centers - bg_ring, axis=1)
        fg = centers[int(np.argmax(dist))]
        bg = centers[int(np.argmin(dist))]

    return _bgr(fg), _bgr(bg), flat_bg
