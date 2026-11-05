import json

import pytest

from wordcatch import config as config_mod
from wordcatch.config import Config


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Отдельная папка APPDATA и поддельный диспетчер учётных данных."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    vault: dict[str, str] = {}
    monkeypatch.setattr(config_mod, "get_secret", lambda n: vault.get(n, ""))
    monkeypatch.setattr(config_mod, "set_secret", lambda n, v: (vault.__setitem__(n, v) if v else vault.pop(n, None))
                        or True)
    return tmp_path / "WordCatch", vault


def test_key_goes_to_secret_store_not_file(env):
    folder, vault = env
    cfg = Config(deepl_key="abc:fx", theme="light")
    cfg.save()
    on_disk = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    assert on_disk["deepl_key"] == "" and on_disk["theme"] == "light"
    assert vault["deepl_key"] == "abc:fx"
    assert Config.load().deepl_key == "abc:fx"


def test_old_config_with_key_is_migrated(env):
    folder, vault = env
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text(json.dumps({"deepl_key": "old:fx", "hotkey": "f8"}), encoding="utf-8")
    cfg = Config.load()
    assert cfg.deepl_key == "old:fx" and cfg.hotkey == "f8"
    assert vault["deepl_key"] == "old:fx"
    assert json.loads((folder / "config.json").read_text(encoding="utf-8"))["deepl_key"] == ""


def test_key_survives_broken_config(env):
    folder, vault = env
    Config(deepl_key="keep:fx", hotkey="f9").save()
    (folder / "config.json").write_text("{ сломано", encoding="utf-8")
    cfg = Config.load()
    assert cfg.deepl_key == "keep:fx"           # ключ не потерян
    assert cfg.hotkey == "alt+q"                 # остальное — по умолчанию
    assert list(folder.glob("config.broken-*.json"))  # испорченный файл отложен, а не стёрт


def test_bom_does_not_reset_settings(env):
    folder, _ = env
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text(json.dumps({"hotkey": "f7"}), encoding="utf-8-sig")
    assert Config.load().hotkey == "f7"


def test_falls_back_to_file_without_secret_store(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(config_mod, "get_secret", lambda n: None)
    monkeypatch.setattr(config_mod, "set_secret", lambda n, v: False)
    Config(deepl_key="file:fx").save()
    assert Config.load().deepl_key == "file:fx"
