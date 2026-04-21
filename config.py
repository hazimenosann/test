import os

# --- Gmail Search Configuration ---
GMAIL_SEARCH_QUERIES = [
    "subject:(領収書 OR 請求書 OR receipt OR invoice OR お支払い確認 OR ご利用明細 OR 購入完了)",
    "has:attachment filename:pdf (領収書 OR 請求書 OR receipt OR invoice)",
    "subject:(payment confirmation OR order confirmation OR your order)",
]

# Only process emails newer than this date (YYYY/MM/DD format for Gmail query)
# Set to None to process all mail
SEARCH_AFTER_DATE = None  # e.g. "2024/01/01"

# Maximum number of emails to fetch per query
MAX_RESULTS = 500

# --- Output Configuration ---
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "receipts")
INDEX_CSV_PATH = os.path.join(OUTPUT_DIR, "receipt_index.csv")
HASH_LOG_PATH = os.path.join(OUTPUT_DIR, "integrity_hashes.json")
PROCESSED_IDS_PATH = os.path.join(OUTPUT_DIR, ".processed_message_ids")

# --- OAuth2 Configuration ---
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "token.json")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# --- Claude API Configuration ---
ANTHROPIC_MODEL = "claude-sonnet-4-6"

# --- 電子帳簿保存法 Compliance Settings ---
FILENAME_UNSAFE_CHARS = r'[\\/*?:"<>|]'
MAX_FILENAME_COUNTERPARTY_LEN = 30

# Amount regex patterns (covers ¥1,234 / 1,234円 / JPY 1,234 / $12.34)
AMOUNT_PATTERNS = [
    r"[¥￥]\s*([0-9,]+)",
    r"([0-9,]+)\s*円",
    r"JPY\s*([0-9,]+)",
    r"\$\s*([0-9,.]+)",
    r"USD\s*([0-9,.]+)",
    r"合計[^\d]*([0-9,]+)",
    r"お支払い金額[^\d]*([0-9,]+)",
    r"ご請求金額[^\d]*([0-9,]+)",
    r"請求金額[^\d]*([0-9,]+)",
    r"total[\s:：]*[¥$]?\s*([0-9,]+\.?[0-9]*)",
    r"amount[\s:：]*[¥$]?\s*([0-9,]+\.?[0-9]*)",
]

# Date regex patterns
DATE_PATTERNS = [
    r"(\d{4})[年/\-](\d{1,2})[月/\-](\d{1,2})日?",
    r"(\d{4})/(\d{2})/(\d{2})",
    r"(\d{2})/(\d{2})/(\d{4})",
]

# Gmail API rate limiting
GMAIL_REQUEST_DELAY = 0.1  # seconds between API calls
GMAIL_RETRY_MAX = 5
GMAIL_RETRY_BASE_DELAY = 1.0
