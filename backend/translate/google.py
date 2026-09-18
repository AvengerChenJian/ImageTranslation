"""Google 翻译后端：直连 gtx 接口，无需 key。

自带连接/读取超时与有限重试：网络不通时快速失败并保留原文，
避免整条链路卡住导致前端看起来"没反应"。
"""
from __future__ import annotations

import logging
import time

import httpx

from ..languages import service_code
from .base import BaseTranslator

logger = logging.getLogger(__name__)


class GoogleTranslatorBackend(BaseTranslator):
    name = "google"

    API_URL = "https://translate.googleapis.com/translate_a/single"
    TIMEOUT = 8.0
    RETRIES = 1

    def __init__(self, timeout: float | None = None) -> None:
        self.timeout = timeout or self.TIMEOUT
        self.client = httpx.Client(
            timeout=self.timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                )
            },
        )

    @staticmethod
    def _extract(data) -> str:
        """把 gtx 返回的嵌套数组拼成完整译文。"""
        try:
            segments = data[0] or []
        except (TypeError, IndexError):
            return ""
        parts = []
        for seg in segments:
            if isinstance(seg, (list, tuple)) and seg and isinstance(seg[0], str):
                parts.append(seg[0])
            elif isinstance(seg, str):
                parts.append(seg)
        return "".join(parts).strip()

    def translate(self, texts: list[str], src: str, tgt: str) -> list[str]:
        self.failure_count = 0  # 每次调用重新计数（引擎是进程内单例）
        target = service_code(tgt, "google") or "en"
        source = (service_code(src, "google") if src and src != "auto" else None) or "auto"

        def one(text: str) -> str:
            if not text.strip():
                return text
            last_err: Exception | None = None
            for attempt in range(self.RETRIES + 1):
                try:
                    resp = self.client.post(
                        self.API_URL,
                        params={"client": "gtx", "sl": source, "tl": target, "dt": "t"},
                        data={"q": text},
                    )
                    resp.raise_for_status()
                    result = self._extract(resp.json())
                    if result:
                        return result
                except Exception as exc:
                    last_err = exc
                    time.sleep(0.3 * (attempt + 1))
            logger.warning("Google 翻译失败(%s)，保留原文：%s", last_err, text[:30])
            self.failure_count += 1
            return text

        return self._parallel(texts, one, workers=2)
