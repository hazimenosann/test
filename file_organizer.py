import os
import re


def ensure_monthly_dir(base_dir, date):
    """Create and return path to receipts/YYYY/YYYY-MM/ directory."""
    year_dir = os.path.join(base_dir, str(date.year))
    month_dir = os.path.join(year_dir, f"{date.year}-{date.month:02d}")
    os.makedirs(month_dir, exist_ok=True)
    return month_dir


def get_output_path(base_dir, date, filename):
    """Return the full output file path for a receipt, creating dirs as needed."""
    month_dir = ensure_monthly_dir(base_dir, date)
    return os.path.join(month_dir, filename)


def resolve_filename_conflict(path):
    """
    If path already exists, append _2, _3, ... before the extension.
    Returns a path that does not currently exist.
    """
    if not os.path.exists(path):
        return path

    base, ext = os.path.splitext(path)
    counter = 2
    while True:
        candidate = f"{base}_{counter}{ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def load_processed_ids(path):
    """Load set of already-processed Gmail message IDs from file."""
    if not os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def save_processed_id(path, msg_id):
    """Append a Gmail message ID to the processed IDs file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(msg_id + "\n")


def is_duplicate(msg_id, processed_ids):
    """Return True if this message ID has already been processed."""
    return msg_id in processed_ids


def write_pdf(path, pdf_bytes):
    """
    Write PDF bytes to path atomically.
    Removes the file if write fails midway to avoid corrupt files.
    """
    import tempfile
    dir_path = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(pdf_bytes)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
