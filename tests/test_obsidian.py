from wordcatch import irregular
from wordcatch.obsidian import add_cards, existing_fronts, irregular_cards


def test_add_cards_creates_file_with_tag_and_skips_duplicates(tmp_path):
    words = tmp_path / "English" / "Слова"
    words.mkdir(parents=True)
    (words / "Базовые.md").write_text("# Базовые\n#flashcards/слова\n\ntired:::уставший\n<!--SR:!2026-11-08,4,270-->\n",
                                      encoding="utf-8")
    target = words / "Из переводчика.md"
    added = add_cards(target, [("Tired", "усталый"), ("resemble", "походить на, напоминать")],
                      "Слова из переводчика", "#flashcards/слова", words)
    assert added == ["resemble"]
    text = target.read_text(encoding="utf-8")
    assert text == "# Слова из переводчика\n#flashcards/слова\n\nresemble:::походить на, напоминать\n"
    # повторно не добавляется
    assert add_cards(target, [("resemble", "x")], "t", "#t", words) == []


def test_add_cards_keeps_sr_comments(tmp_path):
    target = tmp_path / "cards.md"
    target.write_text("# T\n#flashcards/слова\n\nbunch:::связка\n<!--SR:!2026-11-05,1,210-->", encoding="utf-8")
    add_cards(target, [("crowd", "толпа")], "T", "#flashcards/слова", tmp_path)
    text = target.read_text(encoding="utf-8")
    assert "<!--SR:!2026-11-05,1,210-->\n\ncrowd:::толпа\n" in text
    assert existing_fronts(tmp_path) == {"bunch", "crowd"}


def test_sanitize_separators(tmp_path):
    target = tmp_path / "c.md"
    add_cards(target, [("a::b", "x\ny:::z")], "T", "#t", tmp_path)
    assert "a:b:::x y:z" in target.read_text(encoding="utf-8")


def test_irregular_lookup():
    assert irregular.lookup("went")[0].base == "go"
    assert irregular.lookup("gone")[0].kinds_of("gone") == ["V3"]
    assert irregular.lookup("was")[0].base == "be"
    assert irregular.lookup("were")[0].base == "be"
    assert irregular.lookup("left")[0].base == "leave"
    assert [v.base for v in irregular.lookup("saw")] == ["see", "saw"]
    assert irregular.lookup("walked") == []


def test_irregular_three_cards():
    go = irregular.lookup("went")[0]
    cards = irregular_cards(go, "идти, ехать", "пошёл", "ушедший")
    assert cards == [
        ("go", "идти, ехать (V1: go — went — gone)"),
        ("went", "пошёл (V2 от go)"),
        ("gone", "ушедший (V3 от go)"),
    ]


def test_irregular_same_forms_and_variants():
    cut = irregular.lookup("cut")[0]
    assert [f for f, _ in irregular_cards(cut, "резать", "", "")] == ["cut"]
    get = irregular.lookup("got")[0]
    assert [f for f, _ in irregular_cards(get, "получать", "получил", "")] == ["get", "got", "gotten"]
    be = irregular.lookup("was")[0]
    assert [f for f, _ in irregular_cards(be, "быть", "был", "")] == ["be", "was/were", "been"]


def test_irregular_one_card_and_fallback_text():
    go = irregular.lookup("go")[0]
    assert irregular_cards(go, "идти", "", "", mode="one") == [
        ("go — went — gone", "идти — прошедшее время от «идти» — причастие от «идти»")]


def test_irregular_cards_skip_existing(tmp_path):
    target = tmp_path / "Неправильные глаголы.md"
    target.write_text("# Н\n#flashcards/слова/неправильные\n\nwent:::пошёл (V2 от go)\n", encoding="utf-8")
    go = irregular.lookup("go")[0]
    added = add_cards(target, irregular_cards(go, "идти", "пошёл", "ушедший"), "Н", "#t", tmp_path)
    assert added == ["go", "gone"]
