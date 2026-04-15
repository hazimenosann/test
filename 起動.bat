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

echo [*] Releasing port 5000...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":5000 "') do (
    taskkill /PID %%a /F > nul 2>&1
)

python bot.py
if %errorlevel% neq 0 (
    echo.
    echo [!] An error occurred. Please run setup.bat first.
)

pause
