"""
Tests for pipeline/calibrate.py and its integration with staging.py / batch.py.
All file operations use temporary databases.
"""
import os
import sys
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta

import numpy as np

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, PROJECT_ROOT)

import server.config as _cfg

# Use a controlled temp dir for all log output so tests don't pollute the repo
_tmp_log_dir = tempfile.mkdtemp()
_orig_makedirs = os.makedirs

def _patched_makedirs(path, *args, **kwargs):
    if str(path) == "logs":
        path = _tmp_log_dir
    return _orig_makedirs(path, *args, **kwargs)

os.makedirs = _patched_makedirs

checks = []


def check(label, passed):
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {label}")
    checks.append((label, passed))


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _make_db():
    """Return path to a fresh, schema-initialised temp database."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    from server.db import init_db, migrate_schema
    init_db(tmp.name)
    migrate_schema(tmp.name)
    return tmp.name


def _insert_session(db_path, night_offset_days, duration_hours=7.0):
    """Insert a complete sleep session and return (session_id, bed_entry, bed_exit)."""
    base = datetime(2026, 1, 1, 22, 0, 0) + timedelta(days=night_offset_days)
    bed_entry = base.isoformat()
    bed_exit  = (base + timedelta(hours=duration_hours)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "INSERT INTO sleep_sessions (bed_entry, bed_exit, duration_hours, status) "
        "VALUES (?, ?, ?, 'COMPLETE')",
        (bed_entry, bed_exit, duration_hours),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid, bed_entry, bed_exit


def _insert_csi_windows(db_path, bed_entry, bed_exit,
                         mp_values, br_values):
    """Insert synthetic CSI rows at regular 30-second intervals within the session."""
    start = datetime.fromisoformat(bed_entry)
    conn = sqlite3.connect(db_path)
    rows = []
    for i, (mp, br) in enumerate(zip(mp_values, br_values)):
        ts = (start + timedelta(seconds=30 * i)).isoformat()
        rows.append((ts, br, mp, "node1"))
    conn.executemany(
        "INSERT INTO csi_readings (timestamp, breathing_rate, movement_power, node_id) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Deterministic synthetic signal (100 windows per night)
# ---------------------------------------------------------------------------
rng = np.random.default_rng(42)
_N = 100
_KNOWN_MP = rng.uniform(0.0, 0.6, _N).tolist()    # movement_power
_KNOWN_BR = rng.uniform(10.0, 20.0, _N).tolist()  # breathing_rate

_EXPECTED_ML = float(np.percentile(_KNOWN_MP, 25))
_EXPECTED_MH = float(np.percentile(_KNOWN_MP, 75))

_br_arr       = np.array(_KNOWN_BR)
_br_mean      = float(np.mean(_br_arr))
_br_std       = float(np.std(_br_arr))
_EXPECTED_BL  = float(max(8.0, _br_mean - 1.5 * _br_std))
_EXPECTED_BH  = float(min(25.0, _br_mean + 1.5 * _br_std))


# ===========================================================================
# Test 1 — Returns None with fewer than 7 nights
# ===========================================================================
print("\nTest 1: Returns None with fewer than 7 nights")
from pipeline.calibrate import compute_thresholds

db = _make_db()
for i in range(6):
    sid, be, bx = _insert_session(db, i)
    _insert_csi_windows(db, be, bx, _KNOWN_MP, _KNOWN_BR)

result = compute_thresholds(db, min_nights=7)
check("returns None with 6 nights", result is None)

# No row should have been written
conn = sqlite3.connect(db)
count = conn.execute("SELECT COUNT(*) FROM personal_thresholds").fetchone()[0]
conn.close()
check("no row inserted when < 7 nights", count == 0)
os.unlink(db)


# ===========================================================================
# Test 2 — Computes correct percentiles on known data (7 identical nights)
# ===========================================================================
print("\nTest 2: Correct percentiles on known synthetic data")
db = _make_db()
for i in range(7):
    sid, be, bx = _insert_session(db, i)
    _insert_csi_windows(db, be, bx, _KNOWN_MP, _KNOWN_BR)

result = compute_thresholds(db, min_nights=7)
check("returns a result with 7 nights", result is not None)
check("nights_used == 7", result is not None and result.nights_used == 7)
check(
    "movement_low == P25 of mp",
    result is not None and abs(result.movement_low - _EXPECTED_ML) < 1e-9,
)
check(
    "movement_high == P75 of mp",
    result is not None and abs(result.movement_high - _EXPECTED_MH) < 1e-9,
)
check(
    "breathing_low == max(8, mean - 1.5*std)",
    result is not None and abs(result.breathing_low - _EXPECTED_BL) < 1e-6,
)
check(
    "breathing_high == min(25, mean + 1.5*std)",
    result is not None and abs(result.breathing_high - _EXPECTED_BH) < 1e-6,
)
check(
    "breathing_mean == mean of br",
    result is not None and abs(result.breathing_mean - _br_mean) < 1e-6,
)

# Physiological clamp — values must stay within 8–25
check("breathing_low >= 8", result is not None and result.breathing_low >= 8.0)
check("breathing_high <= 25", result is not None and result.breathing_high <= 25.0)
os.unlink(db)


# ===========================================================================
# Test 3 — Second run deactivates old row and inserts a new active one
# ===========================================================================
print("\nTest 3: Upsert deactivates previous row")
db = _make_db()
for i in range(7):
    sid, be, bx = _insert_session(db, i)
    _insert_csi_windows(db, be, bx, _KNOWN_MP, _KNOWN_BR)

first = compute_thresholds(db, min_nights=7)

# Add a new night so recalibration is meaningful
sid8, be8, bx8 = _insert_session(db, 7)
_insert_csi_windows(db, be8, bx8, _KNOWN_MP, _KNOWN_BR)

second = compute_thresholds(db, min_nights=7)
check("second call returns a result", second is not None)

conn = sqlite3.connect(db)
rows = conn.execute(
    "SELECT is_active, computed_at FROM personal_thresholds ORDER BY id"
).fetchall()
conn.close()

check("two rows in personal_thresholds after two runs", len(rows) == 2)
check("first row is deactivated", rows[0][0] == 0)
check("second row is active", rows[1][0] == 1)
os.unlink(db)


# ===========================================================================
# Test 4 — Staging falls back to config constants when no thresholds row
# ===========================================================================
print("\nTest 4: Staging falls back to config constants")
db = _make_db()

from pipeline.staging import load_thresholds, _heuristic_single

thr = load_thresholds(db)
check("load_thresholds returns None on empty DB", thr is None)

# A window where mp is between config LOW and HIGH — expect LIGHT_REM with defaults
w = {
    "mp": (_cfg.MOVEMENT_THRESHOLD_LOW + _cfg.MOVEMENT_THRESHOLD_HIGH) / 2,
    "br": (_cfg.DEEP_BREATHING_MIN + _cfg.DEEP_BREATHING_MAX) / 2,
    "presence": True,
    "still_dist": 0.5,
    "moving_dist": 0.1,
    "audio_tier": "silence",
}
stage_default, _, _ = _heuristic_single(w, 0.9, thr=None)
check("heuristic uses config constants when thr=None", stage_default == "LIGHT_REM")
os.unlink(db)


# ===========================================================================
# Test 5 — Staging uses personal thresholds when active row exists
# ===========================================================================
print("\nTest 5: Staging uses personal thresholds when active row exists")
db = _make_db()

# Insert a threshold row with very wide movement range so nothing triggers WAKE
# and a very narrow breathing range that excludes normal deep sleep
conn = sqlite3.connect(db)
conn.execute(
    """
    INSERT INTO personal_thresholds
      (computed_at, nights_used, movement_low, movement_high,
       breathing_low, breathing_high, breathing_mean, is_active)
    VALUES (?, 7, 0.001, 0.999, 18.0, 20.0, 19.0, 1)
    """,
    (datetime.now().isoformat(),),
)
conn.commit()
conn.close()

thr = load_thresholds(db)
check("load_thresholds returns namespace with active row", thr is not None)
check("movement_low from DB", thr is not None and abs(thr.movement_low - 0.001) < 1e-9)
check("movement_high from DB", thr is not None and abs(thr.movement_high - 0.999) < 1e-9)
check("breathing_low from DB", thr is not None and abs(thr.breathing_low - 18.0) < 1e-9)

# A window with br=14 (inside config DEEP range but outside personal 18–20):
# with personal thresholds it should not be a deep candidate → LIGHT_REM
w_deep_miss = {
    "mp": 0.01,          # very low movement → inside personal mp_low
    "br": 14.0,          # outside personal breathing_low (18) → not deep
    "presence": True,
    "still_dist": 0.5,
    "moving_dist": 0.0,
    "audio_tier": "silence",
}
# High regularity to satisfy the other deep conditions
stage_personal, _, dc_personal = _heuristic_single(w_deep_miss, 0.9, thr=thr)
stage_config,   _, dc_config   = _heuristic_single(w_deep_miss, 0.9, thr=None)

check(
    "deep_candidate=False with personal thresholds (br outside personal range)",
    not dc_personal,
)
check(
    "deep_candidate=True with config constants (br inside config DEEP range)",
    dc_config,
)
os.unlink(db)


# ===========================================================================
# Test 6 — Pipeline integration: no-op on 6 nights, activates on 7th
# ===========================================================================
print("\nTest 6: Pipeline integration — no-op < 7 nights, activates on 7")
db = _make_db()

for i in range(6):
    sid, be, bx = _insert_session(db, i)
    _insert_csi_windows(db, be, bx, _KNOWN_MP, _KNOWN_BR)

result_6 = compute_thresholds(db, min_nights=7)
check("compute_thresholds returns None with 6 nights", result_6 is None)

conn = sqlite3.connect(db)
active_count = conn.execute(
    "SELECT COUNT(*) FROM personal_thresholds WHERE is_active=1"
).fetchone()[0]
conn.close()
check("no active row after 6 nights", active_count == 0)

# Add 7th night
sid7, be7, bx7 = _insert_session(db, 6)
_insert_csi_windows(db, be7, bx7, _KNOWN_MP, _KNOWN_BR)

result_7 = compute_thresholds(db, min_nights=7)
check("compute_thresholds returns result with 7 nights", result_7 is not None)
check("nights_used == 7 on first activation", result_7 is not None and result_7.nights_used == 7)

conn = sqlite3.connect(db)
active_count_7 = conn.execute(
    "SELECT COUNT(*) FROM personal_thresholds WHERE is_active=1"
).fetchone()[0]
conn.close()
check("active row present after 7 nights", active_count_7 == 1)
os.unlink(db)


# ===========================================================================
# Cleanup
# ===========================================================================
os.makedirs = _orig_makedirs
shutil.rmtree(_tmp_log_dir, ignore_errors=True)

# ===========================================================================
# Summary
# ===========================================================================
print()
total  = len(checks)
passed = sum(1 for _, ok in checks if ok)
print(f"  {passed}/{total} checks passed.")
print()
if passed == total:
    print("All checks passed.")
    sys.exit(0)
else:
    print("One or more checks FAILED.")
    for label, ok in checks:
        if not ok:
            print(f"  FAIL: {label}")
    sys.exit(1)
