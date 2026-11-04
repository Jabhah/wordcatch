"""Окно с переводом выбранных абзацев: «оригинал | перевод», закладка в правом верхнем углу."""
from __future__ import annotations

import re

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QTextEdit, QVBoxLayout, QWidget)

from ..cards import CardMaker
from ..config import Config
from ..translate.service import Translator
from .common import BookmarkButton, Theme, run_async

_WORD = re.compile(r"^[A-Za-z][A-Za-z'’-]*$")


class AutoText(QTextEdit):
    """Текст без прокрутки, высота по содержимому. Двойной клик по слову сообщает о нём."""
    word_activated = Signal(str, int, int)

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlainText(text)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.document().contentsChanged.connect(self._fit)

    def _fit(self):
        self.document().setTextWidth(self.viewport().width())
        m = self.contentsMargins()
        self.setFixedHeight(int(self.document().size().height()) + m.top() + m.bottom() + 14)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def mouseDoubleClickEvent(self, e):
        super().mouseDoubleClickEvent(e)
        cur = self.textCursor()
        word = cur.selectedText().strip()
        if _WORD.match(word):
            self.word_activated.emit(word, cur.selectionStart(), cur.selectionEnd())


class ResultWindow(QWidget):
    open_word = Signal(str, str, int, int, QRect)   # слово, абзац, start, end, где показать

    def __init__(self, texts: list[str], cfg: Config, translator: Translator, cards: CardMaker, theme: Theme):
        super().__init__(None, Qt.Window)
        self.setObjectName("window")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle("WordCatch — перевод с экрана")
        self.cfg, self.tr, self.cards, self.t = cfg, translator, cards, theme
        self.alive = True
        self.texts = texts
        self.translations: list[str] = [""] * len(texts)
        self.origs: list[AutoText] = []
        self.trans: list[AutoText] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 10, 12, 14)
        head = QHBoxLayout()
        title = QLabel("Перевод с экрана")
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        head.addWidget(title)
        self.engine_lb = QLabel(translator.engine)
        self.engine_lb.setStyleSheet(f"color: {theme.muted};")
        head.addWidget(self.engine_lb)
        head.addStretch(1)
        hint = QLabel("выдели слово или фразу →")
        hint.setStyleSheet(f"color: {theme.muted};")
        head.addWidget(hint)
        self.auto_btn = QPushButton("Авто")
        self.auto_btn.setProperty("role", "toggle")
        self.auto_btn.setCheckable(True)
        self.auto_btn.setChecked(cfg.auto_select)
        self.auto_btn.setCursor(Qt.PointingHandCursor)
        self.auto_btn.setToolTip("Автовыбор перевода и неправильных глаголов. Выключи, чтобы писать карточку вручную.")
        self.auto_btn.toggled.connect(self._set_auto)
        head.addWidget(self.auto_btn, 0, Qt.AlignVCenter)
        self.bookmark = BookmarkButton(theme)
        self.bookmark.setToolTip("Выдели в оригинале слово или фразу и нажми — карточка уйдёт в Obsidian")
        self.bookmark.clicked.connect(self._save_selection)
        head.addWidget(self.bookmark, 0, Qt.AlignTop)
        root.addLayout(head)

        cols = QGridLayout()
        cols.setHorizontalSpacing(12)
        for c, name in enumerate(("Оригинал", "Перевод")):
            lb = QLabel(name.upper())
            lb.setStyleSheet(f"color: {theme.muted}; font-size: 11px; font-weight: 600; letter-spacing: 1px;")
            cols.addWidget(lb, 0, c)
        host = QWidget()
        host.setObjectName("window")
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 6, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        for i, text in enumerate(texts):
            o = AutoText(text)
            o.word_activated.connect(lambda w, s, e, i=i: self._word_clicked(i, w, s, e))
            o.selectionChanged.connect(lambda i=i: self._remember_selection(i))
            t = AutoText("…")
            grid.addWidget(o, i, 0, Qt.AlignTop)
            grid.addWidget(t, i, 1, Qt.AlignTop)
            self.origs.append(o)
            self.trans.append(t)
        grid.setRowStretch(len(texts), 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)
        root.addLayout(cols)
        root.addWidget(scroll, 1)

        # ручная карточка (когда автовыбор выключен)
        self.editor = QWidget()
        ed = QHBoxLayout(self.editor)
        ed.setContentsMargins(0, 4, 0, 0)
        self.front_ed = QLineEdit()
        self.front_ed.setPlaceholderText("слово или фраза")
        self.back_ed = QLineEdit()
        self.back_ed.setPlaceholderText("перевод — впиши сам")
        self.back_ed.returnPressed.connect(self._save_selection)
        save = QPushButton("В Obsidian")
        save.clicked.connect(self._save_selection)
        ed.addWidget(QLabel("Карточка:"))
        ed.addWidget(self.front_ed, 2)
        ed.addWidget(QLabel(":::"))
        ed.addWidget(self.back_ed, 3)
        ed.addWidget(save)
        self.editor.setVisible(not cfg.auto_select)
        root.addWidget(self.editor)

        foot = QHBoxLayout()
        self.status = QLabel("Двойной клик по слову в оригинале — подробный перевод слова")
        self.status.setStyleSheet(f"color: {theme.muted};")
        foot.addWidget(self.status, 1)
        copy = QPushButton("Копировать перевод")
        copy.clicked.connect(self._copy)
        foot.addWidget(copy)
        root.addLayout(foot)

        self._last_sel: tuple[int, str] | None = None
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        self.resize(min(1100, int(avail.width() * 0.7)), min(760, int(avail.height() * 0.75)))
        self.move(avail.center() - self.rect().center())

        for i, text in enumerate(texts):
            run_async(translator.text, text, done=lambda r, i=i: self._on_tr(i, r),
                      failed=lambda m, i=i: self._on_tr(i, f"⚠ {m}"))

    def closeEvent(self, e):
        self.alive = False
        super().closeEvent(e)

    def _on_tr(self, i: int, text: str):
        if not self.alive:
            return
        self.translations[i] = text
        self.trans[i].setPlainText(text)

    def _copy(self):
        QGuiApplication.clipboard().setText("\n\n".join(self.translations))
        self.status.setText("Перевод скопирован")

    def _remember_selection(self, i: int):
        sel = self.origs[i].textCursor().selectedText().replace("\u2029", " ").strip()
        if sel:
            self._last_sel = (i, sel)
            if not self.cfg.auto_select:
                self.front_ed.setText(sel.strip(" .,;:!?\"'()[]«»"))

    def _set_auto(self, on: bool):
        self.cfg.auto_select = on
        try:
            self.cfg.save()
        except OSError:
            pass
        self.editor.setVisible(not on)
        if not on and self._last_sel:
            self.front_ed.setText(self._last_sel[1].strip(" .,;:!?\"'()[]«»"))

    def _word_clicked(self, i: int, word: str, start: int, end: int):
        pos = QCursor.pos()
        self.open_word.emit(word, self.texts[i], start, end, QRect(pos.x() - 20, pos.y() - 10, 40, 20))

    # ---------- закладка ----------
    def _save_selection(self):
        if self.bookmark.busy:
            return
        if not self.cfg.auto_select:
            front, back = self.front_ed.text().strip(), self.back_ed.text().strip()
            if not front or not back:
                self.status.setText("Заполни карточку внизу: слово (можно выделить в оригинале) и перевод")
                (self.back_ed if front else self.front_ed).setFocus()
                return
            self.bookmark.set_busy(True)
            run_async(self.cards.save_phrase, front, back, done=self._on_saved, failed=self._on_save_error)
            return
        if not self._last_sel:
            self.status.setText("Сначала выдели в оригинале слово или фразу, потом нажми закладку")
            return
        _, sel = self._last_sel
        self.bookmark.set_busy(True)
        self.status.setText(f"Сохраняю «{sel[:40]}» в Obsidian…")
        run_async(self._save_job, sel, done=self._on_saved, failed=self._on_save_error)

    def _save_job(self, sel: str):
        sel = sel.strip(" .,;:!?\"'()[]«»")
        words = sel.split()
        # слово или устойчивое выражение (take after, look forward to) — сначала словарь
        if all(_WORD.match(w) for w in words) and len(words) <= 4:
            info = self.tr.dictionary(sel if len(words) > 1 else words[0])
            if info.senses or len(words) == 1:
                chosen = info.chips()[: max(1, self.cfg.meanings_in_card)]
                return self.cards.save_word(info, chosen)
        return self.cards.save_phrase(sel, self.tr.text(sel))

    def _on_saved(self, res):
        if not self.alive:
            return
        self.bookmark.set_busy(False)
        self.bookmark.set_saved(res.file is not None)
        self.status.setText(res.message)
        if res.added and not self.cfg.auto_select:
            self.back_ed.clear()

    def _on_save_error(self, msg: str):
        if not self.alive:
            return
        self.bookmark.set_busy(False)
        self.status.setText(f"Не удалось сохранить: {msg}")
