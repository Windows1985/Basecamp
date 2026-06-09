"""
Calculates the four-component weighted recovery score and persists it.
"""
import os
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.db import get_connection


def _clamp(value, lo=0.0, hi=1.0):
    return max(lo, min(hi, value))


def calculate_recovery_score(features, session_id, db_path):
    """
    Compute the four-component weighted recovery score from extracted features.

    Writes scores to recovery_scores table and returns a dict with all scores
    plus the features that drove them.
    """
    # ---- Architecture (40 %) --------------------------------------------
    # Targets: deep 20 %, REM 25 %, efficiency 85 %, duration 7.5 h
    deep_score = _clamp(features["deep_sleep_proportion"] / 0.20)
    rem_score = _clamp(features["rem_proportion"] / 0.25)
    eff_score = _clamp(features["sleep_efficiency"] / 0.85)
    dur_score = _clamp(features["total_sleep_duration_hours"] / 7.5)

    architecture_score = (
        deep_score * 0.35
        + rem_score * 0.25
        + eff_score * 0.20
        + dur_score * 0.20
    )

    # ---- Continuity (25 %) ----------------------------------------------
    # Target: 0 awakenings, onset < 20 min
    aw_penalty = _clamp(1.0 - features["awakening_count"] * 0.12)
    onset = features["sleep_onset_latency_minutes"]
    onset_score = _clamp(1.0 - max(0.0, onset - 20.0) / 40.0)

    continuity_score = aw_penalty * 0.60 + onset_score * 0.40

    # ---- Breathing (20 %) -----------------------------------------------
    br_reg = features.get("breathing_regularity")
    reg_score = _clamp((br_reg if br_reg is not None else 0.5) * 1.5)
    apnea_score = _clamp(1.0 - features["apnea_count"] * 0.18)
    snore_score = _clamp(1.0 - features["snoring_duration_minutes"] / 60.0)

    breathing_score = reg_score * 0.30 + apnea_score * 0.45 + snore_score * 0.25

    # Low-confidence penalty: if >50 % of windows were low confidence, discount
    low_conf_pct = float(features.get("csi_low_confidence_pct") or 0.0)
    if low_conf_pct > 50.0:
        penalty = (low_conf_pct - 50.0) / 100.0
        breathing_score *= (1.0 - penalty)

    # ---- Environment (15 %) ---------------------------------------------
    peak_co2 = features["peak_co2"]
    if peak_co2 <= 800:
        co2_score = 1.0
    elif peak_co2 <= 1000:
        co2_score = 1.0 - (peak_co2 - 800) / 200 * 0.3
    elif peak_co2 <= 1500:
        co2_score = 0.7 - (peak_co2 - 1000) / 500 * 0.4
    else:
        co2_score = max(0.0, 0.3 - (peak_co2 - 1500) / 1000 * 0.3)

    temp_score = _clamp(features["temperature_optimality"])
    voc_score = _clamp(1.0 - max(0.0, features["voc_peak"] - 100) / 200)
    light_score = _clamp(1.0 - features["light_intrusion_events"] * 0.2)

    environment_score = (
        co2_score * 0.40
        + temp_score * 0.30
        + voc_score * 0.15
        + light_score * 0.15
    )

    # ---- Weighted total -------------------------------------------------
    from server.config import RECOVERY_WEIGHTS
    total_score = (
        architecture_score * RECOVERY_WEIGHTS["architecture"]
        + continuity_score * RECOVERY_WEIGHTS["continuity"]
        + breathing_score * RECOVERY_WEIGHTS["breathing"]
        + environment_score * RECOVERY_WEIGHTS["environment"]
    )
    total_score_100 = round(_clamp(total_score) * 100, 1)

    # ---- Persist --------------------------------------------------------
    now = datetime.now().isoformat()
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO recovery_scores
              (session_id, timestamp, architecture_score, continuity_score,
               breathing_score, environment_score, total_score, low_confidence_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                now,
                round(architecture_score * 100, 1),
                round(continuity_score * 100, 1),
                round(breathing_score * 100, 1),
                round(environment_score * 100, 1),
                total_score_100,
                low_conf_pct if low_conf_pct > 0 else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "session_id": session_id,
        "architecture_score": round(architecture_score * 100, 1),
        "continuity_score": round(continuity_score * 100, 1),
        "breathing_score": round(breathing_score * 100, 1),
        "environment_score": round(environment_score * 100, 1),
        "total_score": total_score_100,
        "low_confidence_pct": low_conf_pct if low_conf_pct > 0 else None,
        # sub-scores used in attribution
        "_deep_score": deep_score,
        "_rem_score": rem_score,
        "_eff_score": eff_score,
        "_dur_score": dur_score,
        "_aw_penalty": aw_penalty,
        "_onset_score": onset_score,
        "_apnea_score": apnea_score,
        "_snore_score": snore_score,
        "_co2_score": co2_score,
        "_temp_score": temp_score,
    }
