"""
Nightly SQLite backup utility.
Copies data/basecamp.db to data/backups/basecamp_YYYYMMDD_HHMMSS.db,
validates the copy, and retains the 30 most recent backups.

Run directly:  python server/backup.py
Import:        from server.backup import run_backup; run_backup()
"""
import logging
import logging.handlers
import os
import shutil
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.config import DB_PATH, NTFY_SERVER, NTFY_TOPIC

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
_handler = logging.handlers.RotatingFileHandler(
    "logs/backup.log", maxBytes=5 * 1024 * 1024, backupCount=3
)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_stream = logging.StreamHandler()
_stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log = logging.getLogger("backup")
log.setLevel(logging.INFO)
log.addHandler(_handler)
log.addHandler(_stream)

BACKUP_RETENTION = 30


def _notify_failure(reason: str) -> None:
    """Send an ntfy push notification reporting a backup failure."""
    try:
        url = f"{NTFY_SERVER}/{NTFY_TOPIC}".encode()
        req = urllib.request.Request(
            f"{NTFY_SERVER}/{NTFY_TOPIC}",
            data=reason.encode("utf-8"),
            headers={
                "Title": "Basecamp Backup FAILED",
                "Priority": "high",
                "Tags": "warning",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        log.warning(f"Failed to send ntfy notification: {exc}")


def run_backup(db_path: str | None = None, backup_dir: str | None = None) -> bool:
    """
    Back up the SQLite database.

    db_path    : source database path (defaults to server.config.DB_PATH)
    backup_dir : destination directory (defaults to data/backups/ relative to db_path)

    Returns True on success, False on any failure.
    """
    if db_path is None:
        db_path = DB_PATH

    src = Path(db_path)

    if backup_dir is None:
        dest_dir = src.parent / "backups"
    else:
        dest_dir = Path(backup_dir)

    dest_dir.mkdir(parents=True, exist_ok=True)

    # ---- Validate source exists --------------------------------------------
    if not src.exists():
        msg = f"Source database not found: {src}"
        log.error(msg)
        _notify_failure(msg)
        return False

    # ---- Copy ---------------------------------------------------------------
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"basecamp_{timestamp}.db"

    try:
        shutil.copy2(str(src), str(dest))
    except Exception as exc:
        msg = f"Copy failed ({src} → {dest}): {exc}"
        log.error(msg)
        _notify_failure(msg)
        return False

    # ---- Validate backup is a readable SQLite file -------------------------
    try:
        conn = sqlite3.connect(str(dest))
        try:
            # Query sqlite_master to force the file header to be read
            conn.execute("SELECT COUNT(*) FROM sqlite_master")
        finally:
            conn.close()
    except Exception as exc:
        msg = f"Backup validation failed for {dest}: {exc}"
        log.error(msg)
        try:
            dest.unlink()
        except Exception:
            pass
        _notify_failure(msg)
        return False

    log.info(f"Backup created: {dest} ({dest.stat().st_size / 1024:.1f} KB)")

    # ---- Retention: keep only the 30 most recent backups -------------------
    backups = sorted(dest_dir.glob("basecamp_*.db"), key=lambda p: p.name)
    excess = backups[: max(0, len(backups) - BACKUP_RETENTION)]
    for old in excess:
        try:
            old.unlink()
            log.info(f"Deleted old backup: {old.name}")
        except Exception as exc:
            log.warning(f"Could not delete old backup {old.name}: {exc}")

    return True


if __name__ == "__main__":
    success = run_backup()
    sys.exit(0 if success else 1)
