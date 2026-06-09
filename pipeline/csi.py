"""
CSI feature extraction — morning batch path.

Reads the 20 Hz cross-subcarrier variance signal written by server/csi_ingest.py
from the csi_variance table, then for every 30-second window extracts:
  - breathing_rate  (BPM) via bandpass FFT
  - breathing_regularity (0-1, peak / total band power)
  - movement_power  (RMS of high-passed variance signal)

Results are written to csi_readings (one row per window, node_id "node_X" for
individual nodes and "fused" for the quality-weighted multi-node result).

This module replaces the placeholder CSI logic that was previously hardwired
into pipeline/features.py.  features.py calls extract_csi_features() at the
start of extract_features(), which populates csi_readings before features.py
reads from it.
"""
import logging
import os
import sys
from datetime import datetime, timedelta

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.db import get_connection

logger = logging.getLogger(__name__)

# ── Filter parameters ──────────────────────────────────────────────────────────
BREATH_LOW_HZ = 0.10   # 6 BPM lower bound
BREATH_HIGH_HZ = 0.50  # 30 BPM upper bound
MOVE_HIGH_HZ = 0.50    # high-pass cutoff for movement
FILTER_ORDER = 4
FS = 20.0              # variance signal sample rate (Hz)
WINDOW_SECONDS = 30
WINDOW_SAMPLES = int(WINDOW_SECONDS * FS)  # 600
NFFT = 8192            # zero-padded FFT length — gives 0.0024 Hz resolution

# Minimum quality threshold for including a node in the weighted average
MIN_NODE_QUALITY = 0.05


LOW_CONFIDENCE_THRESHOLD = 0.5   # quality < this → low confidence


# ── Signal quality ─────────────────────────────────────────────────────────────

def compute_signal_quality(variance_window, fs=FS):
    """
    Compute a 0.0–1.0 signal quality score for a 30-second variance window.

    Uses FFT-based peak-to-noise ratio in the breathing band (0.1–0.5 Hz):
      - peak power / mean noise power of remaining band bins
      - mapped via sigmoid: quality = 1 / (1 + exp(-(ratio - 4.0) / 1.5))
        ratio 4.0 → 0.50, ratio 2.0 → ~0.12, ratio 8.0 → ~0.93

    Returns 0.0 for zero/empty inputs without raising.
    """
    n = len(variance_window)
    if n < 2:
        return 0.0

    arr = np.asarray(variance_window, dtype=float)
    if not np.any(arr):
        return 0.0

    signal = arr - float(np.mean(arr))

    # Hanning window reduces spectral leakage so real breathing peaks remain
    # sharp, while broadband noise energy stays spread across all bins.
    # Zero-padding to NFFT gives ~167 bins in the breathing band (vs ~13 without),
    # making white noise reliably produce lower peak-to-noise ratios on average.
    hann = np.hanning(n)
    signal = signal * hann
    nfft = max(NFFT, 2 * n)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    psd = np.abs(np.fft.rfft(signal, n=nfft)) ** 2

    band_mask = (freqs >= BREATH_LOW_HZ) & (freqs <= BREATH_HIGH_HZ)
    if not np.any(band_mask):
        return 0.0

    band_psd = psd[band_mask]
    if not np.any(band_psd):
        return 0.0

    peak_idx = int(np.argmax(band_psd))
    peak_power = float(band_psd[peak_idx])

    # Noise: mean over band excluding peak ± 1 bin
    noise_mask = np.ones(len(band_psd), dtype=bool)
    for i in range(max(0, peak_idx - 1), min(len(band_psd), peak_idx + 2)):
        noise_mask[i] = False

    if not np.any(noise_mask):
        return 0.5  # only one or two bins in band — indeterminate

    noise_mean = float(np.mean(band_psd[noise_mask]))
    if noise_mean <= 0:
        return 1.0

    ratio = peak_power / noise_mean
    quality = 1.0 / (1.0 + np.exp(-(ratio - 4.0) / 1.5))
    return float(np.clip(quality, 0.0, 1.0))


# ── Internal helpers ──────────────────────────────────────────────────────────

def _bandpass_sos(low=BREATH_LOW_HZ, high=BREATH_HIGH_HZ, fs=FS, order=FILTER_ORDER):
    from scipy.signal import butter
    nyq = fs / 2.0
    return butter(order, [low / nyq, high / nyq], btype="bandpass", output="sos")


def _highpass_sos(cutoff=MOVE_HIGH_HZ, fs=FS, order=FILTER_ORDER):
    from scipy.signal import butter
    nyq = fs / 2.0
    return butter(order, cutoff / nyq, btype="highpass", output="sos")


def extract_window_features(variance_window, fs=FS):
    """
    Extract breathing rate, regularity, and movement power from one window.

    Args:
        variance_window: 1-D float array (ideally WINDOW_SAMPLES long).
        fs: sample rate in Hz.

    Returns:
        dict with keys: breathing_rate_bpm, breathing_regularity,
                        movement_power, peak_freq_hz.
        Returns None if the window is too short to filter.
    """
    from scipy.signal import sosfiltfilt

    n = len(variance_window)
    if n < max(12, 3 * FILTER_ORDER * 2):
        return None

    signal = variance_window - float(np.mean(variance_window))

    # ── Breathing extraction ──────────────────────────────────────────────────
    bp_sos = _bandpass_sos(fs=fs)
    filtered = sosfiltfilt(bp_sos, signal)

    # Hanning window reduces leakage; zero-padding to NFFT sharpens peak location
    win = np.hanning(n)
    windowed = filtered * win
    nfft = max(NFFT, 2 * n)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    fft_mag = np.abs(np.fft.rfft(windowed, n=nfft))

    band_mask = (freqs >= BREATH_LOW_HZ) & (freqs <= BREATH_HIGH_HZ)
    if not np.any(band_mask):
        return None

    band_freqs = freqs[band_mask]
    band_mag = fft_mag[band_mask]

    peak_idx = int(np.argmax(band_mag))
    peak_freq = float(band_freqs[peak_idx])
    breathing_rate_bpm = peak_freq * 60.0

    band_power = float(np.sum(band_mag ** 2))
    peak_power = float(band_mag[peak_idx] ** 2)
    regularity = peak_power / band_power if band_power > 0 else 0.0

    # ── Movement extraction ───────────────────────────────────────────────────
    hp_sos = _highpass_sos(fs=fs)
    hp_filtered = sosfiltfilt(hp_sos, signal)
    movement_power = float(np.sqrt(np.mean(hp_filtered ** 2)))

    return {
        "breathing_rate_bpm": breathing_rate_bpm,
        "breathing_regularity": regularity,
        "movement_power": movement_power,
        "peak_freq_hz": peak_freq,
    }


def _process_node_variance(timestamps, variance, session_id, window_sec=WINDOW_SECONDS, fs=FS):
    """
    Slice a node's variance signal into non-overlapping windows and extract features.

    Returns a list of dicts, one per window:
        { "window_start", "breathing_rate_bpm", "breathing_regularity",
          "movement_power", "quality" }
    """
    if len(variance) == 0:
        return []

    samples_per_window = int(window_sec * fs)
    n_windows = len(variance) // samples_per_window
    results = []

    for w in range(n_windows):
        chunk = variance[w * samples_per_window : (w + 1) * samples_per_window]
        feats = extract_window_features(chunk, fs=fs)
        if feats is None:
            continue
        sq = compute_signal_quality(chunk, fs=fs)
        results.append({
            "window_start": timestamps[w * samples_per_window],
            "breathing_rate_bpm": feats["breathing_rate_bpm"],
            "breathing_regularity": feats["breathing_regularity"],
            "movement_power": feats["movement_power"],
            "quality": feats["breathing_regularity"],
            "signal_quality": sq,
        })

    return results


def _fuse_nodes(node_windows):
    """
    Quality-weighted average of per-node window results.

    node_windows : dict { node_id -> list_of_window_dicts }

    Returns a list of fused window dicts aligned to the shortest node's
    windows.  Nodes with quality below MIN_NODE_QUALITY are excluded from
    the average for that window.
    """
    if not node_windows:
        return []

    node_ids = list(node_windows.keys())
    # Align by minimum number of windows across nodes
    n_windows = min(len(node_windows[nid]) for nid in node_ids)
    if n_windows == 0:
        return []

    fused = []
    for w in range(n_windows):
        window_start = node_windows[node_ids[0]][w]["window_start"]
        bpms, weights, move_powers = [], [], []

        for nid in node_ids:
            win = node_windows[nid][w]
            q = float(win["quality"])
            if q >= MIN_NODE_QUALITY:
                bpms.append(win["breathing_rate_bpm"])
                weights.append(q)
                move_powers.append(win["movement_power"])

        # Collect signal_quality values for quality-weighted average
        sq_vals = [
            node_windows[nid][w].get("signal_quality") or 0.0
            for nid in node_ids
        ]

        if not bpms:
            # All nodes below threshold — use simple average
            bpms = [node_windows[nid][w]["breathing_rate_bpm"] for nid in node_ids]
            weights = [1.0] * len(bpms)
            move_powers = [node_windows[nid][w]["movement_power"] for nid in node_ids]

        total_w = sum(weights)
        fused_bpm = sum(b * wt for b, wt in zip(bpms, weights)) / total_w
        fused_move = sum(m * wt for m, wt in zip(move_powers, weights)) / total_w
        fused_quality = total_w / len(node_ids)
        fused_sq = float(np.mean(sq_vals)) if sq_vals else None

        fused.append({
            "window_start": window_start,
            "breathing_rate_bpm": fused_bpm,
            "breathing_regularity": fused_quality,
            "movement_power": fused_move,
            "signal_quality": fused_sq,
        })

    return fused


# ── Public API ─────────────────────────────────────────────────────────────────

def extract_csi_features(session_id, db_path):
    """
    Read the stored 20 Hz variance signal for a session, extract per-window
    breathing and movement features, and write them to csi_readings.

    If the csi_variance table contains no data for the session's time window,
    this function returns an empty list without touching csi_readings, so
    existing simulated data in csi_readings is preserved.

    Returns:
        list of fused window dicts (empty if no variance data).
    """
    conn = get_connection(db_path)
    try:
        session = conn.execute(
            "SELECT bed_entry, bed_exit FROM sleep_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if session is None:
            raise ValueError(f"Session {session_id} not found")

        bed_entry = session["bed_entry"]
        bed_exit = session["bed_exit"]

        rows = conn.execute(
            """
            SELECT timestamp, node_id, variance_value
            FROM csi_variance
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY node_id, timestamp
            """,
            (bed_entry, bed_exit),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        logger.debug("No csi_variance data for session %s — keeping existing csi_readings", session_id)
        return []

    # Group by node
    from collections import defaultdict
    node_data = defaultdict(list)
    for row in rows:
        node_data[str(row["node_id"])].append(
            (str(row["timestamp"]), float(row["variance_value"]))
        )

    # Process each node
    node_windows = {}
    for node_id, data in node_data.items():
        timestamps = [d[0] for d in data]
        variance = np.array([d[1] for d in data])
        windows = _process_node_variance(timestamps, variance, session_id)
        if windows:
            node_windows[node_id] = windows

    if not node_windows:
        return []

    # Multi-node fusion
    fused_windows = _fuse_nodes(node_windows)

    # Write to csi_readings — delete old rows for this session's window first
    conn = get_connection(db_path)
    try:
        conn.execute(
            "DELETE FROM csi_readings WHERE timestamp >= ? AND timestamp <= ?",
            (bed_entry, bed_exit),
        )
        now = datetime.utcnow().isoformat()

        # Per-node rows
        for node_id, windows in node_windows.items():
            for win in windows:
                conn.execute(
                    """
                    INSERT INTO csi_readings
                      (timestamp, breathing_rate, movement_power, node_id, signal_quality)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        win["window_start"],
                        win["breathing_rate_bpm"],
                        win["movement_power"],
                        node_id,
                        win.get("signal_quality"),
                    ),
                )

        # Fused rows (node_id = "fused")
        for win in fused_windows:
            conn.execute(
                """
                INSERT INTO csi_readings
                  (timestamp, breathing_rate, movement_power, node_id, signal_quality)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    win["window_start"],
                    win["breathing_rate_bpm"],
                    win["movement_power"],
                    "fused",
                    win.get("signal_quality"),
                ),
            )

        conn.commit()
    finally:
        conn.close()

    logger.info(
        "CSI features written: %d fused windows from %d node(s)",
        len(fused_windows),
        len(node_windows),
    )
    return fused_windows


def summarise_csi_features(fused_windows):
    """Return summary statistics dict from a list of fused window dicts."""
    if not fused_windows:
        return {}

    bpms = [w["breathing_rate_bpm"] for w in fused_windows]
    moves = [w["movement_power"] for w in fused_windows]
    regs = [w["breathing_regularity"] for w in fused_windows]

    return {
        "mean_breathing_rate_bpm": float(np.mean(bpms)),
        "std_breathing_rate_bpm": float(np.std(bpms)),
        "mean_movement_power": float(np.mean(moves)),
        "mean_breathing_regularity": float(np.mean(regs)),
        "n_windows": len(fused_windows),
    }
