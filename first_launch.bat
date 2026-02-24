@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ===================================================
echo     Настройка виртуального окружения и зависимостей
echo ===================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден. Пожалуйста, установите Python и добавьте его в PATH.
    echo Скачать можно с официального сайта: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set pyver=%%i
echo Найден Python версии %pyver%

if exist ".venv\Scripts\python.exe" (
    echo Виртуальное окружение .venv уже существует.
) else (
    echo Создание виртуального окружения в папке .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось создать виртуальное окружение.
        pause
        exit /b 1
    )
    echo Виртуальное окружение успешно создано.
)

if not exist "requirements.txt" (
    echo [ПРЕДУПРЕЖДЕНИЕ] Файл requirements.txt не найден.
    echo Установка пакетов пропущена.
    pause
    exit /b 0
)

echo Установка зависимостей из requirements.txt...
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt

if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости.
    pause
    exit /b 1
) else (
    echo Все зависимости успешно установлены.
)

pause