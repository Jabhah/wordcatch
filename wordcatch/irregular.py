"""Неправильные глаголы: поиск по любой из трёх форм."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "irregular_verbs.json"


@dataclass(frozen=True)
class Verb:
    base: str
    past: tuple[str, ...]
    participle: tuple[str, ...]
    ru: str

    @property
    def forms_text(self) -> str:
        return f"{self.base} — {'/'.join(self.past)} — {'/'.join(self.participle)}"

    def kinds_of(self, word: str) -> list[str]:
        """Какой формой является слово: V1, V2, V3 (может быть несколько: cut, put)."""
        w = word.lower()
        kinds = []
        if w == self.base:
            kinds.append("V1")
        if w in self.past:
            kinds.append("V2")
        if w in self.participle:
            kinds.append("V3")
        return kinds


@lru_cache(maxsize=1)
def _index() -> dict[str, list[Verb]]:
    idx: dict[str, list[Verb]] = {}
    for base, past, pp, ru in json.loads(DATA.read_text(encoding="utf-8")):
        v = Verb(base, tuple(past.split("/")), tuple(pp.split("/")), ru)
        for form in {base, *v.past, *v.participle}:
            idx.setdefault(form, []).append(v)
    return idx


def lookup(word: str) -> list[Verb]:
    """Все неправильные глаголы, у которых есть такая форма (saw -> see и saw «пилить»)."""
    w = word.lower().strip()
    # «saw»: сначала see (V2), потом saw «пилить» (V1)
    return sorted(_index().get(w, []), key=lambda v: v.base == w)


def all_verbs() -> list[Verb]:
    seen, out = set(), []
    for verbs in _index().values():
        for v in verbs:
            if v.base not in seen:
                seen.add(v.base)
                out.append(v)
    return sorted(out, key=lambda v: v.base)
