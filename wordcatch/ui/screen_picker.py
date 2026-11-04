"""Замороженный экран: все найденные абзацы обведены, клик/рамка выбирают, Enter переводит."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..capture import Shot
from ..layout import Block
from .common import Theme

HINT = "Клик — выбрать абзац  ·  рамка мышью — несколько  ·  Enter или правый клик — перевести " \
       "(без выбора — весь экран)  ·  Esc — выход"


class ScreenPicker(QWidget):
    chosen = Signal(list)      # тексты выбранных блоков в порядке чтения

    def __init__(self, shot: Shot, theme: Theme):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.shot, self.t = shot, theme
        self.blocks: list[Block] = []
        self.rects: list[QRectF] = []
        self.selected: set[int] = set()
        self.hover = -1
        self.drag_from: QPoint | None = None
        self.drag_to: QPoint | None = None
        self.message = "Распознаю текст…"
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(shot.screen.geometry())

    def start(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def set_blocks(self, blocks: list[Block]):
        self.blocks = blocks
        origin = self.geometry().topLeft()
        self.rects = [self.shot.to_logical(b.rect).translated(-origin.x(), -origin.y()).adjusted(-4, -3, 4, 3)
                      for b in blocks]
        self.message = HINT if blocks else "Текст на экране не найден  ·  Esc — выход"
        self.update()

    def set_error(self, msg: str):
        self.message = f"{msg}  ·  Esc — выход"
        self.update()

    # ---------- рисование ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawImage(QRectF(self.rect()), self.shot.image)
        p.fillRect(self.rect(), QColor(0, 0, 0, 70))
        accent = QColor(self.t.accent)
        for i, r in enumerate(self.rects):
            fill = QColor(accent)
            if i in self.selected:
                fill.setAlpha(70)
                p.setPen(QPen(accent, 2.2))
            elif i == self.hover:
                fill.setAlpha(38)
                p.setPen(QPen(accent, 1.6))
            else:
                fill.setAlpha(0)
                p.setPen(QPen(QColor(255, 255, 255, 150), 1, Qt.DashLine))
            p.setBrush(fill)
            p.drawRoundedRect(r, 5, 5)
        band = self._band()
        if band is not None:
            c = QColor(accent)
            c.setAlpha(40)
            p.setPen(QPen(accent, 1.5, Qt.DashLine))
            p.setBrush(c)
            p.drawRect(band)
        self._draw_hint(p)

    def _draw_hint(self, p: QPainter):
        f = QFont(self.font())
        f.setPointSizeF(10.5)
        p.setFont(f)
        text = self.message
        if self.selected:
            text = f"Выбрано: {len(self.selected)}  ·  Enter — перевести  ·  Esc — выход"
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 36
        box = QRectF((self.width() - w) / 2, 18, w, fm.height() + 18)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.t.bg))
        p.drawRoundedRect(box, 10, 10)
        p.setPen(QColor(self.t.text))
        p.drawText(box, Qt.AlignCenter, text)

    def _band(self) -> QRect | None:
        if self.drag_from is None or self.drag_to is None:
            return None
        r = QRect(self.drag_from, self.drag_to).normalized()
        return r if r.width() > 6 or r.height() > 6 else None

    # ---------- мышь и клавиатура ----------
    def _block_at(self, pos) -> int:
        for i, r in enumerate(self.rects):
            if r.contains(pos):
                return i
        return -1

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self._confirm()
        elif e.button() == Qt.LeftButton:
            self.drag_from = self.drag_to = e.position().toPoint()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self.drag_from is not None:
            self.drag_to = pos
        self.hover = self._block_at(pos)
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self.drag_from is None:
            return
        band = self._band()
        if band is not None:
            hits = {i for i, r in enumerate(self.rects) if QRectF(band).intersects(r)}
            self.selected |= hits
        else:
            i = self._block_at(e.position().toPoint())
            if i >= 0:
                self.selected ^= {i}
        self.drag_from = self.drag_to = None
        self.update()

    def mouseDoubleClickEvent(self, e):
        i = self._block_at(e.position().toPoint())
        if i >= 0:
            self.selected = {i}
            self._confirm()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._confirm()
        elif e.key() == Qt.Key_A and e.modifiers() & Qt.ControlModifier:
            self.selected = set(range(len(self.blocks)))
            self.update()

    def _confirm(self):
        if not self.blocks:
            return
        idx = sorted(self.selected or range(len(self.blocks)),
                     key=lambda i: (round(self.rects[i].top() / 12), self.rects[i].left()))
        texts = [self.blocks[i].text for i in idx if self.blocks[i].text.strip()]
        self.close()
        if texts:
            self.chosen.emit(texts)
