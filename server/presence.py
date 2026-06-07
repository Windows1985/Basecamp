"""
Presence watcher daemon — monitors HLK-LD2410C radar, maintains bed entry/exit
state, and triggers the morning batch pipeline on confirmed wake.
"""
import os
import sys
import signal
import threading
import time
import logging
import logging.handlers
import subprocess
from datetime import datetime, timedelta
from enum import Enum

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.config import (
    DB_PATH, RADAR_SERIAL_PORT, RADAR_BAUD_RATE, MIN_SLEEP_HOURS, MOCK_HARDWARE,
    WAKE_ABSENCE_MINUTES, WAKE_EARLIEST_HOUR,
    WATCHDOG_INTERVAL_SECONDS, HEARTBEAT_INTERVAL_SECONDS,
)
from server.db import init_db, get_connection

# ---------------------------------------------------------------------------
# Hardware imports
# ---------------------------------------------------------------------------
try:
    import serial
    _SERIAL_AVAILABLE = True
except ImportError:
    _SERIAL_AVAILABLE = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
_handler = logging.handlers.RotatingFileHandler(
    "logs/presence.log", maxBytes=5 * 1024 * 1024, backupCount=3
)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_stream = logging.StreamHandler()
_stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log = logging.getLogger("presence")
log.setLevel(logging.INFO)
log.addHandler(_handler)
log.addHandler(_stream)

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------
FRAME_HEADER = bytes([0xF4, 0xF3, 0xF2, 0xF1])
FRAME_TAIL   = bytes([0xF8, 0xF7, 0xF6, 0xF5])

# Hysteresis counts
PRESENCE_CONFIRM = 3   # consecutive present readings needed
ABSENT_CONFIRM   = 5   # consecutive absent readings needed
IN_BED_SECONDS   = 300 # 5 minutes continuous presence → IN_BED

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
class State(Enum):
    ABSENT        = "ABSENT"
    PRESENT       = "PRESENT"
    IN_BED        = "IN_BED"
    POSSIBLE_EXIT = "POSSIBLE_EXIT"
    EXITED        = "EXITED"


# ---------------------------------------------------------------------------
# Frame parsing
# ---------------------------------------------------------------------------
def _parse_frame(buf):
    """
    Returns (target_status, moving_dist, moving_energy, still_dist, still_energy, detect_dist)
    or None if the buffer does not contain a valid complete frame.
    """
    start = buf.find(FRAME_HEADER)
    if start == -1:
        return None, buf[-4:] if len(buf) >= 4 else buf

    end = buf.find(FRAME_TAIL, start + len(FRAME_HEADER))
    if end == -1:
        return None, buf[start:]

    frame = buf[start + len(FRAME_HEADER): end]
    remainder = buf[end + len(FRAME_TAIL):]

    if len(frame) < 9:
        return None, remainder

    target_status  = frame[0]
    moving_dist    = (frame[1] | (frame[2] << 8))
    moving_energy  = frame[3]
    still_dist     = (frame[4] | (frame[5] << 8))
    still_energy   = frame[6]
    detect_dist    = (frame[7] | (frame[8] << 8))

    return (target_status, moving_dist, moving_energy, still_dist, still_energy, detect_dist), remainder


# ---------------------------------------------------------------------------
# Mock generator
# ---------------------------------------------------------------------------
class MockRadar:
    """Simulates a realistic overnight radar stream."""

    def __init__(self):
        import random
        self._random = random
        self._start = time.time()

    def read_frame(self):
        import random
        elapsed = time.time() - self._start
        # Present 0–0.5h (settling), absent 0.5–0.53h (bathroom simulation at ~3h mark)
        # For testing purposes compress the timeline: present for most of it
        # Simulate: present 0s–10800s, absent 10800–10920 (2 min), present 10920–25200, absent after
        present = True
        if 10800 <= elapsed < 10920:
            present = False
        elif elapsed >= 25200:
            present = False

        noise = random.randint(0, 10)
        still_dist  = (120 + noise) if present else 0
        moving_dist = (random.randint(0, 30)) if present else 0
        target_status = 2 if present else 0  # 2 = still

        time.sleep(0.1)  # ~10 frames/sec
        return {
            "target_status": target_status,
            "moving_dist": moving_dist,
            "still_dist": still_dist,
            "present": present,
        }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _write_radar_event(event_type, presence, still_dist, moving_dist, ts=None, pi_ts=None):
    if ts is None:
        ts = datetime.utcnow().isoformat()
    if pi_ts is None:
        pi_ts = time.monotonic()
    try:
        conn = get_connection(DB_PATH)
        try:
            conn.execute(
                """INSERT INTO radar_events
                   (timestamp, event_type, presence, still_distance, moving_distance, pi_timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (ts, event_type, int(bool(presence)), still_dist, moving_dist, pi_ts),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        log.error(f"DB write radar_event failed: {e}")


def _write_heartbeat():
    try:
        conn = get_connection(DB_PATH)
        try:
            conn.execute(
                """INSERT INTO service_heartbeats (service_name, last_heartbeat, status)
                   VALUES ('presence', ?, 'running')
                   ON CONFLICT(service_name) DO UPDATE
                   SET last_heartbeat=excluded.last_heartbeat, status=excluded.status""",
                (time.time(),),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        log.debug(f"Heartbeat write failed: {e}")


def _write_bed_entry(ts):
    try:
        conn = get_connection(DB_PATH)
        try:
            conn.execute(
                "INSERT INTO sleep_sessions (bed_entry, bed_exit, duration_hours) VALUES (?, NULL, NULL)",
                (ts,),
            )
            conn.commit()
        finally:
            conn.close()
        log.info(f"Bed entry recorded at {ts}")
    except Exception as e:
        log.error(f"DB write bed_entry failed: {e}")


def _write_bed_exit(ts):
    try:
        conn = get_connection(DB_PATH)
        try:
            row = conn.execute(
                "SELECT id, bed_entry FROM sleep_sessions ORDER BY bed_entry DESC LIMIT 1"
            ).fetchone()
            if row is None:
                log.warning("Bed exit detected but no open sleep session found")
                return None, None

            session_id = row["id"]
            entry_dt = datetime.fromisoformat(row["bed_entry"])
            exit_dt  = datetime.fromisoformat(ts)
            duration = (exit_dt - entry_dt).total_seconds() / 3600.0

            conn.execute(
                "UPDATE sleep_sessions SET bed_exit = ?, duration_hours = ? WHERE id = ?",
                (ts, round(duration, 4), session_id),
            )
            conn.commit()
            log.info(f"Bed exit recorded — session {session_id}, duration {duration:.2f}h")
            return session_id, duration
        finally:
            conn.close()
    except Exception as e:
        log.error(f"DB write bed_exit failed: {e}")
        return None, None


# ---------------------------------------------------------------------------
# Main daemon
# ---------------------------------------------------------------------------
_running = True


def _handle_sigterm(signum, frame):
    global _running
    log.info("SIGTERM received, shutting down")
    _running = False


def run():
    global _running
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _handle_sigterm)

    init_db(DB_PATH)

    if MOCK_HARDWARE:
        log.info(f"Presence watcher started — MOCK mode")
        print(f"Presence watcher started — MOCK mode")
        radar = MockRadar()
    else:
        radar = None
        ser = None
        while _running:
            if not _SERIAL_AVAILABLE:
                log.error("pyserial not installed; cannot open radar port")
                time.sleep(30)
                continue
            try:
                ser = serial.Serial(RADAR_SERIAL_PORT, RADAR_BAUD_RATE, timeout=1)
                log.info(f"Presence watcher started — {RADAR_SERIAL_PORT} @ {RADAR_BAUD_RATE}")
                print(f"Presence watcher started — {RADAR_SERIAL_PORT} @ {RADAR_BAUD_RATE}")
                break
            except Exception as e:
                log.error(f"Cannot open {RADAR_SERIAL_PORT}: {e} — retrying in 30s")
                time.sleep(30)
        if not _running:
            return

    state                = State.ABSENT
    presence_count       = 0
    absent_count         = 0
    in_bed_since         = None
    bed_entry_time       = None   # wall-clock time of bed entry
    possible_exit_since  = None   # monotonic time when POSSIBLE_EXIT started
    buf                  = b""
    last_watchdog        = time.monotonic()
    last_heartbeat       = time.monotonic()

    try:
        import sdnotify as _sdnotify
        _notifier = _sdnotify.SystemdNotifier()
    except ImportError:
        _notifier = None

    while _running:
        # --- Read one frame ---------------------------------------------------
        if MOCK_HARDWARE:
            frame_data = radar.read_frame()
            present    = frame_data["present"]
            still_dist = frame_data["still_dist"]
            moving_dist = frame_data["moving_dist"]
        else:
            try:
                chunk = ser.read(64)
                if chunk:
                    buf += chunk
                parsed, buf = _parse_frame(buf)
                if parsed is None:
                    continue
                target_status, moving_dist, _, still_dist, _, _ = parsed
                present = target_status != 0
            except Exception as e:
                log.error(f"Frame parse error: {e}")
                continue

        ts = datetime.utcnow().isoformat()
        pi_ts = time.monotonic()

        # Write raw reading
        _write_radar_event("reading", present, still_dist, moving_dist, ts, pi_ts)

        # Watchdog + heartbeat
        now_mono = time.monotonic()
        if now_mono - last_watchdog >= WATCHDOG_INTERVAL_SECONDS:
            last_watchdog = now_mono
            try:
                if _notifier:
                    _notifier.notify("WATCHDOG=1")
            except Exception:
                pass
        if now_mono - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
            last_heartbeat = now_mono
            _write_heartbeat()

        # --- Hysteresis counters ----------------------------------------------
        if present:
            presence_count += 1
            absent_count    = 0
        else:
            absent_count   += 1
            presence_count  = 0

        # --- State transitions ------------------------------------------------
        if state == State.ABSENT:
            if presence_count >= PRESENCE_CONFIRM:
                state = State.PRESENT
                log.info("State → PRESENT")

        elif state == State.PRESENT:
            if absent_count >= ABSENT_CONFIRM:
                state = State.ABSENT
                presence_count = 0
                in_bed_since = None
                log.info("State → ABSENT (brief presence)")
            elif in_bed_since is None:
                in_bed_since = time.time()
            elif time.time() - in_bed_since >= IN_BED_SECONDS:
                state = State.IN_BED
                bed_ts = datetime.utcnow().isoformat()
                bed_entry_time = datetime.utcnow()
                log.info(f"State → IN_BED at {bed_ts}")
                _write_radar_event("bed_entry", True, still_dist, moving_dist, bed_ts)
                _write_bed_entry(bed_ts)

        elif state == State.IN_BED:
            if absent_count >= ABSENT_CONFIRM:
                state = State.POSSIBLE_EXIT
                log.info("State → POSSIBLE_EXIT")

        elif state == State.POSSIBLE_EXIT:
            if presence_count >= PRESENCE_CONFIRM:
                state = State.IN_BED
                absent_count = 0
                possible_exit_since = None
                log.info("State → IN_BED (returned)")
            else:
                if possible_exit_since is None:
                    possible_exit_since = time.monotonic()

                absence_minutes = (time.monotonic() - possible_exit_since) / 60.0
                local_hour = datetime.now().hour
                sleep_hours = (
                    (datetime.utcnow() - bed_entry_time).total_seconds() / 3600.0
                    if bed_entry_time else 0.0
                )
                valid_exit = (
                    absence_minutes >= WAKE_ABSENCE_MINUTES
                    and local_hour >= WAKE_EARLIEST_HOUR
                    and sleep_hours >= MIN_SLEEP_HOURS
                )
                if valid_exit:
                    state = State.EXITED
                    exit_ts = datetime.utcnow().isoformat()
                    log.info(
                        f"State → EXITED at {exit_ts} "
                        f"(absent {absence_minutes:.0f}min, "
                        f"local {local_hour:02d}:xx, "
                        f"sleep {sleep_hours:.1f}h)"
                    )
                    _write_radar_event("bed_exit", False, still_dist, moving_dist, exit_ts)
                    session_id, duration = _write_bed_exit(exit_ts)

                    if duration is not None and duration >= MIN_SLEEP_HOURS:
                        log.info(f"Sleep {duration:.2f}h ≥ {MIN_SLEEP_HOURS}h — triggering pipeline")
                        subprocess.Popen(
                            [sys.executable, "pipeline/batch.py"],
                            cwd=os.path.join(os.path.dirname(__file__), ".."),
                        )
                    else:
                        log.info(
                            f"Sleep {duration:.2f if duration else 0:.2f}h < {MIN_SLEEP_HOURS}h "
                            "— pipeline not triggered"
                        )

                    # Reset to watch for next session
                    state               = State.ABSENT
                    presence_count      = 0
                    absent_count        = 0
                    in_bed_since        = None
                    bed_entry_time      = None
                    possible_exit_since = None

    if not MOCK_HARDWARE and ser and ser.is_open:
        ser.close()
    log.info("Presence watcher stopped")


if __name__ == "__main__":
    run()
