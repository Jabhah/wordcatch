import json

import pytest

from conftest import FIXTURES
from wordcatch.translate import QuotaError, deepl, mymemory, tatoeba, wiktionary
from wordcatch.translate.service import find_highlight, parse_tagged, strip_stress


def wikt(name):
    return json.loads((FIXTURES / f"wikt_{name}.json").read_text(encoding="utf-8"))["parse"]["wikitext"]


def test_wiktionary_resemble():
    e = wiktionary.parse("resemble", wikt("resemble"))
    assert e.ipa == "/ɹɪˈzɛmbəl/"
    assert e.senses[0].pos == "гл."
    terms = [strip_stress(t) for t in e.senses[0].terms]
    assert "походить на" in terms and "быть похожим на" in terms


def test_wiktionary_form_of():
    went = wiktionary.parse("went", wikt("went"))
    assert (went.lemma, went.form_kind) == ("go", "V2")
    bought = wiktionary.parse("bought", wikt("bought"))
    assert bought.lemma == "buy"


def test_wiktionary_left_has_own_meanings_and_lemma():
    e = wiktionary.parse("left", wikt("left"))
    assert e.lemma == "leave"
    assert any("ле́вый" in s.terms for s in e.senses)


def test_wiktionary_translation_subpage():
    go = wiktionary.parse("go", wikt("go"))
    assert go.subpage and go.lemma == ""
    sub = wiktionary.parse("go", wikt("go_translations"), english_only=False)
    first = sub.senses[0]
    assert first.pos == "гл." and "идти́" in first.terms


def test_wiktionary_struggle_pos():
    e = wiktionary.parse("struggle", wikt("struggle"))
    assert {s.pos for s in e.senses} == {"сущ.", "гл."}


def test_tatoeba():
    data = json.loads((FIXTURES / "tatoeba_resemble.json").read_text(encoding="utf-8"))
    ex = tatoeba.parse(data, 2)
    assert ex[0] == ("I resemble my mother.", "Я похож на мою мать.")
    assert len(ex) == 2


def test_mymemory_parse_and_quota():
    data = json.loads((FIXTURES / "mymemory_text.json").read_text(encoding="utf-8"))
    assert mymemory.parse(data) == "Он ушел домой пораньше."
    with pytest.raises(QuotaError):
        mymemory.parse({"responseStatus": 429, "responseDetails": "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE "
                                                                  "TRANSLATIONS FOR TODAY"})


def test_mymemory_chunks_limit():
    text = ("This is a fairly long sentence about nothing in particular. " * 30).strip()
    chunks = mymemory._chunks(text)
    assert all(len(c.encode("utf-8")) <= mymemory.MAX_BYTES for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_deepl_parse():
    assert deepl.parse({"translations": [{"text": "Привет"}]}) == ["Привет"]
    assert deepl._endpoint("abc:fx").startswith("https://api-free.")
    assert deepl._endpoint("abc").startswith("https://api.deepl")


def test_parse_tagged():
    ct = parse_tagged("Он <w>пошёл</w> домой &amp; спал.")
    assert ct.text == "Он пошёл домой & спал."
    assert ct.text[ct.hl[0]:ct.hl[1]] == "пошёл" and ct.contextual == "пошёл"


def test_find_highlight():
    text = "Некоторые люди похожи на своих собак."
    a, b = find_highlight(text, ["походи́ть на", "напомина́ть", "быть похо́жим на"])
    assert text[a:b] == "похожи"
    assert find_highlight("Он ушел домой.", ["идти́", "е́хать"]) is None
    assert find_highlight("Борьба была тяжёлой.", ["борьба́"]) == (0, 6)


def wikt_ru(name):
    return json.loads((FIXTURES / f"wikt_ru_{name}.json").read_text(encoding="utf-8"))["parse"]["wikitext"]


def test_wiktionary_russian_entries():
    dom = wiktionary.parse_ru("дом", wikt_ru("dom"))
    assert dom.senses[0].pos == "сущ." and dom.senses[0].terms == ["house", "building"]
    form = wiktionary.parse_ru("вернулись", wikt_ru("vernulis"))
    assert form.lemma == "вернуться" and not form.senses
    verb = wiktionary.parse_ru("вернуться", wikt_ru("vernutsya"))
    assert verb.lemma == "" and verb.senses[0].terms[0] == "to return"


def test_direction():
    from wordcatch.translate.service import direction
    assert direction("They went home") == ("en", "ru")
    assert direction("Они вернулись домой") == ("ru", "en")
