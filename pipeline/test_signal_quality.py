"""
Tests for the CSI signal quality marker (Part 1).

Run with:
    python -m pytest pipeline/test_signal_quality.py -v
    # or directly:
    python pipeline/test_signal_quality.py
"""
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.csi import compute_signal_quality, FS, WINDOW_SAMPLES, LOW_CONFIDENCE_THRESHOLD


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sine_window(freq_hz, fs=FS, n=WINDOW_SAMPLES, noise_std=0.0, rng_seed=0):
    """Generate a window containing a sine wave at freq_hz Hz."""
    t = np.arange(n) / fs
    rng = np.random.default_rng(rng_seed)
    sig = np.sin(2 * np.pi * freq_hz * t)
    if noise_std > 0:
        sig = sig + rng.normal(0, noise_std, size=n)
    return sig.astype(float)


def _white_noise_window(n=WINDOW_SAMPLES, rng_seed=1):
    rng = np.random.default_rng(rng_seed)
    return rng.normal(0, 1, size=n).astype(float)


# ── compute_signal_quality ────────────────────────────────────────────────────

class TestComputeSignalQuality(unittest.TestCase):

    def test_returns_float_in_range(self):
        """Quality is always 0.0–1.0 for any finite input."""
        for seed in range(5):
            rng = np.random.default_rng(seed)
            win = rng.normal(0, 1, WINDOW_SAMPLES).astype(float)
            q = compute_signal_quality(win)
            self.assertIsInstance(q, float)
            self.assertGreaterEqual(q, 0.0)
            self.assertLessEqual(q, 1.0)

    def test_clean_15bpm_sine_high_quality(self):
        """A clean 0.25 Hz (15 BPM) sine wave should produce quality > 0.7."""
        win = _sine_window(0.25)
        q = compute_signal_quality(win)
        self.assertGreater(q, 0.7, msg=f"Expected quality > 0.7, got {q:.3f}")

    def test_white_noise_low_quality(self):
        """Pure white noise should produce low mean quality (< 0.4 on average).

        Single realizations can exceed 0.4 by chance (the breathing band has a
        finite number of spectral bins, so the peak/noise ratio varies randomly).
        The mean over 30 independent noise windows is the meaningful measure.
        """
        qualities = [compute_signal_quality(_white_noise_window(rng_seed=s)) for s in range(30)]
        mean_q = float(np.mean(qualities))
        self.assertLess(mean_q, 0.4, msg=f"Expected mean quality < 0.4 for white noise, got {mean_q:.3f}")

    def test_flat_zero_returns_zero_no_error(self):
        """A flat zero signal should return 0.0 without raising."""
        win = np.zeros(WINDOW_SAMPLES)
        q = compute_signal_quality(win)
        self.assertEqual(q, 0.0)

    def test_empty_window_returns_zero(self):
        q = compute_signal_quality(np.array([]))
        self.assertEqual(q, 0.0)

    def test_single_sample_returns_zero(self):
        q = compute_signal_quality(np.array([1.0]))
        self.assertEqual(q, 0.0)

    def test_noisy_sine_still_reasonable(self):
        """A sine with moderate noise should be between 0.2 and 1.0."""
        win = _sine_window(0.25, noise_std=0.5)
        q = compute_signal_quality(win)
        self.assertGreaterEqual(q, 0.0)
        self.assertLessEqual(q, 1.0)


# ── Feature extraction ────────────────────────────────────────────────────────

def _make_temp_db():
    from server.db import init_db, get_connection, migrate_schema
    from server.config import DB_PATH
    tf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tf.close()
    init_db(tf.name)
    migrate_schema(tf.name)
    return tf.name


def _insert_session(db_path, bed_entry="2026-01-01T22:00:00", bed_exit="2026-01-02T06:00:00", duration=8.0):
    from server.db import get_connection
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO sleep_sessions (bed_entry, bed_exit, duration_hours) VALUES (?, ?, ?)",
            (bed_entry, bed_exit, duration),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()


def _insert_csi_rows(db_path, bed_entry, n_windows, qualities, bpm=14.0):
    """Insert n_windows csi_readings rows with given quality values."""
    from server.db import get_connection
    from datetime import datetime, timedelta
    conn = get_connection(db_path)
    try:
        base = datetime.fromisoformat(bed_entry)
        for i in range(n_windows):
            ts = (base + timedelta(seconds=i * 30)).isoformat()
            q = qualities[i] if qualities is not None else None
            conn.execute(
                "INSERT INTO csi_readings (timestamp, breathing_rate, movement_power, node_id, signal_quality)"
                " VALUES (?, ?, ?, ?, ?)",
                (ts, bpm, 0.05, "fused", q),
            )
        conn.commit()
    finally:
        conn.close()


class TestFeatureExtractionQuality(unittest.TestCase):

    def setUp(self):
        self.db = _make_temp_db()

    def tearDown(self):
        os.unlink(self.db)

    def test_excludes_low_confidence_windows_from_breathing_mean(self):
        """High-confidence windows at bpm=14, low-confidence at bpm=20 → mean ~14."""
        from pipeline.features import extract_features
        sid = _insert_session(self.db)
        n = 20
        # First 10 windows: high confidence (q=0.9) at 14 BPM
        # Next 10 windows: low confidence (q=0.1) at 20 BPM
        qualities = [0.9] * 10 + [0.1] * 10
        bpms_values = [14.0] * 10 + [20.0] * 10

        from server.db import get_connection
        from datetime import datetime, timedelta
        conn = get_connection(self.db)
        base = datetime.fromisoformat("2026-01-01T22:00:00")
        try:
            for i in range(n):
                ts = (base + timedelta(seconds=i * 30)).isoformat()
                conn.execute(
                    "INSERT INTO csi_readings (timestamp, breathing_rate, movement_power, node_id, signal_quality)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (ts, bpms_values[i], 0.05, "fused", qualities[i]),
                )
            conn.commit()
        finally:
            conn.close()

        feats = extract_features(sid, self.db)
        # mean_br should be close to 14, not skewed toward 20
        self.assertIsNotNone(feats["mean_breathing_rate"])
        self.assertLess(feats["mean_breathing_rate"], 16.0,
                        msg=f"Expected mean_br ~14 (low-conf excluded), got {feats['mean_breathing_rate']:.2f}")

    def test_breathing_rate_none_when_80pct_low_confidence(self):
        """If >80% windows are low confidence, breathing_rate_mean is None."""
        from pipeline.features import extract_features
        sid = _insert_session(self.db)
        n = 20
        # 18 low-confidence, 2 high-confidence → 90 % low
        qualities = [0.1] * 18 + [0.9] * 2
        _insert_csi_rows(self.db, "2026-01-01T22:00:00", n, qualities)

        feats = extract_features(sid, self.db)
        self.assertIsNone(feats["mean_breathing_rate"],
                          msg="Expected None when >80% low confidence")
        self.assertIsNone(feats["breathing_regularity"],
                          msg="Expected None when >80% low confidence")

    def test_low_confidence_pct_correct(self):
        """csi_low_confidence_pct matches the known fraction."""
        from pipeline.features import extract_features
        sid = _insert_session(self.db)
        n = 10
        # 3 low-confidence (q=0.1), 7 high-confidence (q=0.9) → 30 %
        qualities = [0.1] * 3 + [0.9] * 7
        _insert_csi_rows(self.db, "2026-01-01T22:00:00", n, qualities)

        feats = extract_features(sid, self.db)
        self.assertAlmostEqual(feats["csi_low_confidence_pct"], 30.0, places=1)

    def test_quality_mean_computed(self):
        """csi_quality_mean is the mean of all quality values."""
        from pipeline.features import extract_features
        sid = _insert_session(self.db)
        qualities = [0.8, 0.6, 0.4, 0.2, 0.0]
        _insert_csi_rows(self.db, "2026-01-01T22:00:00", len(qualities), qualities)

        feats = extract_features(sid, self.db)
        expected_mean = float(np.mean(qualities))
        self.assertAlmostEqual(feats["csi_quality_mean"], expected_mean, places=3)


# ── Staging ───────────────────────────────────────────────────────────────────

class TestStagingNoneBreathing(unittest.TestCase):

    def test_heuristic_single_nan_br_no_raise(self):
        """_heuristic_single with NaN breathing rate must not raise and must not return WAKE."""
        from pipeline.staging import _heuristic_single, WAKE
        w = {
            "mp": 0.05,
            "br": float("nan"),
            "presence": True,
            "still_dist": 0.5,
            "moving_dist": 0.0,
            "audio_tier": "silence",
        }
        stage, probable_rem, deep_cand = _heuristic_single(w, regularity=0.5)
        self.assertNotEqual(stage, WAKE, msg="NaN br should not force WAKE")
        self.assertFalse(deep_cand, msg="NaN br cannot be deep candidate")

    def test_heuristic_single_nan_br_snore_sets_rem(self):
        """With NaN br and snoring audio, probable_rem should be True."""
        from pipeline.staging import _heuristic_single
        w = {
            "mp": 0.05,
            "br": float("nan"),
            "presence": True,
            "still_dist": 0.5,
            "moving_dist": 0.0,
            "audio_tier": "snore",
        }
        stage, probable_rem, deep_cand = _heuristic_single(w, regularity=0.5)
        self.assertTrue(probable_rem, msg="Snoring should set probable_rem even with NaN br")


# ── Recovery score penalty ────────────────────────────────────────────────────

class TestRecoveryScorePenalty(unittest.TestCase):

    def _make_features(self, low_conf_pct):
        return {
            "deep_sleep_proportion": 0.18,
            "rem_proportion": 0.22,
            "sleep_efficiency": 0.88,
            "total_sleep_duration_hours": 7.2,
            "awakening_count": 1,
            "sleep_onset_latency_minutes": 15.0,
            "breathing_regularity": 0.6,
            "apnea_count": 0,
            "snoring_duration_minutes": 5.0,
            "peak_co2": 800.0,
            "temperature_optimality": 0.9,
            "voc_peak": 90.0,
            "light_intrusion_events": 0,
            "csi_low_confidence_pct": low_conf_pct,
            "csi_quality_mean": None,
        }

    def setUp(self):
        self.db = _make_temp_db()
        self.sid = _insert_session(self.db)

    def tearDown(self):
        os.unlink(self.db)

    def test_no_penalty_below_50pct(self):
        """No penalty applied when low_conf_pct <= 50."""
        from pipeline.score import calculate_recovery_score
        feats_clean = self._make_features(0.0)
        feats_border = self._make_features(50.0)

        result_clean = calculate_recovery_score(feats_clean, self.sid, self.db)
        # Use a fresh session for the second call
        sid2 = _insert_session(self.db)
        result_border = calculate_recovery_score(feats_border, sid2, self.db)

        self.assertAlmostEqual(
            result_clean["breathing_score"],
            result_border["breathing_score"],
            places=1,
            msg="No penalty at exactly 50%",
        )

    def test_penalty_applied_at_60pct(self):
        """At 60% low confidence, breathing_score is penalised."""
        from pipeline.score import calculate_recovery_score
        feats_clean = self._make_features(0.0)
        feats_penalised = self._make_features(60.0)

        sid2 = _insert_session(self.db)
        sid3 = _insert_session(self.db)
        result_clean = calculate_recovery_score(feats_clean, sid2, self.db)
        result_penalised = calculate_recovery_score(feats_penalised, sid3, self.db)

        self.assertLess(
            result_penalised["breathing_score"],
            result_clean["breathing_score"],
            msg="60% low confidence should reduce breathing_score",
        )
        # Expected penalty factor: 1 - (60 - 50) / 100 = 0.9
        expected = round(result_clean["breathing_score"] * 0.9, 1)
        self.assertAlmostEqual(result_penalised["breathing_score"], expected, places=0)


# ── Report note ───────────────────────────────────────────────────────────────

class TestReportNote(unittest.TestCase):

    def setUp(self):
        self.db = _make_temp_db()

    def tearDown(self):
        os.unlink(self.db)

    def _write_score(self, low_conf_pct):
        from server.db import get_connection
        from datetime import datetime
        sid = _insert_session(self.db)
        conn = get_connection(self.db)
        try:
            conn.execute(
                """
                INSERT INTO recovery_scores
                  (session_id, timestamp, architecture_score, continuity_score,
                   breathing_score, environment_score, total_score, low_confidence_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, datetime.now().isoformat(), 70, 75, 65, 80, 72, low_conf_pct),
            )
            conn.commit()
        finally:
            conn.close()
        return sid

    def test_note_present_when_pct_25(self):
        """Low-confidence note appears in report when pct=25."""
        from pipeline.report import generate_report
        sid = self._write_score(25.0)
        report = generate_report(sid, self.db)
        self.assertIn("breathing rate unavailable", report.lower())
        self.assertIn("25%", report)

    def test_note_absent_when_pct_15(self):
        """Low-confidence note is absent when pct=15."""
        from pipeline.report import generate_report
        sid = self._write_score(15.0)
        report = generate_report(sid, self.db)
        self.assertNotIn("breathing rate unavailable", report.lower())

    def test_note_absent_when_pct_none(self):
        """Low-confidence note is absent when low_confidence_pct is NULL."""
        from pipeline.report import generate_report
        sid = self._write_score(None)
        report = generate_report(sid, self.db)
        self.assertNotIn("breathing rate unavailable", report.lower())


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
