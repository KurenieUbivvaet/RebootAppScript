@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title RebootAppScript - диагностический запуск

call "%~dp0tools\find_python.bat" "%~dp0"
if not defined PY_EXE (
    echo [ОШИБКА] Python не найден. Запустите install.bat.
    pause
    exit /b 1
)

echo ============================================================
echo   Запуск супервизора в консоли (для диагностики)
echo   Закрыть: Ctrl+C
echo ============================================================
echo.

"%PY_EXE%" "%~dp0script.py" --daemon %*
echo.
echo Супервизор завершён.
pause
