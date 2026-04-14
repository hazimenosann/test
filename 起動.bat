@echo off
echo ============================================
echo   Catawiki Bot - Starting...
echo ============================================
echo.

python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python not found. Please run setup.bat first.
    pause
    exit /b
)

python bot.py
if %errorlevel% neq 0 (
    echo.
    echo [!] An error occurred. Please run setup.bat first.
)

pause
