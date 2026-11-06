@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title RebootAppScript - установка
set "SCRIPT_DIR=%~dp0"
set "TASK_NAME=RebootAppScript"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%SCRIPT_DIR%"

echo ============================================================
echo   RebootAppScript - установка
echo   Ежедневный перезапуск "Ассистент" в 00:00
echo ============================================================
echo.

rem ------------------------------------------------------------------
rem  Права администратора
rem ------------------------------------------------------------------
fltmc >nul 2>&1
if errorlevel 1 goto :elevate

goto :checks

:elevate
echo [*] Для установки нужны права администратора.
echo     Сейчас появится запрос UAC - подтвердите его.
set "ELEVATE_TARGET=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath $env:ELEVATE_TARGET -Verb RunAs"
if errorlevel 1 (
    echo.
    echo [ОШИБКА] Права администратора не получены. Установка отменена.
    pause
    exit /b 1
)
exit /b 0

rem ------------------------------------------------------------------
rem  Проверка файлов и поиск Python
rem ------------------------------------------------------------------
:checks
if not exist "%SCRIPT_DIR%script.py" (
    echo [ОШИБКА] Не найден script.py рядом с install.bat.
    echo Распакуйте архив полностью, не меняя структуру папок.
    pause
    exit /b 1
)
if not exist "%SCRIPT_DIR%tools\RebootAppTask.ps1" (
    echo [ОШИБКА] Не найден tools\RebootAppTask.ps1.
    echo Распакуйте архив полностью, не меняя структуру папок.
    pause
    exit /b 1
)

call :find_python
if not defined PY_EXE call :install_python
call :find_python
if not defined PY_EXE (
    echo.
    echo [ОШИБКА] Python установить не удалось.
    echo Установите Python 3.8+ вручную: https://www.python.org/downloads/windows/
    echo При установке отметьте "Add python.exe to PATH".
    pause
    exit /b 1
)

echo [OK] Python: %PY_EXE%
if not exist "%PYTHONW%" set "PYTHONW=%PY_EXE%"
echo [OK] pythonw: %PYTHONW%
echo.

rem ------------------------------------------------------------------
rem  Проверка скрипта и конфигурации
rem ------------------------------------------------------------------
echo [*] Проверяю script.py...
"%PY_EXE%" -m py_compile "%SCRIPT_DIR%script.py"
if errorlevel 1 (
    echo [ОШИБКА] script.py содержит синтаксические ошибки.
    pause
    exit /b 1
)

if not exist "%SCRIPT_DIR%config.json" (
    echo [*] config.json не найден - создаю со значениями по умолчанию...
    "%PY_EXE%" "%SCRIPT_DIR%script.py" --init-config
)

echo [*] Проверяю config.json...
"%PY_EXE%" "%SCRIPT_DIR%script.py" --check
set "CHECK_RC=%errorlevel%"

if "%CHECK_RC%"=="0" goto :register
if "%CHECK_RC%"=="2" goto :config_error
if "%CHECK_RC%"=="4" goto :fix_config
echo.
echo [ОШИБКА] Проверка config.json завершилась с кодом %CHECK_RC%.
pause
exit /b 1

:config_error
echo.
echo [ОШИБКА] Исправьте config.json и запустите install.bat снова.
pause
exit /b 1

:fix_config
echo.
echo [!] Файл приложения из config.json не найден.
echo     Откройте config.json и укажите правильный путь в file_to_run.
choice /C YN /N /M "Открыть config.json сейчас? [Y/N] "
if errorlevel 2 goto :skip_fix
start "" /wait notepad "%SCRIPT_DIR%config.json"
"%PY_EXE%" "%SCRIPT_DIR%script.py" --check
set "CHECK_RC=%errorlevel%"
if "%CHECK_RC%"=="0" goto :register
if "%CHECK_RC%"=="2" goto :config_error
if not "%CHECK_RC%"=="4" (
    echo.
    echo [ОШИБКА] Проверка config.json завершилась с кодом %CHECK_RC%.
    pause
    exit /b 1
)
choice /C YN /N /M "Файл всё ещё не найден. Продолжить установку? [Y/N] "
if errorlevel 2 (
    echo Установка отменена.
    pause
    exit /b 1
)
goto :register

:skip_fix
echo [i] Продолжаю установку без проверки пути к приложению.

rem ------------------------------------------------------------------
rem  Задача автозапуска
rem ------------------------------------------------------------------
:register
echo.
echo [*] Останавливаю предыдущий экземпляр супервизора (если он был запущен)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%tools\RebootAppTask.ps1" -Action Stop -TaskName "%TASK_NAME%" >nul 2>&1
ping -n 3 127.0.0.1 >nul 2>&1

echo [*] Регистрирую задачу автозапуска "%TASK_NAME%"...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%tools\RebootAppTask.ps1" -Action Install -TaskName "%TASK_NAME%" -PythonPath "%PYTHONW%" -ScriptPath "%SCRIPT_DIR%script.py" -Mode Logon
if errorlevel 1 (
    echo.
    echo [ОШИБКА] Не удалось зарегистрировать задачу автозапуска.
    pause
    exit /b 1
)

echo.
echo [*] Запускаю супервизор...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%tools\RebootAppTask.ps1" -Action Start -TaskName "%TASK_NAME%" >nul 2>&1
ping -n 7 127.0.0.1 >nul 2>&1

echo.
"%PY_EXE%" "%SCRIPT_DIR%script.py" --status
echo.
echo ============================================================
echo   Установка завершена
echo ------------------------------------------------------------
echo   Автозапуск:  задача "%TASK_NAME%" (при входе в систему,
echo                с наивысшими правами, без окна консоли)
echo   Перезапуск:  ежедневно в 00:00
echo   Управление:  control.bat
echo   Логи:        %SCRIPT_DIR%logs\rebootapp.log
echo ------------------------------------------------------------
echo   Если супервизор не запустился, смотрите лог.
echo   Изменения config.json применяются после перезапуска
echo   супервизора (control.bat - пункт 4, затем 3).
echo ============================================================
echo.
pause
endlocal
exit /b 0

rem ------------------------------------------------------------------
rem  Подпрограммы
rem ------------------------------------------------------------------
:find_python
call "%SCRIPT_DIR%tools\find_python.bat" "%SCRIPT_DIR%"
exit /b 0

:install_python
echo.
echo [*] Python не найден. Пробую установить автоматически...
where winget >nul 2>&1
if errorlevel 1 goto :python_download

echo [*] Установка Python 3.13 через winget (может занять несколько минут)...
winget install --id Python.Python.3.13 -e --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
call :find_python
if defined PY_EXE (
    echo [OK] Python установлен через winget.
    exit /b 0
)
echo [!] winget не справился, пробую установщик с python.org...

:python_download
set "PY_INSTALLER=%TEMP%\python-3.13.9-amd64.exe"
echo [*] Скачиваю Python 3.13.9 (около 29 МБ)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.9/python-3.13.9-amd64.exe' -OutFile $env:PY_INSTALLER -UseBasicParsing"
if errorlevel 1 (
    echo [ОШИБКА] Не удалось скачать установщик Python.
    echo Проверьте интернет или установите Python вручную:
    echo https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

echo [*] Тихая установка Python...
start "" /wait "%PY_INSTALLER%" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1 Include_launcher=1
if exist "%PY_INSTALLER%" del /q "%PY_INSTALLER%" >nul 2>&1
call :find_python
if defined PY_EXE (
    echo [OK] Python установлен.
    exit /b 0
)
echo [ОШИБКА] Python установлен, но не найден в стандартных папках.
echo Перезапустите install.bat или перезагрузите компьютер.
pause
exit /b 1
