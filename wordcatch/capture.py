"""Снимок экрана через Qt и пересчёт координат: пиксели снимка <-> логические координаты Qt."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QScreen

from . import ocr
from .layout import merge_lines
from .ocr import Line, Rect


@dataclass
class Shot:
    screen: QScreen
    image: QImage          # физические пиксели
    origin: QPoint         # логическая глобальная позиция левого верхнего угла снимка
    dpr: float

    def to_image(self, p: QPoint | QPointF) -> tuple[float, float]:
        return (p.x() - self.origin.x()) * self.dpr, (p.y() - self.origin.y()) * self.dpr

    def to_logical(self, r: Rect) -> QRectF:
        return QRectF(self.origin.x() + r.x / self.dpr, self.origin.y() + r.y / self.dpr,
                      r.w / self.dpr, r.h / self.dpr)


def screen_at(pos: QPoint) -> QScreen:
    return QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()


def grab(screen: QScreen, area: QRect | None = None) -> Shot:
    """area — логический прямоугольник в глобальных координатах (None = весь экран)."""
    geo = screen.geometry()
    area = (area or geo).intersected(geo)
    pix = screen.grabWindow(0, area.x() - geo.x(), area.y() - geo.y(), area.width(), area.height())
    image = pix.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
    dpr = image.width() / max(1, area.width())
    return Shot(screen, image, area.topLeft(), dpr)


def recognize(shot: Shot, scale: float = 2.0) -> list[Line]:
    """OCR снимка; координаты строк — в пикселях снимка. Мелкий текст распознаётся лучше с увеличением."""
    img = shot.image
    limit = ocr.max_dimension()
    scale = max(1.0, min(scale, limit / max(img.width(), img.height(), 1)))
    if scale > 1.01:
        img = img.scaled(round(img.width() * scale), round(img.height() * scale),
                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    else:
        scale = 1.0
    # у ARGB32 строка всегда ровно width*4 байт — это и есть BGRA, который ждёт Windows OCR
    data = bytes(img.constBits())
    en = ocr.recognize(data, img.width(), img.height(), scale)
    ru_lang = ocr.russian_language()
    if not ru_lang:
        return en
    # Английский пакет читает кириллицу как латиницу («npuBeT»), поэтому русские строки
    # берём из русского распознавания (оно же нормально читает английские слова внутри русского текста).
    ru = ocr.recognize(data, img.width(), img.height(), scale, lang=ru_lang)
    return merge_lines(en, ru)
