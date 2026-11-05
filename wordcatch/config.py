"""Настройки программы: dataclass <-> %APPDATA%\\WordCatch\\config.json.

Ключ DeepL в config.json не пишется: он хранится в диспетчере учётных данных Windows
(«WordCatch / deepl_key»). Его не сотрёт ни сброс или порча config.json, ни новая версия программы.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

SECRET_SERVICE = "WordCatch"
SECRET_FIELDS = ("deepl_key",)


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / "WordCatch"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------- секреты: диспетчер учётных данных Windows ----------
def _keyring():
    try:
        import keyring
        return keyring
    except Exception:  # noqa: BLE001 — без keyring работаем по-старому, через config.json
        return None


def get_secret(name: str) -> str | None:
    """None — хранилище недоступно; "" — секрета нет."""
    kr = _keyring()
    if kr is None:
        return None
    try:
        return kr.get_password(SECRET_SERVICE, name) or ""
    except Exception:  # noqa: BLE001
        return None


def set_secret(name: str, value: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        if value:
            kr.set_password(SECRET_SERVICE, name, value)
        else:
            try:
                kr.delete_password(SECRET_SERVICE, name)
            except Exception:  # noqa: BLE001 — нечего удалять
                pass
        return True
    except Exception:  # noqa: BLE001
        return False


@dataclass
class Config:
    hotkey: str = "alt+q"
    mouse_button: str = "x2"          # x1 / x2 / none — кнопки «назад»/«вперёд» на мыши
    suppress_mouse_button: bool = True
    deepl_key: str = ""               # в файл не пишется — см. описание модуля
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
        data: dict = {}
        path = cls.path()
        if path.exists():
            try:
                # utf-8-sig: Блокнот иногда сохраняет файл с BOM — это не должно сбрасывать настройки
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(data, dict):
                    raise ValueError("ожидался объект JSON")
            except (OSError, ValueError):
                # повреждённый файл не перезаписываем молча, а откладываем в копию
                try:
                    path.replace(path.with_name(f"config.broken-{time.strftime('%Y%m%d-%H%M%S')}.json"))
                except OSError:
                    pass
                data = {}
        names = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key in names:
                setattr(cfg, key, value)
        for name in SECRET_FIELDS:
            stored = get_secret(name)
            if stored:
                setattr(cfg, name, stored)
            elif stored == "" and data.get(name):
                # старая версия хранила ключ в config.json — переносим в диспетчер учётных данных
                if set_secret(name, data[name]):
                    cfg.save()
        return cfg

    def save(self) -> None:
        data = asdict(self)
        for name in SECRET_FIELDS:
            if set_secret(name, data[name]):
                data[name] = ""          # секрет в безопасном хранилище — в файле не держим
            # если хранилище недоступно, ключ остаётся в файле, чтобы не потерять его
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path())
