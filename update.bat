@echo off
echo ============================================
echo   Catawiki Bot - アップデート
echo ============================================
echo.

python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python が見つかりません。setup.bat を先に実行してください。
    pause
    exit /b
)

python -c "
import urllib.request, os, sys

BRANCH = 'claude/restore-archived-project-sGOUE'
BASE   = 'https://raw.githubusercontent.com/hazimenosann/test/' + BRANCH + '/'
FILES  = ['bot.py', 'SETUP_GUIDE.txt']

ok = True
for fname in FILES:
    url = BASE + fname
    tmp = fname + '.tmp'
    print(f'ダウンロード中: {fname} ...', end=' ', flush=True)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = r.read()
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, fname)
        print('完了')
    except Exception as e:
        print(f'失敗 ({e})')
        if os.path.exists(tmp):
            os.remove(tmp)
        ok = False

print()
if ok:
    print('アップデート完了！起動.bat でボットを再起動してください。')
else:
    print('一部のファイルの更新に失敗しました。インターネット接続を確認してください。')
    sys.exit(1)
"

echo.
pause
