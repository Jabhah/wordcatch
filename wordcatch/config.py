"""Настройки программы: dataclass <-> %APPDATA%\\WordCatch\\config.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / "WordCatch"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Config:
    hotkey: str = "alt+q"
    mouse_button: str = "x2"          # x1 / x2 / none — кнопки «назад»/«вперёд» на мыши
    suppress_mouse_button: bool = True
    deepl_key: str = ""
    mymemory_email: str = ""          # необязательно: поднимает лимит MyMemory до 50 000 символов в день
    vault_path: str = ""              # пусто = взять открытое хранилище из obsidian.json
    words_file: str = "English/Слова/Из переводчика.md"
    irregular_file: str = "English/Слова/Неправильные глаголы.md"
    dedup_folder: str = "English/Слова"
    deck_tag: str = "#flashcards/слова"
    irregular_tag: str = "#flashcards/слова/неправильные"
    irregular_mode: str = "three"     # three = три карточки, one = одна карточка «go — went — gone»
    meanings_in_card: int = 3
    auto_select: bool = True          # сами выбираются значения, базовая форма и карточки неправильных глаголов
    strip_stress_in_card: bool = True
    ocr_scale: float = 2.0
    theme: str = "dark"               # dark / light

    @classmethod
    def path(cls) -> Path:
        return app_dir() / "config.json"

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cfg
        names = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key in names:
                setattr(cfg, key, value)
        return cfg

    def save(self) -> None:
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path())
