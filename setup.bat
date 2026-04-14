@echo off
chcp 65001 > nul
echo ============================================
echo   Catawiki ボット セットアップ
echo ============================================
echo.

REM --- Python の確認 ---
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python がインストールされていません。
    echo     自動でダウンロードします...
    echo.
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe' -OutFile 'python_installer.exe'"
    echo [*] インストール中...
    python_installer.exe /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
    del python_installer.exe
    echo.
    echo [!] インストール完了。このウィンドウを閉じて setup.bat をもう一度ダブルクリックしてください。
    pause
    exit /b
)

echo [OK] Python が見つかりました
echo.

REM --- pip パッケージのインストール ---
echo [*] 必要なライブラリをインストール中...
python -m pip install --upgrade pip --quiet
python -m pip install playwright --quiet

echo [*] ブラウザをインストール中（少し時間がかかります）...
python -m playwright install chromium

echo.
echo ============================================
echo   セットアップ完了！
echo ============================================
echo.
echo 次のステップ:
echo   1. config.json をメモ帳で開く
echo   2. メールアドレスとパスワードを入力して保存
echo   3. 起動.bat をダブルクリックしてボットを起動
echo.
pause
