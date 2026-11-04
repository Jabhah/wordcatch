"""Общие элементы интерфейса: тема, фоновые задачи, FlowLayout, кнопка-закладка."""
from __future__ import annotations

import html
import traceback
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPoint, QRect, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QApplication, QLayout, QStyleFactory, QToolButton, QWidgetItem


@dataclass(frozen=True)
class Theme:
    bg: str
    surface: str
    text: str
    muted: str
    border: str
    accent: str
    accent_text: str
    mark_bg: str
    mark_text: str
    chip_bg: str
    chip_on_bg: str
    chip_on_text: str


DARK = Theme(bg="#1c1d22", surface="#25262d", text="#ecebe8", muted="#9b9ba6", border="#383943",
             accent="#f2b544", accent_text="#1c1d22", mark_bg="#5b4716", mark_text="#ffd77a",
             chip_bg="#2e2f37", chip_on_bg="#f2b544", chip_on_text="#1c1d22")
LIGHT = Theme(bg="#ffffff", surface="#f5f5f7", text="#1d1d21", muted="#6b6b76", border="#dedee4",
              accent="#c98a10", accent_text="#ffffff", mark_bg="#ffe6a3", mark_text="#5a3d00",
              chip_bg="#efeff3", chip_on_bg="#c98a10", chip_on_text="#ffffff")


def theme_for(name: str) -> Theme:
    return LIGHT if name == "light" else DARK


def _theme_icons(t: Theme) -> dict[str, str]:
    """SVG-значки (стрелка списка, галочка) в цветах темы; Qt берёт их по пути к файлу."""
    from ..config import app_dir
    folder = app_dir() / "theme"
    folder.mkdir(exist_ok=True)
    name = "light" if t is LIGHT else "dark"
    files = {
        "chevron": f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
                   f'<path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="{t.muted}" stroke-width="1.6" '
                   f'stroke-linecap="round" stroke-linejoin="round"/></svg>',
        "check": f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
                 f'<path d="M2.5 6.2 5 8.6l4.6-5" fill="none" stroke="{t.accent_text}" stroke-width="1.8" '
                 f'stroke-linecap="round" stroke-linejoin="round"/></svg>',
    }
    out = {}
    for key, svg in files.items():
        path = folder / f"{key}_{name}.svg"
        if not path.exists() or path.read_text(encoding="utf-8") != svg:
            path.write_text(svg, encoding="utf-8")
        out[key] = path.as_posix()
    return out


def stylesheet(t: Theme) -> str:
    icons = _theme_icons(t)
    return f"""
    QWidget#card {{ background: {t.bg}; border: 1px solid {t.border}; border-radius: 12px; }}
    QWidget#card QLabel {{ color: {t.text}; background: transparent; }}
    QLabel[role="muted"] {{ color: {t.muted}; }}
    QLabel[role="section"] {{ color: {t.muted}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
    QLabel[role="word"] {{ font-size: 20px; font-weight: 600; }}
    QLabel[role="pos"] {{ color: {t.accent}; font-weight: 600; }}
    QLabel[role="status"] {{ color: {t.muted}; font-size: 11px; }}
    QFrame[role="sep"] {{ background: {t.border}; max-height: 1px; min-height: 1px; border: none; }}
    QWidget#contextBox {{ background: {t.surface}; border-radius: 8px; }}
    QPushButton[role="chip"] {{ background: {t.chip_bg}; color: {t.text}; border: 1px solid {t.border};
        border-radius: 12px; padding: 3px 10px; }}
    QPushButton[role="chip"]:checked {{ background: {t.chip_on_bg}; color: {t.chip_on_text};
        border-color: {t.chip_on_bg}; }}
    QPushButton[role="chip"]:hover {{ border-color: {t.accent}; }}
    QPushButton[role="toggle"] {{ background: transparent; color: {t.muted}; border: 1px solid {t.border};
        border-radius: 10px; padding: 2px 10px; font-size: 11px; font-weight: 600; }}
    QPushButton[role="toggle"]:checked {{ background: {t.accent}; color: {t.accent_text};
        border-color: {t.accent}; }}
    QPushButton[role="toggle"]:hover {{ border-color: {t.accent}; }}
    QPushButton[role="link"] {{ background: transparent; color: {t.accent}; border: none; padding: 0; }}
    QWidget#window {{ background: {t.bg}; }}
    QWidget#window QLabel {{ color: {t.text}; }}
    QTextEdit {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; border-radius: 8px;
        padding: 6px; selection-background-color: {t.accent}; selection-color: {t.accent_text}; }}
    QScrollArea {{ background: {t.bg}; border: none; }}
    QPushButton {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; border-radius: 6px;
        padding: 5px 12px; }}
    QPushButton:hover {{ border-color: {t.accent}; }}
    QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; }}
    QDialog {{ background: {t.bg}; }}
    QDialog QLabel, QCheckBox {{ color: {t.text}; background: transparent; }}
    QLineEdit, QComboBox, QSpinBox {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
        border-radius: 6px; padding: 4px 8px; selection-background-color: {t.accent};
        selection-color: {t.accent_text}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {t.accent}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow {{ image: url("{icons['chevron']}"); width: 12px; height: 12px; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {t.muted}; border-radius: 4px;
        background: {t.surface}; }}
    QCheckBox::indicator:hover {{ border-color: {t.accent}; }}
    QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent};
        image: url("{icons['check']}"); }}
    QComboBox QAbstractItemView {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
        selection-background-color: {t.accent}; selection-color: {t.accent_text}; }}
    QMenu {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; padding: 4px; }}
    QMenu::item {{ padding: 5px 22px 5px 22px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
    QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 8px; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; }}
    QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """


def apply_theme(app: QApplication, t: Theme) -> None:
    """Тема программы не зависит от тёмного/светлого режима Windows: своя палитра,
    своя схема цветов (заголовки окон) и общий стиль Fusion, который одинаково слушается палитры."""
    app.setStyle(QStyleFactory.create("Fusion"))
    pal = QPalette()
    for role, color in ((QPalette.Window, t.bg), (QPalette.WindowText, t.text), (QPalette.Base, t.surface),
                        (QPalette.AlternateBase, t.bg), (QPalette.Text, t.text), (QPalette.Button, t.surface),
                        (QPalette.ButtonText, t.text), (QPalette.ToolTipBase, t.surface),
                        (QPalette.ToolTipText, t.text), (QPalette.Highlight, t.accent),
                        (QPalette.HighlightedText, t.accent_text), (QPalette.PlaceholderText, t.muted),
                        (QPalette.Link, t.accent), (QPalette.Mid, t.border), (QPalette.Dark, t.border)):
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(t.muted))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(t.muted))
    app.setPalette(pal)
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light if t is LIGHT else Qt.ColorScheme.Dark)
    except AttributeError:  # Qt < 6.8
        pass
    app.setStyleSheet(stylesheet(t))


def mark(text: str, start: int, end: int, t: Theme) -> str:
    """HTML с подсвеченным фрагментом text[start:end]."""
    if start < 0 or end <= start:
        return html.escape(text)
    return (html.escape(text[:start])
            + f'<span style="background:{t.mark_bg}; color:{t.mark_text}; font-weight:600;">'
            + html.escape(text[start:end]) + "</span>" + html.escape(text[end:]))


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    """Запускает функцию в пуле потоков; результат приходит сигналом в главный поток."""

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args
        self.signals = _Signals()

    def run(self):
        try:
            result = self.fn(*self.args)
        except Exception as e:  # noqa: BLE001 — показываем пользователю текст ошибки
            traceback.print_exc()
            self.signals.failed.emit(str(e) or e.__class__.__name__)
        else:
            self.signals.done.emit(result)


_pool: QThreadPool | None = None
_alive: set[Task] = set()


def _get_pool() -> QThreadPool:
    global _pool
    if _pool is None:
        _pool = QThreadPool()
        _pool.setMaxThreadCount(6)
    return _pool


def run_async(fn, *args, done=None, failed=None) -> Task:
    task = Task(fn, *args)
    task.setAutoDelete(False)
    _alive.add(task)

    def finish(*_):
        _alive.discard(task)

    if done:
        task.signals.done.connect(done)
    if failed:
        task.signals.failed.connect(failed)
    task.signals.done.connect(finish)
    task.signals.failed.connect(finish)
    _get_pool().start(task)
    return task


class FlowLayout(QLayout):
    """Раскладка «чипов» с переносом строк."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def addWidget(self, w):
        self.addItem(QWidgetItem(w))
        self.addChildWidget(w)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _layout(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            if x + hint.width() > rect.right() and line_h > 0:
                x, y = rect.x(), y + line_h + self._spacing
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class BookmarkButton(QToolButton):
    """Закладка-лента в правом верхнем углу: контур — не добавлено, заливка — уже в колоде."""

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.saved = False
        self.busy = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(30, 36)
        self.setToolTip("Добавить карточку в Obsidian (Spaced Repetition)")
        self.setStyleSheet("QToolButton { border: none; background: transparent; }")

    def set_saved(self, saved: bool):
        self.saved = saved
        self.setToolTip("Уже в колоде Obsidian" if saved else "Добавить карточку в Obsidian (Spaced Repetition)")
        self.update()

    def set_busy(self, busy: bool):
        self.busy = busy
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        path = QPainterPath()
        x0, x1, top, bottom = 7, w - 7, 2, h - 4
        path.moveTo(x0, top)
        path.lineTo(x1, top)
        path.lineTo(x1, bottom)
        path.lineTo((x0 + x1) / 2, bottom - 8)
        path.lineTo(x0, bottom)
        path.closeSubpath()
        color = QColor(self.theme.accent)
        if self.underMouse() and not self.saved:
            color = color.lighter(115)
        if self.busy:
            color.setAlpha(120)
        p.setPen(QPen(color, 2))
        p.setBrush(color if self.saved else Qt.NoBrush)
        p.drawPath(path)
        if not self.saved:  # «+» внутри
            cx, cy = (x0 + x1) / 2, top + (bottom - top) / 2 - 3
            p.drawLine(int(cx - 4), int(cy), int(cx + 4), int(cy))
            p.drawLine(int(cx), int(cy - 4), int(cx), int(cy + 4))

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)
