"""
pipeline/trends.py — Trend-aware analysis over the last 7–14 nights.

For each numeric feature available in the database history, computes linear
regression slopes, z-scores, and persistence indicators.  Runs as a second
attribution pass after per-night SHAP analysis.
"""
import logging
import logging.handlers
import os
import sys
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.db import get_connection, migrate_schema

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
_handler = logging.handlers.RotatingFileHandler(
    "logs/trends.log", maxBytes=5 * 1024 * 1024, backupCount=3
)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_stream = logging.StreamHandler()
_stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log = logging.getLogger("trends")
log.setLevel(logging.INFO)
log.addHandler(_handler)
log.addHandler(_stream)

# ---------------------------------------------------------------------------
# Per-feature configuration
# ---------------------------------------------------------------------------

# Slope threshold (units/night) above which a trend is considered significant.
# Default for unlisted features: 10 % of 14-night standard deviation.
SLOPE_THRESHOLDS = {
    "total_score":                2.0,
    "architecture_score":         2.0,
    "continuity_score":           2.0,
    "breathing_score":            2.0,
    "environment_score":          2.0,
    "peak_co2":                   20.0,
    "mean_temperature":           0.3,
    "deep_sleep_proportion":      0.007,   # ≈ 3 min per 7-hour night
    "total_sleep_duration_hours": 0.1,
    "awakening_count":            0.3,
    "sleep_onset_latency_minutes": 2.0,
    "apnea_count":                0.3,
    "snoring_duration_minutes":   2.0,
    "breathing_regularity":       0.02,
    "voc_peak":                   5.0,
    "light_intrusion_events":     0.3,
    "sleep_efficiency":           0.02,
    "mean_co2":                   15.0,
}

# True → a higher value is better sleep (slope > 0 = improving).
_HIGHER_IS_BETTER = {
    "total_score":                True,
    "architecture_score":         True,
    "continuity_score":           True,
    "breathing_score":            True,
    "environment_score":          True,
    "total_sleep_duration_hours": True,
    "deep_sleep_proportion":      True,
    "rem_proportion":             True,
    "sleep_efficiency":           True,
    "breathing_regularity":       True,
    "peak_co2":                   False,
    "mean_co2":                   False,
    "mean_temperature":           False,
    "awakening_count":            False,
    "sleep_onset_latency_minutes": False,
    "apnea_count":                False,
    "snoring_duration_minutes":   False,
    "voc_peak":                   False,
    "voc_mean":                   False,
    "light_intrusion_events":     False,
    "total_movement_score":       False,
}

# Human-readable feature labels for display.
_FEATURE_LABELS = {
    "total_score":                "recovery score",
    "architecture_score":         "architecture score",
    "continuity_score":           "continuity score",
    "breathing_score":            "breathing score",
    "environment_score":          "environment score",
    "peak_co2":                   "room CO2",
    "mean_co2":                   "room CO2 (mean)",
    "mean_temperature":           "room temperature",
    "deep_sleep_proportion":      "deep sleep",
    "total_sleep_duration_hours": "sleep duration",
    "awakening_count":            "awakenings",
    "sleep_onset_latency_minutes": "sleep onset",
    "apnea_count":                "apnea events",
    "snoring_duration_minutes":   "snoring",
    "breathing_regularity":       "breathing regularity",
    "sleep_efficiency":           "sleep efficiency",
    "voc_peak":                   "air quality (VOC)",
    "light_intrusion_events":     "light intrusions",
}

# Units appended to the slope magnitude in descriptions.
_FEATURE_UNITS = {
    "total_score":                "pts",
    "architecture_score":         "pts",
    "continuity_score":           "pts",
    "breathing_score":            "pts",
    "environment_score":          "pts",
    "peak_co2":                   "ppm",
    "mean_co2":                   "ppm",
    "mean_temperature":           "°C",
    "total_sleep_duration_hours": "h",
    "awakening_count":            "",
    "sleep_onset_latency_minutes": "min",
    "apnea_count":                "",
    "snoring_duration_minutes":   "min",
    "sleep_efficiency":           "%",
    "light_intrusion_events":     "",
}

# Keyword used to match shap_values.feature_name (case-insensitive LIKE).
_FEATURE_SHAP_KEYWORD = {
    "deep_sleep_proportion":      "deep sleep",
    "total_sleep_duration_hours": "total sleep",
    "peak_co2":                   "co2",
    "mean_co2":                   "co2",
    "mean_temperature":           "temperature",
    "awakening_count":            "awakening",
    "sleep_onset_latency_minutes": "sleep onset",
    "apnea_count":                "apnea",
    "snoring_duration_minutes":   "snoring",
    "breathing_regularity":       "breathing",
    "sleep_efficiency":           "sleep efficiency",
    "voc_peak":                   "voc",
    "light_intrusion_events":     "light",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_direction(feature_name: str, slope_7: float) -> str:
    """Return 'improving' or 'declining' based on slope sign and goal direction."""
    higher_better = _HIGHER_IS_BETTER.get(feature_name, True)
    if higher_better:
        return "improving" if slope_7 > 0 else "declining"
    else:
        return "improving" if slope_7 < 0 else "declining"


def _magnitude_description(feature_name: str, slope_7: float, nights: int) -> str:
    """Build a plain-English description like 'declining ~4 min/night over 7 nights'."""
    label    = _FEATURE_LABELS.get(feature_name, feature_name.replace("_", " "))
    unit     = _FEATURE_UNITS.get(feature_name, "")
    direction = _get_direction(feature_name, slope_7)
    abs_s    = abs(slope_7)

    # deep_sleep_proportion: convert proportion → minutes (assume 7h night)
    if feature_name == "deep_sleep_proportion":
        mins = abs_s * 420
        return f"{label} {direction} ~{mins:.0f} min/night over {nights} nights"

    # sleep_efficiency: proportion → percentage
    if feature_name == "sleep_efficiency":
        pct = abs_s * 100
        return f"{label} {direction} ~{pct:.1f}%/night over {nights} nights"

    # Numeric formatting
    if abs_s >= 10:
        val_str = f"~{abs_s:.0f}"
    elif abs_s >= 1:
        val_str = f"~{abs_s:.1f}"
    else:
        val_str = f"~{abs_s:.2f}"

    unit_suffix = f" {unit.strip()}/night" if unit else "/night"
    return f"{label} {direction} {val_str}{unit_suffix} over {nights} nights"


def build_factor_display(feature_name: str, slope_7: float, nights: int = 7) -> dict:
    """Public helper: build display dict from raw feature_trends row."""
    return {
        "feature_name":         feature_name,
        "direction":            _get_direction(feature_name, slope_7),
        "magnitude_description": _magnitude_description(feature_name, slope_7, nights),
        "nights_observed":      nights,
    }


def _get_shap_direction(feature_name: str, session_ids: list, db_path: str):
    """
    Return 'positive', 'negative', or None based on the majority sign of SHAP
    values for this feature across the given sessions (best-effort keyword match).
    """
    keyword = _FEATURE_SHAP_KEYWORD.get(feature_name)
    if not keyword or not session_ids:
        return None

    signs = []
    for sid in session_ids:
        conn = get_connection(db_path)
        try:
            rows = conn.execute(
                "SELECT shap_value FROM shap_values "
                "WHERE session_id = ? AND LOWER(feature_name) LIKE ?",
                (sid, f"%{keyword.lower()}%"),
            ).fetchall()
        finally:
            conn.close()
        if rows:
            avg = sum(r["shap_value"] for r in rows) / len(rows)
            signs.append(1 if avg > 0 else -1)

    if len(signs) < 4:
        return None
    pos = sum(1 for s in signs if s > 0)
    if pos / len(signs) > 0.6:
        return "positive"
    if (len(signs) - pos) / len(signs) > 0.6:
        return "negative"
    return None


def _load_session_history(db_path: str, current_session_id: int, max_sessions: int = 14):
    """
    Build per-session feature-like dicts from recovery_scores, sleep_sessions,
    sensor_readings, and sleep_stages.  Excludes current_session_id.
    Returns a list ordered oldest → newest.
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT ss.id, ss.bed_entry, ss.bed_exit, ss.duration_hours,
                   rs.total_score, rs.architecture_score, rs.continuity_score,
                   rs.breathing_score, rs.environment_score
            FROM sleep_sessions ss
            JOIN recovery_scores rs ON rs.session_id = ss.id
            WHERE ss.bed_exit IS NOT NULL AND ss.id != ?
            GROUP BY ss.id
            HAVING rs.timestamp = MAX(rs.timestamp)
            ORDER BY ss.bed_entry DESC
            LIMIT ?
            """,
            (current_session_id, max_sessions),
        ).fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        feat = {
            "session_id":                 row["id"],
            "bed_entry":                  row["bed_entry"],
            "bed_exit":                   row["bed_exit"],
            "total_sleep_duration_hours": float(row["duration_hours"] or 0),
            "total_score":                float(row["total_score"] or 0),
            "architecture_score":         float(row["architecture_score"] or 0),
            "continuity_score":           float(row["continuity_score"] or 0),
            "breathing_score":            float(row["breathing_score"] or 0),
            "environment_score":          float(row["environment_score"] or 0),
        }

        conn = get_connection(db_path)
        try:
            s = conn.execute(
                "SELECT MAX(co2_ppm) AS peak_co2, AVG(temperature) AS mean_temp "
                "FROM sensor_readings WHERE timestamp >= ? AND timestamp <= ?",
                (row["bed_entry"], row["bed_exit"]),
            ).fetchone()
        finally:
            conn.close()
        if s and s["peak_co2"] is not None:
            feat["peak_co2"] = float(s["peak_co2"])
        if s and s["mean_temp"] is not None:
            feat["mean_temperature"] = float(s["mean_temp"])

        conn = get_connection(db_path)
        try:
            st = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN stage='DEEP' THEN 1 ELSE 0 END) AS deep_cnt "
                "FROM sleep_stages WHERE session_id = ?",
                (row["id"],),
            ).fetchone()
        finally:
            conn.close()
        if st and st["total"] and st["total"] > 0:
            feat["deep_sleep_proportion"] = float(st["deep_cnt"] or 0) / float(st["total"])

        result.append(feat)

    return list(reversed(result))  # oldest first for regression


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_trends(session_id: int, features_today: dict, db_path: str,
                   min_sessions: int = 7):
    """
    Compute trend metrics for each numeric feature available in features_today.

    Requires at least min_sessions of historical data with recovery scores.
    Writes results to feature_trends (replacing any existing rows for this session).

    Returns a list of persistent-factor dicts sorted by abs(slope_7) descending,
    or None if fewer than min_sessions historical sessions exist.
    """
    migrate_schema(db_path)

    history = _load_session_history(db_path, session_id, max_sessions=14)

    if len(history) < min_sessions:
        log.info(
            f"Trend analysis skipped for session {session_id}: "
            f"only {len(history)} historical sessions (need {min_sessions})"
        )
        return None

    # Session IDs for SHAP direction lookup (last 7)
    recent_session_ids = [h["session_id"] for h in history[-7:]]

    computed_at   = datetime.now().isoformat()
    trend_rows    = []
    persistent    = []

    for feature_name, today_value in features_today.items():
        if not isinstance(today_value, (int, float)):
            continue

        # Gather historical values for this feature (may be None if not stored)
        hist_vals = [h.get(feature_name) for h in history]
        valid_vals = [v for v in hist_vals if v is not None]

        if len(valid_vals) < min_sessions:
            continue

        # Use the last N non-None values for regression windows
        recent_7  = [v for v in hist_vals if v is not None][-7:]
        recent_14 = valid_vals  # up to 14

        if len(recent_7) < 3:
            continue

        x7  = np.arange(len(recent_7),  dtype=float)
        x14 = np.arange(len(recent_14), dtype=float)

        slope_7  = float(np.polyfit(x7,  recent_7,  1)[0])
        slope_14 = float(np.polyfit(x14, recent_14, 1)[0])
        mean_7   = float(np.mean(recent_7))

        # z-score: tonight vs 14-night mean/std (clamped ±4)
        mean_14 = float(np.mean(recent_14))
        std_14  = float(np.std(recent_14))
        if std_14 == 0.0:
            z_score = None
        else:
            z_score = float(np.clip((today_value - mean_14) / std_14, -4.0, 4.0))

        shap_direction = _get_shap_direction(feature_name, recent_session_ids, db_path)

        # Significance threshold
        threshold = SLOPE_THRESHOLDS.get(feature_name)
        if threshold is None:
            threshold = (std_14 * 0.10) if std_14 > 0 else None

        # Slope/SHAP direction agreement check
        if shap_direction is not None:
            slope_sign_positive = slope_7 > 0
            higher_better       = _HIGHER_IS_BETTER.get(feature_name, True)
            slope_improves      = (slope_sign_positive == higher_better)
            shap_agrees         = (shap_direction == "positive") == slope_improves
        else:
            shap_agrees = True  # no SHAP data → skip check

        is_persistent = bool(
            threshold is not None
            and abs(slope_7) > threshold
            and z_score is not None
            and abs(z_score) > 1.5
            and shap_agrees
        )

        trend_rows.append({
            "feature_name":  feature_name,
            "slope_7":       slope_7,
            "slope_14":      slope_14,
            "mean_7":        mean_7,
            "z_score":       z_score,
            "shap_direction": shap_direction,
            "is_persistent": int(is_persistent),
        })

        if is_persistent:
            d = build_factor_display(feature_name, slope_7, nights=7)
            d["slope_7"] = slope_7
            persistent.append(d)

    if trend_rows:
        conn = get_connection(db_path)
        try:
            conn.execute(
                "DELETE FROM feature_trends WHERE session_id = ?", (session_id,)
            )
            conn.executemany(
                """
                INSERT INTO feature_trends
                  (computed_at, session_id, feature_name, slope_7, slope_14, mean_7,
                   z_score, shap_direction, is_persistent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        computed_at, session_id,
                        t["feature_name"], t["slope_7"], t["slope_14"], t["mean_7"],
                        t["z_score"], t["shap_direction"], t["is_persistent"],
                    )
                    for t in trend_rows
                ],
            )
            conn.commit()
        finally:
            conn.close()

        log.info(
            f"Trend analysis session {session_id}: "
            f"{len(trend_rows)} features, {len(persistent)} persistent"
        )

    persistent.sort(key=lambda f: abs(f["slope_7"]), reverse=True)
    return persistent
