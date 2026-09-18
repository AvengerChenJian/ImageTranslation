"""DeepL 翻译后端（https://www.deepl.com/pro-api，需 auth key，支持一次多段）。"""
from __future__ import annotations

import logging

import httpx

from .. import config
from ..languages import service_code
from .base import BaseTranslator

logger = logging.getLogger(__name__)


class DeepLTranslatorBackend(BaseTranslator):
    name = "deepl"

    def __init__(self, auth_key: str | None = None) -> None:
        self.auth_key = auth_key or config.DEEPL_AUTH_KEY
        if not self.auth_key:
            raise RuntimeError("未配置 DEEPL_AUTH_KEY")
        self.base = "https://api-free.deepl.com" if config.DEEPL_FREE else "https://api.deepl.com"
        self.client = httpx.Client(timeout=30)

    def translate(self, texts: list[str], src: str, tgt: str) -> list[str]:
        self.failure_count = 0  # 每次调用重新计数（引擎是进程内单例）
        target = service_code(tgt, "deepl")
        if not target:
            logger.warning("DeepL 不支持目标语言 %s，保留原文", tgt)
            return list(texts)
        payload = [("auth_key", self.auth_key), ("target_lang", target)]
        if src and src != "auto":
            source = service_code(src, "deepl")
            if source:
                payload.append(("source_lang", source))
        real = [t if t.strip() else " " for t in texts]
        for t in real:
            payload.append(("text", t))

        try:
            resp = self.client.post(f"{self.base}/v2/translate", data=payload)
            resp.raise_for_status()
            trans = resp.json().get("translations", [])
            if len(trans) == len(texts):
                return [t.get("text", o) for t, o in zip(trans, texts)]
            logger.warning("DeepL 返回条数不匹配")
        except Exception as exc:
            logger.warning("DeepL 翻译失败：%s", exc)
        self.failure_count += len(texts)
        return list(texts)
