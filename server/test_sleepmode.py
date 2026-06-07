"""
Integration tests for the sleepmode state machine.

All 7 tests run against a fresh in-memory-style test database.
MOCK_HARDWARE is forced True; a controllable FakeClock is injected so
timing-sensitive transitions can be exercised without sleeping.

Run:  python server/test_sleepmode.py
"""
import os
import sys
import time
import tempfile
import sqlite3
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force mock hardware before importing anything that reads MOCK_HARDWARE
import server.config as _cfg
_cfg.MOCK_HARDWARE = True

from server.db import init_db, get_connection, migrate_schema
from server.sleepmode import SleepModeDaemon, SleepState, _RealClock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeClock:
    """Controllable clock for tests. Both monotonic and wall time advance together."""

    def __init__(self, start_dt: datetime):
        self._dt   = start_dt
        self._mono = 1000.0   # start away from 0 to catch accidental abs-time comparisons

    def monotonic(self):
        return self._mono

    def now(self):
        return self._dt

    def utcnow(self):
        # Simplified: treat local == UTC for test purposes
        return self._dt

    def advance(self, seconds: float):
        self._dt   += timedelta(seconds=seconds)
        self._mono += seconds


def _make_db():
    """Create a fresh test database in a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    migrate_schema(path)
    return path


def _insert_radar(db_path, present: bool, clock: FakeClock):
    """Insert a radar_events row using the fake clock's current time."""
    ts = clock.utcnow().isoformat()
    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO radar_events
               (timestamp, event_type, presence, still_distance, moving_distance)
               VALUES (?, 'reading', ?, ?, 0)""",
            (ts, int(present), 120 if present else 0),
        )
        conn.commit()
    finally:
        conn.close()


def _get_session(db_path, session_id):
    conn = get_connection(db_path)
    try:
        return conn.execute(
            "SELECT * FROM sleep_sessions WHERE id=?", (session_id,)
        ).fetchone()
    finally:
        conn.close()


def _get_latest_session(db_path):
    conn = get_connection(db_path)
    try:
        return conn.execute(
            "SELECT * FROM sleep_sessions ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()


def _make_daemon(db_path, clock, mock_auto_yes=False, mock_auto_exit=False):
    return SleepModeDaemon(
        db_path=db_path,
        mock_hardware=True,
        clock=clock,
        mock_auto_yes=mock_auto_yes,
        mock_auto_exit=mock_auto_exit,
    )


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def _assert(cond, label, detail=""):
    global _PASS, _FAIL
    if cond:
        print(f"  PASS  {label}")
        _PASS += 1
    else:
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))
        _FAIL += 1


# ---------------------------------------------------------------------------
# Test 1 — IDLE → BEDTIME_PROMPT after 2 minutes of sustained presence
# ---------------------------------------------------------------------------

def test_idle_to_bedtime_prompt():
    print("\nTest 1: IDLE → BEDTIME_PROMPT after 2-minute sustained presence")
    db = _make_db()
    clock = FakeClock(datetime(2024, 1, 1, 22, 0, 0))   # 22:00 — inside window (≥21)
    daemon = _make_daemon(db, clock)
    daemon.setup()

    _assert(daemon.state == SleepState.IDLE, "Initial state is IDLE")

    # Tick 1: presence detected at t=0
    _insert_radar(db, True, clock)
    daemon.tick()
    _assert(daemon.state == SleepState.IDLE, "Still IDLE after first presence tick")
    _assert(daemon._presence_start_mono is not None, "Presence arm timer started")

    # Advance 2 minutes — presence maintained
    clock.advance(120)
    _insert_radar(db, True, clock)
    daemon.tick()

    _assert(
        daemon.state == SleepState.BEDTIME_PROMPT,
        "Transitioned to BEDTIME_PROMPT after 2 min presence",
        f"actual state={daemon.state}",
    )


# ---------------------------------------------------------------------------
# Test 2 — BEDTIME_PROMPT → RECORDING on YES press
# ---------------------------------------------------------------------------

def test_bedtime_prompt_yes():
    print("\nTest 2: BEDTIME_PROMPT → RECORDING on YES press")
    db = _make_db()
    clock = FakeClock(datetime(2024, 1, 1, 22, 0, 0))
    daemon = _make_daemon(db, clock)
    daemon.setup()

    # Manually force into BEDTIME_PROMPT
    _insert_radar(db, True, clock)
    daemon.tick()
    clock.advance(121)
    _insert_radar(db, True, clock)
    daemon.tick()
    _assert(daemon.state == SleepState.BEDTIME_PROMPT, "In BEDTIME_PROMPT")

    # Simulate YES touch
    daemon._screen.simulate_touch("YES")
    daemon.tick()

    _assert(
        daemon.state == SleepState.RECORDING,
        "Transitioned to RECORDING after YES",
        f"actual={daemon.state}",
    )

    # Verify bed_entry written to DB
    session = _get_latest_session(db)
    _assert(session is not None, "Sleep session created in DB")
    _assert(
        session["bed_entry"] is not None,
        "bed_entry timestamp written",
        f"bed_entry={session['bed_entry'] if session else None}",
    )
    _assert(
        session["status"] == "RECORDING",
        "Session status is RECORDING",
        f"status={session['status'] if session else None}",
    )


# ---------------------------------------------------------------------------
# Test 3 — RECORDING → MORNING on valid bed exit (absence 15 min, 05:30, ≥4h)
# ---------------------------------------------------------------------------

def test_recording_to_morning():
    print("\nTest 3: RECORDING → MORNING on valid bed exit")
    db = _make_db()
    # Start clock at 05:30 (past WAKE_EARLIEST_HOUR=5) with bed entry 6 hours ago
    clock = FakeClock(datetime(2024, 1, 2, 5, 30, 0))
    daemon = _make_daemon(db, clock)
    daemon.setup()

    # Manually bootstrap RECORDING state with an existing session
    bed_entry_ts = (clock.utcnow() - timedelta(hours=6)).isoformat()
    conn = get_connection(db)
    conn.execute(
        "INSERT INTO sleep_sessions (bed_entry, bed_exit, duration_hours, status, created_at) "
        "VALUES (?, NULL, NULL, 'RECORDING', ?)",
        (bed_entry_ts, time.time()),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM sleep_sessions ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()

    daemon.state              = SleepState.RECORDING
    daemon._session_id        = row["id"]
    daemon._bed_entry_dt      = bed_entry_ts
    daemon._bed_entry_mono    = clock.monotonic() - 6 * 3600
    daemon._entered_state_mono = clock.monotonic() - 6 * 3600
    daemon._absence_start_mono = None
    daemon._exit_mock_done    = True  # disable auto-exit mock

    # Tick with presence — no transition yet
    _insert_radar(db, True, clock)
    daemon.tick()
    _assert(daemon.state == SleepState.RECORDING, "Still RECORDING while present")

    # Start absence: advance 16 minutes, radar shows absent
    clock.advance(16 * 60)
    _insert_radar(db, False, clock)
    # Set absence start to 16 minutes ago in monotonic time
    daemon._absence_start_mono = clock.monotonic() - 16 * 60
    daemon.tick()

    _assert(
        daemon.state == SleepState.MORNING,
        "Transitioned to MORNING after valid exit",
        f"actual={daemon.state}",
    )

    session = _get_session(db, row["id"])
    _assert(session["bed_exit"] is not None, "bed_exit written to DB")
    _assert(
        session["status"] == "PROCESSING",
        "Session status is PROCESSING",
        f"status={session['status']}",
    )

    # Simulate batch completion: insert a recovery score and mark COMPLETE
    conn2 = get_connection(db)
    conn2.execute(
        "INSERT INTO recovery_scores (session_id, timestamp, total_score, "
        "architecture_score, continuity_score, breathing_score, environment_score) "
        "VALUES (?, ?, 78, 80, 75, 70, 82)",
        (row["id"], clock.utcnow().isoformat()),
    )
    conn2.execute(
        "UPDATE sleep_sessions SET status='COMPLETE' WHERE id=?", (row["id"],)
    )
    conn2.commit()
    conn2.close()

    # Call _on_batch_complete directly (avoids needing subprocess)
    daemon._batch_proc = None
    daemon._on_batch_complete()
    session2 = _get_session(db, row["id"])
    _assert(
        session2["status"] == "COMPLETE",
        "Session status updated to COMPLETE after batch",
        f"status={session2['status']}",
    )


# ---------------------------------------------------------------------------
# Test 4 — Recovery: old RECORDING session with no bed_exit → FAILED
# ---------------------------------------------------------------------------

def test_recover_old_session():
    print("\nTest 4: Recovery — old RECORDING session gets FAILED")
    db = _make_db()
    # Clock is on day 2, session is from day 1
    clock = FakeClock(datetime(2024, 1, 2, 8, 0, 0))
    daemon = _make_daemon(db, clock)

    # Insert a session from yesterday with RECORDING status and no bed_exit
    yesterday_entry = "2024-01-01T22:00:00"
    conn = get_connection(db)
    conn.execute(
        "INSERT INTO sleep_sessions (bed_entry, bed_exit, duration_hours, status, created_at) "
        "VALUES (?, NULL, NULL, 'RECORDING', ?)",
        (yesterday_entry, time.time() - 86400),
    )
    # Insert a radar event to serve as last_radar_ts
    conn.execute(
        "INSERT INTO radar_events (timestamp, event_type, presence, still_distance, moving_distance) "
        "VALUES ('2024-01-02T05:00:00', 'reading', 0, 0, 0)",
    )
    conn.commit()
    row = conn.execute("SELECT id FROM sleep_sessions ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()

    session_id = row["id"]

    # Running recover on init should mark it FAILED
    daemon.setup()

    session = _get_session(db, session_id)
    _assert(
        session["status"] == "FAILED",
        "Old RECORDING session marked FAILED",
        f"status={session['status']}",
    )
    _assert(
        session["bed_exit"] is not None,
        "bed_exit set to last radar timestamp",
        f"bed_exit={session['bed_exit']}",
    )


# ---------------------------------------------------------------------------
# Test 5 — Bathroom trip: brief absence < 15 min at 03:00 does not exit
# ---------------------------------------------------------------------------

def test_bathroom_trip():
    print("\nTest 5: Bathroom trip — short absence stays in RECORDING")
    db = _make_db()
    clock = FakeClock(datetime(2024, 1, 2, 3, 0, 0))   # 03:00 — before WAKE_EARLIEST_HOUR
    daemon = _make_daemon(db, clock)
    daemon.setup()

    # Bootstrap RECORDING with bed entry 1 hour ago
    bed_entry_ts = (clock.utcnow() - timedelta(hours=1)).isoformat()
    conn = get_connection(db)
    conn.execute(
        "INSERT INTO sleep_sessions (bed_entry, bed_exit, duration_hours, status, created_at) "
        "VALUES (?, NULL, NULL, 'RECORDING', ?)",
        (bed_entry_ts, time.time()),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM sleep_sessions ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()

    daemon.state               = SleepState.RECORDING
    daemon._session_id         = row["id"]
    daemon._bed_entry_dt       = bed_entry_ts
    daemon._bed_entry_mono     = clock.monotonic() - 3600
    daemon._entered_state_mono = clock.monotonic() - 3600
    daemon._absence_start_mono = None
    daemon._exit_mock_done     = True

    # 5-minute absence at 03:00 — not valid (time < 05:00, sleep < 4h)
    _insert_radar(db, False, clock)
    daemon._absence_start_mono = clock.monotonic()
    clock.advance(5 * 60)
    _insert_radar(db, False, clock)
    daemon.tick()

    _assert(
        daemon.state == SleepState.RECORDING,
        "Still RECORDING during bathroom trip (time=03:00, sleep=1h)",
        f"actual={daemon.state}",
    )

    # Presence returns (advance 1s so the event has a later timestamp)
    clock.advance(1)
    _insert_radar(db, True, clock)
    daemon.tick()
    _assert(
        daemon._absence_start_mono is None,
        "Absence timer reset when presence returned",
    )
    _assert(daemon.state == SleepState.RECORDING, "Still RECORDING after return")


# ---------------------------------------------------------------------------
# Test 6 — Auto-start fallback: 15 min sustained presence without interaction
# ---------------------------------------------------------------------------

def test_auto_start_fallback():
    print("\nTest 6: Auto-start fallback — 15 min presence without pressing YES")
    db = _make_db()
    clock = FakeClock(datetime(2024, 1, 1, 22, 30, 0))
    # Disable auto-YES mock so auto-start via sustained presence fires instead
    daemon = _make_daemon(db, clock, mock_auto_yes=False, mock_auto_exit=False)
    daemon.setup()

    # Get into BEDTIME_PROMPT: 2 min sustained presence
    _insert_radar(db, True, clock)
    daemon.tick()
    clock.advance(121)
    _insert_radar(db, True, clock)
    daemon.tick()
    _assert(daemon.state == SleepState.BEDTIME_PROMPT, "In BEDTIME_PROMPT (no auto-yes)")

    # Hold presence for AUTO_RECORD_MINUTES (15 min) without any touch
    daemon._bedtime_presence_start = clock.monotonic()
    clock.advance(AUTO_RECORD_MINUTES_VALUE * 60 + 1)
    _insert_radar(db, True, clock)
    daemon.tick()

    _assert(
        daemon.state == SleepState.RECORDING,
        "Auto-transitioned to RECORDING after 15 min sustained presence",
        f"actual={daemon.state}",
    )
    session = _get_latest_session(db)
    _assert(
        session is not None and session["status"] == "RECORDING",
        "Session created with status=RECORDING",
    )


# Import the constant for test 6
from server.config import AUTO_RECORD_MINUTES as AUTO_RECORD_MINUTES_VALUE


# ---------------------------------------------------------------------------
# Test 7 — Full night simulation via mock auto-transitions
# ---------------------------------------------------------------------------

def test_full_night_mock():
    print("\nTest 7: Full night simulation with mock auto-transitions")
    db = _make_db()
    # 22:00 — inside bedtime window
    clock = FakeClock(datetime(2024, 1, 1, 22, 0, 0))
    # Enable auto-yes (YES after 10s) and auto-exit (bed exit after 30s)
    daemon = _make_daemon(db, clock, mock_auto_yes=True, mock_auto_exit=True)
    daemon.setup()

    # ---- IDLE phase ----
    _insert_radar(db, True, clock)
    daemon.tick()
    clock.advance(121)
    _insert_radar(db, True, clock)
    daemon.tick()
    _assert(daemon.state == SleepState.BEDTIME_PROMPT, "Reached BEDTIME_PROMPT")

    # ---- BEDTIME_PROMPT → auto-YES at 10s ----
    clock.advance(11)
    _insert_radar(db, True, clock)
    daemon.tick()   # auto-YES injected into queue
    daemon.tick()   # consumed by next tick
    _assert(
        daemon.state == SleepState.RECORDING,
        "Reached RECORDING after mock YES",
        f"actual={daemon.state}",
    )

    # ---- RECORDING → MORNING after 30s mock exit ----
    clock.advance(31)
    _insert_radar(db, False, clock)
    daemon.tick()
    _assert(
        daemon.state == SleepState.MORNING,
        "Reached MORNING after mock bed exit",
        f"actual={daemon.state}",
    )

    # ---- MORNING → IDLE after mock dismiss (5s) ----
    clock.advance(6)
    daemon.tick()   # injects DISMISS
    daemon.tick()   # consumed
    _assert(
        daemon.state == SleepState.IDLE,
        "Returned to IDLE after morning dismiss",
        f"actual={daemon.state}",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_idle_to_bedtime_prompt()
    test_bedtime_prompt_yes()
    test_recording_to_morning()
    test_recover_old_session()
    test_bathroom_trip()
    test_auto_start_fallback()
    test_full_night_mock()

    print(f"\n{'='*50}")
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    if _FAIL:
        sys.exit(1)
