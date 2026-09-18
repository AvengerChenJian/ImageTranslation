"""有道翻译后端（https://ai.youdao.com，需 appKey/appSecret）。"""
from __future__ import annotations

import hashlib
import logging
import time
import uuid

import httpx

from .. import config
from ..languages import service_code
from .base import BaseTranslator

logger = logging.getLogger(__name__)
API_URL = "https://openapi.youdao.com/api"
# 411=访问频率受限，值得重试；其余（108 无效应用ID、202 签名错误、401 余额不足等）无需重试
RETRY_CODES = {"411"}


class YoudaoTranslatorBackend(BaseTranslator):
    name = "youdao"

    def __init__(self, app_key: str | None = None, app_secret: str | None = None) -> None:
        self.app_key = app_key or config.YOUDAO_APP_KEY
        self.app_secret = app_secret or config.YOUDAO_APP_SECRET
        if not (self.app_key and self.app_secret):
            raise RuntimeError("未配置 YOUDAO_APP_KEY / YOUDAO_APP_SECRET")
        self.client = httpx.Client(timeout=15)

    def _sign(self, q: str, salt: str, curtime: str) -> str:
        raw = self.app_key + self._input(q) + salt + curtime + self.app_secret
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _input(q: str) -> str:
        if len(q) <= 20:
            return q
        return q[:10] + str(len(q)) + q[-10:]

    def translate(self, texts: list[str], src: str, tgt: str) -> list[str]:
        self.failure_count = 0  # 每次调用重新计数（引擎是进程内单例）
        to = service_code(tgt, "youdao") or "en"
        frm = service_code(src, "youdao") or "auto" if src != "auto" else "auto"

        def one(text: str) -> str:
            if not text.strip():
                return text
            for attempt in range(5):
                curtime = str(int(time.time()))
                salt = uuid.uuid4().hex
                data = {
                    "q": text,
                    "from": frm,
                    "to": to,
                    "appKey": self.app_key,
                    "salt": salt,
                    "sign": self._sign(text, salt, curtime),
                    "signType": "v3",
                    "curtime": curtime,
                }
                try:
                    resp = self.client.post(API_URL, data=data)
                    resp.raise_for_status()
                    result = resp.json()
                    code = str(result.get("errorCode"))
                    if code == "0":
                        return "".join(result.get("translation", [])) or text
                    if code in RETRY_CODES and attempt < 4:
                        time.sleep(min(4.0, 1.0 * (attempt + 1)))
                        continue
                    logger.warning("有道返回错误码 %s：%s", code, text[:30])
                    break
                except Exception as exc:
                    logger.warning("有道翻译失败(%s)：%s", exc, text[:30])
                    time.sleep(min(4.0, 0.8 * (attempt + 1)))
            self.failure_count += 1
            return text

        # 有道个人版 QPS 较低，并发过高会触发 411 限流
        return self._parallel(texts, one, workers=2)
