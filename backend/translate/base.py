"""翻译引擎接口。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor


class BaseTranslator:
    name = "base"
    # 翻译失败的行数，处理完后由 pipeline 读出并返回给前端
    failure_count = 0

    def translate(self, texts: list[str], src: str, tgt: str) -> list[str]:
        raise NotImplementedError

    # ---- 工具 ----
    @staticmethod
    def _parallel(items: list[str], fn, workers: int = 4) -> list[str]:
        if not items:
            return []
        if len(items) == 1:
            return [fn(items[0])]
        with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
            return list(pool.map(fn, items))
