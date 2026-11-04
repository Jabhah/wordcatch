"""Собирает dist/WordCatch.exe (один файл, без консоли).

    .venv\\Scripts\\python -m pip install pyinstaller
    .venv\\Scripts\\python build.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from wordcatch import __version__  # noqa: E402


def make_icon() -> None:
    from PySide6.QtWidgets import QApplication

    from wordcatch.app import make_icon_pixmap
    from wordcatch.ui.common import DARK

    app = QApplication.instance() or QApplication([])  # нужен для рисования шрифтом
    app.setApplicationName("WordCatch build")
    (ROOT / "assets").mkdir(exist_ok=True)
    if not make_icon_pixmap(DARK.accent, 256).save(str(ROOT / "assets" / "wordcatch.ico"), "ICO"):
        raise SystemExit("не удалось сохранить assets/wordcatch.ico")


def make_version_file() -> None:
    nums = [int(x) for x in __version__.split(".")] + [0] * 4
    v = tuple(nums[:4])
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
  kids=[
    StringFileInfo([StringTable('041904B0', [
      StringStruct('CompanyName', 'jbnj'),
      StringStruct('FileDescription', 'WordCatch — экранный переводчик'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'WordCatch'),
      StringStruct('LegalCopyright', 'MIT © jbnj (github.com/Jabhah)'),
      StringStruct('OriginalFilename', 'WordCatch.exe'),
      StringStruct('ProductName', 'WordCatch'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [0x0419, 1200])])
  ]
)
"""
    (ROOT / "assets" / "version_info.txt").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    make_icon()
    make_version_file()
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "WordCatch.spec"],
                   cwd=ROOT, check=True)
    exe = ROOT / "dist" / "WordCatch.exe"
    print(f"\nГотово: {exe} ({exe.stat().st_size / 1_048_576:.1f} МБ)")
