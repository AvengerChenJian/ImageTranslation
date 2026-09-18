"""默认 OCR 引擎：RapidOCR（开源，ONNX 版 PaddleOCR 模型，CPU 友好）。"""
from __future__ import annotations

import numpy as np

from .. import config
from .base import BaseOCR, TextBox


class RapidOCREngine(BaseOCR):
    name = "rapid"

    def __init__(self, lang: str | None = None) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "未安装 rapidocr-onnxruntime，请执行：pip install rapidocr-onnxruntime"
            ) from exc
        self.lang = lang or config.OCR_LANG
        self.engine = RapidOCR()

    def detect(self, img: np.ndarray) -> list[TextBox]:
        result, _ = self.engine(img)
        boxes: list[TextBox] = []
        if not result:
            return boxes
        for item in result:
            poly, text, score = item[0], item[1], float(item[2])
            if not str(text).strip():
                continue
            boxes.append(TextBox(poly=poly, text=str(text), score=score))
        return boxes
