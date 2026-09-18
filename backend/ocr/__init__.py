"""OCR 引擎工厂。改 .env 里的 OCR_ENGINE 即可切换识别程序。"""
from __future__ import annotations

import threading

from .. import config
from .base import BaseOCR, TextBox, group_boxes, merge_texts, union_rect, clamp_rect  # noqa: F401

_lock = threading.Lock()
_engine: BaseOCR | None = None


def build_ocr_engine(name: str | None = None) -> BaseOCR:
    name = (name or config.OCR_ENGINE or "rapid").strip().lower()
    if name in ("rapid", "rapidocr", "onnx"):
        from .rapid_ocr import RapidOCREngine

        return RapidOCREngine()
    if name in ("paddle", "paddleocr"):
        from .paddle_ocr import PaddleOCREngine

        return PaddleOCREngine()
    if name in ("easy", "easyocr"):
        from .paddle_ocr import EasyOCREngine

        return EasyOCREngine()
    if name in ("tesseract", "tess"):
        from .external_ocr import TesseractEngine

        return TesseractEngine()
    if name in ("http", "api", "service"):
        from .external_ocr import HttpOCREngine

        return HttpOCREngine()
    raise ValueError(f"未知的 OCR 引擎：{name}")


def get_ocr_engine(name: str | None = None) -> BaseOCR:
    """返回进程内共享的引擎实例（构造成本较高，如模型加载）。"""
    global _engine
    if name is not None:
        return build_ocr_engine(name)
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = build_ocr_engine()
    return _engine
