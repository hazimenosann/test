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
def generate_reply(message_text: str, api_key: str) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": message_text}],
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
            json={"webhook_endpoint": url},
        )
        if r.status != 200:
            body = await r.text()
            print(f"[LINE] webhook set failed ({r.status}): {body}")

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
        msg_data = await message_queue.get()
        thread   = msg_data["thread"]
        ai_reply = msg_data["ai_reply"]

        preview = thread["text"][:300] + ("..." if len(thread["text"]) > 300 else "")
        text = (
            "New message on Catawiki:\n\n"
            f"{preview}\n\n"
            "──────────────────\n"
            "AI suggested reply:\n\n"
            f"{ai_reply}\n\n"
            "──────────────────\n"
            "Tap 'Send reply' to send the AI reply.\n"
            "Tap 'Skip' to skip.\n"
            "Or type your own reply to send that instead."
        )
        await line_send(config["line_token"], config["line_user_id"],
                        text, buttons=True)

        # Wait up to 12 hours for user response
        approval_event.clear()
        approval_data.clear()
        try:
            await asyncio.wait_for(approval_event.wait(), timeout=43200)
        except asyncio.TimeoutError:
            await line_send(config["line_token"], config["line_user_id"],
                            "No response in 12 hours. Skipping this message.")
            continue

        action = approval_data.get("action")
        if action == "send":
            reply_text = approval_data.get("custom") or ai_reply
            ok = await send_catawiki_reply(browser_page, thread, reply_text)
            status = "Reply sent on Catawiki!" if ok else "Failed to send reply. Please check Catawiki manually."
            await line_send(config["line_token"], config["line_user_id"], status)
        else:
            await line_send(config["line_token"], config["line_user_id"], "Skipped.")

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
                    ai_reply = generate_reply(thread["text"], config["anthropic_api_key"])
                except Exception as e:
                    print(f"AI error: {e}")
                    await line_send(config["line_token"], config["line_user_id"],
                                    f"AI error for a new message. Please check Catawiki manually.\n\nError: {e}")
                    continue

                if ai_reply.startswith("[NEEDS_REVIEW]"):
                    note = ai_reply.replace("[NEEDS_REVIEW]", "").strip()
                    await line_send(
                        config["line_token"], config["line_user_id"],
                        f"New message needs your attention:\n\n{thread['text'][:300]}\n\n{note}"
                    )
                else:
                    await message_queue.put({"thread": thread, "ai_reply": ai_reply})

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
    except Exception:
        print("Failed to read config.json.")
        input("Press Enter to exit...")
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

    # Start ngrok tunnel
    print("Starting ngrok tunnel...")
    try:
        from pyngrok import ngrok, conf
        conf.get_default().auth_token = config["ngrok_auth_token"]
        tunnel = ngrok.connect(WEBHOOK_PORT, "http")
        webhook_url = f"{tunnel.public_url}/webhook"
        print(f"Public URL: {webhook_url}")
    except Exception as e:
        print(f"ngrok error: {e}")
        print("Make sure pyngrok is installed and your ngrok auth token is correct.")
        input("Press Enter to exit...")
        sys.exit(1)

    # Configure LINE webhook
    print("Setting LINE webhook...")
    await set_line_webhook(config["line_token"], webhook_url)

    # Start local webhook server
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "localhost", WEBHOOK_PORT).start()
    print(f"Webhook server running on port {WEBHOOK_PORT}")

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

        print("Login successful. Bot is running in the background.")
        await line_send(config["line_token"], config["line_user_id"],
                        "Catawiki bot started! You will be notified of new messages here.")

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
