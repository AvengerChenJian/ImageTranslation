"""OCR 统一数据结构与后处理（行合并）。

所有 OCR 引擎（内置库 / 外部可执行文件 / 外部 HTTP 服务）都统一输出
``TextBox``，主流程只依赖这一层，替换识别程序不需要改动任何业务逻辑。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

CJK_RANGES = (
    (0x3000, 0x303F),  # CJK 标点
    (0x3040, 0x30FF),  # 日文假名
    (0x3400, 0x4DBF),  # 扩展 A
    (0x4E00, 0x9FFF),  # 中日韩统一表意文字
    (0xAC00, 0xD7AF),  # 韩文音节
    (0xF900, 0xFAFF),  # 兼容表意文字
    (0xFF00, 0xFFEF),  # 全角/半角形式
)


def is_cjk(ch: str) -> bool:
    if not ch:
        return False
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in CJK_RANGES)


@dataclass
class TextBox:
    """一个文本框。poly 顺序约定为 [左上, 右上, 右下, 左下]。"""

    poly: np.ndarray
    text: str
    score: float = 1.0

    def __post_init__(self) -> None:
        self.poly = np.asarray(self.poly, dtype=np.float32).reshape(4, 2)

    # ---- 几何信息 ----
    @property
    def center(self) -> tuple[float, float]:
        return float(self.poly[:, 0].mean()), float(self.poly[:, 1].mean())

    @property
    def rect(self) -> tuple[int, int, int, int]:
        """轴对齐外接矩形 (x, y, w, h)。"""
        xs, ys = self.poly[:, 0], self.poly[:, 1]
        x0, y0 = float(xs.min()), float(ys.min())
        return int(round(x0)), int(round(y0)), int(round(xs.max() - x0)), int(round(ys.max() - y0))

    @property
    def height(self) -> float:
        """文本竖直方向高度（左右两条边长度的平均），比外接矩形更抗旋转。"""
        h1 = float(np.linalg.norm(self.poly[3] - self.poly[0]))
        h2 = float(np.linalg.norm(self.poly[2] - self.poly[1]))
        return (h1 + h2) / 2.0

    @property
    def angle(self) -> float:
        """倾斜角（度），图像坐标系 y 向下，正值表示向右下倾斜。"""
        dx = float(self.poly[1][0] - self.poly[0][0])
        dy = float(self.poly[1][1] - self.poly[0][1])
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return 0.0
        return math.degrees(math.atan2(dy, dx))


@dataclass
class TextLine:
    """合并后的文本行：一次翻译、一次重绘的最小单位。"""

    text: str
    rect: tuple[int, int, int, int]
    angle: float = 0.0
    font_size: int = 16
    score: float = 1.0
    polys: list[np.ndarray] = field(default_factory=list)

    @property
    def center(self) -> tuple[float, float]:
        x, y, w, h = self.rect
        return x + w / 2.0, y + h / 2.0

    # 运行期填充
    translated: str = ""
    fg_color: tuple[int, int, int] = (0, 0, 0)
    bg_color: tuple[int, int, int] = (255, 255, 255)
    flat_bg: bool = True
    layout: dict | None = None


def merge_texts(parts: list[str]) -> str:
    """把多个片段拼成一句：CJK 之间不加空格，其余按空格分隔。"""
    parts = [p for p in (s.strip() for s in parts) if p]
    if not parts:
        return ""
    out = parts[0]
    for p in parts[1:]:
        if is_cjk(out[-1]) and is_cjk(p[0]):
            out += p
        else:
            out += " " + p
    return out


def _vertical_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    _, ay, _, ah = a
    _, by, _, bh = b
    overlap = min(ay + ah, by + bh) - max(ay, by)
    if overlap <= 0 or ah <= 0 or bh <= 0:
        return 0.0
    return overlap / float(min(ah, bh))


def _h_gap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, _, aw, _ = a
    bx, _, bw, _ = b
    return max(bx - (ax + aw), ax - (bx + bw), 0)


def group_boxes(
    boxes: list[TextBox],
    y_overlap: float = 0.45,
    x_gap_ratio: float = 1.2,
) -> list[list[TextBox]]:
    """把散落的文本框合并成阅读行（同一行的文字一起翻译、一起重绘）。"""
    items = sorted(boxes, key=lambda b: b.center[1])
    lines: list[list[TextBox]] = []
    rects: list[tuple[int, int, int, int]] = []

    for box in items:
        r = box.rect
        placed = False
        for i, line in enumerate(lines):
            if any(_vertical_overlap(r, b.rect) >= y_overlap for b in line):
                # 同一水平带内还要保证横向距离够近
                ref = max((b.rect for b in line), key=lambda x: x[2])
                if _h_gap(r, rects[i]) <= x_gap_ratio * max(ref[3], 1):
                    line.append(box)
                    x0 = min(rects[i][0], r[0])
                    y0 = min(rects[i][1], r[1])
                    x1 = max(rects[i][0] + rects[i][2], r[0] + r[2])
                    y1 = max(rects[i][1] + rects[i][3], r[1] + r[3])
                    rects[i] = (x0, y0, x1 - x0, y1 - y0)
                    placed = True
                    break
        if not placed:
            lines.append([box])
            rects.append(r)

    for line in lines:
        line.sort(key=lambda b: b.center[0])
    return lines


def union_rect(polys: list[np.ndarray]) -> tuple[int, int, int, int]:
    pts = np.vstack([np.asarray(p, dtype=np.float32).reshape(-1, 2) for p in polys])
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    return int(round(x0)), int(round(y0)), int(round(x1 - x0)), int(round(y1 - y0))


def clamp_rect(rect: tuple[int, int, int, int], w: int, h: int) -> tuple[int, int, int, int]:
    x, y, rw, rh = rect
    x0 = max(0, min(x, w - 1))
    y0 = max(0, min(y, h - 1))
    x1 = max(x0 + 1, min(x + rw, w))
    y1 = max(y0 + 1, min(y + rh, h))
    return x0, y0, x1 - x0, y1 - y0


class BaseOCR:
    """OCR 引擎接口：输入 BGR ndarray，输出 TextBox 列表。"""

    name = "base"

    def detect(self, img: np.ndarray) -> list[TextBox]:
        raise NotImplementedError

    def __call__(self, img: np.ndarray) -> list[TextBox]:
        return self.detect(img)
