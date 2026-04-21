import csv
import os

# UTF-8-sig (BOM) ensures Japanese text displays correctly when opened in
# Microsoft Excel on Japanese Windows, which defaults to Shift_JIS detection.
CSV_ENCODING = "utf-8-sig"

FIELDNAMES = [
    "receipt_date",
    "amount",
    "amount_currency",
    "counterparty",
    "filename",
    "filepath",
    "email_subject",
    "email_from",
    "email_message_id",
    "gmail_msg_id",
    "saved_at",
    "sha256",
    "source_type",
    "needs_review",
]


def append_to_index(csv_path, record):
    """Append a receipt record to the CSV index, writing the header if needed."""
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    write_header = not os.path.exists(csv_path)

    with open(csv_path, "a", newline="", encoding=CSV_ENCODING) as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(record)


def search_index(csv_path, date_from=None, date_to=None,
                 amount_min=None, amount_max=None, counterparty=None):
    """
    Search the CSV index with optional filters.
    Returns list of matching record dicts.
    Implements the 電子帳簿保存法 検索要件 (range search by date, amount, counterparty).
    """
    if not os.path.exists(csv_path):
        return []

    results = []
    with open(csv_path, "r", newline="", encoding=CSV_ENCODING) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if date_from and row.get("receipt_date", "") < date_from:
                continue
            if date_to and row.get("receipt_date", "") > date_to:
                continue
            if amount_min is not None:
                try:
                    if int(row.get("amount", 0)) < amount_min:
                        continue
                except ValueError:
                    pass
            if amount_max is not None:
                try:
                    if int(row.get("amount", 0)) > amount_max:
                        continue
                except ValueError:
                    pass
            if counterparty and counterparty.lower() not in row.get("counterparty", "").lower():
                continue
            results.append(row)

    return results


def build_record(date, amount, counterparty, filename, filepath, subject,
                 email_from, email_message_id, gmail_msg_id, saved_at, sha256,
                 source_type, needs_review=False):
    """Build a dict matching the CSV schema."""
    try:
        amount_int = int(amount)
        currency = "JPY"
    except (ValueError, TypeError):
        amount_int = amount
        currency = ""

    return {
        "receipt_date": date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date),
        "amount": amount_int,
        "amount_currency": currency,
        "counterparty": counterparty,
        "filename": filename,
        "filepath": filepath,
        "email_subject": subject,
        "email_from": email_from,
        "email_message_id": email_message_id,
        "gmail_msg_id": gmail_msg_id,
        "saved_at": saved_at,
        "sha256": sha256,
        "source_type": source_type,
        "needs_review": "yes" if needs_review else "",
    }
