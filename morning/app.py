"""
Morning log Flask web app.
Serves the subjective rating form and exposes JSON endpoints for the dashboard.
"""
import os
import sys
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, render_template

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.config import DB_PATH
from server.db import init_db, get_connection, get_latest_session_id

app = Flask(__name__, template_folder="templates")

_DB_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", DB_PATH)
)


def _ensure_db():
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    init_db(_DB_PATH)


@app.route("/")
def index():
    _ensure_db()
    return render_template("log.html")


@app.route("/log", methods=["POST"])
def log():
    _ensure_db()
    data = request.get_json(silent=True) or request.form

    try:
        recovery = int(data.get("recovery", 5))
        energy = int(data.get("energy", 5))
        clarity = int(data.get("clarity", 5))
        mood = int(data.get("mood", 5))
        notes = str(data.get("notes", "")).strip()

        # Clamp 1-10
        recovery = max(1, min(10, recovery))
        energy = max(1, min(10, energy))
        clarity = max(1, min(10, clarity))
        mood = max(1, min(10, mood))

        session_id = get_latest_session_id(_DB_PATH)
        now = datetime.now().isoformat()

        conn = get_connection(_DB_PATH)
        try:
            conn.execute(
                """
                INSERT INTO morning_log
                  (timestamp, session_id, recovery, energy, clarity, mood, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (now, session_id, recovery, energy, clarity, mood, notes or None),
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify({"status": "ok", "session_id": session_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/history")
def history():
    _ensure_db()
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    conn = get_connection(_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT ml.id, ml.timestamp, ml.session_id,
                   ml.recovery, ml.energy, ml.clarity, ml.mood, ml.notes,
                   rs.total_score, rs.architecture_score, rs.continuity_score,
                   rs.breathing_score, rs.environment_score,
                   ss.bed_entry, ss.bed_exit, ss.duration_hours
            FROM morning_log ml
            LEFT JOIN recovery_scores rs ON rs.session_id = ml.session_id
            LEFT JOIN sleep_sessions ss ON ss.id = ml.session_id
            WHERE ml.timestamp >= ?
            ORDER BY ml.timestamp DESC
            """,
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    return jsonify([dict(r) for r in rows])


@app.route("/latest")
def latest():
    _ensure_db()
    conn = get_connection(_DB_PATH)
    try:
        score_row = conn.execute(
            """
            SELECT rs.*, ss.bed_entry, ss.bed_exit, ss.duration_hours
            FROM recovery_scores rs
            JOIN sleep_sessions ss ON ss.id = rs.session_id
            ORDER BY rs.timestamp DESC LIMIT 1
            """
        ).fetchone()

        if score_row is None:
            return jsonify({"error": "No scores available yet"}), 404

        session_id = score_row["session_id"]

        shap_rows = conn.execute(
            "SELECT feature_name, shap_value FROM shap_values "
            "WHERE session_id = ? ORDER BY shap_value DESC",
            (session_id,),
        ).fetchall()

        sensor_rows = conn.execute(
            """
            SELECT timestamp, temperature, humidity, co2_ppm, voc_index, light_lux
            FROM sensor_readings
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp
            """,
            (score_row["bed_entry"], score_row["bed_exit"]),
        ).fetchall()

        csi_rows = conn.execute(
            """
            SELECT timestamp, AVG(breathing_rate) AS br, AVG(movement_power) AS mp
            FROM csi_readings
            WHERE timestamp >= ? AND timestamp <= ?
            GROUP BY timestamp ORDER BY timestamp
            """,
            (score_row["bed_entry"], score_row["bed_exit"]),
        ).fetchall()
    finally:
        conn.close()

    positives = [r["feature_name"] for r in shap_rows if r["shap_value"] > 0][:3]
    negatives = [r["feature_name"] for r in shap_rows if r["shap_value"] <= 0][:3]

    return jsonify({
        "session_id": session_id,
        "total_score": score_row["total_score"],
        "architecture_score": score_row["architecture_score"],
        "continuity_score": score_row["continuity_score"],
        "breathing_score": score_row["breathing_score"],
        "environment_score": score_row["environment_score"],
        "bed_entry": score_row["bed_entry"],
        "bed_exit": score_row["bed_exit"],
        "duration_hours": score_row["duration_hours"],
        "positives": positives,
        "negatives": negatives,
        "sensors": [dict(r) for r in sensor_rows],
        "csi": [dict(r) for r in csi_rows],
    })


if __name__ == "__main__":
    _ensure_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
