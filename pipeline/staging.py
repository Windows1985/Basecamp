"""
pipeline/staging.py — Three-class sleep stage classifier for Basecamp.

Honest capability statement
───────────────────────────
This classifier outputs three classes: WAKE, DEEP, LIGHT_REM.

What it cannot do (without EEG):
  • N1 and N2 are physiologically indistinguishable from radio/acoustic signals;
    they are both reported as LIGHT_REM.
  • REM is estimated probabilistically within the LIGHT_REM class via breathing
    irregularity and snoring presence (probable_rem flag).  This is an
    approximation, not direct classification.

Design: two-phase hybrid
  Phase 1 — Heuristic classifier (always active, always explainable):
    Physics-grounded thresholds derived from published CSI sleep literature and
    this sensor stack's measured capabilities.  Reliable from night 1.

  Phase 2 — ML personalisation (activates after STAGING_MIN_NIGHTS_ML labelled
    nights):
    Random Forest trained on heuristic labels from prior sessions.  It learns
    the user's personal deviations from generic thresholds.  The training labels
    are heuristic results, not EEG ground truth — documented intentionally.

Expected accuracy (population average, not personalised):
  WAKE      ~88 %   (clearest signal: elevated / irregular movement)
  DEEP      ~75 %   (most diagnostic: slow movement + slow regular breathing)
  LIGHT_REM ~65 %   (residual class)

This module outputs a sleep depth index, not clinical PSG staging.
"""

import logging
import logging.handlers
import os
import sys
import pickle
from datetime import datetime, timezone
from collections import Counter
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.db import get_connection, migrate_schema
from server.config import (
    MOVEMENT_THRESHOLD_LOW,
    MOVEMENT_THRESHOLD_HIGH,
    DEEP_BREATHING_MIN,
    DEEP_BREATHING_MAX,
    REGULARITY_THRESHOLD_HIGH,
    REGULARITY_THRESHOLD_LOW,
    DEEP_RUN_MIN_WINDOWS,
    STAGING_MIN_NIGHTS_ML,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
_handler = logging.handlers.RotatingFileHandler(
    "logs/staging.log", maxBytes=5 * 1024 * 1024, backupCount=3
)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_stream = logging.StreamHandler()
_stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log = logging.getLogger("staging")
log.setLevel(logging.INFO)
log.addHandler(_handler)
log.addHandler(_stream)

# ── Stage labels ───────────────────────────────────────────────────────────────
WAKE      = "WAKE"
DEEP      = "DEEP"
LIGHT_REM = "LIGHT_REM"

STAGE_ENCODE = {WAKE: 0, LIGHT_REM: 1, DEEP: 2}
AUDIO_ENCODE = {"silence": 0, "ambient": 1, "snore": 2}

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "staging_model.pkl")


# ── Data loading ───────────────────────────────────────────────────────────────

def _iso_to_unix(ts_str):
    ts_str = str(ts_str).replace(" ", "T")
    try:
        dt = datetime.fromisoformat(ts_str)
    except ValueError:
        dt = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _load_windows(session_id, db_path):
    """
    Load and align all sensor data for a session into 30-second window dicts.
    Returns [] if insufficient data.
    """
    conn = get_connection(db_path)
    try:
        session = conn.execute(
            "SELECT bed_entry, bed_exit FROM sleep_sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        if session is None or not session["bed_exit"]:
            return []

        bed_entry_str = session["bed_entry"]
        bed_exit_str  = session["bed_exit"]

        csi_rows = conn.execute(
            """
            SELECT timestamp,
                   AVG(breathing_rate) AS br,
                   AVG(movement_power) AS mp
            FROM csi_readings
            WHERE timestamp >= ? AND timestamp <= ?
            GROUP BY timestamp
            ORDER BY timestamp
            """,
            (bed_entry_str, bed_exit_str),
        ).fetchall()

        radar_rows = conn.execute(
            """
            SELECT timestamp, presence, still_distance, moving_distance
            FROM radar_events
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp
            """,
            (bed_entry_str, bed_exit_str),
        ).fetchall()

        audio_rows = conn.execute(
            """
            SELECT timestamp, tier
            FROM audio_chunks
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp
            """,
            (bed_entry_str, bed_exit_str),
        ).fetchall()
    finally:
        conn.close()

    if not csi_rows:
        return []

    # Audio lookup by unix timestamp rounded to nearest second
    audio_map = {}
    for r in audio_rows:
        audio_map[round(_iso_to_unix(r["timestamp"]))] = r["tier"] or "silence"

    # Radar: sorted list for forward-fill
    radar_list = sorted(
        [
            {
                "t":       _iso_to_unix(r["timestamp"]),
                "presence": bool(r["presence"]),
                "still":   float(r["still_distance"] or 0),
                "moving":  float(r["moving_distance"] or 0),
            }
            for r in radar_rows
        ],
        key=lambda x: x["t"],
    )

    cur_presence = True   # assume present at bed entry
    cur_still    = 0.5
    cur_moving   = 0.0
    radar_idx    = 0

    windows = []
    for row in csi_rows:
        w_unix = _iso_to_unix(row["timestamp"])
        w_end  = w_unix + 30.0

        # Forward-fill radar state up to this window's start
        while radar_idx < len(radar_list) and radar_list[radar_idx]["t"] <= w_unix:
            ev           = radar_list[radar_idx]
            cur_presence = ev["presence"]
            cur_still    = ev["still"]
            cur_moving   = ev["moving"]
            radar_idx   += 1

        # Audio: nearest chunk within ±30 s
        w_key = round(w_unix)
        tier  = "silence"
        for delta in (0, 30, -30, 15, -15, 20, -20, 45, -45):
            if w_key + delta in audio_map:
                tier = audio_map[w_key + delta]
                break

        br = float(row["br"]) if row["br"] is not None else float("nan")
        mp = float(row["mp"]) if row["mp"] is not None else 0.0
        if np.isnan(mp):
            mp = 0.0

        windows.append({
            "window_start": w_unix,
            "window_end":   w_end,
            "br":           br,
            "mp":           mp,
            "presence":     cur_presence,
            "still_dist":   cur_still,
            "moving_dist":  cur_moving,
            "audio_tier":   tier,
        })

    return windows


# ── Personal thresholds ────────────────────────────────────────────────────────

def load_thresholds(db_path):
    """
    Return the active personal_thresholds row as a SimpleNamespace, or None if
    no active row exists or the table is not yet created.
    """
    try:
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                """
                SELECT computed_at, movement_low, movement_high,
                       breathing_low, breathing_high, breathing_mean
                FROM personal_thresholds
                WHERE is_active = 1
                ORDER BY computed_at DESC
                LIMIT 1
                """
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return SimpleNamespace(
            computed_at=row["computed_at"],
            movement_low=float(row["movement_low"]),
            movement_high=float(row["movement_high"]),
            breathing_low=float(row["breathing_low"]),
            breathing_high=float(row["breathing_high"]),
            breathing_mean=float(row["breathing_mean"]),
        )
    except Exception:
        return None


# ── Heuristic ──────────────────────────────────────────────────────────────────

def _compute_regularity(br_array, idx, half_window=5):
    lo      = max(0, idx - half_window)
    hi      = min(len(br_array), idx + half_window + 1)
    segment = br_array[lo:hi]
    valid   = segment[~np.isnan(segment)]
    if len(valid) < 2:
        return 0.5
    return float(1.0 / (1.0 + np.var(valid)))


def _heuristic_single(w, regularity, thr=None):
    """Return (stage, probable_rem, deep_candidate).

    thr: SimpleNamespace from load_thresholds(), or None to use config constants.
    """
    mp = w["mp"]
    br = w["br"]

    mp_low  = thr.movement_low  if thr is not None else MOVEMENT_THRESHOLD_LOW
    mp_high = thr.movement_high if thr is not None else MOVEMENT_THRESHOLD_HIGH
    br_min  = thr.breathing_low  if thr is not None else DEEP_BREATHING_MIN
    br_max  = thr.breathing_high if thr is not None else DEEP_BREATHING_MAX

    # Step 1: presence check
    if not w["presence"] and mp < mp_low:
        return WAKE, False, False

    # Step 2: movement gate
    if mp > mp_high:
        return WAKE, False, False

    # Step 3: breathing validity
    if np.isnan(br) or br < 5.0 or br > 35.0:
        # Breathing unavailable — inconclusive for breathing-based rules.
        # Movement and audio tier rules still apply; do not force WAKE.
        probable_rem = w["audio_tier"] == "snore"
        return LIGHT_REM, probable_rem, False

    # Step 4: deep candidate (run enforcement applied by caller)
    deep_candidate = (
        mp < mp_low
        and br_min <= br <= br_max
        and regularity > REGULARITY_THRESHOLD_HIGH
        and w["audio_tier"] in ("silence", "ambient")
    )

    # Step 5: REM indicator
    probable_rem = (
        w["audio_tier"] == "snore"
        or (regularity < REGULARITY_THRESHOLD_LOW and mp < mp_low)
    )

    return LIGHT_REM, probable_rem, deep_candidate


def _apply_deep_run(raw_stages, deep_candidates):
    stages = list(raw_stages)
    n      = len(stages)
    i      = 0
    while i < n:
        if deep_candidates[i]:
            j = i
            while j < n and deep_candidates[j]:
                j += 1
            if (j - i) >= DEEP_RUN_MIN_WINDOWS:
                for k in range(i, j):
                    stages[k] = DEEP
            i = j
        else:
            i += 1
    return stages


def _apply_smoothing(stages, k=5):
    n      = len(stages)
    result = list(stages)
    half   = k // 2
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        result[i] = Counter(stages[lo:hi]).most_common(1)[0][0]
    return result


def _apply_min_duration(stages, probable_rem):
    stages       = list(stages)
    probable_rem = list(probable_rem)
    n            = len(stages)

    # Merge short WAKE bursts surrounded by sleep
    i = 0
    while i < n:
        if stages[i] == WAKE:
            j = i
            while j < n and stages[j] == WAKE:
                j += 1
            if (j - i) < 2:
                before = stages[i - 1] if i > 0 else None
                after  = stages[j]     if j < n else None
                if before in (DEEP, LIGHT_REM) and after in (DEEP, LIGHT_REM):
                    fill = after
                    for k in range(i, j):
                        stages[k] = fill
            i = j
        else:
            i += 1

    # Downgrade short DEEP bursts
    i = 0
    while i < n:
        if stages[i] == DEEP:
            j = i
            while j < n and stages[j] == DEEP:
                j += 1
            if (j - i) < DEEP_RUN_MIN_WINDOWS:
                for k in range(i, j):
                    stages[k]       = LIGHT_REM
                    probable_rem[k] = True
            i = j
        else:
            i += 1

    return stages, probable_rem


# ── ML layer ───────────────────────────────────────────────────────────────────

def _build_ml_features(windows, heuristic_stages, sleep_onset_idx):
    n          = len(windows)
    mp_arr     = np.array([w["mp"] for w in windows])
    br_arr     = np.array([w["br"] for w in windows], dtype=float)
    total_dur  = max(1.0, windows[-1]["window_end"] - windows[0]["window_start"])

    X          = []
    prev_stage = WAKE
    cnt        = 0

    for i, w in enumerate(windows):
        lo5 = max(0, i - 2)
        hi5 = min(n, i + 3)
        mp_roll  = mp_arr[lo5:hi5]
        br_roll  = br_arr[lo5:hi5]
        br_valid = br_roll[~np.isnan(br_roll)]

        reg          = _compute_regularity(br_arr, i)
        hour_of_nite = (w["window_start"] - windows[0]["window_start"]) / total_dur
        onset_hr     = max(0.0, i - sleep_onset_idx) * 30.0 / 3600.0

        hs = heuristic_stages[i]
        cnt = cnt + 1 if hs == prev_stage else 1

        feat = [
            w["mp"],
            float(w["br"]) if not np.isnan(w["br"]) else 14.0,
            reg,
            w["moving_dist"],
            float(AUDIO_ENCODE.get(w["audio_tier"], 1)),
            float(hour_of_nite),
            float(onset_hr),
            float(np.mean(mp_roll)),
            float(np.std(mp_roll)),
            float(np.mean(br_valid)) if len(br_valid) else 14.0,
            float(np.std(br_valid))  if len(br_valid) else 1.0,
            float(STAGE_ENCODE.get(prev_stage, 0)),
            float(cnt),
            float(w["presence"]),
            float(STAGE_ENCODE.get(hs, 0)),
        ]
        X.append(feat)
        prev_stage = hs

    return np.array(X)


def _session_count(db_path):
    conn = get_connection(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM sleep_sessions").fetchone()[0]
    finally:
        conn.close()


def _apply_ml_layer(windows, heuristic_stages, probable_rem, db_path):
    """Blend ML predictions with heuristic. Returns (final, ml_labels, ml_conf, source)."""
    n_sessions = _session_count(db_path)
    model_path = os.path.abspath(MODEL_PATH)

    null_return = (
        list(heuristic_stages),
        [None] * len(heuristic_stages),
        [None] * len(heuristic_stages),
        "heuristic",
    )

    if n_sessions < STAGING_MIN_NIGHTS_ML or not os.path.exists(model_path):
        return null_return

    try:
        with open(model_path, "rb") as f:
            model = pickle.load(f)
    except Exception:
        return null_return

    sleep_onset_idx = next(
        (i for i, s in enumerate(heuristic_stages) if s != WAKE), 0
    )

    X = _build_ml_features(windows, heuristic_stages, sleep_onset_idx)

    # If model was trained with a different number of features, fall back
    expected = getattr(model, "_basecamp_n_features", X.shape[1])
    if X.shape[1] != expected:
        # Trim or pad to match
        if X.shape[1] > expected:
            X = X[:, :expected]
        else:
            X = np.pad(X, ((0, 0), (0, expected - X.shape[1])))

    try:
        proba     = model.predict_proba(X)
        ml_preds  = model.predict(X)
    except Exception:
        return null_return

    label_map  = {0: WAKE, 1: LIGHT_REM, 2: DEEP}
    ml_labels  = [label_map.get(int(c), LIGHT_REM) for c in ml_preds]
    ml_conf    = [float(np.max(p)) for p in proba]

    heuristic_w = 0.40 if n_sessions >= 30 else 0.60
    ml_w        = 1.0 - heuristic_w
    STAGE_LIST  = [WAKE, LIGHT_REM, DEEP]

    final = []
    for i, hs in enumerate(heuristic_stages):
        h_vec        = np.zeros(3)
        h_vec[STAGE_ENCODE[hs]] = 1.0
        blended      = heuristic_w * h_vec + ml_w * proba[i]
        final.append(STAGE_LIST[int(np.argmax(blended))])

    return final, ml_labels, ml_conf, "ml_weighted"


# ── DB write ───────────────────────────────────────────────────────────────────

def _write_stages(session_id, windows, final_stages, heuristic_stages,
                  probable_rem, ml_stages, ml_conf, source, db_path):
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM sleep_stages WHERE session_id=?", (session_id,))
        rows = [
            (
                session_id,
                w["window_start"],
                w["window_end"],
                final_stages[i],
                int(probable_rem[i]),
                heuristic_stages[i],
                ml_stages[i] if ml_stages[i] else None,
                ml_conf[i]   if ml_conf[i]   is not None else None,
                source,
            )
            for i, w in enumerate(windows)
        ]
        conn.executemany(
            """
            INSERT INTO sleep_stages
              (session_id, window_start, window_end, stage, probable_rem,
               heuristic_stage, ml_stage, ml_confidence, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


# ── Metrics ────────────────────────────────────────────────────────────────────

def _derive_metrics(windows, final_stages, probable_rem):
    n          = len(windows)
    WIN_MIN    = 0.5   # 30 s per window

    onset_idx  = next((i for i, s in enumerate(final_stages) if s != WAKE), n)
    deep_cnt   = sum(1 for s in final_stages if s == DEEP)
    light_cnt  = sum(1 for s in final_stages if s == LIGHT_REM)
    wake_post  = sum(1 for i, s in enumerate(final_stages)
                     if s == WAKE and i > onset_idx)
    total_slp  = deep_cnt + light_cnt

    rem_cnt    = sum(1 for i, pr in enumerate(probable_rem)
                     if pr and final_stages[i] == LIGHT_REM)

    # Awakening count: distinct WAKE segments after sleep onset
    awakenings = 0
    in_wake    = False
    for i in range(onset_idx, n):
        if final_stages[i] == WAKE:
            if not in_wake:
                awakenings += 1
            in_wake = True
        else:
            in_wake = False

    # Longest DEEP run
    best_deep = cur = 0
    for s in final_stages:
        if s == DEEP:
            cur += 1
            best_deep = max(best_deep, cur)
        else:
            cur = 0

    return {
        "deep_sleep_minutes":          deep_cnt  * WIN_MIN,
        "light_rem_minutes":           light_cnt * WIN_MIN,
        "wake_minutes":                wake_post * WIN_MIN,
        "deep_sleep_proportion":       round(deep_cnt  / total_slp, 4) if total_slp else 0.0,
        "rem_proportion_estimate":     round(rem_cnt   / light_cnt, 4) if light_cnt else 0.0,
        "rem_proportion":              round(rem_cnt   / light_cnt, 4) if light_cnt else 0.0,
        "sleep_onset_window":          onset_idx,
        "sleep_onset_latency_minutes": round(onset_idx * WIN_MIN, 2),
        "awakening_count":             awakenings,
        "longest_deep_block_minutes":  best_deep * WIN_MIN,
        "sleep_efficiency":            round(total_slp / n, 4) if n else 0.0,
    }


# ── Public API ─────────────────────────────────────────────────────────────────

def classify_session(session_id, db_path):
    """
    Classify all 30-second windows of a sleep session.
    Writes to sleep_stages table.  Returns dict of derived metrics (empty on failure).
    """
    migrate_schema(db_path)

    thr = load_thresholds(db_path)
    if thr is not None:
        log.info(
            f"Using personal thresholds from {thr.computed_at}: "
            f"movement=[{thr.movement_low:.3f}, {thr.movement_high:.3f}]  "
            f"breathing=[{thr.breathing_low:.1f}, {thr.breathing_high:.1f}] BPM"
        )
    else:
        log.info("Using default thresholds (no personal calibration active)")

    windows = _load_windows(session_id, db_path)
    if not windows:
        return {}

    n      = len(windows)
    br_arr = np.array([w["br"] for w in windows], dtype=float)

    # Phase 1: heuristic
    raw_stages, deep_cands, prob_rem = [], [], []
    for i, w in enumerate(windows):
        reg  = _compute_regularity(br_arr, i)
        stg, pr, dc = _heuristic_single(w, reg, thr)
        raw_stages.append(stg)
        deep_cands.append(dc)
        prob_rem.append(pr)

    heuristic = _apply_deep_run(raw_stages, deep_cands)
    heuristic = _apply_smoothing(heuristic)
    heuristic, prob_rem = _apply_min_duration(heuristic, prob_rem)

    # Phase 2: ML blend
    final, ml_labels, ml_conf, source = _apply_ml_layer(
        windows, heuristic, prob_rem, db_path
    )

    # Restrict probable_rem to LIGHT_REM windows only
    for i in range(n):
        if final[i] != LIGHT_REM:
            prob_rem[i] = False

    _write_stages(session_id, windows, final, heuristic,
                  prob_rem, ml_labels, ml_conf, source, db_path)

    return _derive_metrics(windows, final, prob_rem)


def retrain_staging_model(db_path):
    """
    Train a Random Forest on historical heuristic stage labels.

    Training labels are heuristic results, not EEG ground truth.
    The model learns user-specific deviations from generic thresholds.
    Saves to data/staging_model.pkl.  Returns True on success.
    """
    try:
        from sklearn.ensemble import RandomForestClassifier
    except ImportError:
        return False

    # Find all sessions that have been staged
    conn = get_connection(db_path)
    try:
        sess_rows = conn.execute(
            "SELECT DISTINCT session_id FROM sleep_stages ORDER BY session_id"
        ).fetchall()
    finally:
        conn.close()

    if not sess_rows:
        return False

    X_all, y_all = [], []

    for sess_row in sess_rows:
        sid = sess_row["session_id"]

        # Reload raw window data for this session
        windows = _load_windows(sid, db_path)
        if not windows:
            continue

        # Load persisted heuristic labels
        conn2 = get_connection(db_path)
        try:
            label_rows = conn2.execute(
                "SELECT window_start, heuristic_stage FROM sleep_stages "
                "WHERE session_id=? ORDER BY window_start",
                (sid,),
            ).fetchall()
        finally:
            conn2.close()

        if not label_rows:
            continue

        # Align labels to windows by window_start (float proximity)
        label_map = {r["window_start"]: r["heuristic_stage"] for r in label_rows}
        aligned_w, aligned_s = [], []
        for w in windows:
            # Try exact match first, then nearest within 5 s
            label = label_map.get(w["window_start"])
            if label is None:
                nearest = min(label_map.keys(), key=lambda t: abs(t - w["window_start"]))
                if abs(nearest - w["window_start"]) < 5.0:
                    label = label_map[nearest]
            if label:
                aligned_w.append(w)
                aligned_s.append(label)

        if len(aligned_w) < 10:
            continue

        onset_idx = next((i for i, s in enumerate(aligned_s) if s != WAKE), 0)
        X_sess    = _build_ml_features(aligned_w, aligned_s, onset_idx)

        for i, feat_row in enumerate(X_sess):
            X_all.append(feat_row)
            y_all.append(STAGE_ENCODE.get(aligned_s[i], 1))

    if len(X_all) < 50:
        return False

    X_arr = np.array(X_all, dtype=float)
    y_arr = np.array(y_all)

    if len(np.unique(y_arr)) < 2:
        return False

    model = RandomForestClassifier(
        n_estimators=100, max_depth=8, random_state=42, class_weight="balanced"
    )
    model.fit(X_arr, y_arr)
    model._basecamp_n_features = X_arr.shape[1]

    model_path = os.path.abspath(MODEL_PATH)
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    with open(model_path, "wb") as f:
        pickle.dump(model, f)

    return True
