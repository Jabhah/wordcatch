"""Карточки для плагина Obsidian Spaced Repetition: «front:::back» (карточка в обе стороны)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .irregular import Verb


def find_vault(configured: str = "") -> Path | None:
    if configured:
        p = Path(configured)
        return p if p.is_dir() else None
    cfg = Path(os.environ.get("APPDATA", "")) / "obsidian" / "obsidian.json"
    try:
        vaults = json.loads(cfg.read_text(encoding="utf-8")).get("vaults", {})
    except (OSError, ValueError):
        return None
    items = sorted(vaults.values(), key=lambda v: (not v.get("open"), -v.get("ts", 0)))
    for v in items:
        p = Path(v.get("path", ""))
        if p.is_dir():
            return p
    return None


_CARD = re.compile(r"^(.+?):{2,3}(.+)$")


def _sanitize(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace(":::", ":").replace("::", ":")


def card_key(front: str) -> str:
    return re.sub(r"\s+", " ", front).strip().lower()


def existing_fronts(folder: Path) -> set[str]:
    """Левые части всех карточек в папке (и подпапках), без учёта регистра."""
    fronts: set[str] = set()
    if not folder.is_dir():
        return fronts
    for md in folder.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if line.startswith("<!--") or "::" not in line:
                continue
            m = _CARD.match(line.strip())
            if m:
                fronts.add(card_key(m.group(1)))
    return fronts


def add_cards(path: Path, cards: list[tuple[str, str]], title: str, tag: str,
              dedup_folder: Path | None = None) -> list[str]:
    """Дописывает карточки в файл (создаёт его с заголовком и тегом). Возвращает добавленные front."""
    known = existing_fronts(dedup_folder or path.parent)
    if path.exists():
        known |= existing_fronts_in_file(path)
    new = []
    for front, back in cards:
        front, back = _sanitize(front), _sanitize(back)
        if not front or not back or card_key(front) in known:
            continue
        known.add(card_key(front))
        new.append((front, back))
    if not new:
        return []
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else f"# {title}\n{tag}\n"
    if not text.endswith("\n"):
        text += "\n"
    for front, back in new:
        text += f"\n{front}:::{back}\n"
    tmp = path.with_name(path.name + ".wordcatch.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return [f for f, _ in new]


def existing_fronts_in_file(path: Path) -> set[str]:
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _CARD.match(line.strip())
        if m and not line.startswith("<!--"):
            out.add(card_key(m.group(1)))
    return out


def irregular_cards(verb: Verb, v1_back: str, v2_tr: str, v3_tr: str, mode: str = "three") -> list[tuple[str, str]]:
    """Карточки для неправильного глагола.
    three: go:::идти (V1: go — went — gone) / went:::пошёл (V2 от go) / gone:::ушедший (V3 от go)
    one:   go — went — gone:::идти — пошёл — ушедший"""
    first_ru = verb.ru.split(",")[0].strip()
    v2 = v2_tr or f"прошедшее время от «{first_ru}»"
    v3 = v3_tr or f"причастие от «{first_ru}»"
    if mode == "one":
        return [(verb.forms_text, f"{v1_back} — {v2} — {v3}")]
    cards = [(verb.base, f"{v1_back} (V1: {verb.forms_text})")]
    used = {verb.base}
    for forms, tr, kind in ((verb.past, v2, "V2"), (verb.participle, v3, "V3")):
        fresh = [f for f in forms if f not in used]
        if not fresh:
            continue
        used.update(fresh)
        cards.append(("/".join(fresh), f"{tr} ({kind} от {verb.base})"))
    return cards
