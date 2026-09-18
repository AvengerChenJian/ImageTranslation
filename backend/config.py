"""全局配置。优先读取项目根目录的 .env。"""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv 未安装时使用系统环境变量
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = BASE_DIR / "backend"
FRONTEND_DIR = BASE_DIR / "frontend"
FONTS_DIR = BACKEND_DIR / "image" / "fonts"
RESULTS_DIR = BASE_DIR / "results"
TMP_DIR = BASE_DIR / "tmp"

for _d in (RESULTS_DIR, TMP_DIR, FONTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env", override=False)


def _bool(v: str, default: bool = False) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on") if v else default


# ---------------- OCR ----------------
OCR_ENGINE = os.getenv("OCR_ENGINE", "rapid").strip().lower()  # rapid|paddle|easy|tesseract|http
OCR_LANG = os.getenv("OCR_LANG", "ch").strip()
OCR_MIN_SCORE = float(os.getenv("OCR_MIN_SCORE", "0.5"))

# Tesseract（外部开源程序）
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip() or None
TESSDATA_PREFIX = os.getenv("TESSDATA_PREFIX", "").strip() or None
TESSERACT_LANG = os.getenv("TESSERACT_LANG", "eng+chi_sim").strip()

# 外部 OCR 服务
OCR_HTTP_URL = os.getenv("OCR_HTTP_URL", "").strip()
OCR_HTTP_TIMEOUT = float(os.getenv("OCR_HTTP_TIMEOUT", "60"))
try:
    OCR_HTTP_EXTRA = json.loads(os.getenv("OCR_HTTP_EXTRA", "") or "{}")
except json.JSONDecodeError:
    OCR_HTTP_EXTRA = {}

# ---------------- 翻译 ----------------
TRANSLATOR = os.getenv("TRANSLATOR", "google").strip().lower()  # google|youdao|deepl|mock
YOUDAO_APP_KEY = os.getenv("YOUDAO_APP_KEY", "").strip()
YOUDAO_APP_SECRET = os.getenv("YOUDAO_APP_SECRET", "").strip()
DEEPL_AUTH_KEY = os.getenv("DEEPL_AUTH_KEY", "").strip()
DEEPL_FREE = _bool(os.getenv("DEEPL_FREE", "true"), True)

# ---------------- 图像处理 ----------------
# OCR 在缩放后的副本上运行以加速，坐标会自动映射回原图
OCR_MAX_SIDE = int(os.getenv("OCR_MAX_SIDE", "1600"))
# 译文允许相对原文本框的最大放大倍率
WIDTH_EXPAND = float(os.getenv("WIDTH_EXPAND", "1.20"))
HEIGHT_EXPAND = float(os.getenv("HEIGHT_EXPAND", "1.80"))
MIN_FONT_SIZE = int(os.getenv("MIN_FONT_SIZE", "10"))

RESULT_TTL = int(os.getenv("RESULT_TTL", "86400"))  # 结果文件保留秒数（暂未启用清理任务）
