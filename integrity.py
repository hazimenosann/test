import datetime
import hashlib
import json
import os
import tempfile


def compute_sha256(file_path):
    """Compute SHA-256 hash of file, reading in 64KB chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_timestamp():
    """Return current UTC time in ISO 8601 format."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save_hash(hash_log_path, filename, sha256, timestamp):
    """Atomically append a hash record to the JSON hash log."""
    if os.path.exists(hash_log_path):
        with open(hash_log_path, "r", encoding="utf-8") as f:
            log = json.load(f)
    else:
        log = {}

    log[filename] = {
        "sha256": sha256,
        "saved_at": timestamp,
        "verified_at": None,
    }

    dir_path = os.path.dirname(hash_log_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, hash_log_path)
    except Exception:
        os.unlink(tmp_path)
        raise


def verify_all_hashes(hash_log_path, receipts_dir):
    """
    Verify all files in the hash log against their stored SHA-256 values.
    Returns list of dicts with keys: file, status (ok/MODIFIED/MISSING).
    """
    if not os.path.exists(hash_log_path):
        return []

    with open(hash_log_path, "r", encoding="utf-8") as f:
        log = json.load(f)

    results = []
    now = generate_timestamp()

    for filename, record in log.items():
        # Support both absolute paths and relative filenames
        if os.path.isabs(filename):
            file_path = filename
        else:
            file_path = os.path.join(receipts_dir, filename)

        if not os.path.exists(file_path):
            results.append({"file": filename, "status": "MISSING"})
            continue

        actual = compute_sha256(file_path)
        if actual == record["sha256"]:
            results.append({"file": filename, "status": "ok"})
            record["verified_at"] = now
        else:
            results.append({"file": filename, "status": "MODIFIED"})

    # Persist updated verified_at timestamps
    dir_path = os.path.dirname(hash_log_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, hash_log_path)
    except Exception:
        os.unlink(tmp_path)

    return results
