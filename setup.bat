@echo off
echo ============================================
echo   Catawiki Bot - Setup
echo ============================================
echo.

python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python is not installed.
    echo     Please install Python from https://www.python.org/downloads/
    echo     Make sure to check "Add Python to PATH" during installation!
    echo.
    pause
    exit /b
)

echo [OK] Python found.
echo.
echo [*] Installing required libraries...
python -m pip install --upgrade pip --quiet
python -m pip install playwright anthropic aiohttp pyngrok --quiet

echo [*] Installing browser (this may take a few minutes)...
python -m playwright install chromium

echo.
echo ============================================
echo   Setup complete!
echo ============================================
echo.
echo Next steps:
echo   1. Open config.json with Notepad and fill in all 5 fields:
echo      - Catawiki email
echo      - Anthropic API key  (console.anthropic.com)
echo      - LINE Channel Access Token
echo      - LINE User ID
echo      - ngrok auth token   (ngrok.com)
echo   2. See SETUP_GUIDE.txt for step-by-step instructions
echo   3. Double-click start.bat to launch the bot
echo.
pause
