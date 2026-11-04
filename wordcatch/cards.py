"""Что и куда записать в Obsidian по нажатию закладки (слово, неправильный глагол, фраза)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import obsidian
from .config import Config
from .irregular import Verb
from .translate.service import Translator, WordInfo, strip_stress


@dataclass
class SaveResult:
    added: list[str]
    file: Path | None
    message: str


class CardMaker:
    def __init__(self, cfg: Config, translator: Translator):
        self.cfg = cfg
        self.tr = translator

    def vault(self) -> Path | None:
        return obsidian.find_vault(self.cfg.vault_path)

    def _paths(self) -> tuple[Path, Path, Path]:
        v = self.vault()
        if v is None:
            raise FileNotFoundError("Не найдено хранилище Obsidian — укажи путь в настройках")
        return v / self.cfg.words_file, v / self.cfg.irregular_file, v / self.cfg.dedup_folder

    def _clean(self, text: str) -> str:
        return strip_stress(text) if self.cfg.strip_stress_in_card else text

    @staticmethod
    def _verb_fronts(verb: Verb, mode: str) -> list[str]:
        if mode == "one":
            return [verb.forms_text]
        fronts, used = [verb.base], {verb.base}
        for forms in (verb.past, verb.participle):
            fresh = [f for f in forms if f not in used]
            if fresh:
                used.update(fresh)
                fronts.append("/".join(fresh))
        return fronts

    def is_saved(self, info: WordInfo) -> bool:
        try:
            _, _, folder = self._paths()
        except FileNotFoundError:
            return False
        known = obsidian.existing_fronts(folder)
        if info.lang == "ru":  # лицевая сторона английская: проверяем по переводу
            return bool(info.alone) and obsidian.card_key(info.alone) in known
        if info.verbs:
            return all(obsidian.card_key(f) in known for f in self._verb_fronts(info.verbs[0], self.cfg.irregular_mode))
        return obsidian.card_key(info.lemma) in known

    def save_word(self, info: WordInfo, chosen: list[str]) -> SaveResult:
        words_file, irregular_file, folder = self._paths()
        back = ", ".join(dict.fromkeys(self._clean(c) for c in chosen if c.strip()))
        if info.lang == "ru":
            # русское слово: карточка в том же виде, что и остальные — «english:::русский»
            if not back:
                return SaveResult([], None, "Выбери хотя бы один перевод")
            added = obsidian.add_cards(words_file, [(back, info.lemma)], "Слова из переводчика",
                                       self.cfg.deck_tag, folder)
            if not added:
                return SaveResult([], words_file, "Уже в колоде")
            return SaveResult(added, words_file, f"Добавлено в «{words_file.stem}»: {back} ::: {info.lemma}")
        if info.verbs:
            verb = info.verbs[0]
            v1 = back or verb.ru
            v2 = self.tr.form_translation(verb.past[0])
            v3 = self.tr.form_translation(verb.participle[0]) if verb.participle != verb.past else v2
            cards = obsidian.irregular_cards(verb, v1, self._clean(v2), self._clean(v3), self.cfg.irregular_mode)
            added = obsidian.add_cards(irregular_file, cards, "Неправильные глаголы", self.cfg.irregular_tag, folder)
            target = irregular_file
        else:
            if not back:
                return SaveResult([], None, "Выбери хотя бы одно значение")
            added = obsidian.add_cards(words_file, [(info.lemma, back)], "Слова из переводчика",
                                       self.cfg.deck_tag, folder)
            target = words_file
        if not added:
            return SaveResult([], target, "Уже в колоде")
        return SaveResult(added, target, f"Добавлено в «{target.stem}»: {', '.join(added)}")

    def save_phrase(self, phrase: str, translation: str) -> SaveResult:
        words_file, _, folder = self._paths()
        added = obsidian.add_cards(words_file, [(phrase, self._clean(translation))], "Слова из переводчика",
                                   self.cfg.deck_tag, folder)
        if not added:
            return SaveResult([], words_file, "Уже в колоде")
        return SaveResult(added, words_file, f"Добавлено в «{words_file.stem}»")
