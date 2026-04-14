import asyncio
import json
import sys
import tkinter as tk
from tkinter import simpledialog, messagebox
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

CONFIG_FILE  = Path("config.json")
TEMPLATE_FILE = Path("templates.json")
BROWSER_DATA  = Path("browser_data")

# ------------------------------------------------------------------ helpers --

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def detect_language(text):
    dutch = ["wanneer", "hoe", "wat", "bedankt", "dank", "verzend",
             "ontvangen", "bestelling", "levering", "horloge"]
    score = sum(1 for w in dutch if w in text.lower())
    return "nl" if score >= 2 else "en"

def find_faq_reply(text, templates, lang):
    low = text.lower()
    for faq in templates["faq"]:
        keywords = faq.get(f"keywords_{lang}", [])
        if any(k in low for k in keywords):
            return faq[f"reply_{lang}"]
    return None

def hr():
    print("-" * 55)

# ------------------------------------------------------------------- login ---

async def ensure_logged_in(page, config):
    await page.goto("https://www.catawiki.com", wait_until="domcontentloaded", timeout=30000)
    if "/login" not in page.url and "catawiki.com" in page.url:
        try:
            # confirm there's a user-avatar / account element visible
            await page.wait_for_selector(
                '[data-testid="header-account"], .header-account, [aria-label="Account"]',
                timeout=5000
            )
            print("✅ ログイン済みです")
            return True
        except PlaywrightTimeoutError:
            pass

    print("🔐 ログイン中...")
    await page.goto("https://www.catawiki.com/login", wait_until="networkidle", timeout=30000)

    try:
        await page.fill('input[type="email"]',    config["email"],    timeout=10000)
        await page.fill('input[type="password"]', config["password"], timeout=10000)
        await page.click('button[type="submit"]', timeout=10000)
        await page.wait_for_load_state("networkidle", timeout=30000)
    except Exception as e:
        await page.screenshot(path="debug_login.png")
        print(f"❌ ログイン失敗: {e}")
        print("   → debug_login.png を確認してください")
        return False

    if "/login" in page.url:
        print("❌ ログイン失敗 — メールアドレスまたはパスワードを確認してください")
        return False

    print("✅ ログイン成功！")
    return True

# ---------------------------------------------------------------- messages ---

MESSAGE_URLS = [
    "https://www.catawiki.com/my/messages",
    "https://www.catawiki.com/messages",
]

THREAD_SELECTORS = (
    ".conversation-list-item, .message-thread, .inbox-row, "
    "[data-testid='conversation-item'], li.conversation"
)

async def fetch_message_threads(page):
    print("📬 メッセージを取得中...")
    for url in MESSAGE_URLS:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        if "message" in page.url:
            break

    await page.screenshot(path="debug_messages.png")
    items = await page.query_selector_all(THREAD_SELECTORS)

    if not items:
        print("⚠️  メッセージが見つかりませんでした")
        print("   → debug_messages.png で画面を確認してください")
        return []

    threads = []
    for el in items:
        text = (await el.inner_text()).strip()
        link = await el.query_selector("a")
        href = await link.get_attribute("href") if link else None
        cls  = await el.get_attribute("class") or ""
        threads.append({"text": text, "href": href,
                         "unread": "unread" in cls.lower() or "new" in cls.lower()})
    return threads

REPLY_SELECTORS  = 'textarea[name="message"], textarea[placeholder], .reply-box textarea'
SEND_SELECTORS   = ('button[type="submit"], .send-button, '
                    'button:has-text("Send"), button:has-text("Verstuur")')

async def send_reply(page, thread, reply_text):
    try:
        if thread.get("href"):
            href = thread["href"]
            if not href.startswith("http"):
                href = "https://www.catawiki.com" + href
            await page.goto(href, wait_until="networkidle", timeout=30000)

        box = await page.query_selector(REPLY_SELECTORS)
        if not box:
            await page.screenshot(path="debug_reply.png")
            print("❌ 入力欄が見つかりません → debug_reply.png を確認")
            return False

        await box.click()
        await box.fill(reply_text)

        btn = await page.query_selector(SEND_SELECTORS)
        if not btn:
            print("❌ 送信ボタンが見つかりません")
            return False

        await btn.click()
        await page.wait_for_load_state("networkidle", timeout=15000)
        return True
    except Exception as e:
        print(f"❌ 送信エラー: {e}")
        return False

# -------------------------------------------------------- feature: messages --

async def feature_check_messages(page, templates):
    threads = await fetch_message_threads(page)
    if not threads:
        return

    print(f"\n📨 {len(threads)} 件のスレッドが見つかりました\n")
    for i, t in enumerate(threads, 1):
        hr()
        print(f"[{i}/{len(threads)}]")
        preview = t["text"][:220] + ("…" if len(t["text"]) > 220 else "")
        print(preview)

        lang  = detect_language(t["text"])
        reply = find_faq_reply(t["text"], templates, lang)

        if reply:
            print(f"\n💡 自動返信案 ({'英語' if lang == 'en' else 'オランダ語'}):")
            print(reply)
            print()
            choice = input("[s] 送信  [e] 編集  [n] スキップ > ").strip().lower()
            if choice == "s":
                ok = await send_reply(page, t, reply)
                print("✅ 送信完了！" if ok else "❌ 送信失敗")
            elif choice == "e":
                print("返信内容を入力してください（空行で確定）:")
                lines = []
                while True:
                    line = input()
                    if line == "":
                        break
                    lines.append(line)
                custom = "\n".join(lines)
                if custom:
                    ok = await send_reply(page, t, custom)
                    print("✅ 送信完了！" if ok else "❌ 送信失敗")
            else:
                print("スキップ")
        else:
            print("⚠️  FAQに一致せず（手動対応が必要です）")
        print()

# ------------------------------------------------------ feature: shipping ---

async def feature_shipping(page, templates):
    hr()
    print("📦 発送通知を送る")
    hr()

    tracking = input("DHLトラッキング番号: ").strip()
    if not tracking:
        print("キャンセル")
        return

    lang = input("言語 (en=英語 / nl=オランダ語) [en]: ").strip().lower() or "en"
    if lang not in ("en", "nl"):
        lang = "en"

    msg = templates["shipping"][lang].replace("{tracking_number}", tracking)

    print("\n送信内容プレビュー:")
    hr()
    print(msg)
    hr()

    print("\nブラウザでCatawikiのメッセージ画面を開きます")
    print("送り先の会話URLをコピーして貼り付けてください")
    input("Enterを押してブラウザを開く...")

    for url in MESSAGE_URLS:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        if "message" in page.url:
            break

    await page.screenshot(path="debug_messages.png")
    print("📸 debug_messages.png に画面を保存しました")

    conv_url = input("\n会話のURL（例: https://www.catawiki.com/my/messages/123）: ").strip()
    if not conv_url:
        print("キャンセル")
        return

    try:
        await page.goto(conv_url, wait_until="networkidle", timeout=30000)
        box = await page.query_selector(REPLY_SELECTORS)
        if not box:
            await page.screenshot(path="debug_shipping.png")
            print("❌ 入力欄が見つかりません → debug_shipping.png を確認")
            return

        await box.fill(msg)
        confirm = input("送信しますか？ (y/n): ").strip().lower()
        if confirm == "y":
            btn = await page.query_selector(SEND_SELECTORS)
            if btn:
                await btn.click()
                print("✅ 発送通知を送信しました！")
            else:
                print("❌ 送信ボタンが見つかりません")
        else:
            print("キャンセル")
    except Exception as e:
        print(f"❌ エラー: {e}")

# -------------------------------------------------------------------- main ---

async def main():
    for f in (CONFIG_FILE, TEMPLATE_FILE):
        if not f.exists():
            print(f"❌ {f} が見つかりません。setup.bat を実行してください。")
            input("Enterで終了...")
            sys.exit(1)

    try:
        config = load_json(CONFIG_FILE)
    except Exception:
        print("❌ config.json の読み込みに失敗しました。")
        print("   config.json をメモ帳で開いて内容を確認してください。")
        print()
        print('   正しい形式の例:')
        print('   {')
        print('     "email": "your@email.com",')
        print('     "default_language": "en"')
        print('   }')
        input("\nEnterで終了...")
        sys.exit(1)

    templates = load_json(TEMPLATE_FILE)

    email = config.get("email", "")
    if not email or email.startswith("ここに"):
        print("❌ config.json にメールアドレスが設定されていません。")
        print()
        print("   config.json をメモ帳で開いて、")
        print('   "email": の部分にCatawikiのメールアドレスを入力してください。')
        print()
        print('   例: "email": "your@email.com"')
        input("\nEnterで終了...")
        sys.exit(1)

    config["email"] = email

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    password = simpledialog.askstring(
        "Catawiki Login",
        "Catawikiのパスワードを入力してください:",
        show="*",
        parent=root
    )
    root.destroy()

    if not password:
        messagebox.showerror("エラー", "パスワードが入力されませんでした。")
        sys.exit(1)

    config["password"] = password
        sys.exit(1)

    BROWSER_DATA.mkdir(exist_ok=True)

    async with async_playwright() as p:
        ctx  = await p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_DATA),
            headless=False,
            args=["--start-maximized"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        ok = await ensure_logged_in(page, config)
        if not ok:
            input("Enterで終了...")
            await ctx.close()
            return

        while True:
            print()
            print("=" * 55)
            print("  🌿 Catawiki 自動化ボット")
            print("=" * 55)
            print("  1. メッセージを確認して自動返信")
            print("  2. 発送通知を送る（トラッキング番号付き）")
            print("  3. 終了")
            print("=" * 55)
            choice = input("  番号を選んでEnter: ").strip()

            if choice == "1":
                await feature_check_messages(page, templates)
            elif choice == "2":
                await feature_shipping(page, templates)
            elif choice == "3":
                print("終了します。お疲れ様でした！")
                break
            else:
                print("1、2、または3を入力してください")

        await ctx.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n終了しました")
