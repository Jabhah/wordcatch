"""MyMemory (translated.net): бесплатно без ключа, 5 000 символов в день (50 000 с e-mail)."""
from __future__ import annotations

import html
import re

import requests

from . import USER_AGENT, QuotaError, TranslateError

API = "https://api.mymemory.translated.net/get"
MAX_BYTES = 480


def _chunks(text: str) -> list[str]:
    """Режет текст по предложениям так, чтобы кусок был не длиннее 480 байт (ограничение сервиса)."""
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    out: list[str] = []
    cur = ""
    for p in parts:
        while len(p.encode("utf-8")) > MAX_BYTES:  # очень длинное предложение — режем по словам
            words, piece = p.split(" "), ""
            while words and len((piece + " " + words[0]).encode("utf-8")) <= MAX_BYTES:
                piece = f"{piece} {words.pop(0)}".strip()
            if not piece:
                piece = words.pop(0)[:200]
            out.append(piece)
            p = " ".join(words)
        cand = f"{cur} {p}".strip()
        if len(cand.encode("utf-8")) <= MAX_BYTES:
            cur = cand
        else:
            if cur:
                out.append(cur)
            cur = p
    if cur:
        out.append(cur)
    return out


def parse(data: dict) -> str:
    status = int(data.get("responseStatus") or 0)
    details = str(data.get("responseDetails") or "")
    if status == 429 or "USED ALL AVAILABLE FREE TRANSLATIONS" in details.upper() or data.get("quotaFinished"):
        raise QuotaError("MyMemory: дневной лимит бесплатных переводов исчерпан. Добавь ключ DeepL в настройках.")
    if status != 200:
        raise TranslateError(f"MyMemory: {details or status}")
    return html.unescape(data.get("responseData", {}).get("translatedText", ""))


def translate(text: str, email: str = "", timeout: float = 15.0, source: str = "en", target: str = "ru") -> str:
    result = []
    for chunk in _chunks(text):
        params = {"q": chunk, "langpair": f"{source}|{target}"}
        if email:
            params["de"] = email
        try:
            r = requests.get(API, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            raise TranslateError(f"MyMemory недоступен: {e}") from e
        result.append(parse(data))
    return " ".join(result)
