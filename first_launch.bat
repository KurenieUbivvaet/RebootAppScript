@echo off
chcp 65001 >nul
echo ============================================================
echo   first_launch.bat устарел
echo   Сейчас будет запущен install.bat
echo ============================================================
echo.
call "%~dp0install.bat"
