"""商品图翻译 · FastAPI 服务入口。"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, pipeline, terms
from .languages import LANGUAGES, public_languages
from .ocr import get_ocr_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")

app = FastAPI(title="商品图翻译", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_MB = 20

# OCR 结果缓存：识别一次后前端可勾选行，转换时用 ocr_id 复用，避免重复识别
_OCR_CACHE: dict[str, list] = {}
_OCR_CACHE_MAX = 16


def _decode(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="无法解析图片，请换一张试试")
    return img


def _save(img: np.ndarray, ext: str = ".png") -> str:
    name = f"{uuid.uuid4().hex}{ext}"
    cv2.imwrite(str(config.RESULTS_DIR / name), img)
    return f"/results/{name}"


# ---------------- 接口 ----------------
@app.get("/api/languages")
def api_languages():
    return {"languages": public_languages(), "auto": {"code": "auto", "name": "自动检测"}}


@app.get("/api/terms")
def api_terms():
    """保护词列表：命中的行不翻译（用于品牌名 / 商标）。"""
    return {"terms": terms.list_terms()}


@app.post("/api/terms/add")
def api_terms_add(term: str = Form(...)):
    return {"terms": terms.add_term(term)}


@app.post("/api/terms/remove")
def api_terms_remove(term: str = Form(...)):
    return {"terms": terms.remove_term(term)}


@app.get("/api/status")
def api_status():
    try:
        ocr_name = get_ocr_engine().name
    except Exception as exc:
        ocr_name = f"不可用({exc})"
    from .translate import get_translator

    try:
        tr_name = get_translator().name
    except Exception as exc:
        tr_name = f"不可用({exc})"
    return {"ocr": ocr_name, "translator": tr_name, "languages": len(LANGUAGES)}


@app.post("/api/ocr")
async def api_ocr(file: UploadFile = File(...), src_lang: str = Form("auto")):
    """识别并返回可勾选的文本行，供前端选择"不翻译"的内容。"""
    data = await file.read()
    img = _decode(data)
    t0 = time.time()
    boxes = pipeline.ocr_only(img)
    key = uuid.uuid4().hex
    if len(_OCR_CACHE) >= _OCR_CACHE_MAX:
        _OCR_CACHE.clear()
    _OCR_CACHE[key] = boxes
    lines = pipeline.lines_from_boxes(img, boxes, src_lang)
    return {
        "ocr_id": key,
        "preview_url": _save(pipeline.annotate_boxes(img, boxes)),
        "count": len(lines),
        "elapsed_ms": int((time.time() - t0) * 1000),
        "lines": [
            {"index": i, "text": l.text, "score": round(l.score, 3), "box": list(l.rect)}
            for i, l in enumerate(lines)
        ],
    }


@app.post("/api/translate")
async def api_translate(
    file: UploadFile = File(...),
    src_lang: str = Form("auto"),
    tgt_lang: str = Form("zh"),
    outline: str = Form("auto"),
    translator: str | None = Form(None),
    ocr_id: str | None = Form(None),
    skip: str = Form(""),
):
    """上传商品图 -> 输出翻译后的图片。

    skip 为行下标的 JSON 数组，命中的行保留原文不参与翻译/擦除/重绘。
    """
    if tgt_lang not in {i["code"] for i in LANGUAGES}:
        raise HTTPException(status_code=400, detail=f"不支持的目标语言：{tgt_lang}")
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"图片不能超过 {MAX_UPLOAD_MB}MB")
    img = _decode(data)

    t0 = time.time()
    try:
        from .translate import get_translator

        tr = get_translator(translator) if translator else get_translator()
        try:
            skip_set = set(json.loads(skip)) if skip else set()
        except json.JSONDecodeError:
            skip_set = set()
        cached = _OCR_CACHE.get(ocr_id) if ocr_id else None
        out, infos, meta = pipeline.process_image(
            img,
            src_lang,
            tgt_lang,
            translator=tr,
            outline=outline,
            boxes=cached,
            skip_indices=skip_set,
            protected=terms.list_terms(),
        )
    except Exception as exc:
        logger.exception("处理失败")
        raise HTTPException(status_code=500, detail=f"处理失败：{exc}") from exc

    return {
        "result_url": _save(out),
        "width": int(out.shape[1]),
        "height": int(out.shape[0]),
        "lines": infos,
        "meta": meta,
        "elapsed_ms": int((time.time() - t0) * 1000),
    }


# ---------------- 静态资源 ----------------
app.mount("/results", StaticFiles(directory=str(config.RESULTS_DIR)), name="results")
app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
