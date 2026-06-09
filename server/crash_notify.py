"""
server/crash_notify.py

Stdlib-only crash notification module for Basecamp daemons.
Sends ntfy push notifications when a daemon fails; tracks failure counts
in SQLite so repeated failures within the same night escalate to high priority.
"""
import json
import os
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    from server.config import DB_PATH, NTFY_SERVER, NTFY_TOPIC
except ImportError:
    DB_PATH = "data/basecamp.db"
    NTFY_SERVER = "https://ntfy.sh"
    NTFY_TOPIC = "basecamp-recovery"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS daemon_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    daemon_name TEXT NOT NULL,
    date TEXT NOT NULL,
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_notified_at TEXT,
    UNIQUE(daemon_name, date)
)
"""


def _ensure_table(conn):
    conn.execute(_CREATE_TABLE_SQL)
    conn.commit()


def _get_failure_count(daemon_name):
    """Return today's failure count for daemon_name without modifying it."""
    today = date.today().isoformat()
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            _ensure_table(conn)
            row = conn.execute(
                "SELECT failure_count FROM daemon_failures WHERE daemon_name=? AND date=?",
                (daemon_name, today),
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()
    except Exception:
        return 0


def _send_ntfy(title, body, priority, tags):
    """POST a notification to ntfy. Returns True on 2xx, False otherwise. Never raises."""
    url = f"{NTFY_SERVER}/{NTFY_TOPIC}"
    payload = json.dumps({
        "topic": NTFY_TOPIC,
        "title": title,
        "message": body,
        "priority": priority,
        "tags": tags,
    }).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status < 300
    except Exception:
        return False


def notify_crash(daemon_name, failure_count, last_error=None):
    """
    Send an ntfy push notification for a daemon crash.

    Increments the failure counter in the database, then sends a push notification.
    Priority is "high" and tag is "rotating_light" for failure_count >= 3; otherwise
    priority is "default" and tag is "warning".

    Returns True on success, False on any failure. Never raises.
    """
    try:
        # Record the failure in the database.
        today = date.today().isoformat()
        now_str = datetime.utcnow().isoformat()
        try:
            conn = sqlite3.connect(DB_PATH)
            try:
                _ensure_table(conn)
                conn.execute(
                    """INSERT INTO daemon_failures
                           (daemon_name, date, failure_count, last_notified_at)
                       VALUES (?, ?, 1, ?)
                       ON CONFLICT(daemon_name, date) DO UPDATE SET
                           failure_count = failure_count + 1,
                           last_notified_at = excluded.last_notified_at""",
                    (daemon_name, today, now_str),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass  # DB errors must not block the notification

        if failure_count >= 3:
            priority = "high"
            tags = ["rotating_light"]
        else:
            priority = "default"
            tags = ["warning"]

        title = f"Basecamp: {daemon_name} crashed"
        body = f"{daemon_name} has failed {failure_count} time(s) tonight."
        if last_error:
            body += f"\n{last_error[:200]}"

        return _send_ntfy(title, body, priority, tags)
    except Exception:
        return False


def notify_recovery(daemon_name):
    """
    Send a low-priority ntfy notification that daemon_name has recovered.

    Only sends if there were failures recorded for daemon_name today.
    Returns True on success, False if no failures today or on any error. Never raises.
    """
    try:
        count = _get_failure_count(daemon_name)
        if count <= 0:
            return False

        title = f"Basecamp: {daemon_name} recovered"
        body = f"{daemon_name} is running again after {count} failure(s) tonight."
        return _send_ntfy(title, body, "low", ["white_check_mark"])
    except Exception:
        return False


if __name__ == "__main__":
    # Called by systemd OnFailure via basecamp-notify@.service.
    # argv[1] is the failed unit name, e.g. "basecamp-logger.service" (%i specifier).
    unit_name = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    daemon_name = unit_name.replace(".service", "")

    # Read the count before incrementing so we can pass count+1 to notify_crash,
    # which will then perform the actual increment.
    pre_count = _get_failure_count(daemon_name)
    failure_count = pre_count + 1

    ok = notify_crash(daemon_name, failure_count)
    sys.exit(0 if ok else 1)
