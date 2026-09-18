"""擦除原文字。

纯色背景 -> 直接用背景主色填充（商品标签绝大多数情况，边缘最干净）
复杂背景 -> 用 OpenCV 的 TELEA 修复算法做内容感知填充（所有行合并成一次修复，更快）
"""
from __future__ import annotations

import cv2
import numpy as np

from ..ocr.base import clamp_rect, union_rect


def build_text_mask(
    img: np.ndarray, polys: list[np.ndarray], bg_color, font_size: float = 16.0
) -> np.ndarray:
    """构造文字掩膜：先用 OCR 框，再用"与背景色的差异"收敛到真正的文字像素。"""
    h, w = img.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    polys_i = [np.asarray(p, dtype=np.int32).reshape(-1, 2) for p in polys]
    if not polys_i:
        return mask
    cv2.fillPoly(mask, polys_i, 255)

    rect = clamp_rect(union_rect(polys), w, h)
    x, y, rw, rh = rect
    region = img[y : y + rh, x : x + rw]
    if region.size == 0:
        return mask

    diff = np.abs(region.astype(np.int16) - np.asarray(bg_color, dtype=np.int16))
    diff = diff.max(axis=2)
    local = mask[y : y + rh, x : x + rw]
    if float(diff.max()) > 30:
        _, binary = cv2.threshold(
            diff.astype(np.uint8), 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
        )
        refined = np.where(local > 0, binary, 0).astype(np.uint8)
        # 只有确实收敛出了文字像素才采用，否则退回整框
        if refined.sum() > 0.03 * max(local.sum(), 1):
            mask[y : y + rh, x : x + rw] = refined

    k = max(1, int(font_size * 0.10))
    kernel = np.ones((2 * k + 1, 2 * k + 1), dtype=np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)
    return cv2.GaussianBlur(mask, (3, 3), 0)


def erase_flat(
    img: np.ndarray,
    mask: np.ndarray,
    bg_color: tuple[int, int, int],
    extra_rect: tuple[int, int, int, int] | None = None,
) -> None:
    """纯色背景：整块填成背景色，无修复痕迹。"""
    h, w = img.shape[:2]
    if extra_rect is not None:
        x0, y0, x1, y1 = extra_rect
        x0 = max(0, min(x0, w - 1))
        y0 = max(0, min(y0, h - 1))
        x1 = max(x0 + 1, min(x1, w))
        y1 = max(y0 + 1, min(y1, h))
        cv2.rectangle(img, (x0, y0), (x1, y1), bg_color, thickness=-1)
        return
    img[mask > 40] = bg_color


def erase_complex(img: np.ndarray, mask: np.ndarray) -> None:
    """复杂背景：内容感知修复（外部统一合并掩膜后调用一次）。"""
    if mask is None or not mask.any():
        return
    img[:] = cv2.inpaint(img, mask, 4, cv2.INPAINT_TELEA)
