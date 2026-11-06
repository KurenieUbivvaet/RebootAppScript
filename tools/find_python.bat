@echo off
rem ---------------------------------------------------------------------------
rem  Поиск Python 3.8+ на компьютере.
rem  Вызов: call "tools\find_python.bat" "<папка проекта>"
rem  Результат: переменные PY_EXE (python.exe) и PYTHONW (pythonw.exe),
rem  пути без кавычек. Если Python не найден - переменные пустые.
rem ---------------------------------------------------------------------------

set "FP_ROOT=%~1"
set "PY_EXE="
set "PYTHONW="

rem 1. Виртуальное окружение проекта (создавалось старой версией скрипта).
if exist "%FP_ROOT%.venv\Scripts\python.exe" set "PY_EXE=%FP_ROOT%.venv\Scripts\python.exe"

rem 2. Лаунчер py (самый надёжный способ).
if not defined PY_EXE (
    for /f "usebackq delims=" %%I in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do (
        if not defined PY_EXE set "PY_EXE=%%I"
    )
)

rem 3. python.exe из PATH (кроме заглушки Microsoft Store в WindowsApps).
if not defined PY_EXE (
    for /f "delims=" %%I in ('where python 2^>nul ^| findstr /i /v "WindowsApps"') do (
        if not defined PY_EXE set "PY_EXE=%%I"
    )
)

rem 4. Типовые папки установки Python.
if not defined PY_EXE (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
        if exist "%%~fD\python.exe" if not defined PY_EXE set "PY_EXE=%%~fD\python.exe"
    )
)
if not defined PY_EXE (
    for /d %%D in ("C:\Program Files\Python3*") do (
        if exist "%%~fD\python.exe" if not defined PY_EXE set "PY_EXE=%%~fD\python.exe"
    )
)
if not defined PY_EXE (
    for /d %%D in ("C:\Program Files (x86)\Python3*") do (
        if exist "%%~fD\python.exe" if not defined PY_EXE set "PY_EXE=%%~fD\python.exe"
    )
)
if not defined PY_EXE (
    for /d %%D in ("C:\Python3*") do (
        if exist "%%~fD\python.exe" if not defined PY_EXE set "PY_EXE=%%~fD\python.exe"
    )
)

rem Проверка версии: нужен Python 3.8 или новее.
if defined PY_EXE (
    "%PY_EXE%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
    if errorlevel 1 set "PY_EXE="
)

rem pythonw.exe нужен, чтобы супервизор работал без окна консоли.
if defined PY_EXE (
    for %%I in ("%PY_EXE%") do (
        if exist "%%~dpIpythonw.exe" set "PYTHONW=%%~dpIpythonw.exe"
    )
    if not defined PYTHONW set "PYTHONW=%PY_EXE%"
)

exit /b 0
