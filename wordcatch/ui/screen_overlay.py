"""Быстрый перевод экрана: перевод рисуется прямо поверх каждого абзаца, на его месте.

Прочитал — Esc или клик, и работаешь дальше. Пробел (держать) показывает оригинал,
клик по абзацу переключает только его, Tab — выбор абзацев, Enter — перевод в отдельном окне.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..capture import Shot
from ..layout import Block, is_russian
from .common import Theme

HINT = "Esc / клик мимо — закрыть  ·  пробел (держать) — оригинал  ·  клик по абзацу — оригинал/перевод  ·  " \
       "Tab — выбрать абзацы  ·  Enter — в окне"
MIN_PX = 9.0
WRAP = Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop


@dataclass
class Item:
    block: Block
    rect: QRectF            # логические координаты внутри окна
    text: str               # оригинал
    bg: QColor
    fg: QColor
    translation: str = ""
    box: QRectF | None = None   # куда помещается перевод (может быть выше исходного блока)
    font_px: float = 0.0
    show_original: bool = False


def background_of(image: QImage, r: QRectF, dpr: float) -> QColor:
    """Цвет фона вокруг абзаца: среднее по точкам чуть снаружи рамки (там нет букв)."""
    x0, y0 = int(r.left() * dpr) - 3, int(r.top() * dpr) - 3
    x1, y1 = int(r.right() * dpr) + 3, int(r.bottom() * dpr) + 3
    pts = []
    for fx in (0.0, 0.25, 0.5, 0.75, 1.0):
        x = int(x0 + (x1 - x0) * fx)
        pts += [(x, y0), (x, y1)]
    for fy in (0.33, 0.66):
        y = int(y0 + (y1 - y0) * fy)
        pts += [(x0, y), (x1, y)]
    rs = gs = bs = n = 0
    for x, y in pts:
        if 0 <= x < image.width() and 0 <= y < image.height():
            c = image.pixelColor(x, y)
            rs, gs, bs, n = rs + c.red(), gs + c.green(), bs + c.blue(), n + 1
    return QColor(rs // n, gs // n, bs // n) if n else QColor("#ffffff")


def text_color_for(bg: QColor) -> QColor:
    lum = (0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()) / 255
    return QColor("#141414") if lum > 0.55 else QColor("#f3f3f3")


def fit_text(text: str, rect: QRectF, start_px: float, base: QFont, limit: QRectF) -> tuple[QRectF, float]:
    """Подбирает размер шрифта, чтобы перевод влез в место оригинала. Если даже мелким шрифтом
    не влезает (русский длиннее английского), рамка растёт вниз, но не дальше края экрана."""
    px = max(MIN_PX, start_px)
    floor = max(MIN_PX, start_px * 0.75)   # мельче не ужимаем — лучше пусть рамка вырастет вниз
    f = QFont(base)
    while True:
        f.setPixelSize(round(px))
        need = QFontMetricsF(f).boundingRect(QRectF(0, 0, rect.width(), 1e6), WRAP, text).height()
        if need <= rect.height() * 1.08 or px <= floor:
            break
        px -= 0.5 if px < 14 else 1
    box = QRectF(rect)
    if need > rect.height():
        box.setHeight(min(need, limit.bottom() - rect.top()))
    return box, round(px)


class ScreenOverlay(QWidget):
    to_picker = Signal()          # Tab: перейти к выбору абзацев на том же снимке
    to_window = Signal(list)      # Enter: открыть оригинал/перевод в отдельном окне

    def __init__(self, shot: Shot, theme: Theme):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.shot, self.t = shot, theme
        self.items: list[Item] = []
        self.blocks: list[Block] = []
        self.peek = False
        self.message = "Распознаю текст…"
        self.font_base = QFont("Segoe UI")
        self.setGeometry(shot.screen.geometry())
        self.setMouseTracking(True)

    def start(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    # ---------- данные ----------
    def set_blocks(self, blocks: list[Block]) -> list[str]:
        """Принимает абзацы после OCR; возвращает тексты, которые надо перевести.
        Русские абзацы не трогаем — их и так можно прочитать."""
        self.blocks = blocks
        origin = self.geometry().topLeft()
        for b in blocks:
            text = b.text.strip()
            if not text or is_russian(text) or not any(ch.isalpha() for ch in text):
                continue
            r = self.shot.to_logical(b.rect).translated(-origin.x(), -origin.y())
            bg = background_of(self.shot.image, r, self.shot.dpr)
            self.items.append(Item(b, r.adjusted(-2, -1, 2, 1), text, bg, text_color_for(bg)))
        self.message = "Перевожу…" if self.items else "Текста для перевода не нашлось  ·  Esc — закрыть"
        self.update()
        return [it.text for it in self.items]

    def set_translations(self, translations: list[str]):
        limit = QRectF(self.rect())
        for it, tr in zip(self.items, translations):
            it.translation = tr.strip()
            lines = max(1, len(it.block.lines))
            # стартовый размер — примерно как у оригинала (высота строки без межстрочного интервала)
            start = it.rect.height() / lines * 0.78
            it.box, it.font_px = fit_text(it.translation, it.rect, start, self.font_base, limit)
        self.message = HINT
        self.update()

    def set_error(self, msg: str):
        self.message = f"{msg}  ·  Esc — закрыть"
        self.update()

    # ---------- рисование ----------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.drawImage(QRectF(self.rect()), self.shot.image)
        if not self.peek:
            for it in self.items:
                if not it.translation or it.show_original or it.box is None:
                    continue
                p.setPen(Qt.NoPen)
                p.setBrush(it.bg)
                p.drawRoundedRect(it.box.adjusted(-2, -1, 2, 1), 3, 3)
                # тонкая полоска слева — видно, что это перевод
                p.setBrush(QColor(self.t.accent))
                p.drawRoundedRect(QRectF(it.box.left() - 4, it.box.top(), 2, it.box.height()), 1, 1)
                f = QFont(self.font_base)
                f.setPixelSize(int(it.font_px))
                p.setFont(f)
                p.setPen(it.fg)
                p.drawText(it.box, WRAP, it.translation)
        self._draw_hint(p)

    def _draw_hint(self, p: QPainter):
        f = QFont(self.font())
        f.setPointSizeF(9.5)
        p.setFont(f)
        text = "Оригинал (отпусти пробел — перевод)" if self.peek else self.message
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 30
        box = QRectF((self.width() - w) / 2, self.height() - fm.height() - 34, w, fm.height() + 14)
        p.setPen(QPen(QColor(self.t.border), 1))
        bg = QColor(self.t.bg)
        bg.setAlpha(235)
        p.setBrush(bg)
        p.drawRoundedRect(box, 9, 9)
        p.setPen(QColor(self.t.text))
        p.drawText(box, Qt.AlignCenter, text)

    # ---------- управление ----------
    def _item_at(self, pos) -> Item | None:
        for it in self.items:
            if (it.box or it.rect).contains(pos):
                return it
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            it = self._item_at(e.position())
            if it is not None and it.translation:
                it.show_original = not it.show_original
                self.update()
                return
        self.close()   # клик мимо абзацев или правой кнопкой — закрыть и работать дальше

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Space and not e.isAutoRepeat():
            self.peek = True
            self.update()
        elif k == Qt.Key_Tab:
            self.to_picker.emit()
            self.close()
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            if self.items:
                self.to_window.emit([it.text for it in self.items])
            self.close()
        elif k == Qt.Key_Space:
            pass
        else:
            self.close()   # Esc и вообще любая другая клавиша — закрыть

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self.peek = False
            self.update()
