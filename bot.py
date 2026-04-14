import anthropic
import asyncio
import json
import sys
import tkinter as tk
from tkinter import simpledialog, messagebox
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

CONFIG_FILE  = Path("config.json")
BROWSER_DATA = Path("browser_data")

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
- Keep replies concise but complete — no unnecessary filler
- If you can answer confidently, write the full reply ready to send
- If the message requires information you don't have (specific order status, tracking number,
  custom requests, complaints needing investigation, or anything else outside your knowledge),
  start your reply with exactly: [NEEDS_REVIEW]
  Then briefly explain what information is needed from the seller.

Never make up order details, tracking numbers, or delivery dates you don't know."""

# ------------------------------------------------------------------ helpers --

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def hr():
    print("-" * 55)

# ----------------------------------------------------------------- AI reply --

def generate_reply(message_text: str, api_key: str) -> str:
    """Call Claude API to generate a human-like reply."""
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"}
        }],
        messages=[{
            "role": "user",
            "content": message_text
        }]
    )

    return response.content[0].text.strip()

# ------------------------------------------------------------------- login ---

async def ensure_logged_in(page, config):
    await page.goto("https://www.catawiki.com", wait_until="domcontentloaded", timeout=30000)
    if "/login" not in page.url and "catawiki.com" in page.url:
        try:
            await page.wait_for_selector(
                '[data-testid="header-account"], .header-account, [aria-label="Account"]',
                timeout=5000
            )
            print("Already logged in.")
            return True
        except PlaywrightTimeoutError:
            pass

    print("Logging in to Catawiki...")
    await page.goto("https://www.catawiki.com/login", wait_until="networkidle", timeout=30000)

    try:
        await page.fill('input[type="email"]',    config["email"],    timeout=10000)
        await page.fill('input[type="password"]', config["password"], timeout=10000)
        await page.click('button[type="submit"]', timeout=10000)
        await page.wait_for_load_state("networkidle", timeout=30000)
    except Exception as e:
        await page.screenshot(path="debug_login.png")
        print(f"Login failed: {e}")
        print("  -> See debug_login.png")
        return False

    if "/login" in page.url:
        print("Login failed -- check email and password in config.json")
        return False

    print("Login successful!")
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
    print("Fetching messages...")
    for url in MESSAGE_URLS:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        if "message" in page.url:
            break

    await page.screenshot(path="debug_messages.png")
    items = await page.query_selector_all(THREAD_SELECTORS)

    if not items:
        print("No messages found.")
        print("  -> Check debug_messages.png to verify the page loaded correctly")
        return []

    threads = []
    for el in items:
        text = (await el.inner_text()).strip()
        link = await el.query_selector("a")
        href = await link.get_attribute("href") if link else None
        cls  = await el.get_attribute("class") or ""
        threads.append({
            "text": text,
            "href": href,
            "unread": "unread" in cls.lower() or "new" in cls.lower()
        })
    return threads

REPLY_SELECTORS = 'textarea[name="message"], textarea[placeholder], .reply-box textarea'
SEND_SELECTORS  = ('button[type="submit"], .send-button, '
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
            print("Reply box not found -- see debug_reply.png")
            return False

        await box.click()
        await box.fill(reply_text)

        btn = await page.query_selector(SEND_SELECTORS)
        if not btn:
            print("Send button not found")
            return False

        await btn.click()
        await page.wait_for_load_state("networkidle", timeout=15000)
        return True
    except Exception as e:
        print(f"Send error: {e}")
        return False

# -------------------------------------------------------- feature: messages --

async def feature_check_messages(page, api_key):
    threads = await fetch_message_threads(page)
    if not threads:
        return

    print(f"\n{len(threads)} message thread(s) found.\n")

    for i, t in enumerate(threads, 1):
        hr()
        print(f"[{i}/{len(threads)}]")
        preview = t["text"][:300] + ("..." if len(t["text"]) > 300 else "")
        print(preview)
        print()

        print("Generating reply with AI...")
        try:
            reply = generate_reply(t["text"], api_key)
        except Exception as e:
            print(f"AI error: {e}")
            print("Skipping this message.")
            continue

        needs_review = reply.startswith("[NEEDS_REVIEW]")

        if needs_review:
            print()
            print("*** THIS MESSAGE NEEDS YOUR ATTENTION ***")
            print(reply.replace("[NEEDS_REVIEW]", "").strip())
            print()
            input("Press Enter to continue to the next message...")
            continue

        print()
        print("AI reply:")
        hr()
        print(reply)
        hr()
        print()
        print("[s] Send  [e] Edit  [n] Skip")
        choice = input("> ").strip().lower()

        if choice == "s":
            ok = await send_reply(page, t, reply)
            print("Sent!" if ok else "Failed to send.")
        elif choice == "e":
            # Open an edit dialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            edited = simpledialog.askstring(
                "Edit reply",
                "Edit the reply below:",
                initialvalue=reply,
                parent=root
            )
            root.destroy()
            if edited and edited.strip():
                ok = await send_reply(page, t, edited.strip())
                print("Sent!" if ok else "Failed to send.")
            else:
                print("Cancelled.")
        else:
            print("Skipped.")

        print()

# -------------------------------------------------------------------- main ---

async def main():
    if not CONFIG_FILE.exists():
        print(f"config.json not found. Please run setup.bat first.")
        input("Press Enter to exit...")
        sys.exit(1)

    try:
        config = load_json(CONFIG_FILE)
    except Exception:
        print("Failed to read config.json.")
        print()
        print("Correct format:")
        print('{')
        print('  "email": "your@email.com",')
        print('  "anthropic_api_key": "sk-ant-..."')
        print('}')
        input("\nPress Enter to exit...")
        sys.exit(1)

    email = config.get("email", "")
    if not email or email.startswith("Enter"):
        print("Please set your email in config.json")
        input("Press Enter to exit...")
        sys.exit(1)

    api_key = config.get("anthropic_api_key", "")
    if not api_key or api_key.startswith("Enter"):
        print("Please set your Anthropic API key in config.json")
        print("Get your key at: https://console.anthropic.com/")
        input("Press Enter to exit...")
        sys.exit(1)

    # Ask for Catawiki password via dialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    password = simpledialog.askstring(
        "Catawiki Login",
        "Enter your Catawiki password:",
        show="*",
        parent=root
    )
    root.destroy()

    if not password:
        sys.exit(0)

    config["password"] = password

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
            input("Press Enter to exit...")
            await ctx.close()
            return

        while True:
            print()
            print("=" * 55)
            print("  Catawiki AI Customer Service Bot")
            print("=" * 55)
            print("  1. Check messages and generate AI replies")
            print("  2. Exit")
            print("=" * 55)
            choice = input("  Enter number: ").strip()

            if choice == "1":
                await feature_check_messages(page, api_key)
            elif choice == "2":
                print("Goodbye!")
                break
            else:
                print("Please enter 1 or 2.")

        await ctx.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited.")
