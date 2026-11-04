"""Официальный DeepL API (бесплатный тариф: ключ оканчивается на «:fx», 500 000 символов в месяц)."""
from __future__ import annotations

import requests

from . import USER_AGENT, QuotaError, TranslateError


def _endpoint(key: str) -> str:
    host = "api-free.deepl.com" if key.strip().endswith(":fx") else "api.deepl.com"
    return f"https://{host}/v2/translate"


def translate(texts: list[str], key: str, context: str | None = None, xml: bool = False,
              timeout: float = 15.0, source: str = "en", target: str = "ru") -> list[str]:
    body: dict = {"text": texts, "source_lang": source.upper(),
                  "target_lang": "EN-US" if target == "en" else target.upper()}
    if context:
        body["context"] = context
    if xml:
        body["tag_handling"] = "xml"
    try:
        r = requests.post(_endpoint(key), json=body, timeout=timeout,
                          headers={"Authorization": f"DeepL-Auth-Key {key.strip()}", "User-Agent": USER_AGENT})
    except requests.RequestException as e:
        raise TranslateError(f"DeepL недоступен: {e}") from e
    if r.status_code == 403:
        raise TranslateError("DeepL: неверный ключ API (проверь в настройках)")
    if r.status_code == 456:
        raise QuotaError("DeepL: месячный лимит бесплатного тарифа исчерпан")
    if r.status_code == 429:
        raise TranslateError("DeepL: слишком много запросов, попробуй через пару секунд")
    if r.status_code != 200:
        raise TranslateError(f"DeepL: ошибка {r.status_code}")
    return parse(r.json())


def parse(data: dict) -> list[str]:
    return [t.get("text", "") for t in data.get("translations", [])]


def usage(key: str, timeout: float = 10.0) -> tuple[int, int]:
    """Сколько символов израсходовано и каков лимит в этом месяце."""
    url = _endpoint(key).replace("/translate", "/usage")
    r = requests.get(url, headers={"Authorization": f"DeepL-Auth-Key {key.strip()}", "User-Agent": USER_AGENT},
                     timeout=timeout)
    if r.status_code != 200:
        raise TranslateError("DeepL: неверный ключ API" if r.status_code == 403 else f"DeepL: ошибка {r.status_code}")
    d = r.json()
    return int(d.get("character_count", 0)), int(d.get("character_limit", 0))
