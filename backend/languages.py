"""语言代码注册表：前端 -> 内部 code -> 各翻译服务/字体 的映射。"""
from __future__ import annotations

# code: 本项目内部统一代码
# font: 重绘时使用的字体族
# google: deep-translator(Google) 代码；youdao: 有道代码；deepl: DeepL 代码（None=不支持）
LANGUAGES: list[dict] = [
    {"code": "auto", "name": "自动检测", "font": "default", "google": None, "youdao": None, "deepl": None},
    {"code": "zh", "name": "中文(简体)", "font": "zh", "google": "zh-CN", "youdao": "zh-CHS", "deepl": "ZH"},
    {"code": "zh-TW", "name": "中文(繁体)", "font": "zh-Hant", "google": "zh-TW", "youdao": "zh-CHT", "deepl": "ZH-HANT"},
    {"code": "en", "name": "英语", "font": "default", "google": "en", "youdao": "en", "deepl": "EN-US"},
    {"code": "ja", "name": "日语", "font": "ja", "google": "ja", "youdao": "ja", "deepl": "JA"},
    {"code": "ko", "name": "韩语", "font": "ko", "google": "ko", "youdao": "ko", "deepl": "KO"},
    {"code": "fr", "name": "法语", "font": "default", "google": "fr", "youdao": "fr", "deepl": "FR"},
    {"code": "de", "name": "德语", "font": "default", "google": "de", "youdao": "de", "deepl": "DE"},
    {"code": "es", "name": "西班牙语", "font": "default", "google": "es", "youdao": "es", "deepl": "ES"},
    {"code": "ru", "name": "俄语", "font": "default", "google": "ru", "youdao": "ru", "deepl": "RU"},
    {"code": "pt", "name": "葡萄牙语", "font": "default", "google": "pt", "youdao": "pt", "deepl": "PT-BR"},
    {"code": "it", "name": "意大利语", "font": "default", "google": "it", "youdao": "it", "deepl": "IT"},
    {"code": "ar", "name": "阿拉伯语", "font": "ar", "google": "ar", "youdao": "ar", "deepl": "AR"},
    {"code": "th", "name": "泰语", "font": "th", "google": "th", "youdao": "th", "deepl": None},
    {"code": "vi", "name": "越南语", "font": "default", "google": "vi", "youdao": "vi", "deepl": None},
    {"code": "id", "name": "印尼语", "font": "default", "google": "id", "youdao": "id", "deepl": "ID"},
    {"code": "tr", "name": "土耳其语", "font": "default", "google": "tr", "youdao": "tr", "deepl": "TR"},
    {"code": "nl", "name": "荷兰语", "font": "default", "google": "nl", "youdao": "nl", "deepl": "NL"},
    {"code": "pl", "name": "波兰语", "font": "default", "google": "pl", "youdao": "pl", "deepl": "PL"},
]

_BY_CODE = {item["code"]: item for item in LANGUAGES}


def lang_meta(code: str) -> dict:
    return _BY_CODE.get(code, _BY_CODE["en"])


def service_code(code: str, service: str) -> str | None:
    """取某翻译服务对应的语言代码，不支持时返回 None。"""
    return lang_meta(code).get(service)


def font_family(code: str) -> str:
    return lang_meta(code).get("font") or "default"


def public_languages() -> list[dict]:
    """给前端下拉框用。"""
    return [{"code": i["code"], "name": i["name"]} for i in LANGUAGES if i["code"] != "auto"]
