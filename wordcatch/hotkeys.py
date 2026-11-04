"""Глобальные хоткеи: клавиатура через WinAPI RegisterHotKey, кнопки мыши через pynput."""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from pynput import mouse
from PySide6.QtCore import QObject, Signal

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

MOD = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN = 0x0201, 0x0204, 0x0207
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x020B, 0x020C
XBUTTONS = {"x1": 1, "x2": 2}

_NAMED_KEYS = {"space": 0x20, "tab": 0x09, "enter": 0x0D, "esc": 0x1B, "insert": 0x2D, "delete": 0x2E,
               "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "pause": 0x13,
               "`": 0xC0, "~": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE,
               ",": 0xBC, ".": 0xBE, "/": 0xBF, "\\": 0xDC}


def parse_hotkey(text: str) -> tuple[int, int]:
    """«alt+q» -> (MOD_ALT, VK_Q). Бросает ValueError, если не удалось разобрать."""
    parts = [p.strip().lower() for p in text.replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ValueError("пустой хоткей")
    mods = 0
    for p in parts[:-1]:
        if p not in MOD:
            raise ValueError(f"неизвестный модификатор «{p}»")
        mods |= MOD[p]
    key = parts[-1]
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x6F + int(key[1:])
    elif key in _NAMED_KEYS:
        vk = _NAMED_KEYS[key]
    else:
        raise ValueError(f"неизвестная клавиша «{key}»")
    return mods, vk


class HotkeyManager(QObject):
    triggered = Signal()
    mouse_pressed = Signal()     # любой клик мышью (для закрытия всплывающих окон)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self._kb_thread: threading.Thread | None = None
        self._kb_thread_id = 0
        self._mouse: mouse.Listener | None = None
        self._xbutton = 0
        self._suppress = True
        self.paused = False

    # ---------- клавиатура ----------
    def _kb_loop(self, mods: int, vk: int, ready: threading.Event):
        self._kb_thread_id = kernel32.GetCurrentThreadId()
        ok = user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk)
        ready.set()
        if not ok:
            self.error.emit("Не удалось занять хоткей — возможно, он уже используется другой программой. "
                            "Выбери другой в настройках.")
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and not self.paused:
                self.triggered.emit()
        user32.UnregisterHotKey(None, 1)

    # ---------- мышь ----------
    def _mouse_filter(self, msg, data):
        if msg in (WM_XBUTTONDOWN, WM_XBUTTONUP) and self._xbutton:
            button = (data.mouseData >> 16) & 0xFFFF
            if button == self._xbutton and not self.paused:
                if msg == WM_XBUTTONDOWN:
                    self.triggered.emit()
                if self._suppress:
                    self._mouse.suppress_event()
        elif msg in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
            self.mouse_pressed.emit()
        return False  # колбэки pynput не нужны

    def start(self, hotkey: str, mouse_button: str, suppress: bool) -> None:
        self.stop()
        try:
            mods, vk = parse_hotkey(hotkey)
        except ValueError as e:
            self.error.emit(f"Хоткей «{hotkey}» не распознан: {e}")
        else:
            ready = threading.Event()
            self._kb_thread = threading.Thread(target=self._kb_loop, args=(mods, vk, ready), daemon=True)
            self._kb_thread.start()
            ready.wait(2)
        self._xbutton = XBUTTONS.get(mouse_button, 0)
        self._suppress = suppress
        self._mouse = mouse.Listener(win32_event_filter=self._mouse_filter)
        self._mouse.daemon = True
        self._mouse.start()

    def stop(self) -> None:
        if self._kb_thread and self._kb_thread.is_alive():
            user32.PostThreadMessageW(self._kb_thread_id, WM_QUIT, 0, 0)
            self._kb_thread.join(1)
        self._kb_thread = None
        if self._mouse:
            self._mouse.stop()
            self._mouse = None
