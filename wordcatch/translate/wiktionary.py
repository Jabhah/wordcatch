"""Английский Wiktionary: русские переводы по значениям, транскрипция, базовая форма."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import requests

from . import USER_AGENT, TranslateError

API = "https://en.wiktionary.org/w/api.php"
_session = requests.Session()  # keep-alive: повторные запросы заметно быстрее
_session.headers["User-Agent"] = USER_AGENT

POS_RU = {
    "noun": "сущ.", "proper noun": "имя собств.", "verb": "гл.", "adjective": "прил.", "adverb": "нареч.",
    "pronoun": "мест.", "preposition": "предлог", "conjunction": "союз", "interjection": "межд.",
    "determiner": "определитель", "numeral": "числ.", "particle": "частица", "phrase": "фраза",
    "prepositional phrase": "фраза", "idiom": "идиома", "proverb": "пословица", "contraction": "сокращ.",
    "article": "артикль", "prefix": "приставка", "suffix": "суффикс",
}

_HEADER = re.compile(r"^(={3,6})\s*([^=]+?)\s*\1\s*$")
_TRANS_TOP = re.compile(r"^\{\{(?:trans-top(?:-see|-also)?|checktrans-top)\b")
_NESTED = re.compile(r"\{\{[^{}]*\}\}")
_LEMMA_TEMPLATES = {
    "infl of", "inflection of", "past of", "simple past of", "past participle of", "present participle of",
    "third-person singular of", "plural of", "comparative of", "superlative of", "alternative spelling of",
    "alternative form of", "alt form of", "alt sp of", "en-past of", "en-simple past of", "en-ing form of",
    "en-third-person singular of", "en-past participle of", "en-comparative of", "en-superlative of",
    "en-irregular plural of", "ed-form of",
}
_RU_TERM = re.compile(r"\{\{t{1,2}\+?(?:-check|check)?\|ru\|((?:\[\[[^\]]*\]\]|[^{}|])+)([^{}]*)\}\}(\s*\{\{(?:q|qualifier|i)\|([^{}]*)\}\})?")
_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_IPA = re.compile(r"\{\{IPA\|en\|([^|}]+)")
_FORM_OF = re.compile(r"\{\{((?:en-)?[a-z][a-z \-]*?\bof)\|(?:en\|)?([^|}]+)([^{}]*)\}\}")


@dataclass
class Sense:
    pos: str            # часть речи по-русски
    gloss: str          # краткое описание значения (англ.)
    terms: list[str]    # русские переводы (с ударениями)


@dataclass
class Entry:
    word: str
    ipa: str = ""
    senses: list[Sense] = field(default_factory=list)
    lemma: str = ""          # базовая форма, если страница — форма другого слова
    form_kind: str = ""      # V2 / V3 / ing / 3sg / plural / ...
    subpage: bool = False    # переводы вынесены на страницу «слово/translations»
    incomplete: bool = False  # подстраница не загрузилась (сеть/лимит)


def _english_section(wikitext: str) -> str:
    if "==English==" not in wikitext:
        return ""
    sec = wikitext.split("==English==", 1)[1]
    return re.split(r"\n==[^=]", sec, maxsplit=1)[0]


def _clean_term(term: str) -> str:
    term = _LINK.sub(r"\1", term).replace("'''", "").replace("''", "")  # вики-курсив/жирный
    return re.sub(r"\s+", " ", term).strip()


def _form_kind(template: str, params: str) -> str:
    t = template.lower()
    p = params.lower()
    if "past participle" in t or "past|part" in p or "|pp" in p:
        return "V3"
    if "simple past" in t or "spast" in p or t.endswith("past of"):
        return "V2"
    if "ed-form" in p:
        return "V2/V3"
    if "ing" in t or "pres|part" in p or "ing-form" in p:
        return "ing"
    if "third-person" in t or "3|s|pres" in p or "s-verb-form" in p:
        return "3sg"
    if "plural" in t or "|p" in p:
        return "plural"
    if "comparative" in t:
        return "сравн."
    if "superlative" in t:
        return "превосх."
    return ""


def parse(word: str, wikitext: str, english_only: bool = True) -> Entry:
    """Разбирает викитекст страницы (или подстраницы /translations)."""
    entry = Entry(word)
    text = _english_section(wikitext) if english_only else wikitext
    if not text and english_only:
        return entry
    m = _IPA.search(text)
    if m:
        ipa = m.group(1).strip()
        entry.ipa = ipa if ipa.startswith(("/", "[")) else f"/{ipa}/"
    pos = ""
    gloss: str | None = None
    for line in text.splitlines():
        h = _HEADER.match(line)
        if h:
            name = h.group(2).strip().lower()
            if name in POS_RU:
                pos = POS_RU[name]
            continue
        if "see translation subpage" in line:
            entry.subpage = True
        if line.startswith("# ") and not entry.lemma:
            f = _FORM_OF.search(line)
            if f and f.group(1).strip() in _LEMMA_TEMPLATES:
                entry.lemma = _clean_term(f.group(2))
                entry.form_kind = _form_kind(f.group(1), f.group(3))
        stripped = line.strip()
        if _TRANS_TOP.match(stripped):
            inner = stripped[2:stripped.find("}}")] if "}}" in stripped else stripped[2:]
            # вложенные шаблоны внутри описания значения: {{trans-top|to {{w|x}} y}}
            if "{{" in inner:
                end = stripped.rfind("}}", 0, stripped.find("{{multitrans") if "{{multitrans" in stripped else None)
                inner = stripped[2:end]
            while _NESTED.search(inner):
                inner = _NESTED.sub("", inner)
            params = [p for p in inner.split("|")[1:] if "=" not in p]
            gloss = _LINK.sub(r"\1", params[0]).strip() if params else ""
            continue
        if "{{trans-bottom" in line:
            gloss = None
            continue
        if gloss is not None and re.match(r"^\*\s*Russian\s*:", line):
            terms = []
            for tm in _RU_TERM.finditer(line):
                term = _clean_term(tm.group(1))
                qual = (tm.group(4) or "").strip()
                if qual.startswith("+"):
                    term = f"{term} {qual[1:].strip()}"
                if term and term not in terms:
                    terms.append(term)
            if terms:
                entry.senses.append(Sense(pos, gloss, terms))
    return entry


def fetch_wikitext(page: str, timeout: float = 8.0) -> str | None:
    try:
        r = _session.get(API, params={"action": "parse", "page": page, "prop": "wikitext", "format": "json",
                                      "formatversion": 2, "redirects": 1}, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        raise TranslateError(f"Wiktionary недоступен: {e}") from e
    if "error" in data:
        return None
    return data.get("parse", {}).get("wikitext")


def lookup(word: str) -> Entry | None:
    """Загружает статью; если переводы вынесены на подстраницу — подгружает её."""
    wt = fetch_wikitext(word)
    if wt is None:
        return None
    entry = parse(word, wt)
    if entry.subpage:
        try:
            sub = fetch_wikitext(f"{word}/translations")
        except TranslateError:
            entry.incomplete = True  # основная статья есть, подстраница не загрузилась — не кешируем
            return entry
        if sub:
            entry.senses.extend(parse(word, sub, english_only=False).senses)
    return entry


# ---------- русские статьи английского Wiktionary (значения по-английски) ----------
_RU_FORM_OF = re.compile(r"\{\{((?:[a-z][a-z \-]*?\bof)|infl of|inflection of)\|ru\|([^|}]+)")
_TEMPLATE_DROP = re.compile(r"\{\{(?:gloss|q|qualifier|i|lb|lbl|label|sense|ux|uxi|n-g|non-gloss)\|[^{}]*\}\}")


def _strip_stress(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text)
    return unicodedata.normalize("NFC", nfd.replace("\u0301", "").replace("\u0300", ""))


def parse_ru(word: str, wikitext: str) -> Entry:
    """Раздел ==Russian==: английские значения русского слова и его начальная форма."""
    entry = Entry(word)
    if "==Russian==" not in wikitext:
        return entry
    text = re.split(r"\n==[^=]", wikitext.split("==Russian==", 1)[1], maxsplit=1)[0]
    pos = ""
    for line in text.splitlines():
        h = _HEADER.match(line)
        if h:
            name = h.group(2).strip().lower()
            pos = POS_RU.get(name, "прич." if name == "participle" else pos)
            continue
        if not line.startswith("# "):
            continue
        f = _RU_FORM_OF.search(line)
        if f:
            if not entry.lemma:
                entry.lemma = _strip_stress(_clean_term(f.group(2)))
            continue
        body = _TEMPLATE_DROP.sub("", line[2:])
        while _NESTED.search(body):
            body = _NESTED.sub("", body)
        body = _LINK.sub(r"\1", body).replace("'''", "").replace("''", "")
        terms = [t.strip(" .;:") for t in re.split(r"[,;]", body)]
        terms = [t for t in terms if t and len(t) <= 40][:4]
        if terms:
            entry.senses.append(Sense(pos, "", terms))
    if entry.senses:
        entry.lemma = ""  # у слова свои значения — это не просто форма другого слова
    return entry


def lookup_ru(word: str) -> Entry | None:
    wt = fetch_wikitext(word)
    if wt is None:
        return None
    entry = parse_ru(word, wt)
    if entry.lemma and entry.lemma != word and not entry.senses:
        lemma_wt = fetch_wikitext(entry.lemma)
        if lemma_wt:
            entry.senses = parse_ru(entry.lemma, lemma_wt).senses
    return entry
