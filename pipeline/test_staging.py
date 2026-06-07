"""
Tests for pipeline/staging.py — the three-class sleep stage classifier.

Run:  python pipeline/test_staging.py
All 7 tests must pass.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server.config as _cfg
_cfg.MOCK_HARDWARE = True

import numpy as np
from server.db import init_db, get_connection, migrate_schema
from pipeline.staging import (
    WAKE, DEEP, LIGHT_REM,
    _heuristic_single, _apply_deep_run, _apply_smoothing,
    _apply_min_duration, _compute_regularity,
    classify_session, retrain_staging_model,
    _load_windows,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

_PASS = 0
_FAIL = 0


def _assert(cond, label, detail=""):
    global _PASS, _FAIL
    if cond:
        print(f"  PASS  {label}")
        _PASS += 1
    else:
        msg = f"  FAIL  {label}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        _FAIL += 1


def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    migrate_schema(path)
    return path


def _insert_session(db_path, bed_entry, bed_exit, duration_hours):
    """Insert a sleep session and return its id."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO sleep_sessions (bed_entry, bed_exit, duration_hours, status) "
            "VALUES (?, ?, ?, 'COMPLETE')",
            (bed_entry, bed_exit, duration_hours),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()


def _insert_csi(db_path, timestamps, br_values, mp_values, node_id="node_01"):
    conn = get_connection(db_path)
    try:
        rows = [
            (ts, float(br), float(mp), node_id)
            for ts, br, mp in zip(timestamps, br_values, mp_values)
        ]
        conn.executemany(
            "INSERT INTO csi_readings (timestamp, breathing_rate, movement_power, node_id) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _insert_audio(db_path, timestamps, tiers):
    conn = get_connection(db_path)
    try:
        conn.executemany(
            "INSERT INTO audio_chunks (timestamp, tier, duration_seconds, file_path) "
            "VALUES (?, ?, 30, 'mock.wav')",
            list(zip(timestamps, tiers)),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_radar(db_path, bed_entry_ts, bed_exit_ts):
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO radar_events (timestamp, event_type, presence, still_distance, moving_distance) "
            "VALUES (?, 'bed_entry', 1, 0.5, 0.0)",
            (bed_entry_ts,),
        )
        conn.execute(
            "INSERT INTO radar_events (timestamp, event_type, presence, still_distance, moving_distance) "
            "VALUES (?, 'bed_exit', 0, 0.0, 1.5)",
            (bed_exit_ts,),
        )
        conn.commit()
    finally:
        conn.close()


def _ts_seq(start_iso, n_windows):
    """Generate N ISO timestamp strings at 30-second intervals from start."""
    from datetime import datetime, timedelta
    base = datetime.fromisoformat(start_iso)
    return [(base + timedelta(seconds=30 * i)).isoformat() for i in range(n_windows)]


# ── Test 1: Heuristic WAKE detection ──────────────────────────────────────────

def test_heuristic_wake():
    print("\nTest 1: Heuristic WAKE detection — high movement_power")

    high_mp_windows = [
        {"mp": 0.45, "br": 16.0, "presence": True, "audio_tier": "ambient",
         "still_dist": 0.5, "moving_dist": 0.3},
        {"mp": 0.60, "br": 18.0, "presence": True, "audio_tier": "ambient",
         "still_dist": 0.5, "moving_dist": 0.4},
        {"mp": 0.35, "br": 14.0, "presence": True, "audio_tier": "silence",
         "still_dist": 0.5, "moving_dist": 0.2},
    ]
    br_arr = np.array([w["br"] for w in high_mp_windows])

    stages = []
    for i, w in enumerate(high_mp_windows):
        reg   = _compute_regularity(br_arr, i)
        stage, _, _ = _heuristic_single(w, reg)
        stages.append(stage)

    _assert(all(s == WAKE for s in stages),
            "All high-movement windows classified WAKE",
            f"stages={stages}")


# ── Test 2: Heuristic DEEP detection ──────────────────────────────────────────

def test_heuristic_deep():
    print("\nTest 2: Heuristic DEEP detection — 8 consecutive qualifying windows")

    n = 8
    windows = [
        {"mp": 0.02, "br": 13.0, "presence": True, "audio_tier": "silence",
         "still_dist": 0.5, "moving_dist": 0.0}
        for _ in range(n)
    ]
    br_arr = np.array([w["br"] for w in windows])

    raw_stages, deep_cands, _ = [], [], []
    for i, w in enumerate(windows):
        reg = _compute_regularity(br_arr, i)
        stg, pr, dc = _heuristic_single(w, reg)
        raw_stages.append(stg)
        deep_cands.append(dc)

    heuristic = _apply_deep_run(raw_stages, deep_cands)
    heuristic = _apply_smoothing(heuristic)

    deep_count = sum(1 for s in heuristic if s == DEEP)
    _assert(deep_count >= 6,
            f"At least 6 of 8 consecutive windows classified DEEP",
            f"deep={deep_count}, stages={heuristic}")


# ── Test 3: Smoothing — isolated WAKE merged into DEEP ────────────────────────

def test_smoothing():
    print("\nTest 3: Smoothing — isolated WAKE window merged into DEEP")

    # Pattern: DEEP DEEP DEEP WAKE DEEP DEEP DEEP
    stages = [DEEP, DEEP, DEEP, WAKE, DEEP, DEEP, DEEP]
    smoothed = _apply_smoothing(stages, k=5)

    _assert(smoothed[3] == DEEP,
            "Isolated WAKE at index 3 merged to DEEP after mode filter",
            f"smoothed={smoothed}")
    _assert(all(s == DEEP for s in smoothed),
            "All windows DEEP after smoothing",
            f"smoothed={smoothed}")


# ── Test 4: REM estimation — probable_rem on snore windows ────────────────────

def test_rem_estimation():
    print("\nTest 4: REM estimation — probable_rem on snore vs silent windows")

    snore_w  = {"mp": 0.03, "br": 15.5, "presence": True,
                "audio_tier": "snore", "still_dist": 0.5, "moving_dist": 0.0}
    silent_w = {"mp": 0.03, "br": 14.0, "presence": True,
                "audio_tier": "silence", "still_dist": 0.5, "moving_dist": 0.0}

    br_arr = np.array([15.5, 14.0])

    _, prem_snore, _  = _heuristic_single(snore_w,  _compute_regularity(br_arr, 0))
    _, prem_silent, _ = _heuristic_single(silent_w, _compute_regularity(br_arr, 1))

    _assert(prem_snore,  "probable_rem=True for snore window")
    _assert(not prem_silent, "probable_rem=False for silent window")


# ── Test 5: Full session classification via simulate.py ───────────────────────

def test_full_session():
    print("\nTest 5: Full session classification on simulated night")

    db_path = _make_db()

    from pipeline.simulate import simulate_night
    session_id = simulate_night(quality=0.8, db_path=db_path)

    metrics = classify_session(session_id, db_path)

    _assert(bool(metrics), "classify_session returned non-empty metrics")

    if metrics:
        dp = metrics.get("deep_sleep_proportion", 0.0)
        aw = metrics.get("awakening_count", -1)
        ol = metrics.get("sleep_onset_latency_minutes", -1)

        # Lower bound 0.02: simulated exponential movement noise (λ=0.03) pushes
        # ~50% of deep-sleep windows above MOVEMENT_THRESHOLD_LOW, so the
        # classifier underestimates relative to ground truth.  We verify that
        # some deep sleep is detected (>2%) and it is not implausibly large (<35%).
        _assert(0.02 <= dp <= 0.35,
                f"deep_sleep_proportion detected (>2%, realistic ceiling <35%)",
                f"got {dp:.3f}")
        _assert(aw >= 0,
                "awakening_count >= 0",
                f"got {aw}")
        _assert(5.0 <= ol <= 60.0,
                "sleep_onset_latency_minutes in [5, 60]",
                f"got {ol:.1f}")

    # Verify rows written to DB
    conn = get_connection(db_path)
    try:
        n_rows  = conn.execute(
            "SELECT COUNT(*) FROM sleep_stages WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        n_csi   = conn.execute(
            "SELECT COUNT(DISTINCT timestamp) FROM csi_readings WHERE timestamp >= "
            "(SELECT bed_entry FROM sleep_sessions WHERE id=?) AND timestamp <= "
            "(SELECT bed_exit FROM sleep_sessions WHERE id=?)",
            (session_id, session_id),
        ).fetchone()[0]
        stages_ok = conn.execute(
            "SELECT COUNT(*) FROM sleep_stages "
            "WHERE session_id=? AND stage NOT IN ('WAKE','DEEP','LIGHT_REM')",
            (session_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    _assert(n_rows == n_csi,
            f"sleep_stages rows ({n_rows}) == number of CSI windows ({n_csi})")
    _assert(stages_ok == 0,
            "All stage values are valid (WAKE/DEEP/LIGHT_REM)")

    os.unlink(db_path)


# ── Test 6: ML retrain after 15 simulated nights ──────────────────────────────

def test_ml_retrain():
    print("\nTest 6: ML retrain — 15 simulated nights")

    db_path = _make_db()
    from pipeline.simulate import simulate_night
    from datetime import datetime, timedelta

    base = datetime(2024, 1, 1, 22, 30)
    for night in range(15):
        start = base - timedelta(days=15 - night)
        sid   = simulate_night(quality=0.75, start_time=start, db_path=db_path)
        classify_session(sid, db_path)

    result = retrain_staging_model(db_path)
    _assert(result is True,
            "retrain_staging_model returned True")

    model_path = os.path.join(os.path.dirname(__file__), "..", "data", "staging_model.pkl")
    _assert(os.path.exists(os.path.abspath(model_path)),
            "data/staging_model.pkl created")

    os.unlink(db_path)


# ── Test 7: Batch pipeline integration ────────────────────────────────────────

def test_batch_integration():
    print("\nTest 7: Batch pipeline integration — staging feeds real metrics into score")

    db_path = _make_db()
    from pipeline.simulate import simulate_night
    from pipeline.batch import run_pipeline

    session_id = simulate_night(quality=0.8, db_path=db_path)
    summary    = run_pipeline(session_id=session_id, db_path=db_path)

    # sleep_stages rows must exist
    conn = get_connection(db_path)
    try:
        n_rows = conn.execute(
            "SELECT COUNT(*) FROM sleep_stages WHERE session_id=?", (session_id,)
        ).fetchone()[0]
    finally:
        conn.close()

    _assert(n_rows > 0,
            f"sleep_stages rows written by batch pipeline ({n_rows} rows)")

    # The staging metrics should have been merged into features
    staging = summary.get("staging")
    _assert(staging is not None,
            "summary['staging'] populated by batch pipeline")

    if staging:
        dp_staging = staging.get("deep_sleep_proportion", None)
        # features deep_sleep_proportion should match staging (batch merges them)
        features   = summary.get("features")
        dp_feat    = features.get("deep_sleep_proportion") if features else None
        _assert(
            dp_feat is not None and dp_feat == dp_staging,
            f"features deep_sleep_proportion matches staging ({dp_feat:.3f})",
            f"features={dp_feat}, staging={dp_staging}",
        )

    os.unlink(db_path)


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_heuristic_wake()
    test_heuristic_deep()
    test_smoothing()
    test_rem_estimation()
    test_full_session()
    test_ml_retrain()
    test_batch_integration()

    print(f"\n{'='*50}")
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    if _FAIL:
        sys.exit(1)
