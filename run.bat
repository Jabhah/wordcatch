@echo off
chcp 65001 >nul
rem Запуск WordCatch (иконка появится в трее рядом с часами)
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Создаю окружение и ставлю зависимости, это займёт пару минут...
    py -3 -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0run.pyw"
exit /b 0

:error
echo Не получилось установить зависимости. Нужен Python 3.12+ с python.org.
pause
exit /b 1
