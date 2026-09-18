"""翻译引擎工厂。改 .env 里的 TRANSLATOR 即可切换。"""
from __future__ import annotations

import logging
import threading

from .. import config
from .base import BaseTranslator  # noqa: F401

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_instance: BaseTranslator | None = None


def build_translator(name: str | None = None) -> BaseTranslator:
    name = (name or config.TRANSLATOR or "google").strip().lower()
    if name in ("mock", "none", "off", "debug"):
        from .mock import MockTranslator

        return MockTranslator()
    if name == "google":
        from .google import GoogleTranslatorBackend

        return GoogleTranslatorBackend()
    if name == "youdao":
        from .youdao import YoudaoTranslatorBackend

        return YoudaoTranslatorBackend()
    if name in ("deepl", "deep-l"):
        from .deepl import DeepLTranslatorBackend

        return DeepLTranslatorBackend()
    raise ValueError(f"未知的翻译引擎：{name}")


def get_translator(name: str | None = None) -> BaseTranslator:
    global _instance
    if name is not None:
        return build_translator(name)
    if _instance is None:
        with _lock:
            if _instance is None:
                try:
                    _instance = build_translator()
                except Exception as exc:  # 配置缺失时退回 Google / mock，保证服务可用
                    logger.warning("初始化翻译引擎失败(%s)，回退到 google", exc)
                    try:
                        _instance = build_translator("google")
                    except Exception:
                        logger.warning("Google 后端不可用，回退到 mock")
                        _instance = build_translator("mock")
    return _instance
