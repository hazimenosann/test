@echo off
echo ============================================
echo   Catawiki Bot - Update
echo ============================================
echo.

python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python not found. Please run setup.bat first.
    pause
    exit /b
)

python update.py
if %errorlevel% neq 0 (
    echo.
    echo [!] Update failed.
)

echo.
pause
