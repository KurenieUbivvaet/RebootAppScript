@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title RebootAppScript - управление
set "SCRIPT_DIR=%~dp0"
set "TASK_NAME=RebootAppScript"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%SCRIPT_DIR%"

set "ACTION=%~1"
set "ELEVATED=%~2"

if not defined ACTION goto :main_menu
if /i "%ACTION%"=="menu" goto :main_menu
if /i "%ACTION%"=="status" goto :direct_status
if /i "%ACTION%"=="restart" goto :direct_restart
if /i "%ACTION%"=="start" goto :direct_start
if /i "%ACTION%"=="stop" goto :direct_stop
if /i "%ACTION%"=="config" goto :direct_config
if /i "%ACTION%"=="logs" goto :direct_logs
if /i "%ACTION%"=="install" goto :direct_install
if /i "%ACTION%"=="uninstall" goto :direct_uninstall

echo Неизвестная команда: %ACTION%
echo.
echo Команды: status, restart, start, stop, config, logs, install, uninstall
set "RC=2"
goto :end

rem ==================================================================
rem  Меню
rem ==================================================================
:main_menu
call :require_admin menu
if errorlevel 9 goto :end

:menu_loop
cls
echo ============================================================
echo   RebootAppScript - управление
echo ============================================================
echo   1. Статус (задача, приложение, последний перезапуск)
echo   2. Перезапустить "Ассистент" сейчас
echo   3. Запустить супервизор
echo   4. Остановить супервизор
echo   5. Открыть config.json
echo   6. Открыть лог
echo   7. Установить / обновить автозапуск
echo   8. Удалить автозапуск
echo   0. Выход
echo ============================================================
echo.
choice /C 123456780 /N /M "Выберите пункт: "
if errorlevel 9 goto :menu_exit
if errorlevel 8 goto :menu_uninstall
if errorlevel 7 goto :menu_install
if errorlevel 6 goto :menu_logs
if errorlevel 5 goto :menu_config
if errorlevel 4 goto :menu_stop
if errorlevel 3 goto :menu_start
if errorlevel 2 goto :menu_restart
goto :menu_status

:menu_status
call :show_status
echo.
pause
goto :menu_loop

:menu_restart
call :do_restart
echo.
pause
goto :menu_loop

:menu_start
call :do_start
echo.
pause
goto :menu_loop

:menu_stop
call :do_stop
echo.
pause
goto :menu_loop

:menu_config
call :open_config
echo.
choice /C YN /N /M "Перезапустить супервизор, чтобы применить настройки? [Y/N] "
if errorlevel 2 goto :menu_loop
call :do_stop
call :do_start
echo.
pause
goto :menu_loop

:menu_logs
call :show_logs
echo.
pause
goto :menu_loop

:menu_install
call "%SCRIPT_DIR%install.bat"
goto :menu_loop

:menu_uninstall
call "%SCRIPT_DIR%uninstall.bat"
goto :menu_loop

:menu_exit
set "RC=0"
goto :end

rem ==================================================================
rem  Прямые команды
rem ==================================================================
:direct_status
call :show_status
set "RC=0"
goto :end

:direct_restart
call :require_admin restart
if errorlevel 9 goto :end
call :do_restart
set "RC=%errorlevel%"
goto :end

:direct_start
call :require_admin start
if errorlevel 9 goto :end
call :do_start
set "RC=%errorlevel%"
goto :end

:direct_stop
call :require_admin stop
if errorlevel 9 goto :end
call :do_stop
set "RC=%errorlevel%"
goto :end

:direct_config
call :open_config
echo.
echo Изменения вступят в силу после перезапуска супервизора:
echo   control.bat stop
echo   control.bat start
set "RC=0"
goto :end

:direct_logs
call :show_logs
set "RC=0"
goto :end

:direct_install
call "%SCRIPT_DIR%install.bat"
set "RC=%errorlevel%"
goto :end

:direct_uninstall
call "%SCRIPT_DIR%uninstall.bat"
set "RC=%errorlevel%"
goto :end

rem ==================================================================
rem  Подпрограммы
rem ==================================================================
:find_python
call "%SCRIPT_DIR%tools\find_python.bat" "%SCRIPT_DIR%"
exit /b 0

:show_status
call :find_python
if not defined PY_EXE (
    echo [ОШИБКА] Python не найден. Запустите install.bat.
    goto :show_task_status
)
"%PY_EXE%" "%SCRIPT_DIR%script.py" --status

:show_task_status
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%tools\RebootAppTask.ps1" -Action Status -TaskName "%TASK_NAME%"
if errorlevel 1 (
    echo.
    echo [!] Автозапуск не настроен. Запустите install.bat.
)
exit /b 0

:do_restart
call :find_python
if not defined PY_EXE (
    echo [ОШИБКА] Python не найден. Запустите install.bat.
    exit /b 1
)
"%PY_EXE%" "%SCRIPT_DIR%script.py" --restart-now
exit /b %errorlevel%

:do_start
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%tools\RebootAppTask.ps1" -Action Start -TaskName "%TASK_NAME%"
if errorlevel 1 (
    echo [!] Не удалось запустить супервизор.
    echo     Возможно, автозапуск не установлен - выполните пункт 7.
    exit /b 1
)
exit /b 0

:do_stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%tools\RebootAppTask.ps1" -Action Stop -TaskName "%TASK_NAME%"
if errorlevel 1 (
    echo [!] Не удалось остановить супервизор.
    exit /b 1
)
exit /b 0

:open_config
if not exist "%SCRIPT_DIR%config.json" (
    echo [!] config.json не найден - создайте его через install.bat.
    exit /b 1
)
start "" /wait notepad "%SCRIPT_DIR%config.json"
exit /b 0

:show_logs
if not exist "%SCRIPT_DIR%logs" mkdir "%SCRIPT_DIR%logs" >nul 2>&1
powershell -NoProfile -Command "Get-Content -LiteralPath '%SCRIPT_DIR%logs\rebootapp.log' -Tail 30 -Encoding UTF8 -ErrorAction SilentlyContinue"
echo.
start "" explorer "%SCRIPT_DIR%logs"
exit /b 0

:require_admin
fltmc >nul 2>&1
if not errorlevel 1 exit /b 0

echo [*] Для этого действия нужны права администратора.
echo     Сейчас появится запрос UAC - подтвердите его.
set "ELEVATE_TARGET=%~f0"
set "ELEVATE_ACTION=%~1"
set "ELEVATE_ARGS=elevated"
if defined ELEVATE_ACTION set "ELEVATE_ARGS=%ELEVATE_ACTION% elevated"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath $env:ELEVATE_TARGET -ArgumentList $env:ELEVATE_ARGS -Verb RunAs"
if errorlevel 1 (
    echo [ОШИБКА] Права администратора не получены.
    pause
)
exit /b 9

:end
if not defined RC set "RC=0"
if defined ELEVATED (
    echo.
    pause >nul
)
exit /b %RC%
