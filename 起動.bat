@echo off
chcp 65001 > nul
echo ============================================
echo   Catawiki 自動化ボット 起動中...
echo ============================================
echo.

python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python が見つかりません。先に setup.bat を実行してください。
    pause
    exit /b
)

python bot.py
if %errorlevel% neq 0 (
    echo.
    echo [!] エラーが発生しました。
    echo     setup.bat を実行してライブラリをインストールしてください。
)

pause
