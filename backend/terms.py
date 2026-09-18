"""保护词：品牌名、商标等不需要翻译的内容。

命中的文本行会跳过翻译与重绘，原样保留。词表存在项目根目录的
``protected_terms.json``，可直接手工编辑，也可以通过 /api/terms 增删。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from . import config

_lock = threading.Lock()
_PATH: Path = config.BASE_DIR / "protected_terms.json"


def list_terms() -> list[str]:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [str(t).strip() for t in data if str(t).strip()]


def _save(terms: list[str]) -> list[str]:
    _PATH.write_text(json.dumps(terms, ensure_ascii=False, indent=2), encoding="utf-8")
    return terms


def add_term(term: str) -> list[str]:
    term = (term or "").strip()
    if not term:
        return list_terms()
    with _lock:
        terms = list_terms()
        if term.lower() not in {t.lower() for t in terms}:
            terms.append(term)
            _save(terms)
    return list_terms()


def remove_term(term: str) -> list[str]:
    with _lock:
        terms = [t for t in list_terms() if t.lower() != (term or "").strip().lower()]
        _save(terms)
    return terms


def match_protected(text: str, terms: list[str] | None = None) -> str | None:
    """返回命中的保护词（大小写不敏感，子串匹配）。"""
    low = (text or "").lower()
    for term in terms if terms is not None else list_terms():
        t = term.strip().lower()
        if t and t in low:
            return term
    return None
