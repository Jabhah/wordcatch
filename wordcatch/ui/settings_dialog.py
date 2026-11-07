"""Окно настроек."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)

from ..config import Config
from ..hotkeys import parse_hotkey
from ..obsidian import find_vault
from ..translate import deepl
from .common import run_async


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.setObjectName("window")
        self.setWindowTitle("WordCatch — настройки")
        self.setMinimumWidth(560)
        self.cfg = cfg
        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setVerticalSpacing(8)

        self.hotkey = QLineEdit(cfg.hotkey)
        self.hotkey.setPlaceholderText("например: alt+q, ctrl+shift+e, f8")
        form.addRow("Хоткей", self.hotkey)
        self.mouse = QComboBox()
        for value, title in (("none", "не использовать"), ("x1", "боковая «назад» (X1)"),
                             ("x2", "боковая «вперёд» (X2)")):
            self.mouse.addItem(title, value)
        self.mouse.setCurrentIndex(max(0, self.mouse.findData(cfg.mouse_button)))
        form.addRow("Кнопка мыши", self.mouse)
        self.suppress = QCheckBox("не передавать нажатие программам (браузер не будет листать)")
        self.suppress.setChecked(cfg.suppress_mouse_button)
        form.addRow("", self.suppress)

        key_row = QWidget()
        kl = QHBoxLayout(key_row)
        kl.setContentsMargins(0, 0, 0, 0)
        self.deepl = QLineEdit(cfg.deepl_key)
        self.deepl.setEchoMode(QLineEdit.Password)
        self.deepl.setPlaceholderText("пусто — переводить через MyMemory")
        check = QPushButton("Проверить")
        check.clicked.connect(self._check_key)
        kl.addWidget(self.deepl, 1)
        kl.addWidget(check)
        form.addRow("Ключ DeepL API", key_row)
        self.key_status = QLabel("Бесплатный ключ: deepl.com/pro-api → тариф API Free (500 000 символов в месяц).\n"
                                 "Вводится один раз: хранится в диспетчере учётных данных Windows.")
        self.key_status.setWordWrap(True)
        self.key_status.setProperty("role", "muted")
        form.addRow("", self.key_status)
        self.email = QLineEdit(cfg.mymemory_email)
        self.email.setPlaceholderText("необязательно: поднимает лимит MyMemory до 50 000 символов в день")
        form.addRow("E-mail для MyMemory", self.email)

        vault_row = QWidget()
        vl = QHBoxLayout(vault_row)
        vl.setContentsMargins(0, 0, 0, 0)
        self.vault = QLineEdit(cfg.vault_path)
        auto = find_vault("")
        self.vault.setPlaceholderText(f"авто: {auto}" if auto else "не найдено — укажи папку хранилища")
        browse = QPushButton("Обзор…")
        browse.clicked.connect(self._browse)
        vl.addWidget(self.vault, 1)
        vl.addWidget(browse)
        form.addRow("Хранилище Obsidian", vault_row)
        self.words_file = QLineEdit(cfg.words_file)
        form.addRow("Файл для слов", self.words_file)
        self.deck_tag = QLineEdit(cfg.deck_tag)
        form.addRow("Тег колоды", self.deck_tag)
        self.irregular_file = QLineEdit(cfg.irregular_file)
        form.addRow("Файл неправильных глаголов", self.irregular_file)
        self.irregular_tag = QLineEdit(cfg.irregular_tag)
        form.addRow("Тег неправильных глаголов", self.irregular_tag)
        self.irregular_mode = QComboBox()
        self.irregular_mode.addItem("три карточки: go / went / gone", "three")
        self.irregular_mode.addItem("одна карточка: go — went — gone", "one")
        self.irregular_mode.setCurrentIndex(max(0, self.irregular_mode.findData(cfg.irregular_mode)))
        form.addRow("Неправильные глаголы", self.irregular_mode)
        self.dedup = QLineEdit(cfg.dedup_folder)
        form.addRow("Где искать дубли", self.dedup)
        self.meanings = QComboBox()
        for n in range(1, 9):
            self.meanings.addItem(str(n), n)
        self.meanings.setCurrentIndex(max(0, self.meanings.findData(cfg.meanings_in_card)))
        form.addRow("Значений в карточке", self.meanings)
        self.auto = QCheckBox("автовыбор: значения, базовая форма и неправильные глаголы подставляются сами\n"
                              "(выключено — карточку пишешь вручную)")
        self.auto.setChecked(cfg.auto_select)
        form.addRow("", self.auto)
        self.stress = QCheckBox("убирать знаки ударения (походи́ть → походить)")
        self.stress.setChecked(cfg.strip_stress_in_card)
        form.addRow("", self.stress)
        self.theme = QComboBox()
        self.theme.addItem("тёмная", "dark")
        self.theme.addItem("светлая", "light")
        self.theme.setCurrentIndex(max(0, self.theme.findData(cfg.theme)))
        form.addRow("Тема", self.theme)
        self.screen_mode = QComboBox()
        self.screen_mode.addItem("сразу поверх текста — прочитал и Esc", "overlay")
        self.screen_mode.addItem("выбрать абзацы → перевод в отдельном окне", "pick")
        self.screen_mode.setCurrentIndex(max(0, self.screen_mode.findData(cfg.screen_mode)))
        form.addRow("Хоткей мимо слова", self.screen_mode)
        root.addLayout(form)

        self.error = QLabel("")
        self.error.setStyleSheet("color: #d64545;")
        root.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Папка хранилища Obsidian", self.vault.text())
        if path:
            self.vault.setText(path)

    def _check_key(self):
        key = self.deepl.text().strip()
        if not key:
            self.key_status.setText("Ключ не указан — будет использоваться MyMemory")
            return
        self.key_status.setText("Проверяю…")

        def ok(res):
            used, limit = res
            self.key_status.setText(f"Ключ работает: использовано {used:,} из {limit:,} символов в этом месяце"
                                    .replace(",", " "))

        run_async(deepl.usage, key, done=ok, failed=lambda m: self.key_status.setText(f"Ошибка: {m}"))

    def result_config(self) -> Config:
        return replace(
            self.cfg,
            hotkey=self.hotkey.text().strip().lower(),
            mouse_button=self.mouse.currentData(),
            suppress_mouse_button=self.suppress.isChecked(),
            deepl_key=self.deepl.text().strip(),
            mymemory_email=self.email.text().strip(),
            vault_path=self.vault.text().strip(),
            words_file=self.words_file.text().strip() or Config.words_file,
            deck_tag=self.deck_tag.text().strip() or Config.deck_tag,
            irregular_file=self.irregular_file.text().strip() or Config.irregular_file,
            irregular_tag=self.irregular_tag.text().strip() or Config.irregular_tag,
            irregular_mode=self.irregular_mode.currentData(),
            dedup_folder=self.dedup.text().strip() or Config.dedup_folder,
            meanings_in_card=self.meanings.currentData(),
            auto_select=self.auto.isChecked(),
            strip_stress_in_card=self.stress.isChecked(),
            theme=self.theme.currentData(),
            screen_mode=self.screen_mode.currentData(),
        )

    def _accept(self):
        try:
            parse_hotkey(self.hotkey.text())
        except ValueError as e:
            self.error.setText(f"Хоткей: {e}")
            return
        if self.vault.text().strip() and find_vault(self.vault.text().strip()) is None:
            self.error.setText("Папка хранилища не найдена")
            return
        self.accept()


