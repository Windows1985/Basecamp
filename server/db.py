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


def migrate_schema(db_path):
    """
    Add columns/tables introduced after initial schema.
    ALTER TABLE errors are swallowed — they fire when a column already exists.
    """
    column_migrations = [
        "ALTER TABLE radar_events ADD COLUMN pi_timestamp REAL",
        "ALTER TABLE audio_chunks ADD COLUMN pi_timestamp REAL",
        "ALTER TABLE csi_variance ADD COLUMN pi_timestamp REAL",
        "ALTER TABLE sensor_readings ADD COLUMN max_lux REAL",
        "ALTER TABLE sleep_sessions ADD COLUMN status TEXT DEFAULT 'COMPLETE'",
        "ALTER TABLE sleep_sessions ADD COLUMN created_at REAL",
    ]
    conn = sqlite3.connect(db_path)
    try:
        for sql in column_migrations:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # column already exists

        # Default any NULL status rows on sleep_sessions to COMPLETE
        conn.execute(
            "UPDATE sleep_sessions SET status='COMPLETE' WHERE status IS NULL"
        )

        # Ensure new tables exist (idempotent — schema.sql uses IF NOT EXISTS)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS service_heartbeats (
                service_name TEXT PRIMARY KEY,
                last_heartbeat REAL,
                status TEXT
            );
            CREATE TABLE IF NOT EXISTS daemon_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                state TEXT NOT NULL DEFAULT 'IDLE',
                updated_at REAL NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


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
