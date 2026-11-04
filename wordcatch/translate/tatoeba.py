"""Tatoeba: англо-русские пары предложений (примеры употребления), лицензия CC BY 2.0 FR."""
from __future__ import annotations

import requests

from . import USER_AGENT, TranslateError

API = "https://tatoeba.org/en/api_v0/search"


def parse(data: dict, limit: int = 3, target: str = "rus") -> list[tuple[str, str]]:
    """Пары (предложение, перевод) — в порядке «язык поиска, язык перевода»."""
    out: list[tuple[str, str]] = []
    for s in data.get("results", []):
        tr = next((t.get("text", "") for grp in s.get("translations", []) for t in grp if t.get("lang") == target), "")
        if s.get("text") and tr:
            out.append((s["text"], tr))
        if len(out) >= limit:
            break
    return out


def examples(word: str, limit: int = 3, timeout: float = 8.0, source: str = "eng",
             target: str = "rus") -> list[tuple[str, str]]:
    try:
        r = requests.get(API, params={"from": source, "to": target, "query": f"={word}", "orphans": "no",
                                      "unapproved": "no", "sort": "relevance"},
                         headers={"User-Agent": USER_AGENT}, timeout=timeout)
        r.raise_for_status()
        return parse(r.json(), limit, target)
    except (requests.RequestException, ValueError) as e:
        raise TranslateError(f"Tatoeba недоступна: {e}") from e
