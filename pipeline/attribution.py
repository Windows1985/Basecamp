"""
Rule-based attribution that explains what drove the recovery score up or down.
Writes results to the shap_values table and returns human-readable factor lists.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.db import get_connection


def _fmt_time(iso_str):
    """Convert ISO timestamp to a human-readable time string like '3:40am'."""
    if iso_str is None:
        return "unknown time"
    try:
        dt = datetime.fromisoformat(iso_str)
        h = dt.hour % 12 or 12
        m = dt.minute
        am_pm = "am" if dt.hour < 12 else "pm"
        return f"{h}:{m:02d}{am_pm}"
    except Exception:
        return iso_str


def generate_attribution(session_id, features, scores, db_path):
    """
    Identify the top 3 positive and top 3 negative factors from features and scores.

    Writes them to shap_values (positive = positive shap_value, negative = negative).
    Returns (positives, negatives) as lists of plain-English strings.
    """
    factors = []  # list of (shap_value, label)

    # --- Architecture factors ---
    deep_pct = features["deep_sleep_proportion"] * 100
    deep_hours = features["deep_sleep_proportion"] * features["total_sleep_duration_hours"]
    deep_shap = (scores["_deep_score"] - 0.5) * 2  # map 0..1 → -1..+1 centred at 0.5
    if deep_pct >= 20:
        label = f"Deep sleep duration was strong at approximately {deep_hours:.1f}h ({deep_pct:.0f}% of night)"
    else:
        label = f"Deep sleep was low at {deep_pct:.0f}% of night (target: 20%)"
    factors.append((deep_shap, label))

    rem_pct = features["rem_proportion"] * 100
    rem_hours = features["rem_proportion"] * features["total_sleep_duration_hours"]
    rem_shap = (scores["_rem_score"] - 0.5) * 2
    if rem_pct >= 20:
        label = f"REM sleep was good at {rem_pct:.0f}% of night ({rem_hours:.1f}h)"
    else:
        label = f"REM sleep was low at {rem_pct:.0f}% of night (target: 25%)"
    factors.append((rem_shap, label))

    dur = features["total_sleep_duration_hours"]
    dur_shap = (scores["_dur_score"] - 0.5) * 2
    if dur >= 7.0:
        label = f"Total sleep duration was healthy at {dur:.1f}h"
    else:
        label = f"Total sleep duration was short at {dur:.1f}h (target: 7.5h)"
    factors.append((dur_shap, label))

    eff_pct = features["sleep_efficiency"] * 100
    eff_shap = (scores["_eff_score"] - 0.5) * 2
    if eff_pct >= 85:
        label = f"Sleep efficiency was excellent at {eff_pct:.0f}%"
    else:
        label = f"Sleep efficiency was low at {eff_pct:.0f}% (target: 85%)"
    factors.append((eff_shap, label))

    # --- Continuity factors ---
    aw = features["awakening_count"]
    aw_shap = (scores["_aw_penalty"] - 0.5) * 2
    if aw == 0:
        label = "No awakenings detected — uninterrupted sleep throughout the night"
    elif aw <= 2:
        label = f"{aw} brief awakening{'s' if aw > 1 else ''} detected"
    else:
        label = f"{aw} awakenings detected, disrupting sleep continuity"
    factors.append((aw_shap, label))

    onset = features["sleep_onset_latency_minutes"]
    onset_shap = (scores["_onset_score"] - 0.5) * 2
    if onset <= 15:
        label = f"Sleep onset was fast at {onset:.0f} minutes"
    elif onset <= 25:
        label = f"Sleep onset was normal at {onset:.0f} minutes"
    else:
        label = f"Sleep onset was slow at {onset:.0f} minutes (target: under 20 min)"
    factors.append((onset_shap, label))

    # --- Breathing factors ---
    apneas = features["apnea_count"]
    apnea_shap = (scores["_apnea_score"] - 0.5) * 2
    if apneas == 0:
        label = "No apnea events detected"
    elif apneas <= 3:
        label = f"{apneas} brief apnea event{'s' if apneas > 1 else ''} detected"
    else:
        label = f"{apneas} apnea events detected — significant breathing disruptions"
    factors.append((apnea_shap, label))

    snore_min = features["snoring_duration_minutes"]
    snore_shap = (scores["_snore_score"] - 0.5) * 2
    if snore_min < 5:
        label = "Minimal snoring detected"
    elif snore_min < 20:
        label = f"Moderate snoring for approximately {snore_min:.0f} minutes"
    else:
        label = f"Extended snoring for {snore_min:.0f} minutes across the night"
    factors.append((snore_shap, label))

    reg = features["breathing_regularity"]
    reg_shap = (min(reg * 1.5, 1.0) - 0.5) * 2
    if reg > 0.6:
        label = "Breathing was regular throughout the night"
    else:
        label = f"Breathing showed irregular patterns (regularity score: {reg:.2f})"
    factors.append((reg_shap, label))

    # --- Environment factors ---
    peak_co2 = features["peak_co2"]
    co2_time = _fmt_time(features.get("peak_co2_time"))
    co2_shap = (scores["_co2_score"] - 0.5) * 2
    if peak_co2 <= 800:
        label = f"CO2 stayed low, peaking at {peak_co2:.0f}ppm — excellent ventilation"
    elif peak_co2 <= 1000:
        label = f"CO2 was acceptable, peaking at {peak_co2:.0f}ppm at {co2_time}"
    elif peak_co2 <= 1500:
        label = f"CO2 peaked at {peak_co2:.0f}ppm at {co2_time}, above the 1000ppm threshold"
    else:
        label = f"CO2 peaked at {peak_co2:.0f}ppm at {co2_time}, well above the 1000ppm threshold"
    factors.append((co2_shap, label))

    temp = features["mean_temperature"]
    temp_shap = (scores["_temp_score"] - 0.5) * 2
    if 18.0 <= temp <= 20.5:
        label = f"Bedroom temperature was optimal at {temp:.1f}°C"
    elif temp < 18.0:
        label = f"Bedroom was slightly cool at {temp:.1f}°C (optimal: 18-20°C)"
    else:
        label = f"Bedroom was warm at {temp:.1f}°C (optimal: 18-20°C)"
    factors.append((temp_shap, label))

    voc = features["voc_peak"]
    voc_shap_raw = max(0.0, 1.0 - max(0.0, voc - 100) / 200)
    voc_shap = (voc_shap_raw - 0.5) * 2
    if voc < 100:
        label = f"Air quality was good (peak VOC index: {voc:.0f})"
    elif voc < 150:
        label = f"Air quality was moderate (peak VOC index: {voc:.0f})"
    else:
        label = f"Air quality was poor (peak VOC index: {voc:.0f})"
    factors.append((voc_shap, label))

    light_ev = features["light_intrusion_events"]
    light_shap_raw = max(0.0, 1.0 - light_ev * 0.2)
    light_shap = (light_shap_raw - 0.5) * 2
    if light_ev == 0:
        label = "No light intrusions detected — room stayed dark all night"
    elif light_ev == 1:
        label = "One light intrusion detected (possibly a phone check)"
    else:
        label = f"{light_ev} light intrusion events detected"
    factors.append((light_shap, label))

    # Sort into positives and negatives
    factors.sort(key=lambda x: x[0], reverse=True)
    positives = [label for shap, label in factors if shap > 0][:3]
    negatives = [label for shap, label in factors if shap <= 0][:3]

    # Persist to shap_values table
    now = datetime.now().isoformat()
    conn = get_connection(db_path)
    try:
        # Clear previous values for this session
        conn.execute("DELETE FROM shap_values WHERE session_id = ?", (session_id,))
        conn.executemany(
            "INSERT INTO shap_values (session_id, timestamp, feature_name, shap_value) "
            "VALUES (?, ?, ?, ?)",
            [(session_id, now, label[:120], float(shap)) for shap, label in factors],
        )
        conn.commit()
    finally:
        conn.close()

    return positives, negatives
