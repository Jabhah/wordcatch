"""Сборка перевода из источников + кеш SQLite. Все методы блокирующие — вызывать из фоновых потоков."""
from __future__ import annotations

import html
import json
import re
import sqlite3
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

import simplemma

from .. import irregular
from ..config import Config, app_dir
from ..layout import is_russian
from . import TranslateError, deepl, mymemory, tatoeba, wiktionary
from .wiktionary import Sense


def strip_stress(text: str) -> str:
    """Убирает знаки ударения из русских слов Wiktionary: «походи́ть» -> «походить»."""
    nfd = unicodedata.normalize("NFD", text)
    return unicodedata.normalize("NFC", nfd.replace("́", "").replace("̀", ""))


def direction(text: str) -> tuple[str, str]:
    """Куда переводить: русский текст — на английский, всё остальное — на русский."""
    return ("ru", "en") if is_russian(text) else ("en", "ru")


@dataclass
class WordInfo:
    surface: str                       # как слово написано на экране
    lemma: str                         # базовая форма
    ipa: str = ""
    form_kind: str = ""
    senses: list[Sense] = field(default_factory=list)
    verbs: list[irregular.Verb] = field(default_factory=list)
    alone: str = ""                    # машинный перевод слова без контекста (если словаря мало)
    errors: list[str] = field(default_factory=list)
    lang: str = "en"                   # язык слова на экране: en (перевод на русский) или ru (на английский)

    def chips(self) -> list[str]:
        """Плоский список уникальных переводов в порядке значений."""
        out: list[str] = []
        seen = set()
        for s in self.senses:
            for t in s.terms:
                key = strip_stress(t).lower()
                if key not in seen:
                    seen.add(key)
                    out.append(t)
        if self.alone and strip_stress(self.alone).lower() not in seen and len(out) < 2:
            out.insert(0, self.alone)
        return out


@dataclass
class ContextTranslation:
    text: str
    hl: tuple[int, int] | None = None  # где в переводе стоит слово
    contextual: str = ""               # как слово перевелось в этом тексте
    engine: str = ""


class Cache:
    def __init__(self, path=None):
        self._path = str(path or app_dir() / "cache.db")
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT NOT NULL, ts REAL NOT NULL)")

    def _conn(self):
        return sqlite3.connect(self._path, timeout=5)

    def get(self, key: str):
        with self._lock, self._conn() as c:
            row = c.execute("SELECT v FROM cache WHERE k = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO cache (k, v, ts) VALUES (?, ?, ?)",
                      (key, json.dumps(value, ensure_ascii=False), time.time()))


_TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё]+")


def _stem(word: str) -> str:
    w = strip_stress(word).lower()
    if len(w) <= 4:
        return w
    return w[: max(4, len(w) - 2)]


def find_highlight(text: str, candidates: list[str]) -> tuple[int, int] | None:
    """Ищет в русском переводе слово, похожее на одно из словарных значений (по основе)."""
    stems = []
    for c in candidates:
        first = _TOKEN.findall(strip_stress(c))
        if first:
            # для «быть похожим на» берём самое длинное слово
            stems.append(_stem(max(first, key=len)))
    stems = sorted({s for s in stems if len(s) >= 3}, key=len, reverse=True)
    for m in _TOKEN.finditer(text):
        tok = m.group(0).lower().replace("ё", "е")
        for s in stems:
            if tok.startswith(s.replace("ё", "е")):
                return m.start(), m.end()
    return None


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def parse_tagged(result: str) -> ContextTranslation:
    """Разбирает ответ DeepL вида «Он <w>пошёл</w> домой»."""
    m = re.search(r"<w>(.*?)</w>", result, re.S)
    if not m:
        return ContextTranslation(html.unescape(re.sub(r"</?w>", "", result)))
    before = html.unescape(result[: m.start()])
    inside = html.unescape(m.group(1))
    after = html.unescape(re.sub(r"</?w>", "", result[m.end():]))
    return ContextTranslation(before + inside + after, (len(before), len(before) + len(inside)), inside.strip())


class Translator:
    def __init__(self, cfg: Config, cache: Cache | None = None):
        self.cfg = cfg
        self.cache = cache or Cache()
        self.pool = ThreadPoolExecutor(max_workers=4)

    # ---------- текст ----------
    @property
    def engine(self) -> str:
        return "DeepL" if self.cfg.deepl_key.strip() else "MyMemory"

    def texts(self, texts: list[str]) -> list[str]:
        """Перевод списка текстов (абзацев): английский -> русский, русский -> английский.
        Пустые строки возвращаются как есть."""
        engine = self.engine
        out: list[str | None] = []
        missing: dict[tuple[str, str], list[int]] = {}
        for i, t in enumerate(texts):
            src, dst = direction(t)
            hit = self.cache.get(f"text:{engine}:{src}{dst}:{t}") if t.strip() else ""
            out.append(hit)
            if hit is None:
                missing.setdefault((src, dst), []).append(i)
        for (src, dst), idx in missing.items():
            batch = [texts[i] for i in idx]
            if engine == "DeepL":
                res: list[str] = []
                for k in range(0, len(batch), 40):
                    res.extend(deepl.translate(batch[k:k + 40], self.cfg.deepl_key, source=src, target=dst))
            else:
                res = list(self.pool.map(
                    lambda s, a=src, b=dst: mymemory.translate(s, self.cfg.mymemory_email, source=a, target=b),
                    batch))
            for i, r in zip(idx, res):
                out[i] = r
                self.cache.put(f"text:{engine}:{src}{dst}:{texts[i]}", r)
        return [o or "" for o in out]

    def text(self, text: str) -> str:
        return self.texts([text])[0]

    def context(self, paragraph: str, start: int, end: int) -> ContextTranslation:
        """Перевод абзаца; DeepL дополнительно показывает, как перевелось слово (через XML-теги).
        Направление выбирается по самому слову: русское слово — перевод на английский."""
        engine = self.engine
        src, dst = direction(paragraph[start:end])
        key = f"ctx:{engine}:{src}{dst}:{start}:{end}:{paragraph}"
        hit = self.cache.get(key)
        if hit:
            ct = ContextTranslation(**hit)
            ct.hl = tuple(ct.hl) if ct.hl else None
            return ct
        if engine == "DeepL":
            tagged = _xml_escape(paragraph[:start]) + "<w>" + _xml_escape(paragraph[start:end]) + "</w>" + \
                _xml_escape(paragraph[end:])
            ct = parse_tagged(deepl.translate([tagged], self.cfg.deepl_key, xml=True, source=src, target=dst)[0])
        else:
            ct = ContextTranslation(mymemory.translate(paragraph, self.cfg.mymemory_email, source=src, target=dst))
        ct.engine = engine
        self.cache.put(key, asdict(ct))
        return ct

    # ---------- словарь ----------
    def _wikt(self, word: str) -> wiktionary.Entry | None:
        key = f"wikt:{word}"
        hit = self.cache.get(key)
        if hit is not None:
            if hit == {}:
                return None
            hit["senses"] = [Sense(**s) for s in hit["senses"]]
            return wiktionary.Entry(**hit)
        entry = wiktionary.lookup(word)
        if entry is None or not entry.incomplete:
            self.cache.put(key, asdict(entry) if entry else {})
        return entry

    def _wikt_safe(self, word: str, errors: list[str]) -> wiktionary.Entry | None:
        try:
            return self._wikt(word)
        except TranslateError as e:
            errors.append(str(e))
            return None

    def _wikt_ru(self, word: str, errors: list[str]) -> wiktionary.Entry | None:
        key = f"wiktru:{word}"
        hit = self.cache.get(key)
        if hit is not None:
            if hit == {}:
                return None
            hit["senses"] = [Sense(**s) for s in hit["senses"]]
            return wiktionary.Entry(**hit)
        try:
            entry = wiktionary.lookup_ru(word)
        except TranslateError as e:
            errors.append(str(e))
            return None
        self.cache.put(key, asdict(entry) if entry else {})
        return entry

    def _dictionary_ru(self, word: str) -> WordInfo:
        """Русское слово: английские значения из русских статей Wiktionary + перевод DeepL/MyMemory."""
        lw = word.lower()
        info = WordInfo(surface=word, lemma=lw, lang="ru")
        entry = self._wikt_ru(lw, info.errors)
        if entry is None:
            guess = simplemma.lemmatize(lw, lang="ru").lower()
            if guess != lw:
                entry = self._wikt_ru(guess, info.errors)
                info.lemma = guess
        if entry:
            if entry.lemma:
                info.lemma = entry.lemma.lower()
            info.senses.extend(entry.senses)
        try:
            alone = self.text(info.lemma).strip().strip(".")
            info.alone = "" if is_russian(alone) else alone
        except TranslateError as e:
            info.errors.append(str(e))
        return info

    def dictionary(self, word: str) -> WordInfo:
        if is_russian(word):
            return self._dictionary_ru(word)
        lw = word.lower()
        info = WordInfo(surface=word, lemma=lw)
        info.verbs = irregular.lookup(lw)
        guess = info.verbs[0].base if info.verbs else simplemma.lemmatize(lw, lang="en").lower()
        # Статью самого слова и вероятной базовой формы грузим параллельно.
        fut_lemma = self.pool.submit(self._wikt_safe, guess, info.errors) if guess != lw else None
        entry = self._wikt_safe(lw, info.errors)
        if entry is None and word != lw:
            entry = self._wikt_safe(word, info.errors)  # имена собственные: «Paris»
        lemma_entry = fut_lemma.result() if fut_lemma else None
        if info.verbs:
            info.lemma = info.verbs[0].base
        elif entry and entry.lemma and " " not in entry.lemma:
            info.lemma = entry.lemma.lower()
        else:
            info.lemma = guess
        if info.lemma != lw and info.lemma != guess:
            lemma_entry = self._wikt_safe(info.lemma, info.errors)
        if entry:
            info.ipa = entry.ipa
            info.form_kind = entry.form_kind
            info.senses.extend(entry.senses)
        if info.lemma != lw and lemma_entry:
            info.ipa = info.ipa or lemma_entry.ipa
            info.senses.extend(lemma_entry.senses)
        # Для форм глагола (went, struggling) сначала значения глагола, для plural — существительного.
        verbish = bool(info.verbs) or info.form_kind in ("V2", "V3", "V2/V3", "ing", "3sg")
        first_pos = "гл." if verbish else ("сущ." if info.form_kind == "plural" else "")
        if first_pos:
            info.senses.sort(key=lambda s: s.pos != first_pos)
        if len(info.senses) < 1:
            try:
                alone = self.text(info.lemma).strip().strip(".")
                info.alone = "" if alone.lower() in (lw, info.lemma) else alone
            except TranslateError as e:
                info.errors.append(str(e))
        return info

    def examples(self, word: str) -> list[tuple[str, str]]:
        src, dst = ("rus", "eng") if is_russian(word) else ("eng", "rus")
        key = f"tatoeba:{src}:{word.lower()}"
        hit = self.cache.get(key)
        if hit is not None:
            return [tuple(x) for x in hit]
        res = tatoeba.examples(word.lower(), source=src, target=dst)
        self.cache.put(key, res)
        return res

    def form_translation(self, form: str) -> str:
        """Перевод отдельной формы глагола (went -> пошёл) для карточек V2/V3.
        Только через DeepL: MyMemory на отдельных формах выдаёт мусор, тогда в карточке будет подпись
        «прошедшее время от …»."""
        if self.engine != "DeepL":
            return ""
        try:
            tr = self.text(form).strip().strip(".")
        except TranslateError:
            return ""
        return "" if tr.lower() == form.lower() else tr
