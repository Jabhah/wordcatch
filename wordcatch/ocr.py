"""Распознавание текста встроенным Windows OCR (Windows.Media.Ocr)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

OCR_LANG = "en-US"


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    def contains(self, px: float, py: float, tol: float = 0.0) -> bool:
        return self.x - tol <= px <= self.right + tol and self.y - tol <= py <= self.bottom + tol

    def intersects(self, other: "Rect") -> bool:
        return not (other.x > self.right or other.right < self.x or other.y > self.bottom or other.bottom < self.y)

    def united(self, other: "Rect") -> "Rect":
        x, y = min(self.x, other.x), min(self.y, other.y)
        return Rect(x, y, max(self.right, other.right) - x, max(self.bottom, other.bottom) - y)


@dataclass
class Word:
    text: str
    rect: Rect


@dataclass
class Line:
    words: list[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def rect(self) -> Rect:
        r = self.words[0].rect
        for w in self.words[1:]:
            r = r.united(w.rect)
        return r


MISSING_LANGUAGE = (
    "В Windows не установлен английский пакет распознавания текста.\n"
    "Параметры → Время и язык → Язык и регион → Добавить язык → English (United States),\n"
    "или в PowerShell от администратора:\n"
    'Add-WindowsCapability -Online -Name "Language.OCR~~~en-US~0.0.1.0"'
)


class OcrUnavailable(RuntimeError):
    pass


def language_supported() -> bool:
    return OcrEngine.is_language_supported(Language(OCR_LANG))


def russian_language() -> str | None:
    """Тег установленного русского пакета распознавания (ru / ru-RU) или None."""
    for lang in OcrEngine.available_recognizer_languages:
        if lang.language_tag.lower().startswith("ru"):
            return lang.language_tag
    return None


_engines: dict[str, OcrEngine] = {}


def _get_engine(lang: str = OCR_LANG) -> OcrEngine:
    if lang not in _engines:
        if lang == OCR_LANG and not language_supported():
            raise OcrUnavailable(MISSING_LANGUAGE)
        _engines[lang] = OcrEngine.try_create_from_language(Language(lang))
    return _engines[lang]


def max_dimension() -> int:
    return int(OcrEngine.max_image_dimension)


async def _recognize(bgra: bytes, width: int, height: int, lang: str):
    writer = DataWriter()
    writer.write_bytes(bgra)
    bitmap = SoftwareBitmap(BitmapPixelFormat.BGRA8, width, height, BitmapAlphaMode.PREMULTIPLIED)
    bitmap.copy_from_buffer(writer.detach_buffer())
    return await _get_engine(lang).recognize_async(bitmap)


def recognize(bgra: bytes, width: int, height: int, scale: float = 1.0,
              offset_x: float = 0.0, offset_y: float = 0.0, lang: str = OCR_LANG) -> list[Line]:
    """Распознаёт BGRA-картинку. Координаты результата делятся на scale и сдвигаются на offset,
    то есть возвращаются в системе координат исходного (не увеличенного) снимка."""
    result = asyncio.run(_recognize(bgra, width, height, lang))
    lines: list[Line] = []
    for ln in result.lines:
        words = []
        for w in ln.words:
            br = w.bounding_rect
            words.append(Word(w.text, Rect(br.x / scale + offset_x, br.y / scale + offset_y,
                                           br.width / scale, br.height / scale)))
        if words:
            lines.append(Line(words))
    return lines
