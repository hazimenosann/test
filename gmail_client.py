import base64
import time
from email.utils import parsedate_to_datetime

from googleapiclient.errors import HttpError

import config


def _retry(func, *args, **kwargs):
    """Call func with exponential backoff on rate limit errors."""
    for attempt in range(config.GMAIL_RETRY_MAX):
        try:
            return func(*args, **kwargs)
        except HttpError as e:
            if e.resp.status == 429 and attempt < config.GMAIL_RETRY_MAX - 1:
                time.sleep(config.GMAIL_RETRY_BASE_DELAY * (2 ** attempt))
            else:
                raise


def search_receipt_messages(service, queries, after_date=None):
    """Search Gmail with given queries and return deduplicated message ID list."""
    seen = set()
    msg_ids = []

    for query in queries:
        if after_date:
            query = f"{query} after:{after_date}"

        page_token = None
        while True:
            time.sleep(config.GMAIL_REQUEST_DELAY)
            try:
                result = _retry(
                    service.users().messages().list(
                        userId="me", q=query, maxResults=500, pageToken=page_token
                    ).execute
                )
            except HttpError as e:
                print(f"  [警告] 検索クエリ失敗: {e}")
                break

            for msg in result.get("messages", []):
                mid = msg["id"]
                if mid not in seen:
                    seen.add(mid)
                    msg_ids.append(mid)

            page_token = result.get("nextPageToken")
            if not page_token:
                break

    return msg_ids


def get_message_detail(service, msg_id):
    """Fetch full message payload for a given Gmail message ID."""
    time.sleep(config.GMAIL_REQUEST_DELAY)
    return _retry(
        service.users().messages().get(userId="me", id=msg_id, format="full").execute
    )


def extract_headers(payload):
    """Parse Gmail payload headers into a lowercase-keyed dict."""
    headers = {}
    for h in payload.get("headers", []):
        headers[h["name"].lower()] = h["value"]
    return headers


def _decode_base64url(data):
    """Decode Gmail's base64url-encoded string, padding as needed."""
    data = data.replace("-", "+").replace("_", "/")
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.b64decode(data)


def _walk_parts(payload):
    """Recursively yield all leaf parts of a MIME message."""
    parts = payload.get("parts", [])
    if not parts:
        yield payload
    else:
        for part in parts:
            yield from _walk_parts(part)


def extract_attachments(service, msg_id, payload):
    """
    Return list of dicts with keys: filename, data (bytes), mime_type.
    Handles both inline data and external attachment IDs.
    """
    attachments = []
    for part in _walk_parts(payload):
        mime = part.get("mimeType", "")
        filename = part.get("filename", "")
        body = part.get("body", {})

        is_pdf = mime == "application/pdf" or filename.lower().endswith(".pdf")
        is_image = mime in ("image/jpeg", "image/png", "image/gif", "image/webp")

        if not (is_pdf or is_image):
            continue

        if body.get("attachmentId"):
            time.sleep(config.GMAIL_REQUEST_DELAY)
            try:
                att = _retry(
                    service.users().messages().attachments().get(
                        userId="me", messageId=msg_id, id=body["attachmentId"]
                    ).execute
                )
                data = _decode_base64url(att["data"])
            except HttpError as e:
                print(f"  [警告] 添付ダウンロード失敗 ({filename}): {e}")
                continue
        elif body.get("data"):
            data = _decode_base64url(body["data"])
        else:
            continue

        attachments.append({"filename": filename or "attachment", "data": data, "mime_type": mime})

    return attachments


def extract_html_body(payload):
    """Return the first HTML body part as a decoded string, or None."""
    for part in _walk_parts(payload):
        if part.get("mimeType") == "text/html":
            data = part.get("body", {}).get("data", "")
            if data:
                raw = _decode_base64url(data)
                try:
                    return raw.decode("utf-8")
                except UnicodeDecodeError:
                    from charset_normalizer import from_bytes
                    result = from_bytes(raw).best()
                    return str(result) if result else raw.decode("utf-8", errors="replace")
    return None


def extract_plain_body(payload):
    """Return the first plain-text body part as a decoded string, or empty string."""
    for part in _walk_parts(payload):
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                raw = _decode_base64url(data)
                try:
                    return raw.decode("utf-8")
                except UnicodeDecodeError:
                    return raw.decode("utf-8", errors="replace")
    return ""
