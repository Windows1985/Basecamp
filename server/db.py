import os
import sqlite3


def init_db(db_path):
    """Create tables if they don't exist. Returns db_path."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
    conn = sqlite3.connect(db_path)
    try:
        with open(schema_path) as f:
            conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()
    return db_path


def get_connection(db_path):
    """Return a sqlite3 connection with Row factory enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_latest_session_id(db_path):
    """Return the id of the most recent sleep session, or None."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM sleep_sessions ORDER BY bed_entry DESC LIMIT 1"
        ).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()
