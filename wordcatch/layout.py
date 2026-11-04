"""Разметка результата OCR: слово под курсором, абзацы, склейка переносов."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .ocr import Line, Rect, Word

_EDGE_PUNCT = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)
_LETTER = re.compile(r"[A-Za-zА-Яа-яЁё]")  # слово должно содержать хоть одну букву (англ. или рус.)


def clean_word(text: str) -> str:
    """Убирает знаки препинания по краям: «(resemble,» -> «resemble». Апостроф внутри сохраняется."""
    text = text.replace("’", "'").replace("‘", "'")
    text = _EDGE_PUNCT.sub("", text)
    if text.lower().endswith("'s"):
        text = text[:-2]
    return text


@dataclass
class Block:
    lines: list[Line]

    @property
    def rect(self) -> Rect:
        r = self.lines[0].rect
        for ln in self.lines[1:]:
            r = r.united(ln.rect)
        return r

    @property
    def text(self) -> str:
        return join_lines([ln.text for ln in self.lines])


def join_lines(texts: list[str]) -> str:
    """Склеивает строки абзаца, убирая переносы: «ques-» + «tion» -> «question»."""
    out = ""
    for t in texts:
        t = t.strip()
        if not t:
            continue
        if out.endswith("-") and len(out) > 1 and out[-2].isalpha() and t[:1].islower():
            out = out[:-1] + t
        else:
            out = f"{out} {t}" if out else t
    return out


@dataclass
class Hit:
    word: str            # очищенное слово (с учётом склейки переноса)
    raw: Word            # слово OCR, на которое навели
    line_index: int
    word_index: int


def word_at(lines: list[Line], x: float, y: float, tol: float = 4.0) -> Hit | None:
    """Находит слово, в прямоугольник которого попадает точка (с допуском tol px)."""
    best: tuple[float, int, int] | None = None
    for li, ln in enumerate(lines):
        lr = ln.rect
        if not lr.contains(x, y, tol):
            continue
        for wi, w in enumerate(ln.words):
            if w.rect.contains(x, y, tol):
                cx = w.rect.x + w.rect.w / 2
                dist = abs(cx - x)
                if best is None or dist < best[0]:
                    best = (dist, li, wi)
    if best is None:
        return None
    _, li, wi = best
    ln = lines[li]
    raw = ln.words[wi]
    text = raw.text
    # Перенос: «ques-» в конце строки + «tion» в начале следующей.
    if wi == len(ln.words) - 1 and text.endswith("-") and li + 1 < len(lines) and lines[li + 1].words:
        nxt = lines[li + 1].words[0].text
        if nxt[:1].islower():
            text = text[:-1] + nxt
    elif wi == 0 and li > 0 and lines[li - 1].words:
        prev = lines[li - 1].words[-1].text
        if prev.endswith("-") and len(prev) > 1 and text[:1].islower() and _same_block(lines[li - 1], ln):
            text = prev[:-1] + text
    word = clean_word(text)
    if not word or not _LETTER.search(word):
        return None
    return Hit(word, raw, li, wi)


def _same_block(a: Line, b: Line) -> bool:
    ra, rb = a.rect, b.rect
    h = max(min(ra.h, rb.h), 1.0)
    gap = rb.y - ra.bottom
    if gap > 0.9 * h or gap < -0.6 * h:
        return False
    if max(ra.h, rb.h) / h > 1.6:
        return False
    overlap = min(ra.right, rb.right) - max(ra.x, rb.x)
    return overlap > 0 or abs(ra.x - rb.x) < 2 * h


def group_blocks(lines: list[Line]) -> list[Block]:
    """Объединяет строки в абзацы: близко по вертикали, похожая высота, перекрываются по горизонтали."""
    order = sorted(range(len(lines)), key=lambda i: (lines[i].rect.y, lines[i].rect.x))
    blocks: list[Block] = []
    for i in order:
        ln = lines[i]
        target = None
        for b in reversed(blocks):
            if _same_block(b.lines[-1], ln):
                target = b
                break
        if target is not None:
            target.lines.append(ln)
        else:
            blocks.append(Block([ln]))
    return blocks


@dataclass
class Context:
    """Абзац, где стоит слово, и позиция слова в его тексте."""
    text: str
    start: int
    end: int
    block: Block


def context_of(lines: list[Line], hit: Hit) -> Context:
    target = lines[hit.line_index]
    block = next((b for b in group_blocks(lines) if any(ln is target for ln in b.lines)), Block([target]))
    # Собираем текст абзаца построчно, запоминая, где окажется нужное слово.
    out = ""
    start = end = -1
    for ln in block.lines:
        piece = ln.text.strip()
        joined_hyphen = out.endswith("-") and len(out) > 1 and out[-2].isalpha() and piece[:1].islower()
        if joined_hyphen:
            out = out[:-1]
        elif out:
            out += " "
        base = len(out)
        if ln is target:
            pos = 0
            for wi, w in enumerate(ln.words):
                if wi == hit.word_index:
                    start = base + pos
                    end = start + len(w.text)
                    break
                pos += len(w.text) + 1
        out += piece
    if start < 0:
        idx = out.lower().find(hit.word.lower())
        start, end = (idx, idx + len(hit.word)) if idx >= 0 else (0, 0)
    # Сужаем до очищенного слова (без запятых и скобок; при переносе дефис уже убран из текста).
    low, w = out.lower(), hit.word.lower()
    k = low.find(w, max(0, start - len(w)), end + len(w))
    if w and k >= 0:
        start, end = k, k + len(w)
    return Context(out, start, end, block)


def trim_context(text: str, start: int, end: int, max_sentences: int = 3) -> tuple[str, int, int, bool]:
    """Обрезает длинный абзац до нескольких предложений вокруг слова.
    Возвращает (текст, новый start, новый end, был ли обрезан)."""
    bounds = [0] + [m.end() for m in re.finditer(r"[.!?…]+[\"')\]]*\s+", text)] + [len(text)]
    bounds = sorted(set(bounds))
    sentences = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
    if len(sentences) <= max_sentences:
        return text, start, end, False
    idx = next((i for i, (a, b) in enumerate(sentences) if a <= start < b), 0)
    lo = max(0, idx - (max_sentences - 1) // 2)
    hi = min(len(sentences), lo + max_sentences)
    lo = max(0, hi - max_sentences)
    a, b = sentences[lo][0], sentences[hi - 1][1]
    return text[a:b].strip(), start - a, end - a, True


# ---------- русский и английский текст ----------
_CYR = re.compile(r"[А-Яа-яЁё]")
_LAT_LETTER = re.compile(r"[A-Za-z]")
# Похожие буквы: OCR иногда пишет английское слово кириллицей («НОМЕ») и наоборот.
_CYR_TO_LAT = str.maketrans("АВЕКМНОРСТХаеорсхуі", "ABEKMHOPCTXaeopcxyi")
_LAT_TO_CYR = str.maketrans("ABEKMHOPCTXaeopcxy", "АВЕКМНОРСТХаеорсху")


def cyrillic_share(text: str) -> float:
    cyr = len(_CYR.findall(text))
    lat = len(_LAT_LETTER.findall(text))
    return cyr / (cyr + lat) if cyr + lat else 0.0


def is_russian(text: str) -> bool:
    return cyrillic_share(text) > 0.5


def fix_mixed_script(word: str) -> str:
    """Слово из смеси кириллицы и латиницы приводит к преобладающему алфавиту."""
    cyr, lat = len(_CYR.findall(word)), len(_LAT_LETTER.findall(word))
    if not cyr or not lat:
        return word
    return word.translate(_LAT_TO_CYR) if cyr >= lat else word.translate(_CYR_TO_LAT)


def _overlap(a: Rect, b: Rect) -> float:
    w = min(a.right, b.right) - max(a.x, b.x)
    h = min(a.bottom, b.bottom) - max(a.y, b.y)
    if w <= 0 or h <= 0:
        return 0.0
    return (w * h) / max(1.0, min(a.w * a.h, b.w * b.h))


def merge_lines(en: list[Line], ru: list[Line]) -> list[Line]:
    """Склеивает результаты английского и русского OCR одного снимка.
    Русские строки (больше половины букв — кириллица) берутся из русского распознавания:
    английский пакет читает кириллицу как «npuBeT». Остальное — из английского, он точнее на латинице."""
    replaced: set[int] = set()
    out: list[Line] = []
    for r in ru:
        if not is_russian(r.text):
            continue
        rr = r.rect
        hits = [i for i, e in enumerate(en) if _overlap(rr, e.rect) > 0.4]
        replaced.update(hits)
        out.append(Line([Word(fix_mixed_script(w.text), w.rect) for w in r.words]))
    out.extend(e for i, e in enumerate(en) if i not in replaced)
    out.sort(key=lambda ln: (ln.rect.y, ln.rect.x))
    return out
