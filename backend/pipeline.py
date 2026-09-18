"""主流程：OCR -> 行合并 -> 翻译 -> 排版 -> 擦除 -> 重绘。"""
from __future__ import annotations

import logging

import cv2
import numpy as np
from PIL import Image

from . import config
from .image.analyze import detect_colors
from .image.inpaint import build_text_mask, erase_complex, erase_flat
from .image.render import (
    bgr_to_rgb,
    ensure_contrast,
    estimate_font_size,
    fit_text,
    render_line,
)
from .image.textfix import recover_spaces
from .languages import LANGUAGES
from .ocr import get_ocr_engine
from .ocr.base import TextBox, TextLine, clamp_rect, group_boxes, merge_texts, union_rect
from . import terms
from .translate import get_translator

logger = logging.getLogger(__name__)


def _prepare_ocr_image(img: np.ndarray) -> tuple[np.ndarray, float]:
    """大图先缩放再送 OCR，坐标按比例映射回原图。"""
    h, w = img.shape[:2]
    max_side = max(h, w)
    if max_side <= config.OCR_MAX_SIDE:
        return img, 1.0
    scale = config.OCR_MAX_SIDE / float(max_side)
    small = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    return small, scale


def _build_lines(img: np.ndarray, boxes: list[TextBox], src_lang: str, tgt_lang: str) -> list[TextLine]:
    h, w = img.shape[:2]
    lines: list[TextLine] = []
    for group in group_boxes(boxes):
        polys = [b.poly for b in group]
        rect = clamp_rect(union_rect(polys), w, h)
        if rect[2] < 2 or rect[3] < 2:
            continue
        raw = merge_texts([b.text for b in group])
        if not raw:
            continue
        font_h = float(np.median([b.height for b in group])) or float(rect[3])
        measure_lang = src_lang if src_lang and src_lang != "auto" else tgt_lang
        # OCR 可能吞掉词间空格，先按像素间隙补回再送去翻译
        text = recover_spaces(
            img, rect, raw, measure_lang, estimate_font_size(raw, measure_lang, font_h, float(rect[2]))
        )
        line = TextLine(
            text=text,
            rect=rect,
            angle=float(np.median([b.angle for b in group])),
            score=float(np.mean([b.score for b in group])),
            polys=polys,
        )
        line.font_size = estimate_font_size(text, measure_lang, font_h, float(rect[2]))
        line.fg_color, line.bg_color, line.flat_bg = detect_colors(img, rect)
        lines.append(line)
    return lines


def _erase_rect_for(line: TextLine) -> tuple[int, int, int, int]:
    """译文占位区域与原文字区域的并集，纯色背景时整块清干净。"""
    x, y, rw, rh = line.rect
    cx, cy = line.center
    layout = line.layout or {"width": rw, "height": rh, "size": line.font_size}
    pad = max(2, int(layout["size"] * 0.30))
    half_w = layout["width"] / 2.0 + pad
    half_h = layout["height"] / 2.0 + pad
    if abs(line.angle) > 1.0:
        # 旋转后外接矩形会变大
        rad = np.deg2rad(abs(line.angle))
        cos_a, sin_a = float(np.cos(rad)), float(np.sin(rad))
        half_w, half_h = half_w * cos_a + half_h * sin_a, half_h * cos_a + half_w * sin_a
    dx0, dy0 = int(cx - half_w), int(cy - half_h)
    dx1, dy1 = int(cx + half_w), int(cy + half_h)
    return (min(dx0, x), min(dy0, y), max(dx1, x + rw), max(dy1, y + rh))


def process_image(
    img: np.ndarray,
    src_lang: str = "auto",
    tgt_lang: str = "zh",
    *,
    ocr=None,
    translator=None,
    outline: str = "auto",
    boxes: list[TextBox] | None = None,
    skip_indices: set[int] | None = None,
    protected: list[str] | None = None,
) -> tuple[np.ndarray, list[dict], dict]:
    """输入 BGR 图片，输出 (结果图 BGR, 文本行信息, 处理元信息)。

    skip_indices: 需要保留原文的行下标（用户手动取消勾选的行）
    protected:    保护词表，命中的行同样保留原文
    boxes:        复用已有的 OCR 结果，避免重复识别
    """
    ocr = ocr or get_ocr_engine()
    translator = translator or get_translator()
    src_lang = src_lang or "auto"
    tgt_lang = tgt_lang or "zh"
    if tgt_lang not in {i["code"] for i in LANGUAGES}:
        tgt_lang = "zh"

    h, w = img.shape[:2]
    if boxes is None:
        boxes = ocr_only(img, ocr)
    boxes = [b for b in boxes if b.score >= config.OCR_MIN_SCORE and b.text.strip()]
    logger.info("OCR(%s) 识别到 %d 个文本框", ocr.name, len(boxes))

    lines = _build_lines(img, boxes, src_lang, tgt_lang)
    meta = {"ocr": ocr.name, "translator": translator.name, "total": len(lines), "translation_failed": 0}
    if not lines:
        return img, [], meta

    # ---- 保留原文的行：手动取消勾选 + 保护词命中 ----
    skip: set[int] = set(skip_indices or ())
    hit_term: dict[int, str] = {}
    for i, line in enumerate(lines):
        term = terms.match_protected(line.text, protected or [])
        if term:
            skip.add(i)
            hit_term[i] = term

    # ---- 翻译（只翻译未被跳过的行）----
    pending = [(i, l.text) for i, l in enumerate(lines) if i not in skip]
    if pending:
        translated = translator.translate([t for _, t in pending], src_lang, tgt_lang)
        for (i, _), tgt in zip(pending, translated):
            lines[i].translated = (tgt or "").strip() or lines[i].text
    for i, line in enumerate(lines):
        if i in skip:
            line.translated = line.text
    meta["skipped"] = len(skip)

    # ---- 排版：先算出译文占位，再决定擦除范围 ----
    # 译文允许比原框大，但必须留在画布内（居中绘制，向两侧等量扩张）
    for i, line in enumerate(lines):
        if i in skip:
            continue
        x, y, rw, rh = line.rect
        cx, cy = line.center
        pad = 4
        max_w = min(rw * config.WIDTH_EXPAND, 2 * min(cx, w - cx) - 2 * pad)
        max_h = min(rh * config.HEIGHT_EXPAND, 2 * min(cy, h - cy) - 2 * pad)
        line.layout = fit_text(
            line.translated,
            tgt_lang,
            line.font_size,
            max(max_w, 12),
            max(max_h, 12),
        )

    # ---- 擦除 ----
    complex_mask = np.zeros((h, w), dtype=np.uint8)
    for i, line in enumerate(lines):
        if i in skip:  # 保留原文的行不擦除、不重绘
            continue
        mask = build_text_mask(img, line.polys, line.bg_color, line.font_size)
        if line.flat_bg:
            erase_flat(img, mask, line.bg_color, _erase_rect_for(line))
        else:
            complex_mask = np.maximum(complex_mask, mask)
    erase_complex(img, complex_mask)

    # ---- 重绘 ----
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).convert("RGBA")
    for i, line in enumerate(lines):
        if i in skip:
            continue
        layout = line.layout
        if not layout or not layout["lines"]:
            continue
        fg = bgr_to_rgb(line.fg_color)
        bg = bgr_to_rgb(line.bg_color)
        color = ensure_contrast(fg, bg)
        stroke = None
        if outline == "on" or (outline == "auto" and not line.flat_bg):
            stroke = (max(1, layout["size"] // 18), bg)
        render_line(pil, layout, line.center, color, line.angle, stroke)

    out = cv2.cvtColor(np.asarray(pil.convert("RGB")), cv2.COLOR_RGB2BGR)

    infos = [
        {
            "index": i,
            "src": l.text,
            "tgt": l.translated,
            "box": list(l.rect),
            "score": round(l.score, 3),
            "font_size": l.layout["size"] if l.layout else l.font_size,
            "flat_bg": l.flat_bg,
            "skipped": i in skip,
            "term": hit_term.get(i),
        }
        for i, l in enumerate(lines)
    ]
    meta["translation_failed"] = int(getattr(translator, "failure_count", 0))
    return out, infos, meta


def lines_from_boxes(
    img: np.ndarray, boxes: list[TextBox], src_lang: str = "auto", tgt_lang: str = "zh"
) -> list[TextLine]:
    """把 OCR 文本框合并成用户可见的"行"，下标即前端勾选用的 index。"""
    kept = [b for b in boxes if b.score >= config.OCR_MIN_SCORE and b.text.strip()]
    return _build_lines(img, kept, src_lang, tgt_lang)


def annotate_boxes(img: np.ndarray, boxes, color=(0, 200, 0)) -> np.ndarray:
    """调试用：把 OCR 框画出来。"""
    canvas = img.copy()
    for b in boxes:
        pts = np.asarray(b.poly, dtype=np.int32).reshape(-1, 2)
        cv2.polylines(canvas, [pts], True, color, 2, cv2.LINE_AA)
    return canvas


def ocr_only(img: np.ndarray, ocr=None) -> list[TextBox]:
    """只做 OCR，返回映射回原图坐标的文本框。"""
    ocr = ocr or get_ocr_engine()
    ocr_img, scale = _prepare_ocr_image(img)
    boxes = ocr(ocr_img)
    if scale != 1.0:
        inv = 1.0 / scale
        boxes = [TextBox(poly=b.poly * inv, text=b.text, score=b.score) for b in boxes]
    return boxes
