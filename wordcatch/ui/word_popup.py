"""Карточка слова у курсора: абзац с подсвеченным словом, его перевод, затем значения слова."""
from __future__ import annotations

import html

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from ..cards import CardMaker
from ..config import Config
from ..layout import is_russian, trim_context
from ..translate.service import ContextTranslation, Translator, WordInfo, find_highlight, strip_stress
from .common import BookmarkButton, FlowLayout, Theme, mark, run_async

WIDTH = 460
CONTENT_W = WIDTH - 26  # ширина содержимого карточки (минус поля)
MAX_SENSES = 4
MAX_TERMS_PER_SENSE = 5


def _flow_row(widgets) -> QWidget:
    """Строка «чипов» с переносом; высота считается заранее, иначе QVBoxLayout её обрезает."""
    host = QWidget()
    flow = FlowLayout(host)
    for w in widgets:
        w.ensurePolished()
        flow.addWidget(w)
    host.setFixedHeight(flow.heightForWidth(CONTENT_W))
    return host


def _label(text: str = "", role: str = "", rich: bool = False, wrap: bool = True) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    lb.setTextFormat(Qt.RichText if rich else Qt.PlainText)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


class WordPopup(QWidget):
    closed = Signal()

    def __init__(self, word: str, paragraph: str, start: int, end: int, anchor: QRect,
                 cfg: Config, translator: Translator, cards: CardMaker, theme: Theme):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.alive = True
        self.word, self.cfg, self.tr, self.cards, self.t = word, cfg, translator, cards, theme
        self.anchor = anchor
        self.full = (paragraph, start, end)
        self.short = trim_context(paragraph, start, end, 3)
        self.expanded = not self.short[3]
        self.info: WordInfo | None = None
        self.ctx: ContextTranslation | None = None
        self.chips: list[QPushButton] = []
        self.user_touched_chips = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 18)
        self.card = QWidget(objectName="card")
        shadow = QGraphicsDropShadowEffect(blurRadius=28, offset=QPoint(0, 6))
        shadow.setColor(QColor(0, 0, 0, 110))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)
        self.card.setFixedWidth(WIDTH)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(16, 10, 10, 14)
        lay.setSpacing(8)

        # --- шапка: подпись + закладка в правом верхнем углу
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(_label("В ТЕКСТЕ", "section", wrap=False))
        head.addStretch(1)
        self.auto_btn = QPushButton("Авто")
        self.auto_btn.setProperty("role", "toggle")
        self.auto_btn.setCheckable(True)
        self.auto_btn.setChecked(cfg.auto_select)
        self.auto_btn.setCursor(Qt.PointingHandCursor)
        self.auto_btn.setToolTip("Автовыбор: значения, базовая форма и карточки неправильных глаголов "
                                 "подставляются сами.\nВыключи, чтобы писать карточку вручную.")
        self.auto_btn.toggled.connect(self._set_auto)
        head.addWidget(self.auto_btn, 0, Qt.AlignVCenter)
        self.bookmark = BookmarkButton(theme)
        self.bookmark.setEnabled(False)
        self.bookmark.clicked.connect(self._save)
        head.addWidget(self.bookmark, 0, Qt.AlignTop)
        lay.addLayout(head)

        # --- контекст: оригинал с подсветкой и перевод
        box = QWidget(objectName="contextBox")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.setSpacing(6)
        self.orig = _label(rich=True)
        self.trans = _label("Перевожу абзац…", "muted", rich=True)
        bl.addWidget(self.orig)
        bl.addWidget(self.trans)
        self.more = QPushButton("показать весь абзац", objectName="more")
        self.more.setProperty("role", "link")
        self.more.setCursor(Qt.PointingHandCursor)
        self.more.clicked.connect(self._toggle_expand)
        self.more.setVisible(self.short[3])
        bl.addWidget(self.more, 0, Qt.AlignLeft)
        lay.addWidget(box)

        # --- слово
        row = QHBoxLayout()
        row.setSpacing(10)
        self.word_lb = _label(word, "word", wrap=False)
        self.ipa_lb = _label("", "muted", wrap=False)
        row.addWidget(self.word_lb)
        row.addWidget(self.ipa_lb)
        row.addStretch(1)
        lay.addLayout(row)
        self.forms_lb = _label("", rich=True)
        self.forms_lb.hide()
        lay.addWidget(self.forms_lb)
        self.here_lb = _label("", rich=True)
        self.here_lb.hide()
        lay.addWidget(self.here_lb)

        sep = QFrame()
        sep.setProperty("role", "sep")
        lay.addWidget(sep)
        self.section_word = _label("ПЕРЕВОД СЛОВА", "section", wrap=False)
        lay.addWidget(self.section_word)
        self.senses_box = QVBoxLayout()
        self.senses_box.setSpacing(6)
        self.loading = _label("Ищу в словаре…", "muted")
        self.senses_box.addWidget(self.loading)
        lay.addLayout(self.senses_box)

        self.examples_lb = _label("", rich=True)
        self.examples_lb.hide()
        lay.addSpacing(4)
        lay.addWidget(self.examples_lb)

        # --- что уйдёт в Obsidian: в авто-режиме предпросмотр, вручную — два поля
        sep2 = QFrame()
        sep2.setProperty("role", "sep")
        lay.addWidget(sep2)
        self.preview = _label("", rich=True)
        lay.addWidget(self.preview)
        self.editor = QWidget()
        el = QVBoxLayout(self.editor)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(6)
        el.addWidget(_label("КАРТОЧКА — ПИШЕШЬ САМ", "section", wrap=False))
        self.front_ed = QLineEdit()
        self.front_ed.setPlaceholderText("слово или фраза (лицевая сторона)")
        self.back_ed = QLineEdit()
        self.back_ed.setPlaceholderText("перевод — впиши сам или нажми на значения выше")
        self.back_ed.returnPressed.connect(self._save)
        el.addWidget(self.front_ed)
        el.addWidget(self.back_ed)
        lay.addWidget(self.editor)
        self.status = _label("", "status")
        lay.addWidget(self.status)

        self._render_context()
        self._apply_mode()
        self._watch = QTimer(self, interval=250, timeout=self._check_distance)

        run_async(translator.dictionary, word, done=self._on_dict, failed=self._on_dict_error)
        run_async(translator.context, paragraph, start, end, done=self._on_ctx, failed=self._on_ctx_error)
        run_async(translator.examples, word, done=self._on_examples, failed=lambda _: None)

    # ---------- показ и закрытие ----------
    def fit(self):
        """Размер по содержимому с учётом переноса строк (adjustSize его не учитывает)."""
        lay = self.layout()
        lay.activate()
        w = WIDTH + lay.contentsMargins().left() + lay.contentsMargins().right()
        self.resize(w, lay.totalHeightForWidth(w))

    def popup(self):
        self.fit()
        self._place()
        self.show()
        self.raise_()
        self.activateWindow()
        self._watch.start()

    def _place(self):
        screen = QGuiApplication.screenAt(self.anchor.center()) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = min(max(avail.left(), self.anchor.left() - 30), avail.right() - w)
        y = self.anchor.bottom() + 4
        if y + h > avail.bottom():
            y = max(avail.top(), self.anchor.top() - h - 4)
        self.move(x, y)

    def _relayout(self):
        if not self.alive:
            return
        top_before = self.y()
        self.fit()
        # если карточка открыта над словом — растём вверх, чтобы не наехать на слово
        if top_before < self.anchor.top():
            self._place()
        else:
            screen = QGuiApplication.screenAt(self.anchor.center()) or QGuiApplication.primaryScreen()
            avail = screen.availableGeometry()
            if self.y() + self.height() > avail.bottom():
                self._place()

    def outside_click(self):
        if self.alive and not self.geometry().contains(QCursor.pos()):
            self.close()

    def _check_distance(self):
        g = self.geometry().adjusted(-220, -160, 220, 160)
        if not g.contains(QCursor.pos()) and not self.anchor.contains(QCursor.pos()):
            self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        self.alive = False
        self._watch.stop()
        self.closed.emit()
        super().closeEvent(e)

    # ---------- контекст ----------
    def _toggle_expand(self):
        self.expanded = not self.expanded
        self.more.setText("свернуть" if self.expanded else "показать весь абзац")
        self._render_context()
        self._relayout()

    def _render_context(self):
        text, s, e = self.full if self.expanded else self.short[:3]
        self.orig.setText(mark(text, s, e, self.t))
        if self.ctx is None:
            return
        tr = self.ctx.text
        hl = self.ctx.hl
        if hl is None and self.info is not None:
            cands = self.info.chips() + ([self.info.verbs[0].ru] if self.info.verbs else [])
            hl = find_highlight(tr, cands)
        self.trans.setProperty("role", "")
        self.trans.setStyleSheet(f"color: {self.t.text};")
        self.trans.setText(mark(tr, hl[0], hl[1], self.t) if hl else html.escape(tr))

    def _on_ctx(self, ct: ContextTranslation):
        if not self.alive:
            return
        self.ctx = ct
        self._render_context()
        if ct.contextual:
            self.here_lb.setText(f'<span style="color:{self.t.muted}">здесь:</span> '
                                 f'<b style="color:{self.t.accent}">{html.escape(ct.contextual)}</b>')
            self.here_lb.show()
            self._add_contextual_chip()
        self._update_status()
        self._relayout()

    def _on_ctx_error(self, msg: str):
        if not self.alive:
            return
        self.trans.setText(html.escape(f"Перевод абзаца недоступен: {msg}"))
        self._relayout()

    # ---------- словарь ----------
    def _on_dict(self, info: WordInfo):
        if not self.alive:
            return
        self.info = info
        self.loading.hide()
        title = info.surface if info.lemma == info.surface.lower() else f"{info.surface} → {info.lemma}"
        self.word_lb.setText(title)
        self.ipa_lb.setText(info.ipa)
        if info.lang == "ru":
            self.section_word.setText("ПЕРЕВОД НА АНГЛИЙСКИЙ")
        if info.verbs:
            v = info.verbs[0]
            kinds = v.kinds_of(info.surface)
            parts = []
            for kind, forms in (("V1", (v.base,)), ("V2", v.past), ("V3", v.participle)):
                txt = html.escape("/".join(forms))
                if kind in kinds:
                    txt = f'<span style="background:{self.t.mark_bg};color:{self.t.mark_text};font-weight:600">' \
                          f'&nbsp;{txt}&nbsp;</span>'
                parts.append(txt)
            self.forms_lb.setText(f'<span style="color:{self.t.muted}">неправильный глагол:</span> '
                                  + " — ".join(parts))
            self.forms_lb.show()
        self._build_senses(info)
        if self.ctx:
            self._render_context()  # подсветка по словарю для перевода без DeepL
        run_async(self.cards.is_saved, info, done=self._on_saved_state, failed=lambda _: None)
        self._update_status()
        self._relayout()

    def _on_dict_error(self, msg: str):
        if not self.alive:
            return
        self.loading.setText(f"Словарь недоступен: {msg}")
        self._relayout()

    def _make_chip(self, text: str) -> QPushButton:
        chip = QPushButton(text)
        chip.setProperty("role", "chip")
        chip.setCheckable(True)
        chip.setCursor(Qt.PointingHandCursor)
        chip.toggled.connect(lambda on, c=chip: self._on_chip(c, on))
        self.chips.append(chip)
        return chip

    @staticmethod
    def _check(chip: QPushButton, on: bool):
        chip.blockSignals(True)
        chip.setChecked(on)
        chip.blockSignals(False)

    def _on_chip(self, chip: QPushButton, on: bool):
        self.user_touched_chips = True
        if not self.cfg.auto_select:
            # вручную: значение дописывается в поле перевода или убирается из него
            term = self._card_text(chip.text())
            # для русского слова значения английские — они идут на лицевую сторону
            field = self.front_ed if self.info is not None and self.info.lang == "ru" else self.back_ed
            parts = [p.strip() for p in field.text().split(",") if p.strip()]
            if on and term not in parts:
                parts.append(term)
            elif not on:
                parts = [p for p in parts if p != term]
            field.setText(", ".join(parts))
        self._update_preview()

    def _card_text(self, text: str) -> str:
        return strip_stress(text) if self.cfg.strip_stress_in_card else text

    def _default_selection(self):
        """Автовыбор: «в этом тексте» (если есть) + первые N значений словаря."""
        for c in self.chips:
            self._check(c, False)
        n = max(1, self.cfg.meanings_in_card)
        contextual = (self.ctx.contextual.strip(" .,!?:;«»\"'").lower() if self.ctx and self.ctx.contextual else "")
        picked = [c for c in self.chips if contextual and strip_stress(c.text()).lower() == contextual]
        for c in self.chips:
            if len(picked) >= n:
                break
            if c not in picked:
                picked.append(c)
        for c in picked:
            self._check(c, True)

    def _build_senses(self, info: WordInfo):
        seen = set()
        shown = 0
        if not info.senses and info.alone:
            self.senses_box.addWidget(_flow_row([self._make_chip(info.alone)]))
        for sense in info.senses:
            terms = [t for t in sense.terms if strip_stress(t).lower() not in seen][:MAX_TERMS_PER_SENSE]
            if not terms:
                continue
            if shown >= MAX_SENSES:
                break
            shown += 1
            seen.update(strip_stress(t).lower() for t in terms)
            head = _label(f'<span style="color:{self.t.accent};font-weight:600">{html.escape(sense.pos)}</span>'
                          f'&nbsp; <span style="color:{self.t.muted}">{html.escape(sense.gloss)}</span>', rich=True)
            head.ensurePolished()
            head.setFixedHeight(head.heightForWidth(CONTENT_W))
            if shown > 1:
                self.senses_box.addSpacing(8)
            self.senses_box.addWidget(head)
            self.senses_box.addWidget(_flow_row([self._make_chip(t) for t in terms]))
        if not self.chips:
            self.senses_box.addWidget(_label("В словаре нет русского перевода этого слова.", "muted"))
        if self.ctx and self.ctx.contextual:
            self._add_contextual_chip()
        if self.cfg.auto_select:
            self._default_selection()
        self.bookmark.setEnabled(True)
        self._update_preview()

    def _add_contextual_chip(self):
        """Перевод слова «в этом тексте» (DeepL) — отдельным чипом первым."""
        if self.info is None or not self.ctx or not self.ctx.contextual:
            return
        word = self.ctx.contextual.strip(" .,!?:;«»\"'")
        if word and not any(strip_stress(c.text()).lower() == word.lower() for c in self.chips):
            chip = self._make_chip(word)
            self.chips.remove(chip)
            self.chips.insert(0, chip)
            self.senses_box.insertWidget(0, _flow_row([_label("в этом тексте:", "muted", wrap=False), chip]))
        if self.cfg.auto_select and not self.user_touched_chips:
            self._default_selection()
        self._update_preview()

    # ---------- автовыбор / вручную ----------
    def _set_auto(self, on: bool):
        self.cfg.auto_select = on
        try:
            self.cfg.save()
        except OSError:
            pass
        self.user_touched_chips = False
        if on:
            self._default_selection()
        else:
            for c in self.chips:
                self._check(c, False)
            self.front_ed.clear()
            self.back_ed.clear()
            self._prefill_manual()
        self._apply_mode()
        self._update_preview()
        if not on:
            self.front_ed.setFocus()
        self._relayout()

    def _apply_mode(self):
        auto = self.cfg.auto_select
        self.editor.setVisible(not auto)
        self.preview.setVisible(auto)
        if not auto and not self.front_ed.text() and not self.back_ed.text():
            self._prefill_manual()

    def _prefill_manual(self):
        """Слово с экрана — в поле своего языка: английское на лицевую сторону, русское на обратную."""
        word = self.word.lower() if self.word[1:].islower() else self.word
        if is_russian(word):
            self.back_ed.setText(word)
        else:
            self.front_ed.setText(word)

    def _update_preview(self):
        if not self.cfg.auto_select or self.info is None:
            return
        m = self.t.muted
        if self.info.verbs:
            fronts = CardMaker._verb_fronts(self.info.verbs[0], self.cfg.irregular_mode)
            what = (f"{len(fronts)} карточки: {', '.join(fronts)}" if len(fronts) > 1 else fronts[0])
            text = (f'<span style="color:{m}">в Obsidian →</span> {html.escape(what)} '
                    f'<span style="color:{m}">(неправильный глагол)</span>')
        else:
            chosen = ", ".join(dict.fromkeys(self._card_text(c.text()) for c in self.chips if c.isChecked()))
            chosen_html = html.escape(chosen) or "<i>выбери значения</i>"
            lemma = f"<b>{html.escape(self.info.lemma)}</b>"
            sep = f'<span style="color:{m}">:::</span>'
            # русское слово: лицевая сторона — английский перевод, как и у остальных карточек
            pair = f"{chosen_html} {sep} {lemma}" if self.info.lang == "ru" else f"{lemma} {sep} {chosen_html}"
            text = f'<span style="color:{m}">в Obsidian →</span> {pair}'
        self.preview.setText(text)

    def _on_examples(self, examples):
        if not self.alive or not examples:
            return
        rows = []
        for en, ru in examples[:2]:
            rows.append(f'<div style="margin-top:4px">{html.escape(en)}<br>'
                        f'<span style="color:{self.t.muted}">{html.escape(ru)}</span></div>')
        self.examples_lb.setText(f'<span style="color:{self.t.muted};font-size:11px;font-weight:600">'
                                 f'ПРИМЕРЫ</span>' + "".join(rows))
        self.examples_lb.show()
        self._relayout()

    def _update_status(self):
        parts = []
        if self.ctx:
            parts.append(self.ctx.engine)
        if self.info:
            parts.append("Wiktionary")
            if self.info.errors:
                parts.append("⚠ " + self.info.errors[0])
        self.status.setText(" · ".join(parts))

    # ---------- закладка ----------
    def _on_saved_state(self, saved: bool):
        if self.alive:
            self.bookmark.set_saved(saved)

    def _save(self):
        if self.bookmark.busy:
            return
        if not self.cfg.auto_select:
            front, back = self.front_ed.text().strip(), self.back_ed.text().strip()
            if not front or not back:
                self.status.setText("Заполни оба поля карточки: слово и перевод")
                (self.back_ed if front else self.front_ed).setFocus()
                return
            self.bookmark.set_busy(True)
            self.status.setText("Сохраняю в Obsidian…")
            run_async(self.cards.save_phrase, front, back, done=self._on_saved, failed=self._on_save_error)
            return
        if self.info is None:
            return
        chosen = [c.text() for c in self.chips if c.isChecked()]
        self.bookmark.set_busy(True)
        self.status.setText("Сохраняю в Obsidian…")
        run_async(self.cards.save_word, self.info, chosen, done=self._on_saved, failed=self._on_save_error)

    def _on_saved(self, res):
        if not self.alive:
            return
        self.bookmark.set_busy(False)
        if res.file is not None:
            self.bookmark.set_saved(True)
        self.status.setText(res.message)
        self._relayout()

    def _on_save_error(self, msg: str):
        if not self.alive:
            return
        self.bookmark.set_busy(False)
        self.status.setText(f"Не удалось сохранить: {msg}")
