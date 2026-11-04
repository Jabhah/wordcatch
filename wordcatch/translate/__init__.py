"""Источники перевода: Wiktionary (словарь), DeepL / MyMemory (текст), Tatoeba (примеры)."""

USER_AGENT = "WordCatch/0.1 (personal screen translator; Windows)"


class TranslateError(RuntimeError):
    """Ошибка сервиса перевода, текст понятен пользователю."""


class QuotaError(TranslateError):
    """Исчерпан лимит сервиса."""
