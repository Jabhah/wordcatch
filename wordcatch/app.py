"""Главный контроллер: трей, хоткеи, выбор режима (слово / блоки на экране)."""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QRect, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import APP_NAME, capture, ocr
from .capture import Shot
from .cards import CardMaker
from .config import Config, app_dir
from .hotkeys import HotkeyManager
from .layout import context_of, group_blocks, word_at
from .translate.service import Translator
from .ui.common import apply_theme, run_async, theme_for
from .ui.result_window import ResultWindow
from .ui.screen_picker import ScreenPicker
from .ui.settings_dialog import SettingsDialog
from .ui.word_popup import WordPopup

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
PROJECT_DIR = Path(__file__).resolve().parents[1]
BAND_HALF_HEIGHT = 220  # сколько экрана выше и ниже курсора распознаём в режиме слова (логические px)


def make_icon_pixmap(accent: str, size: int = 64) -> QPixmap:
    """Значок «Aя»: рисуется в сетке 64×64 и масштабируется до нужного размера."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.scale(size / 64, size / 64)
    p.setBrush(QColor(accent))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    p.setPen(QColor("#1c1d22"))
    f = QFont("Segoe UI")
    f.setPixelSize(30)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRect(0, -2, 64, 64), Qt.AlignCenter, "Aя")
    p.end()
    return pix


def make_icon(accent: str) -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64):
        icon.addPixmap(make_icon_pixmap(accent, size))
    return icon


def autostart_command() -> str:
    if getattr(sys, "frozen", False):  # собранный WordCatch.exe
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe") if exe.name.lower() == "python.exe" else exe
    return f'"{pyw}" "{PROJECT_DIR / "run.pyw"}"'


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(on: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


class Controller(QObject):
    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.cfg = Config.load()
        self.translator = Translator(self.cfg)
        self.cards = CardMaker(self.cfg, self.translator)
        self.theme = theme_for(self.cfg.theme)
        apply_theme(qapp, self.theme)
        self.popup: WordPopup | None = None
        self.picker: ScreenPicker | None = None
        self.windows: list[ResultWindow] = []
        self.busy = False

        self.hotkeys = HotkeyManager()
        self.hotkeys.triggered.connect(self.on_trigger, Qt.QueuedConnection)
        self.hotkeys.mouse_pressed.connect(self.on_mouse_pressed, Qt.QueuedConnection)
        self.hotkeys.error.connect(lambda m: self.tray.showMessage(APP_NAME, m, QSystemTrayIcon.Warning),
                                   Qt.QueuedConnection)
        self._build_tray()
        self.hotkeys.start(self.cfg.hotkey, self.cfg.mouse_button, self.cfg.suppress_mouse_button)

        engine = "DeepL" if self.cfg.deepl_key else "MyMemory (5 000 символов в день; ключ DeepL — в настройках)"
        self.tray.showMessage(APP_NAME, f"Наведи на слово и нажми {self.hotkey_text()}. Перевод: {engine}",
                              QSystemTrayIcon.Information, 4000)

    # ---------- трей ----------
    def hotkey_text(self) -> str:
        names = {"x1": " или боковую кнопку «назад»", "x2": " или боковую кнопку «вперёд»"}
        return self.cfg.hotkey.upper().replace("+", " + ") + names.get(self.cfg.mouse_button, "")

    def _build_tray(self):
        self.tray = QSystemTrayIcon(make_icon(self.theme.accent), self.qapp)
        self.tray.setToolTip(f"{APP_NAME} — {self.cfg.hotkey.upper()}")
        menu = QMenu()
        self.pause_act = QAction("Пауза", menu, checkable=True)
        self.pause_act.toggled.connect(self._toggle_pause)
        menu.addAction(self.pause_act)
        menu.addAction("Настройки…", self.open_settings)
        menu.addAction("Открыть файл карточек", self.open_cards_file)
        auto = QAction("Запускать вместе с Windows", menu, checkable=True)
        auto.setChecked(autostart_enabled())
        auto.toggled.connect(set_autostart)
        menu.addAction(auto)
        menu.addSeparator()
        menu.addAction("Выход", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.open_settings() if r == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()
        self._menu = menu

    def _toggle_pause(self, on: bool):
        self.hotkeys.paused = on
        self.tray.setToolTip(f"{APP_NAME} — {'на паузе' if on else self.cfg.hotkey.upper()}")

    def open_settings(self):
        dlg = SettingsDialog(self.cfg)
        if dlg.exec():
            new = dlg.result_config()
            new.save()
            for f in vars(new):
                setattr(self.cfg, f, getattr(new, f))  # общий объект у переводчика и карточек
            self.theme = theme_for(self.cfg.theme)
            apply_theme(self.qapp, self.theme)
            self.tray.setIcon(make_icon(self.theme.accent))
            self.hotkeys.start(self.cfg.hotkey, self.cfg.mouse_button, self.cfg.suppress_mouse_button)
            self.tray.setToolTip(f"{APP_NAME} — {self.cfg.hotkey.upper()}")

    def open_cards_file(self):
        vault = self.cards.vault()
        if not vault:
            self.tray.showMessage(APP_NAME, "Хранилище Obsidian не найдено — укажи его в настройках")
            return
        path = vault / self.cfg.words_file
        target = path if path.exists() else path.parent if path.parent.exists() else vault
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def quit(self):
        self.hotkeys.stop()
        self.tray.hide()
        self.qapp.quit()

    # ---------- хоткей ----------
    def on_mouse_pressed(self):
        if self.popup is not None:
            self.popup.outside_click()

    def on_trigger(self):
        if self.busy or self.picker is not None:
            return
        if self.popup is not None:
            self.popup.close()
        pos = QCursor.pos()
        screen = capture.screen_at(pos)
        full = capture.grab(screen)  # снимок сразу, до любых изменений на экране
        geo = screen.geometry()
        band = QRect(geo.left(), pos.y() - BAND_HALF_HEIGHT, geo.width(), 2 * BAND_HALF_HEIGHT).intersected(geo)
        top_px = round((band.top() - geo.top()) * full.dpr)
        crop = Shot(screen, full.image.copy(0, top_px, full.image.width(), round(band.height() * full.dpr)),
                    band.topLeft(), full.dpr)
        self.busy = True
        run_async(self._find_word, crop, pos,
                  done=lambda res: self._on_word_search(res, full, crop),
                  failed=self._on_ocr_error)

    def _find_word(self, crop: Shot, pos):
        lines = capture.recognize(crop, self.cfg.ocr_scale)
        x, y = crop.to_image(pos)
        hit = word_at(lines, x, y, tol=4 * crop.dpr)
        return (lines, hit)

    def _on_ocr_error(self, msg: str):
        self.busy = False
        self.tray.showMessage(APP_NAME, f"Не удалось распознать текст: {msg}", QSystemTrayIcon.Warning)

    def _on_word_search(self, res, full: Shot, crop: Shot):
        self.busy = False
        lines, hit = res
        if hit is not None:
            ctx = context_of(lines, hit)
            anchor = crop.to_logical(hit.raw.rect).toAlignedRect()
            self.show_word(hit.word, ctx.text, ctx.start, ctx.end, anchor)
        else:
            self.show_picker(full)

    def show_word(self, word: str, paragraph: str, start: int, end: int, anchor: QRect):
        if self.popup is not None:
            self.popup.close()
        popup = WordPopup(word, paragraph, start, end, anchor, self.cfg, self.translator, self.cards, self.theme)
        popup.closed.connect(lambda p=popup: self._popup_closed(p))
        self.popup = popup
        popup.popup()

    def _popup_closed(self, p):
        if self.popup is p:
            self.popup = None

    # ---------- режим блоков ----------
    def show_picker(self, shot: Shot):
        picker = ScreenPicker(shot, self.theme)
        picker.chosen.connect(self.show_result)
        picker.destroyed.connect(lambda *_: setattr(self, "picker", None))
        self.picker = picker
        picker.start()
        run_async(lambda: group_blocks(capture.recognize(shot, min(self.cfg.ocr_scale, 1.5))),
                  done=lambda blocks: picker.set_blocks(blocks) if self.picker is picker else None,
                  failed=lambda m: picker.set_error(m) if self.picker is picker else None)

    def show_result(self, texts: list[str]):
        win = ResultWindow(texts, self.cfg, self.translator, self.cards, self.theme)
        win.open_word.connect(self.show_word)
        win.destroyed.connect(lambda *_, w=win: self.windows.remove(w) if w in self.windows else None)
        self.windows.append(win)
        win.show()
        win.raise_()
        win.activateWindow()


def selftest(out_path: str) -> int:
    """WordCatch.exe --selftest out.txt — проверка собранного exe: OCR (en+ru), лемматизатор, данные."""
    import simplemma
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication, QImage

    from . import irregular
    from .capture import recognize

    lines_out = []
    try:
        img = QImage(900, 120, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor("white"))
        p = QPainter(img)
        p.setPen(QColor("black"))
        f = QFont("Segoe UI")
        f.setPixelSize(16)
        p.setFont(f)
        p.drawText(10, 40, "They went home early, tired but happy.")
        p.drawText(10, 80, "Они вернулись домой уставшие.")
        p.end()
        shot = Shot(QGuiApplication.primaryScreen(), img, QPoint(0, 0), 1.0)
        lines_out.append("ocr: " + " | ".join(ln.text for ln in recognize(shot, 2.0)))
        lines_out.append(f"ru ocr: {ocr.russian_language()}")
        lines_out.append(f"lemma: {simplemma.lemmatize('struggling', lang='en')} {simplemma.lemmatize('домой', lang='ru')}")
        lines_out.append(f"irregular: {irregular.lookup('went')[0].forms_text}")
        code = 0
    except Exception as e:  # noqa: BLE001
        import traceback
        lines_out.append("ERROR: " + "".join(traceback.format_exception(e)))
        code = 1
    Path(out_path).write_text("\n".join(lines_out), encoding="utf-8")
    return code


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(sys.argv)
    if "--selftest" in sys.argv:
        return selftest(sys.argv[sys.argv.index("--selftest") + 1])
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setFont(QFont("Segoe UI", 10))
    qapp.setWindowIcon(make_icon(theme_for(Config.load().theme).accent))

    lock = QLockFile(str(app_dir() / "wordcatch.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, "WordCatch уже запущен — его значок в трее рядом с часами.")
        return 0
    if not ocr.language_supported():
        QMessageBox.critical(None, APP_NAME, ocr.MISSING_LANGUAGE)
        return 1
    ctrl = Controller(qapp)  # noqa: F841 — держим ссылку до выхода
    code = qapp.exec()
    lock.unlock()
    return code
