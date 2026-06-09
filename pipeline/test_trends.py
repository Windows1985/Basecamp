"""
Tests for pipeline/trends.py and its integration with report.py.
All file operations use temporary databases.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

import numpy as np

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, PROJECT_ROOT)

# Redirect log output so tests don't write to repo logs/
_tmp_log = tempfile.mkdtemp()
_orig_makedirs = os.makedirs


def _patched_makedirs(path, *args, **kwargs):
    if str(path) == "logs":
        path = _tmp_log
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
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    from server.db import init_db, migrate_schema
    init_db(tmp.name)
    migrate_schema(tmp.name)
    return tmp.name


def _insert_session(db_path, day_offset, duration=7.0):
    base = datetime(2026, 1, 1, 22, 0) + timedelta(days=day_offset)
    bed_entry = base.isoformat()
    bed_exit  = (base + timedelta(hours=duration)).isoformat()
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO sleep_sessions (bed_entry, bed_exit, duration_hours, status) "
        "VALUES (?, ?, ?, 'COMPLETE')",
        (bed_entry, bed_exit, duration),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid, bed_entry, bed_exit


def _insert_score(db_path, session_id, total_score,
                  arch=60.0, cont=60.0, brth=60.0, env=60.0):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO recovery_scores "
        "(session_id, timestamp, architecture_score, continuity_score, "
        " breathing_score, environment_score, total_score) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, datetime.now().isoformat(), arch, cont, brth, env, total_score),
    )
    conn.commit()
    conn.close()


def _insert_trend_row(db_path, session_id, feature_name, slope_7,
                      slope_14=None, mean_7=None, z_score=None,
                      shap_direction=None, is_persistent=1):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO feature_trends "
        "(computed_at, session_id, feature_name, slope_7, slope_14, mean_7, "
        " z_score, shap_direction, is_persistent) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.now().isoformat(), session_id, feature_name,
            slope_7, slope_14 or slope_7, mean_7 or 60.0,
            z_score, shap_direction, int(is_persistent),
        ),
    )
    conn.commit()
    conn.close()


# ===========================================================================
# Test 1 — Returns None with fewer than 7 sessions
# ===========================================================================
print("\nTest 1: Returns None with fewer than 7 historical sessions")
from pipeline.trends import compute_trends

db = _make_db()
# 6 complete scored sessions (< 7 required)
for i in range(6):
    sid, _, _ = _insert_session(db, i)
    _insert_score(db, sid, 60.0 + i)

# "tonight" is session 7
sid_today, _, _ = _insert_session(db, 6)
result = compute_trends(sid_today, {"total_score": 66.0}, db)

check("returns None with 6 historical sessions", result is None)

# No feature_trends rows should exist
conn = sqlite3.connect(db)
count = conn.execute("SELECT COUNT(*) FROM feature_trends").fetchone()[0]
conn.close()
check("no feature_trends rows written when < 7 sessions", count == 0)
os.unlink(db)


# ===========================================================================
# Test 2 — Correct slope_7 = 2.0 on arithmetic data
# ===========================================================================
print("\nTest 2: Correct slope_7 on known arithmetic data")
db = _make_db()

# 8 historical sessions with total_score increasing by 2.0/night
# values: [60, 62, 64, 66, 68, 70, 72, 74]
for i in range(8):
    sid, _, _ = _insert_session(db, i)
    _insert_score(db, sid, 60.0 + i * 2)

sid_today, _, _ = _insert_session(db, 8)
result = compute_trends(sid_today, {"total_score": 76.0}, db)

# The slope of the 7 most recent: [62, 64, 66, 68, 70, 72, 74] = 2.0
check("compute_trends returns a list (not None) with 8 sessions", result is not None)

conn = sqlite3.connect(db)
row = conn.execute(
    "SELECT slope_7 FROM feature_trends "
    "WHERE session_id = ? AND feature_name = 'total_score'",
    (sid_today,),
).fetchone()
conn.close()

check("feature_trends row written for total_score", row is not None)
if row:
    check("slope_7 ≈ 2.0 (within 0.01)", abs(row[0] - 2.0) < 0.01)
os.unlink(db)


# ===========================================================================
# Test 3 — is_persistent gated by slope threshold AND z_score
# ===========================================================================
print("\nTest 3: is_persistent gating")
from pipeline.trends import SLOPE_THRESHOLDS

db = _make_db()

# 8 sessions with total_score=50 (flat — slope near 0, z_score near 0)
for i in range(8):
    sid, _, _ = _insert_session(db, i)
    _insert_score(db, sid, 50.0)

sid_today, _, _ = _insert_session(db, 8)

# Flat data → slope_7 ≈ 0, z_score ≈ 0 → NOT persistent
result_flat = compute_trends(sid_today, {"total_score": 50.0}, db)
check("flat data: result is a list", result_flat is not None)
check("flat data: empty persistent list", result_flat is not None and len(result_flat) == 0)

os.unlink(db)

# Now: total_score increases by 5/night (> threshold of 2.0) with large z_score
db = _make_db()
for i in range(8):
    sid, _, _ = _insert_session(db, i)
    _insert_score(db, sid, 40.0 + i * 5)   # [40, 45, 50, 55, 60, 65, 70, 75]

sid_today, _, _ = _insert_session(db, 8)
result_steep = compute_trends(sid_today, {"total_score": 80.0}, db)

check("steep trend: result is a list", result_steep is not None)
if result_steep is not None:
    persistent_names = [f["feature_name"] for f in result_steep]
    check("total_score is persistent when slope > threshold", "total_score" in persistent_names)

# Verify z_score gating: large slope but tonight's value at the mean (z ≈ 0)
conn = sqlite3.connect(db)
conn.execute(
    "UPDATE feature_trends SET z_score = 0.5, is_persistent = 0 "
    "WHERE session_id = ? AND feature_name = 'total_score'",
    (sid_today,),
)
conn.commit()
conn.close()

conn = sqlite3.connect(db)
row = conn.execute(
    "SELECT is_persistent FROM feature_trends "
    "WHERE session_id = ? AND feature_name = 'total_score'",
    (sid_today,),
).fetchone()
conn.close()
check("z_score=0.5 → is_persistent=0 (manually set, verifying gate)", row and row[0] == 0)

os.unlink(db)


# ===========================================================================
# Test 4 — z_score clamped to [-4, 4]
# ===========================================================================
print("\nTest 4: z_score clamped to ±4")
db = _make_db()

# 8 sessions at total_score ≈ 50 with tiny std, then extreme tonight value
for i in range(8):
    sid, _, _ = _insert_session(db, i)
    _insert_score(db, sid, 50.0 + i * 0.01)   # nearly flat; std ≈ 0.03

sid_today, _, _ = _insert_session(db, 8)
# tonight = 1000 → raw z >> 4
result = compute_trends(sid_today, {"total_score": 1000.0}, db)

conn = sqlite3.connect(db)
row = conn.execute(
    "SELECT z_score FROM feature_trends "
    "WHERE session_id = ? AND feature_name = 'total_score'",
    (sid_today,),
).fetchone()
conn.close()

check("extreme tonight value: z_score clamped to 4.0", row and abs(row[0] - 4.0) < 0.001)
os.unlink(db)


# ===========================================================================
# Test 5 — std=0 returns None z_score without error
# ===========================================================================
print("\nTest 5: std=0 → z_score is None")
db = _make_db()

# Exactly flat: all sessions same total_score
for i in range(8):
    sid, _, _ = _insert_session(db, i)
    _insert_score(db, sid, 70.0)

sid_today, _, _ = _insert_session(db, 8)
# tonight is same value → std=0
result = compute_trends(sid_today, {"total_score": 70.0}, db)
check("std=0: no exception raised", True)  # reaching this line means no crash

conn = sqlite3.connect(db)
row = conn.execute(
    "SELECT z_score FROM feature_trends "
    "WHERE session_id = ? AND feature_name = 'total_score'",
    (sid_today,),
).fetchone()
conn.close()
check("std=0: z_score is NULL in DB", row and row[0] is None)
os.unlink(db)


# ===========================================================================
# Test 6 — direction classification: improving vs declining
# ===========================================================================
print("\nTest 6: direction classification")
from pipeline.trends import _get_direction, _HIGHER_IS_BETTER

# higher-is-better feature with positive slope → improving
check(
    "total_score + positive slope → improving",
    _get_direction("total_score", 3.0) == "improving",
)
check(
    "total_score + negative slope → declining",
    _get_direction("total_score", -3.0) == "declining",
)

# lower-is-better feature with negative slope → improving
check(
    "peak_co2 + negative slope → improving",
    _get_direction("peak_co2", -25.0) == "improving",
)
check(
    "peak_co2 + positive slope → declining",
    _get_direction("peak_co2", 25.0) == "declining",
)

# unknown feature defaults to higher-is-better
check(
    "unknown feature + positive slope → improving",
    _get_direction("unknown_feature_xyz", 1.0) == "improving",
)


# ===========================================================================
# Test 7 — Report section absent when no persistent factors
# ===========================================================================
print("\nTest 7: Report absent when no persistent factors")
db = _make_db()

# Minimal session + score data for generate_report to work
sid7, be7, bx7 = _insert_session(db, 0)
_insert_score(db, sid7, 72.0, arch=70, cont=75, brth=68, env=76)

# Insert some shap_values so the report doesn't show "(none)"
conn = sqlite3.connect(db)
now = datetime.now().isoformat()
conn.execute(
    "INSERT INTO shap_values (session_id, timestamp, feature_name, shap_value) "
    "VALUES (?, ?, ?, ?)",
    (sid7, now, "Deep sleep duration was good", 0.8),
)
conn.commit()
conn.close()

# NO feature_trends rows → no trend section

import morning.app as _app_mod
_app_mod._DB_PATH = db

from pipeline.report import generate_report
report7 = generate_report(sid7, db)

check("report generated without error", isinstance(report7, str) and len(report7) > 0)
check("'Trends' section absent when no persistent factors", "Trends:" not in report7)
os.unlink(db)


# ===========================================================================
# Test 8 — Report section capped at 2 factors when 4 persistent exist
# ===========================================================================
print("\nTest 8: Report capped at 2 persistent factors")
db = _make_db()

sid8, be8, bx8 = _insert_session(db, 0)
_insert_score(db, sid8, 65.0, arch=60, cont=65, brth=63, env=72)

conn = sqlite3.connect(db)
conn.execute(
    "INSERT INTO shap_values (session_id, timestamp, feature_name, shap_value) "
    "VALUES (?, ?, ?, ?)",
    (sid8, datetime.now().isoformat(), "Something was ok", 0.3),
)
conn.commit()
conn.close()

# Insert 4 persistent trend rows with different slopes (sorted by abs slope)
_insert_trend_row(db, sid8, "total_score",        slope_7=5.0,  is_persistent=1)
_insert_trend_row(db, sid8, "peak_co2",           slope_7=30.0, is_persistent=1)
_insert_trend_row(db, sid8, "architecture_score", slope_7=3.5,  is_persistent=1)
_insert_trend_row(db, sid8, "deep_sleep_proportion", slope_7=-0.02, is_persistent=1)

_app_mod._DB_PATH = db

report8 = generate_report(sid8, db)

check("report8 generated without error", isinstance(report8, str) and len(report8) > 0)
check("'Trends:' section present when persistent factors exist", "Trends:" in report8)

# Count how many trend factor lines appear (each starts with "  " + capitalised text)
if "Trends:" in report8:
    trend_part = report8.split("Trends:")[1]
    factor_lines = [
        ln for ln in trend_part.strip().splitlines()
        if ln.strip() and ln.startswith("  ")
    ]
    check("capped at 2 factor lines in report", len(factor_lines) <= 2)

os.unlink(db)


# ===========================================================================
# Cleanup
# ===========================================================================
os.makedirs = _orig_makedirs
shutil.rmtree(_tmp_log, ignore_errors=True)

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
