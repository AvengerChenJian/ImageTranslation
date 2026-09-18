"""译文重绘：字体选择、自动排版（换行 + 自适应字号）、旋转贴回。"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .. import config
from ..languages import font_family
from ..ocr.base import is_cjk

LINE_SPACING = 1.18

WIN_FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"

FONT_CANDIDATES: dict[str, list[str]] = {
    "default": ["arial.ttf", "segoeui.ttf", "tahoma.ttf", "DejaVuSans.ttf", "NotoSans-Regular.ttf"],
    "zh": [
        "msyh.ttc", "msyhbd.ttc", "msyhl.ttc", "simhei.ttf", "simsun.ttc",
        "NotoSansSC-Regular.otf", "NotoSansCJKsc-Regular.otf",
    ],
    "zh-Hant": ["msjh.ttc", "msjhbd.ttc", "mingliu.ttc", "NotoSansTC-Regular.otf"],
    "ja": ["meiryo.ttc", "msgothic.ttc", "YuGothR.ttc", "NotoSansJP-Regular.otf"],
    "ko": ["malgun.ttf", "malgunbd.ttf", "gulim.ttc", "NotoSansKR-Regular.otf"],
    "ar": ["arial.ttf", "segoeui.ttf", "NotoSansArabic-Regular.ttf"],
    "th": ["leelawui.ttf", "LeelawUI.ttf", "leelaui.ttf", "tahoma.ttf", "NotoSansThai-Regular.ttf"],
}

SEARCH_DIRS = [config.FONTS_DIR, WIN_FONTS]

_font_index: dict[str, str] | None = None


def _font_file_index() -> dict[str, str]:
    """文件名 -> 实际路径 的索引（含所有语种候选，供缺字形时跨语种回退）。"""
    global _font_index
    if _font_index is None:
        idx: dict[str, str] = {}
        names = {n for fam in FONT_CANDIDATES.values() for n in fam}
        for directory in SEARCH_DIRS:
            if not directory:
                continue
            for name in names:
                p = Path(directory) / name
                if p.exists() and name not in idx:
                    idx[name] = str(p)
        _font_index = idx
    return _font_index


@lru_cache(maxsize=None)
def resolve_font_path(lang_code: str) -> str | None:
    """按目标语言挑一个能覆盖该语种字形的字体。"""
    family = font_family(lang_code)
    names = FONT_CANDIDATES.get(family) or FONT_CANDIDATES["default"]
    names = list(names) + [n for n in FONT_CANDIDATES["default"] if n not in names]
    index = _font_file_index()
    for name in names:
        if name in index:
            return index[name]
    return next(iter(index.values()), None)


@lru_cache(maxsize=None)
def _glyph_coverage(path: str) -> set[int] | None:
    """字体的字符覆盖表（需要 fonttools）；读不了返回 None。"""
    try:
        from fontTools.ttLib import TTFont

        tt = TTFont(path, fontNumber=0, lazy=True)
        return set(tt.getBestCmap().keys())
    except Exception:
        return None


@lru_cache(maxsize=None)
def _notdef_bytes(path: str) -> bytes | None:
    """该字体"缺字形"（未分配码位 U+0378）的渲染样本，用于无 fonttools 时的判断。"""
    font = _load_font(path, 32)
    try:
        data = font.getmask(chr(0x0378)).tobytes()
    except Exception:
        return None
    return data if any(data) else None  # 缺字形样本是空白则不可用


@lru_cache(maxsize=8192)
def _char_missing(path: str, ch: str) -> bool:
    coverage = _glyph_coverage(path)
    if coverage is not None:
        return ord(ch) not in coverage
    probe = _notdef_bytes(path)
    if probe is None:
        return False  # 无法判断时按"有字形"处理
    font = _load_font(path, 32)
    try:
        return font.getmask(ch).tobytes() == probe
    except Exception:
        return False


@lru_cache(maxsize=512)
def pick_font_for_text(text: str, lang_code: str) -> str | None:
    """选一个能覆盖译文全部字符的字体。

    翻译失败保留原文时（如中文原文配泰文目标字体）会缺字形渲染成方框，
    这里按字形覆盖跨语种回退：泰文字体缺中文字形 -> 自动换微软雅黑。
    """
    family = font_family(lang_code)
    families = [family, "default"] + [f for f in FONT_CANDIDATES if f not in (family, "default")]
    chars = tuple({c for c in text if not c.isspace()})
    index = _font_file_index()
    fallback: str | None = None
    for fam in families:
        for name in FONT_CANDIDATES.get(fam, []):
            path = index.get(name)
            if not path:
                continue
            fallback = fallback or path
            if not any(_char_missing(path, c) for c in chars):
                return path
    return fallback or resolve_font_path(lang_code)


@lru_cache(maxsize=4096)
def _load_font(path: str | None, size: int) -> ImageFont.FreeTypeFont:
    if path:
        return ImageFont.truetype(path, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 不支持 size
        return ImageFont.load_default()


def load_font(lang_code: str, size: int) -> ImageFont.FreeTypeFont:
    return _load_font(resolve_font_path(lang_code), int(size))


def ink_height(text: str, font) -> int:
    bbox = font.getbbox(text)
    return int(bbox[3] - bbox[1])


def _search(lo: int, hi: int, fits) -> int:
    """二分查找满足 fits 的最大字号。"""
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if fits(mid):
            lo = mid
        else:
            hi = mid
    return lo


def estimate_font_size(text: str, lang_code: str, target_h: float = 0.0, target_w: float = 0.0) -> int:
    """反推原始字号：分别按"渲染高度贴合框高"和"渲染宽度贴合框宽"估计，取较小者。

    OCR 检测框四周通常有留白，小字号的留白占比更大，只用高度会明显偏大；
    同时用宽度约束可以把它拉回来。
    """
    if not text:
        return 16
    path = pick_font_for_text(text, lang_code)
    candidates: list[int] = []

    if target_h > 1:
        candidates.append(
            _search(6, max(12, int(target_h * 3) + 2), lambda s: ink_height(text, _load_font(path, s)) <= target_h)
        )
    if target_w > 1:
        candidates.append(
            _search(6, max(12, int(target_w * 3) + 2), lambda s: _width(text, _load_font(path, s)) <= target_w)
        )
    if not candidates:
        return 16

    size = min(candidates)
    # 字体缺字会让测量结果异常小，退回经验值
    if ink_height(text, _load_font(path, size)) < 0.35 * size:
        size = int(round(max(target_h * 1.15, 16)))
    return max(8, int(size))


def tokenize(text: str) -> list[str]:
    """CJK 逐字成 token，拉丁文按词成 token，便于正确断行。"""
    tokens: list[str] = []
    buf = ""
    for ch in text:
        if ch in ("\n", "\r"):
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append("\n")
        elif ch == " ":
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(" ")
        elif is_cjk(ch):
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    return tokens


def _width(s: str, font) -> float:
    try:
        return float(font.getlength(s))
    except AttributeError:
        return float(font.getbbox(s)[2])


def wrap_text(text: str, font, max_width: float) -> list[str]:
    lines: list[str] = []
    cur = ""
    for tok in tokenize(text):
        if tok == "\n":
            lines.append(cur.rstrip())
            cur = ""
            continue
        if tok == " ":
            if cur:
                cur += " "
            continue
        candidate = cur + tok
        if cur and _width(candidate.rstrip(), font) > max_width:
            lines.append(cur.rstrip())
            cur = tok
        else:
            cur = candidate
    if cur.strip():
        lines.append(cur.rstrip())
    return [l for l in lines if l] or ([text] if text else [])


def fit_text(
    text: str,
    lang_code: str,
    base_size: int,
    max_w: float,
    max_h: float,
    min_size: int | None = None,
) -> dict:
    """从原始字号起逐步缩小，直到译文能装进 max_w × max_h。"""
    min_size = min_size or config.MIN_FONT_SIZE
    size = max(min_size, int(base_size))
    path = pick_font_for_text(text, lang_code)
    best = None
    while size >= min_size:
        font = _load_font(path, size)
        lines = wrap_text(text, font, max_w)
        width = max((_width(l, font) for l in lines), default=0.0)
        height = len(lines) * size * LINE_SPACING
        if width <= max_w and height <= max_h:
            best = {"font": font, "size": size, "lines": lines, "width": width, "height": height}
            break
        size -= max(1, int(size * 0.06))
    if best is None:
        size = min_size
        font = _load_font(path, size)
        lines = wrap_text(text, font, max_w)
        width = max((_width(l, font) for l in lines), default=0.0)
        best = {"font": font, "size": size, "lines": lines, "width": width,
                "height": len(lines) * size * LINE_SPACING}
    return best


# ---------------- 颜色 ----------------
def _rel_luminance(rgb) -> float:
    def f(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast_ratio(a, b) -> float:
    l1, l2 = sorted((_rel_luminance(a), _rel_luminance(b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def ensure_contrast(fg, bg, min_ratio: float = 2.5):
    """译文色与背景对比不足时，自动切到黑或白。"""
    if contrast_ratio(fg, bg) >= min_ratio:
        return tuple(int(v) for v in fg)
    black, white = (0, 0, 0), (255, 255, 255)
    return white if contrast_ratio(white, bg) >= contrast_ratio(black, bg) else black


def bgr_to_rgb(c) -> tuple[int, int, int]:
    return (int(c[2]), int(c[1]), int(c[0]))


# ---------------- 绘制 ----------------
def _paste_rgba(base: Image.Image, layer: Image.Image, x0: int, y0: int) -> None:
    W, H = base.size
    lw, lh = layer.size
    dx0, dy0 = max(x0, 0), max(y0, 0)
    dx1, dy1 = min(x0 + lw, W), min(y0 + lh, H)
    if dx1 <= dx0 or dy1 <= dy0:
        return
    sub = layer.crop((dx0 - x0, dy0 - y0, dx1 - x0, dy1 - y0))
    base.alpha_composite(sub, (dx0, dy0))


def render_line(
    img_rgba: Image.Image,
    layout: dict,
    center: tuple[float, float],
    color,
    angle: float = 0.0,
    stroke: tuple[int, tuple] | None = None,
) -> None:
    """把一行（可能已折行）文本绘制到图片上，支持旋转。"""
    font = layout["font"]
    size = layout["size"]
    lines = layout["lines"]
    if not lines:
        return

    line_h = size * LINE_SPACING
    total_h = line_h * len(lines)
    width = max(layout["width"], 1.0)
    # 留出足够边距，保证旋转后不会被裁掉
    side = int(max(width, total_h)) + int(size * 1.2) + 4

    layer = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx = side / 2.0
    start_y = side / 2.0 - total_h / 2.0
    for i, line in enumerate(lines):
        cy = start_y + (i + 0.5) * line_h
        if stroke:
            draw.text(
                (cx, cy), line, font=font, fill=color, anchor="mm",
                stroke_width=stroke[0], stroke_fill=stroke[1],
            )
        else:
            draw.text((cx, cy), line, font=font, fill=color, anchor="mm")

    if abs(angle) > 1.0:
        layer = layer.rotate(-angle, resample=Image.BICUBIC, expand=False)

    _paste_rgba(img_rgba, layer, int(round(center[0] - side / 2.0)), int(round(center[1] - side / 2.0)))
