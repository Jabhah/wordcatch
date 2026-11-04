from wordcatch.layout import clean_word, context_of, group_blocks, join_lines, trim_context, word_at
from wordcatch.ocr import Line, Rect, Word


def make_line(text: str, x: float, y: float, h: float = 16, cw: float = 8) -> Line:
    words = []
    cx = x
    for t in text.split():
        words.append(Word(t, Rect(cx, y, len(t) * cw, h)))
        cx += (len(t) + 1) * cw
    return Line(words)


def test_clean_word():
    assert clean_word("(resemble,") == "resemble"
    assert clean_word("dog's") == "dog"
    assert clean_word("don't.") == "don't"
    assert clean_word("“Hello”") == "Hello"


def test_word_at_finds_word_with_tolerance():
    lines = [make_line("Some people resemble their dogs.", 10, 20)]
    hit = word_at(lines, 10 + 12 * 8 + 5, 25)
    assert hit and hit.word == "resemble"
    assert word_at(lines, 10 + 12 * 8 + 5, 20 + 16 + 3).word == "resemble"  # допуск снизу
    assert word_at(lines, 500, 25) is None
    assert word_at(lines, 50, 100) is None


def test_word_at_ignores_numbers_but_keeps_russian():
    lines = [make_line("Привет 2026", 0, 0)]
    assert word_at(lines, 4, 4).word == "Привет"
    assert word_at(lines, 7 * 8 + 4, 4) is None


def test_hyphen_merge_both_halves():
    lines = [make_line("this is a ques-", 0, 0), make_line("tion for you", 0, 20)]
    first = word_at(lines, 10 * 8 + 4, 5)
    second = word_at(lines, 4, 25)
    assert first.word == "question"
    assert second.word == "question"


def test_join_lines():
    assert join_lines(["a ques-", "tion here"]) == "a question here"
    assert join_lines(["well-", "Known"]) == "well- Known"
    assert join_lines(["one", "two"]) == "one two"


def test_group_blocks_separates_paragraphs_and_columns():
    lines = [
        make_line("First paragraph line one", 0, 0),
        make_line("first paragraph line two", 0, 20),
        make_line("Second paragraph far below", 0, 120),
        make_line("Sidebar text", 600, 0),
    ]
    blocks = group_blocks(lines)
    texts = sorted(b.text for b in blocks)
    assert texts == sorted([
        "First paragraph line one first paragraph line two",
        "Second paragraph far below",
        "Sidebar text",
    ])


def test_context_of_marks_word_position():
    lines = [make_line("They went home early.", 0, 0), make_line("Then they slept.", 0, 20)]
    hit = word_at(lines, 5 * 8 + 4, 5)
    ctx = context_of(lines, hit)
    assert ctx.text == "They went home early. Then they slept."
    assert ctx.text[ctx.start:ctx.end] == "went"


def test_context_of_word_with_punctuation_on_second_line():
    lines = [make_line("Some people", 0, 0), make_line("(resemble, really) dogs", 0, 20)]
    hit = word_at(lines, 3 * 8, 25)
    ctx = context_of(lines, hit)
    assert ctx.text[ctx.start:ctx.end] == "resemble"


def test_context_of_hyphenated_word():
    lines = [make_line("this is a ques-", 0, 0), make_line("tion for you", 0, 20)]
    for x, y in ((10 * 8 + 4, 5), (4, 25)):
        ctx = context_of(lines, word_at(lines, x, y))
        assert ctx.text == "this is a question for you"
        assert ctx.text[ctx.start:ctx.end] == "question"


def test_trim_context():
    text = "One. Two. Three has word. Four. Five. Six."
    s = text.index("word")
    t, a, b, cut = trim_context(text, s, s + 4, max_sentences=3)
    assert cut and t[a:b] == "word"
    assert t == "Two. Three has word. Four."


def test_script_detection_and_mixed_fix():
    from wordcatch.layout import cyrillic_share, fix_mixed_script, is_russian
    assert is_russian("Привет, мир") and not is_russian("Hello world")
    assert not is_russian("Нажми Download and choose Settings now please")
    assert cyrillic_share("2026") == 0.0
    assert fix_mixed_script("дoм") == "дом"      # латинская o в русском слове
    assert fix_mixed_script("hоme") == "home"    # кириллическая о в английском слове


def test_merge_lines_prefers_russian_ocr_for_cyrillic():
    from wordcatch.layout import merge_lines
    en = [make_line("npuBeT, ceroAHR Mbl", 0, 0), make_line("They went home", 0, 30)]
    ru = [make_line("Привет, сегодня мы", 0, 0), make_line("They went home", 0, 30)]
    merged = merge_lines(en, ru)
    assert [ln.text for ln in merged] == ["Привет, сегодня мы", "They went home"]
    hit = word_at(merged, 9 * 8 + 4, 5)
    assert hit.word == "сегодня"


def test_merge_lines_keeps_english_when_no_russian():
    from wordcatch.layout import merge_lines
    en = [make_line("Only English here", 0, 0)]
    assert [ln.text for ln in merge_lines(en, [])] == ["Only English here"]
