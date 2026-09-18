"""离线调试用翻译后端：原样返回原文，用于不联网跑通整条链路。"""
from __future__ import annotations

from .base import BaseTranslator


class MockTranslator(BaseTranslator):
    name = "mock"

    def translate(self, texts: list[str], src: str, tgt: str) -> list[str]:
        return list(texts)
