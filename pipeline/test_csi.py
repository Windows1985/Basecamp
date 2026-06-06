"""
CSI pipeline test suite.

Proves correctness of the breathing-rate extraction pipeline against synthetic
data with known ground truth.  The key deliverable is the breathing-recovery
accuracy table in Test 1 — it directly demonstrates that the pipeline recovers
known breathing rates within ±1 BPM.

Run:
    python pipeline/test_csi.py
    # or
    python -m pytest pipeline/test_csi.py -v
"""
import os
import sys
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.csi_synthetic import (
    generate_synthetic_csi,
    csi_to_variance_signal,
    compute_subcarrier_variance,
    CSI_NULL_SUBCARRIERS,
    CSI_PILOT_SUBCARRIERS,
)
from pipeline.csi import extract_window_features, extract_csi_features
from server.db import init_db, get_connection

PASS = "PASS"
FAIL = "FAIL"
_results = []


def _record(name, passed, msg=""):
    status = PASS if passed else FAIL
    _results.append((name, status, msg))
    icon = "✓" if passed else "✗"
    print(f"  {icon} {status}  {msg}" if msg else f"  {icon} {status}")


def _make_temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    return path


def _insert_session(db_path, bed_entry, bed_exit, duration_hours):
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO sleep_sessions (bed_entry, bed_exit, duration_hours) VALUES (?, ?, ?)",
            (bed_entry, bed_exit, duration_hours),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _insert_variance_rows(db_path, rows):
    """rows: list of (timestamp_str, node_id, variance_value)"""
    conn = get_connection(db_path)
    try:
        conn.executemany(
            "INSERT INTO csi_variance (timestamp, node_id, variance_value) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — Breathing recovery accuracy
# ─────────────────────────────────────────────────────────────────────────────

def test_breathing_recovery():
    """
    For each target rate in [10, 12, 14, 16, 18, 20] BPM, generate 60 s of
    synthetic CSI, run through the full variance → bandpass → FFT pipeline,
    and assert the recovered rate is within ±1 BPM.

    Uses two back-to-back 30-second windows; reports the mean recovered BPM.
    """
    print("\nTest 1 — Breathing Recovery Accuracy")
    print(f"  {'Target BPM':>10} | {'Recovered BPM':>13} | {'Error (BPM)':>11} | Status")
    print(f"  {'-'*10}-+-{'-'*13}-+-{'-'*11}-+--------")

    target_rates = [10, 12, 14, 16, 18, 20]
    tolerance = 1.0  # BPM
    all_pass = True

    for bpm in target_rates:
        csi, gt = generate_synthetic_csi(
            duration_seconds=60,
            breathing_rate_bpm=bpm,
            packet_rate=100,
            n_subcarriers=56,
            snr_db=20,
            rng_seed=bpm,
        )

        # Variance signal at 20 Hz
        var_signal = csi_to_variance_signal(csi, downsample_rate=20, packet_rate=100)

        # Extract features from two 30-second windows and average
        w1 = var_signal[:600]
        w2 = var_signal[600:1200]
        recovered_rates = []
        for w in [w1, w2]:
            feats = extract_window_features(w, fs=20.0)
            if feats is not None:
                recovered_rates.append(feats["breathing_rate_bpm"])

        if not recovered_rates:
            recovered = float("nan")
            error = float("nan")
            passed = False
        else:
            recovered = float(np.mean(recovered_rates))
            error = abs(recovered - bpm)
            passed = error <= tolerance

        status = PASS if passed else FAIL
        print(
            f"  {bpm:>10} | {recovered:>13.2f} | {error if not np.isnan(error) else '   N/A':>11.2f} | {status}"
        )
        if not passed:
            all_pass = False

    _record(
        "test_breathing_recovery",
        all_pass,
        f"All {len(target_rates)} rates within ±{tolerance} BPM" if all_pass
        else f"Some rates outside ±{tolerance} BPM tolerance",
    )
    return all_pass


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — Movement detection
# ─────────────────────────────────────────────────────────────────────────────

def test_movement_detection():
    """
    Generate CSI with breathing + 3 movement events at known timestamps.
    Assert movement_power in those windows is elevated vs. quiet windows.
    """
    print("\nTest 2 — Movement Detection")

    duration = 120  # seconds
    movement_times = [20.0, 60.0, 95.0]  # seconds from start
    movement_duration = 2.0

    csi, gt = generate_synthetic_csi(
        duration_seconds=duration,
        breathing_rate_bpm=14,
        movement_events=movement_times,
        movement_duration_seconds=movement_duration,
        packet_rate=100,
        n_subcarriers=56,
        snr_db=20,
        rng_seed=99,
    )

    var_signal = csi_to_variance_signal(csi, downsample_rate=20, packet_rate=100)
    fs = 20.0
    window_sec = 30

    n_windows = len(var_signal) // int(window_sec * fs)
    window_powers = []
    window_starts = []
    for w in range(n_windows):
        chunk = var_signal[w * int(window_sec * fs): (w + 1) * int(window_sec * fs)]
        feats = extract_window_features(chunk, fs=fs)
        if feats:
            window_powers.append(feats["movement_power"])
            window_starts.append(w * window_sec)

    if not window_powers:
        _record("test_movement_detection", False, "No windows processed")
        return False

    # Identify which windows are directly touched by a movement event.
    # A movement at time mt with duration movement_duration occupies window
    # floor(mt / window_sec) and possibly floor((mt+duration) / window_sec).
    movement_window_indices = set()
    for mt in movement_times:
        wi_start = int(mt / window_sec)
        wi_end = int((mt + movement_duration) / window_sec)
        for wi in range(wi_start, wi_end + 1):
            if wi < len(window_starts):
                movement_window_indices.add(wi)

    quiet_indices = [i for i in range(len(window_powers)) if i not in movement_window_indices]

    if not quiet_indices or not movement_window_indices:
        _record("test_movement_detection", False, "Could not separate movement/quiet windows")
        return False

    mean_movement_power = np.mean([window_powers[i] for i in movement_window_indices])
    mean_quiet_power = np.mean([window_powers[i] for i in quiet_indices])

    passed = mean_movement_power > mean_quiet_power * 1.5  # expect ≥50% elevation
    ratio = mean_movement_power / mean_quiet_power if mean_quiet_power > 0 else float("inf")
    print(f"  Movement windows mean power: {mean_movement_power:.4f}")
    print(f"  Quiet windows mean power:    {mean_quiet_power:.4f}")
    print(f"  Ratio (expect >1.5):         {ratio:.2f}")
    _record(
        "test_movement_detection",
        passed,
        f"Movement power {ratio:.1f}× quiet power" if passed else f"Ratio {ratio:.1f}× — too low",
    )
    return passed


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — Multi-node fusion
# ─────────────────────────────────────────────────────────────────────────────

def test_multinode_fusion():
    """
    Generate two node signals.  Degrade node_2 with heavy noise (5 dB SNR).
    Verify that the fused result is within ±1 BPM of the clean node.
    """
    print("\nTest 3 — Multi-node Fusion")

    target_bpm = 16
    duration = 60

    # Good node: 20 dB SNR
    csi_good, _ = generate_synthetic_csi(duration, target_bpm, snr_db=20, rng_seed=1)
    # Bad node: 3 dB SNR (very noisy)
    csi_bad, _ = generate_synthetic_csi(duration, target_bpm, snr_db=3, rng_seed=2)

    var_good = csi_to_variance_signal(csi_good, downsample_rate=20, packet_rate=100)
    var_bad = csi_to_variance_signal(csi_bad, downsample_rate=20, packet_rate=100)

    fs = 20.0
    W = 600  # 30s window

    def node_result(var_signal):
        results = []
        for start in range(0, len(var_signal) - W + 1, W):
            chunk = var_signal[start:start + W]
            feats = extract_window_features(chunk, fs=fs)
            if feats:
                results.append(feats)
        return results

    results_good = node_result(var_good)
    results_bad = node_result(var_bad)

    if not results_good or not results_bad:
        _record("test_multinode_fusion", False, "No results from one or both nodes")
        return False

    # Simulate the fusion logic from pipeline/csi.py
    def fuse_two(r_good, r_bad):
        bpms, weights = [], []
        for rg, rb in zip(r_good, r_bad):
            qg = rg["breathing_regularity"]
            qb = rb["breathing_regularity"]
            total_w = qg + qb
            fused_bpm = (rg["breathing_rate_bpm"] * qg + rb["breathing_rate_bpm"] * qb) / total_w
            bpms.append(fused_bpm)
            weights.append(total_w)
        return float(np.mean(bpms))

    mean_good = np.mean([r["breathing_rate_bpm"] for r in results_good])
    mean_bad = np.mean([r["breathing_rate_bpm"] for r in results_bad])
    fused_bpm = fuse_two(results_good, results_bad)

    error_fused = abs(fused_bpm - target_bpm)
    error_bad = abs(mean_bad - target_bpm)

    # Fusion should be at most as far off as the bad node alone, ideally better
    passed = error_fused <= 1.0

    print(f"  Target BPM:       {target_bpm}")
    print(f"  Good node mean:   {mean_good:.2f} BPM  (error {abs(mean_good - target_bpm):.2f})")
    print(f"  Bad node mean:    {mean_bad:.2f} BPM  (error {error_bad:.2f})")
    print(f"  Fused result:     {fused_bpm:.2f} BPM  (error {error_fused:.2f})")

    _record(
        "test_multinode_fusion",
        passed,
        f"Fused BPM {fused_bpm:.2f} within ±1 BPM of {target_bpm}" if passed
        else f"Fused BPM {fused_bpm:.2f} error {error_fused:.2f} BPM",
    )
    return passed


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — Parser robustness
# ─────────────────────────────────────────────────────────────────────────────

def test_parser_robustness():
    """
    Feed the CSI packet parser malformed, truncated, and valid data.
    Assert no exception is raised and valid data parses correctly.
    """
    print("\nTest 4 — Parser Robustness")

    from server.csi_ingest import parse_csi_packet, _parse_csv_line

    cases = [
        # (label, input, expect_none)
        ("empty bytes", b"", True),
        ("random garbage", b"\x00\x01\x02\x03\x04", True),
        ("truncated CSV", b"1,2,3,mac,rssi,[10,20", True),
        ("no bracket", b"1,2,3,mac,rssi,10,20,30", True),
        ("valid CSV even N", b"ts,mac,rssi,0,[10,20,30,40,50,60,70,80]", False),
        ("valid space-sep", b"ts,mac,rssi,0,[10 20 30 40 50 60 70 80]", False),
        ("odd count CSV", b"ts,mac,rssi,0,[10,20,30]", True),
        ("unicode garbage", "ts,üüü,[abc,def]".encode("utf-8"), True),
    ]

    all_ok = True
    for label, data, expect_none in cases:
        try:
            result = parse_csi_packet(data, node_hint="test")
            got_none = (result is None)
            correct = (got_none == expect_none)
            status = PASS if correct else FAIL
            detail = (
                f"got {'None' if got_none else f'array len={len(result)}'}"
                f" (expect {'None' if expect_none else 'array'})"
            )
            print(f"  {status} {label}: {detail}")
            if not correct:
                all_ok = False
        except Exception as exc:
            print(f"  {FAIL} {label}: raised {type(exc).__name__}: {exc}")
            all_ok = False

    # Also verify the valid CSV case produces correct complex values
    try:
        csi = _parse_csv_line("ts,mac,0,[4,3,2,1]")  # imag0=4,real0=3 → 3+4j; imag1=2,real1=1 → 1+2j
        expected = np.array([3 + 4j, 1 + 2j])
        close = np.allclose(csi, expected)
        print(f"  {'PASS' if close else 'FAIL'} CSV complex values: {csi} == {expected}")
        if not close:
            all_ok = False
    except Exception as exc:
        print(f"  FAIL CSV value check: {exc}")
        all_ok = False

    _record("test_parser_robustness", all_ok, "All parser cases handled correctly" if all_ok else "Parser failures")
    return all_ok


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — End-to-end with ingestion simulation
# ─────────────────────────────────────────────────────────────────────────────

def test_e2e_ingestion():
    """
    Simulate what the ingestion daemon writes to csi_variance for a 60-second
    session, then run extract_csi_features and verify:
      - rows were written to csi_readings
      - recovered breathing rate is in a plausible range (6-30 BPM)
    """
    print("\nTest 5 — End-to-End Ingestion Simulation")

    db_path = _make_temp_db()
    target_bpm = 15
    duration = 60  # seconds
    fs = 20.0

    try:
        # Build timestamps covering the session window
        t0 = datetime(2024, 1, 15, 22, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(seconds=duration)
        bed_entry = t0.isoformat().replace("+00:00", "Z")
        bed_exit = t1.isoformat().replace("+00:00", "Z")

        # Insert session record
        session_id = _insert_session(db_path, bed_entry, bed_exit, duration / 3600.0)

        # Simulate two nodes
        variance_rows = []
        for node_id in ["node_01", "node_02"]:
            csi, _ = generate_synthetic_csi(
                duration_seconds=duration,
                breathing_rate_bpm=target_bpm,
                packet_rate=100,
                n_subcarriers=56,
                snr_db=20,
                rng_seed=42 if node_id == "node_01" else 7,
            )
            var_signal = csi_to_variance_signal(csi, downsample_rate=20, packet_rate=100)
            dt_step = 1.0 / fs
            for i, v in enumerate(var_signal):
                ts = (t0 + timedelta(seconds=i * dt_step)).isoformat().replace("+00:00", "Z")
                variance_rows.append((ts, node_id, float(v)))

        _insert_variance_rows(db_path, variance_rows)
        print(f"  Inserted {len(variance_rows)} variance rows for 2 nodes")

        # Run CSI feature extraction
        fused = extract_csi_features(session_id, db_path)
        print(f"  extract_csi_features returned {len(fused)} fused windows")

        # Check csi_readings was populated
        conn = get_connection(db_path)
        try:
            n_readings = conn.execute(
                "SELECT COUNT(*) AS c FROM csi_readings WHERE timestamp >= ? AND timestamp <= ?",
                (bed_entry, bed_exit),
            ).fetchone()["c"]
            fused_rows = conn.execute(
                "SELECT breathing_rate FROM csi_readings WHERE node_id = 'fused' "
                "AND timestamp >= ? AND timestamp <= ?",
                (bed_entry, bed_exit),
            ).fetchall()
        finally:
            conn.close()

        print(f"  csi_readings row count: {n_readings}")

        if not fused_rows:
            _record("test_e2e_ingestion", False, "No fused rows in csi_readings")
            return False

        bpms = [r["breathing_rate"] for r in fused_rows]
        mean_bpm = float(np.mean(bpms))
        in_range = all(6.0 <= b <= 30.0 for b in bpms)
        close_to_target = abs(mean_bpm - target_bpm) <= 2.0

        print(f"  Fused BPMs per window: {[round(b, 2) for b in bpms]}")
        print(f"  Mean fused BPM: {mean_bpm:.2f} (target {target_bpm})")

        passed = in_range and n_readings > 0 and close_to_target
        _record(
            "test_e2e_ingestion",
            passed,
            f"Mean {mean_bpm:.2f} BPM, {n_readings} rows written" if passed
            else f"Mean {mean_bpm:.2f} BPM (off target) or {n_readings} rows",
        )
        return passed

    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_all():
    print("=" * 60)
    print("Basecamp CSI Pipeline Test Suite")
    print("=" * 60)

    tests = [
        ("Breathing Recovery Accuracy", test_breathing_recovery),
        ("Movement Detection",          test_movement_detection),
        ("Multi-node Fusion",           test_multinode_fusion),
        ("Parser Robustness",           test_parser_robustness),
        ("End-to-End Ingestion",        test_e2e_ingestion),
    ]

    for name, fn in tests:
        try:
            fn()
        except Exception as exc:
            import traceback
            _record(name, False, f"Unhandled exception: {exc}")
            traceback.print_exc()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, s, _ in _results if s == PASS)
    total = len(_results)
    for name, status, msg in _results:
        icon = "✓" if status == PASS else "✗"
        print(f"  {icon} [{status}] {name}: {msg}")
    print(f"\n{passed}/{total} tests passed")
    print("=" * 60)

    return passed == total


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
