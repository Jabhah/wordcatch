# Сборка WordCatch.exe:  .venv\Scripts\python build.py   (или .venv\Scripts\pyinstaller WordCatch.spec)
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

import simplemma

SIMPLEMMA = Path(simplemma.__file__).parent
datas = [
    ("wordcatch/data/irregular_verbs.json", "wordcatch/data"),
    # из словарей simplemma нужны только английский и русский
    (str(SIMPLEMMA / "strategies/dictionaries/data/en.plzma"), "simplemma/strategies/dictionaries/data"),
    (str(SIMPLEMMA / "strategies/dictionaries/data/ru.plzma"), "simplemma/strategies/dictionaries/data"),
]
hiddenimports = collect_submodules("winrt") + [
    "pynput.mouse._win32",
    "pynput.keyboard._win32",
    "pynput._util.win32",
]
excludes = [
    "tkinter", "pytest", "pyflakes", "unittest",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtNetwork", "PySide6.QtOpenGL", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth",
]

a = Analysis(
    ["run.pyw"],
    pathex=["."],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="WordCatch",
    icon="assets/wordcatch.ico",
    console=False,
    upx=False,
    version="assets/version_info.txt",
)
