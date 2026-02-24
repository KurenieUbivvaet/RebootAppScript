@echo off
chcp 65001 >nul
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Запуск от имени администратора...
    powershell start -verb runas '%0'
    exit /b
)
cd /d "%~dp0"

rem Проверяем существование виртуальной среды
if exist ".venv\Scripts\activate.bat" (
    echo Активируем виртуальную среду...
    call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\activate.bat" (
    echo Активируем виртуальную среду...
    call "venv\Scripts\activate.bat"
) else (
    echo Виртуальная среда не найдена, использую системный Python
)

rem Запускаем скрипт
python script.py

rem Пауза
echo.
pause