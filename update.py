import urllib.request
import os
import sys

BRANCH = "claude/restore-archived-project-sGOUE"
BASE   = "https://raw.githubusercontent.com/hazimenosann/test/" + BRANCH + "/"
FILES  = ["bot.py", "SETUP_GUIDE.txt"]

print("============================================")
print("  Catawiki Bot - Update")
print("============================================")
print()

ok = True
for fname in FILES:
    url = BASE + fname
    tmp = fname + ".tmp"
    print("Downloading: " + fname + " ...", end=" ", flush=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 200:
                raise Exception("HTTP " + str(r.status))
            data = r.read()
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, fname)
        print("OK")
    except Exception as e:
        print("FAILED (" + str(e) + ")")
        if os.path.exists(tmp):
            os.remove(tmp)
        ok = False

print()
if ok:
    print("Update complete! Restart the bot with start.bat")
else:
    print("Some files failed to download.")
    print("Check your internet connection and try again.")
    sys.exit(1)
