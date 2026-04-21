import datetime
import json
import logging
import re
from email.utils import parseaddr, parsedate_to_datetime

import anthropic

import config

logger = logging.getLogger(__name__)

_anthropic_client = None


def _get_client():
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic()
    return _anthropic_client


_SYSTEM_PROMPT = """あなたは電子帳簿保存法に対応した領収書・請求書の情報抽出AIです。
メールの件名・本文・送信者情報から以下の3つの情報を抽出してJSON形式で返してください。

出力フォーマット（必ずJSONのみ、説明文なし）:
{
  "date": "YYYYMMDD",
  "amount": "数値のみ（例: 12800）",
  "counterparty": "取引先名（例: Amazon.co.jp）"
}

ルール:
- date: 取引日・決済日・発行日を優先。見つからない場合は受信日を使用。
- amount: 合計金額・お支払い金額を抽出。数字とカンマのみ（通貨記号なし）。
- counterparty: 企業名・サービス名を優先。なければ送信元ドメイン。
- 不明な場合: date="", amount="0", counterparty="" とする。"""


def extract_metadata_with_claude(subject, body_text, sender, received_date):
    """
    Use Claude API to extract date, amount, and counterparty from email content.
    Falls back to regex/header-based extraction on API failure.
    """
    prompt = f"""件名: {subject}
送信者: {sender}
受信日: {received_date}

本文（最初の3000文字）:
{body_text[:3000]}"""

    try:
        client = _get_client()
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=256,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)
        date_str = result.get("date", "")
        amount_str = str(result.get("amount", "0")).replace(",", "")
        counterparty = result.get("counterparty", "")
        return {
            "date": _parse_date(date_str, received_date),
            "amount": amount_str if amount_str and amount_str != "0" else "金額不明",
            "counterparty": counterparty or _extract_counterparty_from_sender(sender),
        }
    except Exception as e:
        logger.warning(f"Claude API 抽出失敗: {e}。正規表現にフォールバックします。")
        return _fallback_extract(subject, body_text, sender, received_date)


def _fallback_extract(subject, body_text, sender, received_date):
    """Regex-based extraction used when Claude API is unavailable."""
    text = f"{subject}\n{body_text}"
    return {
        "date": _extract_date_regex(text, received_date),
        "amount": _extract_amount_regex(text),
        "counterparty": _extract_counterparty_from_sender(sender),
    }


def _parse_date(date_str, fallback_date):
    """Parse YYYYMMDD string to datetime.date, falling back to fallback_date."""
    if date_str and len(date_str) == 8:
        try:
            return datetime.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
        except ValueError:
            pass
    return fallback_date


def _extract_date_regex(text, fallback_date):
    """Extract date from text using regex patterns, return datetime.date."""
    today = datetime.date.today()
    five_years_ago = today.replace(year=today.year - 5)

    for pattern in config.DATE_PATTERNS:
        for m in re.finditer(pattern, text):
            try:
                groups = m.groups()
                if len(groups) == 3:
                    # Check if format is MM/DD/YYYY (third group is 4 digits)
                    if len(groups[2]) == 4:
                        year, month, day = int(groups[2]), int(groups[0]), int(groups[1])
                    else:
                        year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                    d = datetime.date(year, month, day)
                    if five_years_ago <= d <= today:
                        return d
            except (ValueError, IndexError):
                continue

    return fallback_date


def _extract_amount_regex(text):
    """Extract the largest monetary amount from text using regex."""
    amounts = []
    for pattern in config.AMOUNT_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            raw = m.group(1).replace(",", "").replace("，", "")
            try:
                amounts.append(int(float(raw)))
            except ValueError:
                continue

    if amounts:
        return str(max(amounts))
    return "金額不明"


def _extract_counterparty_from_sender(sender):
    """Extract company name from email From header."""
    display_name, email_addr = parseaddr(sender)
    if display_name:
        # Remove common noise like "no-reply at", angle brackets, etc.
        name = re.sub(r"\s*<[^>]+>", "", display_name).strip()
        if name:
            return name[:config.MAX_FILENAME_COUNTERPARTY_LEN]
    if "@" in email_addr:
        domain = email_addr.split("@")[1]
        # Use the second-level domain as company name
        parts = domain.split(".")
        return parts[-2] if len(parts) >= 2 else domain
    return sender[:config.MAX_FILENAME_COUNTERPARTY_LEN]


def parse_received_date(date_header, fallback=None):
    """Parse email Date header to datetime.date."""
    if fallback is None:
        fallback = datetime.date.today()
    if not date_header:
        return fallback
    try:
        return parsedate_to_datetime(date_header).date()
    except Exception:
        return fallback


def build_filename(date, amount, counterparty):
    """
    Build 電子帳簿保存法-compliant filename: YYYYMMDD_金額_取引先.pdf
    Sanitizes unsafe characters from all components.
    """
    date_str = date.strftime("%Y%m%d")
    amount_clean = re.sub(config.FILENAME_UNSAFE_CHARS, "_", str(amount))
    counterparty_clean = re.sub(config.FILENAME_UNSAFE_CHARS, "_", str(counterparty))
    counterparty_clean = counterparty_clean[:config.MAX_FILENAME_COUNTERPARTY_LEN].strip()
    return f"{date_str}_{amount_clean}_{counterparty_clean}.pdf"
