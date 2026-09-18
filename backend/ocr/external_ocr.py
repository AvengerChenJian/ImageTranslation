"""把识别交给外部开源程序：Tesseract（命令行）或任意 OCR HTTP 服务。

* TesseractEngine：调用系统安装的 tesseract 可执行文件，用 TSV 输出取坐标。
* HttpOCREngine：POST 图片给外部服务（Umi-OCR / 自建 RapidOCR、PaddleOCR
  服务 / Docker OCR 容器），支持多种常见返回格式，无需改动主流程。
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from .. import config
from .base import BaseOCR, TextBox


def _poly_from_xyxy(v) -> list[list[float]]:
    x0, y0, x1, y1 = [float(t) for t in v]
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def normalize_poly(raw) -> list[list[float]] | None:
    """兼容多种 OCR 服务的框格式：

    支持 [[x,y]x4] 四点多边形、[x0,y0,x1,y1] 矩形、[x,y,w,h]（由调用方判定）。
    """
    arr = np.asarray(raw, dtype=float).reshape(-1, 2)
    if arr.shape[0] < 2:
        return None
    if arr.shape[0] == 2:  # 两个点 -> 当成左上/右下
        return _poly_from_xyxy([arr[0][0], arr[0][1], arr[1][0], arr[1][1]])
    return [[float(p[0]), float(p[1])] for p in arr[:4]]


class TesseractEngine(BaseOCR):
    """外部开源程序 Tesseract（https://github.com/tesseract-ocr/tesseract）。"""

    name = "tesseract"

    def __init__(self, lang: str | None = None) -> None:
        self.cmd = config.TESSERACT_CMD or shutil.which("tesseract")
        if not self.cmd:
            raise RuntimeError(
                "未找到 tesseract，请安装后设置 TESSERACT_CMD 或加入 PATH"
            )
        self.lang = lang or config.TESSERACT_LANG
        self.env = os.environ.copy()
        if config.TESSDATA_PREFIX:
            self.env["TESSDATA_PREFIX"] = config.TESSDATA_PREFIX

    def detect(self, img: np.ndarray) -> list[TextBox]:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "input.png"
            cv2.imwrite(str(src), img)
            out_base = str(Path(td) / "out")
            cmd = [self.cmd, str(src), out_base, "-l", self.lang, "--psm", "11", "tsv"]
            proc = subprocess.run(cmd, capture_output=True, text=True, env=self.env)
            if proc.returncode != 0:
                raise RuntimeError(f"tesseract 执行失败：{proc.stderr.strip()[:300]}")
            tsv = Path(out_base + ".tsv").read_text(encoding="utf-8", errors="ignore")

        boxes: list[TextBox] = []
        lines = tsv.strip().split("\n")
        if not lines or len(lines) < 2:
            return boxes
        header = lines[0].split("\t")
        try:
            i_left = header.index("left")
            i_top = header.index("top")
            i_w = header.index("width")
            i_h = header.index("height")
            i_conf = header.index("conf")
            i_text = header.index("text")
        except ValueError:
            return boxes

        for row in lines[1:]:
            cols = row.split("\t")
            if len(cols) <= max(i_left, i_top, i_w, i_h, i_conf, i_text):
                continue
            text = cols[i_text].strip()
            if not text:
                continue
            try:
                x, y, w, h = (int(float(cols[i]) ) for i in (i_left, i_top, i_w, i_h))
                conf = float(cols[i_conf])
            except ValueError:
                continue
            if w <= 0 or h <= 0:
                continue
            boxes.append(
                TextBox(
                    poly=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
                    text=text,
                    score=max(0.0, min(1.0, conf / 100.0)),
                )
            )
        return boxes


class HttpOCREngine(BaseOCR):
    """外部 OCR HTTP 服务（Umi-OCR / 自建服务 / Docker 容器）。

    请求：POST {OCR_HTTP_URL}，JSON 体包含 ``image``（base64，带 data URI 前缀）
    与 ``base64``（纯 base64）两种字段，方便对接不同服务；可用
    ``OCR_HTTP_EXTRA`` 追加自定义字段（如 Umi-OCR 的 options）。
    响应：自动解析以下常见结构——
      * ``{"result": [[poly, text, score], ...]}``（RapidOCR 服务）
      * ``{"data": [{"box": ..., "text": ..., "score": ...}, ...]}``（Umi-OCR）
      * ``{"boxes": [...], "texts": [...], "scores": [...]}``
    """

    name = "http"

    def __init__(self, url: str | None = None, timeout: float | None = None) -> None:
        import httpx

        self.url = url or config.OCR_HTTP_URL
        if not self.url:
            raise RuntimeError("使用 OCR_ENGINE=http 时必须配置 OCR_HTTP_URL")
        self.timeout = timeout or config.OCR_HTTP_TIMEOUT
        self.client = httpx.Client(timeout=self.timeout)

    def detect(self, img: np.ndarray) -> list[TextBox]:
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            raise RuntimeError("图片编码失败")
        b64 = base64.b64encode(buf.tobytes()).decode("ascii")
        payload: dict = {"image": f"data:image/png;base64,{b64}", "base64": b64}
        if config.OCR_HTTP_EXTRA:
            payload.update(config.OCR_HTTP_EXTRA)

        resp = self.client.post(self.url, json=payload)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"OCR 服务返回的不是 JSON：{resp.text[:200]}") from exc
        return self._parse(data)

    @staticmethod
    def _parse(data) -> list[TextBox]:
        items: list[tuple] = []

        def pick(d: dict, *keys, default=None):
            for k in keys:
                if isinstance(d, dict) and k in d and d[k] is not None:
                    return d[k]
            return default

        # 服务可能把结果包在 data / result / results 里
        node = data
        if isinstance(data, dict):
            for key in ("data", "result", "results", "items", "ocrResult"):
                cand = data.get(key)
                if isinstance(cand, list) and cand and not isinstance(cand[0], (int, float, str)):
                    node = cand
                    break
                if isinstance(cand, dict):
                    node = cand
                    break

        if isinstance(node, dict):
            boxes = pick(node, "boxes", "box", "dt_boxes", "regions", default=[])
            texts = pick(node, "texts", "text", "rec_texts", default=[])
            scores = pick(node, "scores", "score", "rec_scores", default=[])
            if isinstance(boxes, list) and isinstance(texts, list):
                for i, b in enumerate(boxes):
                    t = texts[i] if i < len(texts) else ""
                    s = scores[i] if i < len(scores) else 1.0
                    items.append((b, t, s))
            elif isinstance(node, dict) and "text" in node and "box" in node:
                items.append((node["box"], node["text"], node.get("score", 1.0)))

        if isinstance(node, list):
            for it in node:
                if isinstance(it, dict):
                    poly = pick(it, "box", "poly", "points", "bbox", "dt_box")
                    text = pick(it, "text", "content", "transcription", default="")
                    score = pick(it, "score", "confidence", "prob", default=1.0)
                    if poly is not None:
                        items.append((poly, text, score))
                elif isinstance(it, (list, tuple)) and len(it) >= 2:
                    # [poly, text, score?]
                    score = it[2] if len(it) > 2 else 1.0
                    items.append((it[0], it[1], score))

        boxes: list[TextBox] = []
        for raw_poly, text, score in items:
            text = str(text).strip()
            if not text:
                continue
            poly = normalize_poly(raw_poly)
            if poly is None:
                continue
            try:
                sc = float(score)
            except (TypeError, ValueError):
                sc = 1.0
            if sc > 1.0:  # 有的服务返回 0~100
                sc = sc / 100.0
            boxes.append(TextBox(poly=poly, text=text, score=sc))
        return boxes
