"""
Extracts sleep features from raw sensor data for a given session.
"""
import os
import sys
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.db import get_connection


def extract_features(session_id, db_path):
    """
    Load all sensor data for a session and return a feature dictionary.
    """
    conn = get_connection(db_path)
    try:
        session = conn.execute(
            "SELECT bed_entry, bed_exit, duration_hours FROM sleep_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if session is None:
            raise ValueError(f"Session {session_id} not found")

        bed_entry_str = session["bed_entry"]
        bed_exit_str = session["bed_exit"]
        duration_hours = float(session["duration_hours"])

        # Average CSI across all nodes per timestamp
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

        sensor_rows = conn.execute(
            """
            SELECT timestamp, temperature, humidity, co2_ppm, voc_index, light_lux
            FROM sensor_readings
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp
            """,
            (bed_entry_str, bed_exit_str),
        ).fetchall()

        audio_rows = conn.execute(
            """
            SELECT timestamp, tier, duration_seconds
            FROM audio_chunks
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp
            """,
            (bed_entry_str, bed_exit_str),
        ).fetchall()
    finally:
        conn.close()

    if not csi_rows:
        return _empty_features(session_id, duration_hours)

    br_raw = np.array([float(r["br"]) for r in csi_rows])
    mp_raw = np.array([float(r["mp"]) for r in csi_rows])

    # 5-sample moving average (2.5 min) for stage estimation
    W = 5
    br_smooth = np.convolve(br_raw, np.ones(W) / W, mode="valid")
    mp_smooth = np.convolve(mp_raw, np.ones(W) / W, mode="valid")
    n = len(br_smooth)

    # ---- Sleep onset latency --------------------------------------------
    # First run of >= 10 consecutive samples (5 min) below movement threshold
    LOW_MP = 0.12
    sleep_onset_idx = None
    for i in range(n - 10):
        if np.all(mp_smooth[i : i + 10] < LOW_MP):
            sleep_onset_idx = i
            break

    if sleep_onset_idx is None:
        sleep_onset_latency = 30.0
        sleep_onset_idx = min(20, n - 1)  # fallback for stage windowing
    else:
        sleep_onset_latency = sleep_onset_idx * 0.5  # samples × 0.5 min/sample

    # ---- Sleep stage estimation -----------------------------------------
    # Deep: low movement + low-end breathing (simulate.py: br ≈ 12.5-13.5)
    # REM:  low movement + higher / irregular breathing (simulate.py: br ≈ 15-16)
    deep_mask = (mp_smooth < 0.10) & (br_smooth >= 10.0) & (br_smooth < 13.8)

    # Local breathing variance (window ±5 samples)
    br_local_var = np.array([
        float(np.var(br_smooth[max(0, i - 5) : min(n, i + 6)]))
        for i in range(n)
    ])
    rem_mask = (mp_smooth < 0.08) & (~deep_mask) & (
        (br_smooth > 14.8) | (br_local_var > 2.0)
    )

    stages = np.full(n, "light", dtype=object)
    stages[deep_mask] = "deep"
    stages[rem_mask] = "rem"
    stages[: sleep_onset_idx] = "awake"

    deep_proportion = float(np.sum(stages == "deep") / n)
    rem_proportion = float(np.sum(stages == "rem") / n)

    # ---- Breathing metrics ----------------------------------------------
    valid_br = br_raw[br_raw > 2]  # exclude apnea zeroes
    mean_br = float(np.mean(valid_br)) if len(valid_br) > 0 else 14.0
    std_br = float(np.std(valid_br)) if len(valid_br) > 0 else 1.0

    br_variance = float(np.var(br_smooth))
    breathing_regularity = 1.0 / (1.0 + br_variance)

    # ---- Apnea count ----------------------------------------------------
    apnea_count = int(np.sum(br_raw < 2.0))

    # ---- Movement -------------------------------------------------------
    total_movement = float(np.sum(mp_raw) * 30)  # weighted by 30 s sample window

    # ---- Awakenings (movement spikes above threshold that resolve) ------
    AWAKE_TH = 0.45
    awakening_count = 0
    in_awakening = False
    for val in mp_smooth[sleep_onset_idx:]:
        if val > AWAKE_TH and not in_awakening:
            awakening_count += 1
            in_awakening = True
        elif val < AWAKE_TH * 0.6:
            in_awakening = False

    # ---- Snoring --------------------------------------------------------
    snore_samples = sum(1 for a in audio_rows if a["tier"] == "snore")
    snoring_duration_minutes = float(snore_samples * 30 / 60)

    # ---- Environmental --------------------------------------------------
    if sensor_rows:
        temps = np.array([float(r["temperature"]) for r in sensor_rows])
        humids = np.array([float(r["humidity"]) for r in sensor_rows])
        co2s = np.array([float(r["co2_ppm"]) for r in sensor_rows])
        vocs = np.array([float(r["voc_index"]) for r in sensor_rows])
        lights = np.array([float(r["light_lux"]) for r in sensor_rows])

        mean_temp = float(np.mean(temps))
        # Optimal 18-20 °C; penalty grows with deviation
        temp_deviation = abs(mean_temp - 19.0)
        temperature_optimality = float(max(0.0, 1.0 - temp_deviation / 4.0))

        mean_humidity = float(np.mean(humids))
        mean_co2 = float(np.mean(co2s))
        peak_co2 = float(np.max(co2s))
        peak_co2_idx = int(np.argmax(co2s))
        peak_co2_time = sensor_rows[peak_co2_idx]["timestamp"]

        voc_mean = float(np.mean(vocs))
        voc_peak = float(np.max(vocs))
        light_intrusion_events = int(np.sum(lights > 5.0))
    else:
        mean_temp = 20.0
        temperature_optimality = 1.0
        mean_humidity = 65.0
        mean_co2 = 700.0
        peak_co2 = 1000.0
        peak_co2_time = None
        voc_mean = 80.0
        voc_peak = 100.0
        light_intrusion_events = 0

    # ---- Sleep efficiency -----------------------------------------------
    sleep_samples = int(np.sum(stages != "awake"))
    actual_sleep_hours = sleep_samples * 30 / 3600
    sleep_efficiency = min(1.0, actual_sleep_hours / max(duration_hours, 0.1))

    return {
        "session_id": session_id,
        "mean_breathing_rate": mean_br,
        "std_breathing_rate": std_br,
        "breathing_regularity": breathing_regularity,
        "total_movement_score": total_movement,
        "awakening_count": awakening_count,
        "sleep_onset_latency_minutes": sleep_onset_latency,
        "deep_sleep_proportion": deep_proportion,
        "rem_proportion": rem_proportion,
        "apnea_count": apnea_count,
        "snoring_duration_minutes": snoring_duration_minutes,
        "mean_co2": mean_co2,
        "peak_co2": peak_co2,
        "peak_co2_time": peak_co2_time,
        "mean_temperature": mean_temp,
        "temperature_optimality": temperature_optimality,
        "mean_humidity": mean_humidity,
        "voc_mean": voc_mean,
        "voc_peak": voc_peak,
        "light_intrusion_events": light_intrusion_events,
        "total_sleep_duration_hours": duration_hours,
        "sleep_efficiency": sleep_efficiency,
    }


def _empty_features(session_id, duration_hours):
    return {
        "session_id": session_id,
        "mean_breathing_rate": 14.0,
        "std_breathing_rate": 1.0,
        "breathing_regularity": 0.5,
        "total_movement_score": 0.0,
        "awakening_count": 0,
        "sleep_onset_latency_minutes": 20.0,
        "deep_sleep_proportion": 0.0,
        "rem_proportion": 0.0,
        "apnea_count": 0,
        "snoring_duration_minutes": 0.0,
        "mean_co2": 700.0,
        "peak_co2": 1000.0,
        "peak_co2_time": None,
        "mean_temperature": 20.0,
        "temperature_optimality": 1.0,
        "mean_humidity": 65.0,
        "voc_mean": 80.0,
        "voc_peak": 100.0,
        "light_intrusion_events": 0,
        "total_sleep_duration_hours": duration_hours,
        "sleep_efficiency": 0.85,
    }
