"""可选 OCR 引擎：PaddleOCR / EasyOCR（依赖较重，按需安装）。"""
from __future__ import annotations

import numpy as np

from .. import config
from .base import BaseOCR, TextBox


class PaddleOCREngine(BaseOCR):
    name = "paddle"

    def __init__(self, lang: str | None = None) -> None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "未安装 paddleocr，请执行：pip install paddleocr paddlepaddle"
            ) from exc
        self.lang = lang or config.OCR_LANG
        self.engine = PaddleOCR(use_angle_cls=True, lang=self.lang, show_log=False)

    def detect(self, img: np.ndarray) -> list[TextBox]:
        result = self.engine.ocr(img, cls=True)
        boxes: list[TextBox] = []
        if not result or not result[0]:
            return boxes
        for line in result[0]:
            poly, info = line[0], line[1]
            text, score = str(info[0]), float(info[1])
            if not text.strip():
                continue
            boxes.append(TextBox(poly=poly, text=text, score=score))
        return boxes


class EasyOCREngine(BaseOCR):
    name = "easy"

    def __init__(self, lang: str | None = None) -> None:
        try:
            import easyocr
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("未安装 easyocr，请执行：pip install easyocr") from exc
        self.lang = lang or config.OCR_LANG
        # EasyOCR 语言代码与本项目略有差异，这里做最小映射
        lang_map = {"ch": "ch_sim", "zh": "ch_sim", "en": "en", "ja": "ja", "ko": "ko"}
        self.reader = easyocr.Reader([lang_map.get(self.lang, "en")], gpu=False)

    def detect(self, img: np.ndarray) -> list[TextBox]:
        result = self.reader.readtext(img)
        boxes: list[TextBox] = []
        for poly, text, score in result:
            if not str(text).strip():
                continue
            boxes.append(TextBox(poly=np.asarray(poly), text=str(text), score=float(score)))
        return boxes
