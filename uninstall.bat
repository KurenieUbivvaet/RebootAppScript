@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title RebootAppScript - удаление автозапуска
set "SCRIPT_DIR=%~dp0"
set "TASK_NAME=RebootAppScript"
cd /d "%SCRIPT_DIR%"

echo ============================================================
echo   RebootAppScript - удаление автозапуска
echo ============================================================
echo.

fltmc >nul 2>&1
if errorlevel 1 goto :elevate

goto :remove

:elevate
echo [*] Для удаления нужны права администратора.
echo     Сейчас появится запрос UAC - подтвердите его.
set "ELEVATE_TARGET=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath $env:ELEVATE_TARGET -Verb RunAs"
if errorlevel 1 (
    echo.
    echo [ОШИБКА] Права администратора не получены.
    pause
    exit /b 1
)
exit /b 0

:remove
if not exist "%SCRIPT_DIR%tools\RebootAppTask.ps1" (
    echo [ОШИБКА] Не найден tools\RebootAppTask.ps1.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%tools\RebootAppTask.ps1" -Action Uninstall -TaskName "%TASK_NAME%"
if errorlevel 1 (
    echo.
    echo [ОШИБКА] Не удалось удалить задачу автозапуска.
    pause
    exit /b 1
)

echo.
echo [!] Автозапуск удалён. Сам "Ассистент" продолжает работать.
echo.
choice /C YN /N /M "Удалить логи и файл состояния? [y/N] "
if errorlevel 2 goto :keep

if exist "%SCRIPT_DIR%logs" rmdir /s /q "%SCRIPT_DIR%logs" 2>nul
if exist "%SCRIPT_DIR%state.json" del /q "%SCRIPT_DIR%state.json" 2>nul
echo [OK] Логи и состояние удалены.

:keep
echo.
echo ============================================================
echo   Готово. Скрипт больше не запускается автоматически.
echo   Папку проекта можно удалить вручную.
echo ============================================================
echo.
pause
endlocal
exit /b 0
