"""
Generates a formatted recovery report and sends it via ntfy.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.db import get_connection


def _build_recommendation(features, scores):
    """Return one actionable sentence based on the worst factor."""
    worst_score = min(
        scores["architecture_score"],
        scores["continuity_score"],
        scores["breathing_score"],
        scores["environment_score"],
    )

    if scores["environment_score"] == worst_score and features["peak_co2"] > 1200:
        return (
            f"CO2 peaked at {features['peak_co2']:.0f}ppm — try cracking a window "
            "before bed to improve overnight ventilation."
        )
    if scores["environment_score"] == worst_score and features["mean_temperature"] > 21:
        return (
            f"The bedroom reached {features['mean_temperature']:.1f}°C — lowering "
            "the temperature to 18-20°C can meaningfully improve deep sleep."
        )
    if scores["breathing_score"] == worst_score:
        if features["apnea_count"] >= 5:
            return (
                f"{features['apnea_count']} apnea events were detected — consider "
                "checking your sleep position or speaking to a doctor about sleep apnoea."
            )
        return (
            f"Snoring lasted {features['snoring_duration_minutes']:.0f} minutes — "
            "try sleeping on your side to reduce airway restriction."
        )
    if scores["continuity_score"] == worst_score:
        return (
            f"{features['awakening_count']} awakenings disrupted your sleep — "
            "reducing caffeine after 2pm and keeping a consistent bedtime may help."
        )
    if scores["architecture_score"] == worst_score:
        return (
            f"You slept {features['total_sleep_duration_hours']:.1f}h — "
            "an earlier bedtime of 30-60 minutes would help reach the 7.5h target."
        )
    return (
        "Maintain your current sleep habits — this was a strong night overall."
    )


def generate_report(session_id, db_path):
    """
    Read scores and attributions for a session, build a formatted report,
    send it via ntfy, and return the report string.
    """
    from server.config import NTFY_SERVER, NTFY_TOPIC

    conn = get_connection(db_path)
    try:
        score_row = conn.execute(
            """
            SELECT architecture_score, continuity_score, breathing_score,
                   environment_score, total_score
            FROM recovery_scores WHERE session_id = ?
            ORDER BY timestamp DESC LIMIT 1
            """,
            (session_id,),
        ).fetchone()

        shap_rows = conn.execute(
            "SELECT feature_name, shap_value FROM shap_values WHERE session_id = ? "
            "ORDER BY shap_value DESC",
            (session_id,),
        ).fetchall()

        session_row = conn.execute(
            "SELECT bed_entry, bed_exit, duration_hours FROM sleep_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()

    if score_row is None:
        return "No recovery score found for this session."

    total = score_row["total_score"]
    arch = score_row["architecture_score"]
    cont = score_row["continuity_score"]
    brth = score_row["breathing_score"]
    env = score_row["environment_score"]

    positives = [r["feature_name"] for r in shap_rows if r["shap_value"] > 0][:3]
    negatives = [r["feature_name"] for r in shap_rows if r["shap_value"] <= 0][:3]

    # Reconstruct features dict from scores for recommendation logic
    # (approximate — full features not stored in DB, but enough for recommendation)
    mock_features = {
        "peak_co2": 0,
        "mean_temperature": 19.0,
        "apnea_count": 0,
        "snoring_duration_minutes": 0,
        "awakening_count": 0,
        "total_sleep_duration_hours": session_row["duration_hours"] if session_row else 7.0,
    }

    # Try to load actual values from the database for a better recommendation
    conn2 = get_connection(db_path)
    try:
        bed_entry = session_row["bed_entry"] if session_row else None
        bed_exit = session_row["bed_exit"] if session_row else None
        if bed_entry and bed_exit:
            co2_row = conn2.execute(
                "SELECT MAX(co2_ppm) AS peak FROM sensor_readings "
                "WHERE timestamp >= ? AND timestamp <= ?",
                (bed_entry, bed_exit),
            ).fetchone()
            temp_row = conn2.execute(
                "SELECT AVG(temperature) AS avg_temp FROM sensor_readings "
                "WHERE timestamp >= ? AND timestamp <= ?",
                (bed_entry, bed_exit),
            ).fetchone()
            apnea_count = conn2.execute(
                "SELECT COUNT(*) AS cnt FROM csi_readings "
                "WHERE timestamp >= ? AND timestamp <= ? AND breathing_rate < 2",
                (bed_entry, bed_exit),
            ).fetchone()
            snore_count = conn2.execute(
                "SELECT COUNT(*) AS cnt FROM audio_chunks "
                "WHERE timestamp >= ? AND timestamp <= ? AND tier = 'snore'",
                (bed_entry, bed_exit),
            ).fetchone()

            if co2_row and co2_row["peak"]:
                mock_features["peak_co2"] = float(co2_row["peak"])
            if temp_row and temp_row["avg_temp"]:
                mock_features["mean_temperature"] = float(temp_row["avg_temp"])
            if apnea_count:
                mock_features["apnea_count"] = int(apnea_count["cnt"]) // 4  # 4 nodes
            if snore_count:
                mock_features["snoring_duration_minutes"] = int(snore_count["cnt"]) * 30 / 60
    finally:
        conn2.close()

    recommendation = _build_recommendation(mock_features, {
        "architecture_score": arch,
        "continuity_score": cont,
        "breathing_score": brth,
        "environment_score": env,
    })

    pos_lines = "\n".join(f"  - {p}" for p in positives) if positives else "  - (none)"
    neg_lines = "\n".join(f"  - {n}" for n in negatives) if negatives else "  - (none)"

    report = (
        f"Recovery: {total:.0f}/100\n"
        f"\n"
        f"Architecture: {arch:.0f}  Continuity: {cont:.0f}  "
        f"Breathing: {brth:.0f}  Environment: {env:.0f}\n"
        f"\n"
        f"Positive:\n{pos_lines}\n"
        f"\n"
        f"Negative:\n{neg_lines}\n"
        f"\n"
        f"Recommendation: {recommendation}"
    )

    # Send via ntfy (fire-and-forget; failures are non-fatal)
    _send_ntfy(report, total, NTFY_SERVER, NTFY_TOPIC)

    return report


def _send_ntfy(body, score, server, topic):
    try:
        import requests

        url = f"{server}/{topic}"
        priority = "high" if score < 50 else ("default" if score < 75 else "low")
        requests.post(
            url,
            data=body.encode("utf-8"),
            headers={
                "Title": f"Basecamp Recovery: {score:.0f}/100",
                "Priority": priority,
                "Tags": "zzz",
            },
            timeout=10,
        )
    except Exception:
        pass  # ntfy is best-effort; network may be unavailable in dev
