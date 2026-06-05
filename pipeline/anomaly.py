"""
Isolation Forest anomaly detector for sleep sessions.
Requires >= 7 historical sessions to train.
"""
import os
import sys
import pickle

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.db import get_connection

MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "anomaly_model.pkl"
)

FEATURE_KEYS = [
    "total_sleep_duration_hours",
    "deep_sleep_proportion",
    "rem_proportion",
    "sleep_efficiency",
    "awakening_count",
    "apnea_count",
    "snoring_duration_minutes",
    "peak_co2",
    "mean_temperature",
    "breathing_regularity",
]


def _scores_to_vector(row):
    return [
        float(row["total_score"] or 0),
        float(row["architecture_score"] or 0),
        float(row["continuity_score"] or 0),
        float(row["breathing_score"] or 0),
        float(row["environment_score"] or 0),
    ]


def _load_all_score_vectors(db_path):
    """Return a 2-D list of score vectors for all sessions that have scores."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT total_score, architecture_score, continuity_score,
                   breathing_score, environment_score
            FROM recovery_scores
            ORDER BY timestamp ASC
            """
        ).fetchall()
    finally:
        conn.close()
    return [_scores_to_vector(r) for r in rows]


def train_baseline(db_path):
    """
    Load all historical sessions and train an Isolation Forest.
    Saves model to data/anomaly_model.pkl.
    Returns True on success, False if insufficient data.
    """
    vectors = _load_all_score_vectors(db_path)
    if len(vectors) < 7:
        return False

    from sklearn.ensemble import IsolationForest

    X = np.array(vectors)
    model = IsolationForest(n_estimators=100, contamination=0.1, random_state=42)
    model.fit(X)

    model_path = os.path.abspath(MODEL_PATH)
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    with open(model_path, "wb") as f:
        pickle.dump(model, f)

    return True


def detect_anomaly(session_id, db_path):
    """
    Score the current session against the trained baseline.

    Returns (is_anomaly: bool, description: str) or (None, None) if model
    is unavailable or there is insufficient data.
    """
    model_path = os.path.abspath(MODEL_PATH)
    if not os.path.exists(model_path):
        return None, None

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT total_score, architecture_score, continuity_score,
                   breathing_score, environment_score
            FROM recovery_scores
            WHERE session_id = ?
            ORDER BY timestamp DESC LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None, None

    try:
        with open(model_path, "rb") as f:
            model = pickle.load(f)
    except Exception:
        return None, None

    all_vectors = _load_all_score_vectors(db_path)
    if len(all_vectors) < 7:
        return None, None

    X_all = np.array(all_vectors)
    current = np.array([_scores_to_vector(row)])

    prediction = model.predict(current)[0]  # 1 = normal, -1 = anomaly
    is_anomaly = prediction == -1

    if not is_anomaly:
        return False, "Tonight's sleep profile is within normal range."

    # Identify which component deviates most
    means = X_all.mean(axis=0)
    stds = X_all.std(axis=0) + 1e-9
    z_scores = np.abs((current[0] - means) / stds)

    component_names = [
        "overall recovery",
        "sleep architecture",
        "sleep continuity",
        "breathing quality",
        "environment",
    ]
    worst_idx = int(np.argmax(z_scores))
    worst_name = component_names[worst_idx]
    worst_val = current[0][worst_idx]
    baseline_mean = means[worst_idx]

    direction = "lower" if worst_val < baseline_mean else "higher"
    description = (
        f"Anomalous night detected — {worst_name} score ({worst_val:.1f}) is "
        f"significantly {direction} than your baseline average ({baseline_mean:.1f})."
    )
    return True, description
