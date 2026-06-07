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
from server.config import ANOMALY_MIN_NIGHTS

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


def _detect_anomaly_mad(current_vec, all_vectors):
    """
    MAD z-score anomaly detection on total_score.
    Used for sessions < ANOMALY_MIN_NIGHTS — robust to small samples and
    outliers without requiring a trained model. Flags nights more than 3 MADs
    from the median as anomalous.
    """
    scores = np.array([v[0] for v in all_vectors])  # total_score is index 0
    current_score = current_vec[0]
    median = np.median(scores)
    mad = np.median(np.abs(scores - median))
    if mad < 1e-9:
        return False, "Tonight's sleep profile is within normal range."
    mad_z = abs(current_score - median) / (1.4826 * mad)  # 1.4826 normalises MAD to ~std
    if mad_z > 3.0:
        direction = "lower" if current_score < median else "higher"
        return True, (
            f"Anomalous night detected — recovery score ({current_score:.1f}) is "
            f"significantly {direction} than your median ({median:.1f}) "
            f"[MAD z={mad_z:.1f}]."
        )
    return False, "Tonight's sleep profile is within normal range."


def detect_anomaly(session_id, db_path):
    """
    Score the current session against the trained baseline.

    For < ANOMALY_MIN_NIGHTS sessions: uses MAD z-score (robust, no model needed).
    For >= ANOMALY_MIN_NIGHTS sessions: uses Isolation Forest for multivariate detection.

    Returns (is_anomaly: bool, description: str) or (None, None) if insufficient data.
    """
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

    all_vectors = _load_all_score_vectors(db_path)
    if len(all_vectors) < 7:
        return None, None

    current = _scores_to_vector(row)

    if len(all_vectors) < ANOMALY_MIN_NIGHTS:
        # Use MAD z-score for small sample sizes — Isolation Forest is unreliable
        # on fewer than ANOMALY_MIN_NIGHTS nights due to high variance in contamination estimate
        return _detect_anomaly_mad(current, all_vectors)

    # Isolation Forest for larger datasets
    model_path = os.path.abspath(MODEL_PATH)
    if not os.path.exists(model_path):
        return _detect_anomaly_mad(current, all_vectors)

    try:
        with open(model_path, "rb") as f:
            model = pickle.load(f)
    except Exception:
        return _detect_anomaly_mad(current, all_vectors)

    X_all = np.array(all_vectors)
    current_arr = np.array([current])
    prediction = model.predict(current_arr)[0]  # 1 = normal, -1 = anomaly
    is_anomaly = prediction == -1

    if not is_anomaly:
        return False, "Tonight's sleep profile is within normal range."

    means = X_all.mean(axis=0)
    stds = X_all.std(axis=0) + 1e-9
    z_scores = np.abs((current_arr[0] - means) / stds)

    component_names = [
        "overall recovery",
        "sleep architecture",
        "sleep continuity",
        "breathing quality",
        "environment",
    ]
    worst_idx = int(np.argmax(z_scores))
    worst_name = component_names[worst_idx]
    worst_val = current_arr[0][worst_idx]
    baseline_mean = means[worst_idx]

    direction = "lower" if worst_val < baseline_mean else "higher"
    description = (
        f"Anomalous night detected — {worst_name} score ({worst_val:.1f}) is "
        f"significantly {direction} than your baseline average ({baseline_mean:.1f})."
    )
    return True, description
