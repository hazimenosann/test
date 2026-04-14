import anthropic
import asyncio
import json
import sys
import hashlib
import aiohttp
from aiohttp import web
import tkinter as tk
from tkinter import simpledialog
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ── Constants ────────────────────────────────────────────────────────────────
CONFIG_FILE    = Path("config.json")
BROWSER_DATA   = Path("browser_data")
SEEN_FILE      = Path("seen_messages.json")
WEBHOOK_PORT   = 5000
CHECK_INTERVAL = 300   # check Catawiki every 5 minutes

# ── AI system prompt ─────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a customer service assistant for a Catawiki seller who handcrafts and sells wooden watches.

About the seller:
- Sells unique, handcrafted hardwood watches on Catawiki
- Ships with DHL within 2-3 business days after payment confirmation
- Delivery within Europe: 3-7 business days
- Each watch is handmade from genuine, sustainably sourced hardwood — every piece is unique
- Water resistance: 3 ATM (splash and rain resistant, NOT suitable for swimming or diving)
- Case diameter: approximately 42mm, thickness: 12mm, strap width: 22mm
- Returns/issues: handled with care and goodwill

Your job:
- Reply to customer messages in a friendly, warm, and human-like way
- Always respond in the SAME LANGUAGE as the customer (English or Dutch)
- Keep replies concise but complete
- If you can answer confidently, write the full reply ready to send
- If the message requires information you don't have (specific order status, tracking number,
  custom requests, complaints needing investigation), start your reply with exactly: [NEEDS_REVIEW]
  Then briefly explain what information is needed from the seller.

Never make up order details, tracking numbers, or delivery dates you don't know."""

# ── Shared state ─────────────────────────────────────────────────────────────
message_queue  = asyncio.Queue()
approval_event = asyncio.Event()
approval_data: dict = {}
browser_page   = None   # set after login

# ── Helpers ──────────────────────────────────────────────────────────────────
def load_json(path, default=None):
    p = Path(path)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def thread_id(thread: dict) -> str:
    """Stable unique ID for a message thread."""
    key = (thread.get("href") or "") + thread["text"][:100]
    return hashlib.md5(key.encode()).hexdigest()

# ── Claude API ────────────────────────────────────────────────────────────────
def generate_reply(message_text: str, api_key: str) -> dict:
    """Generate AI reply and Japanese translations in a single API call.

    Returns a dict with keys:
      reply      – the reply to send to Catawiki (EN or NL, buyer's language)
      reply_ja   – Japanese translation of that reply (for the seller to read)
      message_ja – Japanese translation of the buyer's original message
      lang       – detected buyer language ("en", "nl", or "other")
      needs_review – True when the reply starts with [NEEDS_REVIEW]
    """
    client = anthropic.Anthropic(api_key=api_key)

    user_prompt = (
        f"{message_text}\n\n"
        "---\n"
        "After writing the reply above, also output the following block EXACTLY "
        "(no extra text before or after the block):\n\n"
        "<<<TRANSLATIONS>>>\n"
        "LANG: <en|nl|other>\n"
        "MESSAGE_JA: <Japanese translation of the buyer's message above>\n"
        "REPLY_JA: <Japanese translation of the reply you just wrote>\n"
        "<<<END>>>"
    )

    resp = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_prompt}],
    )
    full_text = resp.content[0].text.strip()

    # Split reply from translation block
    if "<<<TRANSLATIONS>>>" in full_text and "<<<END>>>" in full_text:
        reply_part, rest = full_text.split("<<<TRANSLATIONS>>>", 1)
        trans_block, _ = rest.split("<<<END>>>", 1)
        reply = reply_part.strip()

        lang = "other"
        message_ja = ""
        reply_ja = ""
        for line in trans_block.strip().splitlines():
            if line.startswith("LANG:"):
                lang = line[5:].strip().lower()
            elif line.startswith("MESSAGE_JA:"):
                message_ja = line[11:].strip()
            elif line.startswith("REPLY_JA:"):
                reply_ja = line[9:].strip()
    else:
        # Fallback: treat entire response as reply, no translations
        reply = full_text
        lang = "other"
        message_ja = ""
        reply_ja = ""

    needs_review = reply.startswith("[NEEDS_REVIEW]")
    return {
        "reply": reply,
        "reply_ja": reply_ja,
        "message_ja": message_ja,
        "lang": lang,
        "needs_review": needs_review,
    }

def translate_to_buyer_language(japanese_text: str, target_lang: str, api_key: str) -> str:
    """Translate a Japanese message to the buyer's language (EN or NL)."""
    if target_lang == "nl":
        instruction = "Translate the following Japanese text to Dutch. Output only the translation."
    else:
        instruction = "Translate the following Japanese text to English. Output only the translation."

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": f"{instruction}\n\n{japanese_text}"}],
    )
    return resp.content[0].text.strip()

# ── LINE ──────────────────────────────────────────────────────────────────────
async def line_send(token: str, user_id: str, text: str, buttons: bool = False):
    msg: dict = {"type": "text", "text": text}
    if buttons:
        msg["quickReply"] = {"items": [
            {"type": "action", "action": {
                "type": "message", "label": "Send reply", "text": "__SEND__"}},
            {"type": "action", "action": {
                "type": "message", "label": "Skip", "text": "__SKIP__"}},
        ]}
    async with aiohttp.ClientSession() as s:
        await s.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"to": user_id, "messages": [msg]},
        )

async def set_line_webhook(token: str, url: str):
    async with aiohttp.ClientSession() as s:
        r = await s.put(
            "https://api.line.me/v1/webhook/endpoint",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"webhookEndpoint": url},
        )
        if r.status == 200:
            print("[LINE] Webhook URL を自動設定しました。")
        else:
            body = await r.text()
            print(f"[LINE] Webhook URL の自動設定に失敗しました ({r.status}): {body}")
            print(f"[LINE] 手動で設定してください：")
            print(f"  LINE Developersコンソール → Messaging API → Webhook URL")
            print(f"  に以下を貼り付けて「更新」→「検証」:")
            print(f"  {url}")

# ── LINE webhook server ───────────────────────────────────────────────────────
async def handle_webhook(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400)

    for event in data.get("events", []):
        if event.get("type") == "message":
            msg = event.get("message", {})
            if msg.get("type") == "text":
                text = msg["text"].strip()
                if text == "__SEND__":
                    approval_data.update({"action": "send", "custom": None})
                    approval_event.set()
                elif text == "__SKIP__":
                    approval_data.update({"action": "skip"})
                    approval_event.set()
                else:
                    # Treat any other text as a custom reply
                    approval_data.update({"action": "send", "custom": text})
                    approval_event.set()

    return web.Response(status=200)

# ── Catawiki ──────────────────────────────────────────────────────────────────
MESSAGE_URLS = [
    "https://www.catawiki.com/my/messages",
    "https://www.catawiki.com/messages",
]
THREAD_SEL = (
    ".conversation-list-item, .message-thread, .inbox-row, "
    "[data-testid='conversation-item'], li.conversation"
)
REPLY_SEL = 'textarea[name="message"], textarea[placeholder], .reply-box textarea'
SEND_SEL  = ('button[type="submit"], .send-button, '
             'button:has-text("Send"), button:has-text("Verstuur")')

async def ensure_logged_in(page, config) -> bool:
    await page.goto("https://www.catawiki.com",
                    wait_until="domcontentloaded", timeout=30000)
    try:
        await page.wait_for_selector(
            '[data-testid="header-account"], .header-account', timeout=5000)
        return True
    except PlaywrightTimeoutError:
        pass

    await page.goto("https://www.catawiki.com/login",
                    wait_until="networkidle", timeout=30000)
    try:
        await page.fill('input[type="email"]',    config["email"],    timeout=10000)
        await page.fill('input[type="password"]', config["password"], timeout=10000)
        await page.click('button[type="submit"]', timeout=10000)
        await page.wait_for_load_state("networkidle", timeout=30000)
    except Exception as e:
        await page.screenshot(path="debug_login.png")
        print(f"Login failed: {e}")
        return False
    return "/login" not in page.url

async def fetch_threads(page) -> list:
    for url in MESSAGE_URLS:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        if "message" in page.url:
            break
    items = await page.query_selector_all(THREAD_SEL)
    threads = []
    for el in items:
        text = (await el.inner_text()).strip()
        link = await el.query_selector("a")
        href = await link.get_attribute("href") if link else None
        threads.append({"text": text, "href": href})
    return threads

async def send_catawiki_reply(page, thread: dict, reply_text: str) -> bool:
    try:
        href = thread.get("href", "")
        if href and not href.startswith("http"):
            href = "https://www.catawiki.com" + href
        if href:
            await page.goto(href, wait_until="networkidle", timeout=30000)
        box = await page.query_selector(REPLY_SEL)
        if not box:
            return False
        await box.click()
        await box.fill(reply_text)
        btn = await page.query_selector(SEND_SEL)
        if not btn:
            return False
        await btn.click()
        await page.wait_for_load_state("networkidle", timeout=15000)
        return True
    except Exception:
        return False

# ── Message processing loop ───────────────────────────────────────────────────
async def process_messages_loop(config: dict):
    """Send LINE notifications and wait for approval one message at a time."""
    while True:
        msg_data  = await message_queue.get()
        thread    = msg_data["thread"]
        ai_reply  = msg_data["ai_reply"]       # EN/NL reply to Catawiki
        reply_ja  = msg_data["reply_ja"]       # Japanese translation of reply
        message_ja = msg_data["message_ja"]    # Japanese translation of buyer msg
        buyer_lang = msg_data["lang"]          # "en" / "nl" / "other"

        preview    = thread["text"][:200] + ("..." if len(thread["text"]) > 200 else "")
        preview_ja = message_ja[:200] + ("..." if len(message_ja) > 200 else "") if message_ja else ""

        lines = ["【新着Catawikiメッセージ】\n"]
        lines.append(f"【原文】\n{preview}\n")
        if preview_ja:
            lines.append(f"【日本語訳】\n{preview_ja}\n")
        lines.append("──────────────────")
        lines.append("【AI返信案（原文）】")
        lines.append(ai_reply)
        if reply_ja:
            lines.append("\n【AI返信案（日本語訳）】")
            lines.append(reply_ja)
        lines.append("\n──────────────────")
        lines.append("「返信を送る」→AI返信をそのまま送信")
        lines.append("「スキップ」→この会話をスキップ")
        lines.append("日本語で入力→自動翻訳して送信")

        text = "\n".join(lines)
        await line_send(config["line_token"], config["line_user_id"],
                        text, buttons=True)

        # Wait up to 12 hours for user response
        approval_event.clear()
        approval_data.clear()
        try:
            await asyncio.wait_for(approval_event.wait(), timeout=43200)
        except asyncio.TimeoutError:
            await line_send(config["line_token"], config["line_user_id"],
                            "12時間応答なし。この会話をスキップします。")
            continue

        action = approval_data.get("action")
        if action == "send":
            custom = approval_data.get("custom")
            if custom:
                # User typed a custom reply in Japanese — translate it first
                try:
                    reply_text = await asyncio.get_event_loop().run_in_executor(
                        None, translate_to_buyer_language,
                        custom, buyer_lang, config["anthropic_api_key"]
                    )
                    await line_send(
                        config["line_token"], config["line_user_id"],
                        f"翻訳しました：\n{reply_text}\n\nCatawikiに送信します..."
                    )
                except Exception as e:
                    print(f"Translation error: {e}")
                    reply_text = custom   # fallback: send as-is
                    await line_send(config["line_token"], config["line_user_id"],
                                    f"翻訳に失敗しました。原文のまま送信します。\nエラー: {e}")
            else:
                reply_text = ai_reply
            ok = await send_catawiki_reply(browser_page, thread, reply_text)
            status = "返信をCatawikiに送りました！" if ok else "送信に失敗しました。Catawikiを直接確認してください。"
            await line_send(config["line_token"], config["line_user_id"], status)
        else:
            await line_send(config["line_token"], config["line_user_id"], "スキップしました。")

# ── Catawiki check loop ───────────────────────────────────────────────────────
async def check_catawiki_loop(config: dict):
    """Check Catawiki for new messages every 5 minutes."""
    seen_ids: set = set(load_json(SEEN_FILE, default=[]))
    print("Bot is running. Checking Catawiki every 5 minutes...")

    while True:
        try:
            threads = await fetch_threads(browser_page)
            for thread in threads:
                tid = thread_id(thread)
                if tid in seen_ids:
                    continue

                seen_ids.add(tid)
                save_json(SEEN_FILE, list(seen_ids))

                print(f"New message found. Generating AI reply...")
                try:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, generate_reply, thread["text"], config["anthropic_api_key"]
                    )
                except Exception as e:
                    print(f"AI error: {e}")
                    await line_send(config["line_token"], config["line_user_id"],
                                    f"AIエラーが発生しました。Catawikiを直接確認してください。\n\nエラー: {e}")
                    continue

                if result["needs_review"]:
                    note = result["reply"].replace("[NEEDS_REVIEW]", "").strip()
                    msg_preview = thread["text"][:200]
                    msg_ja = result["message_ja"][:200] if result["message_ja"] else ""
                    lines = ["【要確認メッセージ】\n",
                             f"【原文】\n{msg_preview}"]
                    if msg_ja:
                        lines.append(f"\n【日本語訳】\n{msg_ja}")
                    lines.append(f"\n{note}")
                    await line_send(config["line_token"], config["line_user_id"],
                                    "\n".join(lines))
                else:
                    await message_queue.put({
                        "thread":     thread,
                        "ai_reply":   result["reply"],
                        "reply_ja":   result["reply_ja"],
                        "message_ja": result["message_ja"],
                        "lang":       result["lang"],
                    })

        except Exception as e:
            print(f"Catawiki check error: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    global browser_page

    if not CONFIG_FILE.exists():
        print("config.json not found. Run setup.bat first.")
        input("Press Enter to exit...")
        sys.exit(1)

    try:
        config = load_json(CONFIG_FILE)
    except Exception as e:
        print("config.json の読み込みに失敗しました。")
        print(f"エラー内容: {e}")
        print()
        print("よくある原因：")
        print("  - 値を入力したあとダブルクォーテーション(\")が消えている")
        print("  - 最後の項目の後にカンマ(,)が残っている")
        print("  - ファイルが正しく保存されていない")
        print()
        print("config.json の正しい書き方の例：")
        print('{')
        print('  "email": "yourname@gmail.com",')
        print('  "anthropic_api_key": "sk-ant-abc123...",')
        print('  "line_token": "XYZ123...",')
        print('  "line_user_id": "U1234567890abcdef",')
        print('  "ngrok_auth_token": "2abc123..."')
        print('}')
        input("\nEnterキーを押して終了...")
        sys.exit(1)

    for key in ["email", "anthropic_api_key", "line_token", "line_user_id", "ngrok_auth_token"]:
        val = config.get(key, "")
        if not val or val.startswith("Enter"):
            print(f"Please set '{key}' in config.json")
            input("Press Enter to exit...")
            sys.exit(1)

    # Ask for Catawiki password
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    password = simpledialog.askstring(
        "Catawiki Login", "Enter your Catawiki password:", show="*", parent=root)
    root.destroy()
    if not password:
        sys.exit(0)
    config["password"] = password

    # Start local webhook server FIRST (before registering with LINE)
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT).start()
    print(f"Webhookサーバー起動完了 (port {WEBHOOK_PORT})")

    # Start ngrok tunnel
    print("ngrokトンネルを起動中...")
    try:
        from pyngrok import ngrok, conf
        conf.get_default().auth_token = config["ngrok_auth_token"]
        domain = config.get("ngrok_domain", "").strip()
        if domain:
            tunnel = ngrok.connect(WEBHOOK_PORT, "http", hostname=domain)
        else:
            tunnel = ngrok.connect(WEBHOOK_PORT, "http")
        webhook_url = f"{tunnel.public_url}/webhook"
        print(f"Webhook URL: {webhook_url}")
    except Exception as e:
        print(f"ngrokエラー: {e}")
        print("pyngrokがインストールされているか、ngrok認証トークンが正しいか確認してください。")
        input("Enterキーを押して終了...")
        sys.exit(1)

    # Configure LINE webhook (automatic)
    await set_line_webhook(config["line_token"], webhook_url)

    # Start browser
    BROWSER_DATA.mkdir(exist_ok=True)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_DATA),
            headless=True,   # run in background (no visible browser window)
            args=["--no-sandbox"],
        )
        browser_page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        ok = await ensure_logged_in(browser_page, config)
        if not ok:
            print("Catawiki login failed.")
            input("Press Enter to exit...")
            return

        print("ログイン成功。ボットはバックグラウンドで動作中。")
        await line_send(config["line_token"], config["line_user_id"],
                        "Catawikiボット起動しました！\n新着メッセージが届いたらここに通知します。")

        await asyncio.gather(
            check_catawiki_loop(config),
            process_messages_loop(config),
        )
        await ctx.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped.")
