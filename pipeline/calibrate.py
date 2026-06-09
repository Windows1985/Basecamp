"""
pipeline/calibrate.py — Compute adaptive personal thresholds from historical CSI data.

After 7+ nights of real data, replaces the hardcoded movement/breathing constants
from server/config.py with values derived from the user's own signal distribution.
"""
import logging
import logging.handlers
import os
import sys
from datetime import datetime
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.db import get_connection, migrate_schema

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
_handler = logging.handlers.RotatingFileHandler(
    "logs/calibrate.log", maxBytes=5 * 1024 * 1024, backupCount=3
)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_stream = logging.StreamHandler()
_stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log = logging.getLogger("calibrate")
log.setLevel(logging.INFO)
log.addHandler(_handler)
log.addHandler(_stream)

# Physiologically valid breathing rate range (BPM) for clamping
_BR_PHYS_MIN = 8.0
_BR_PHYS_MAX = 25.0


def compute_thresholds(db_path, min_nights=7):
    """
    Derive personal movement and breathing thresholds from the last 30 nights of
    CSI readings.

    Returns a SimpleNamespace with computed fields on success, or None if fewer
    than min_nights nights of CSI data are available.  On success, deactivates any
    existing active row and writes a new is_active=1 row to personal_thresholds.
    """
    migrate_schema(db_path)

    conn = get_connection(db_path)
    try:
        session_rows = conn.execute(
            """
            SELECT id, bed_entry, bed_exit
            FROM sleep_sessions
            WHERE bed_exit IS NOT NULL
            ORDER BY bed_entry DESC
            LIMIT 30
            """
        ).fetchall()
    finally:
        conn.close()

    if not session_rows:
        return None

    all_mp = []
    all_br = []
    nights_with_data = 0

    for sess in session_rows:
        conn = get_connection(db_path)
        try:
            csi_rows = conn.execute(
                """
                SELECT AVG(movement_power) AS mp, AVG(breathing_rate) AS br
                FROM csi_readings
                WHERE timestamp >= ? AND timestamp <= ?
                GROUP BY timestamp
                ORDER BY timestamp
                """,
                (sess["bed_entry"], sess["bed_exit"]),
            ).fetchall()
        finally:
            conn.close()

        if not csi_rows:
            continue

        nights_with_data += 1
        for row in csi_rows:
            if row["mp"] is not None:
                all_mp.append(float(row["mp"]))
            if row["br"] is not None and float(row["br"]) > 2.0:
                all_br.append(float(row["br"]))

    if nights_with_data < min_nights:
        log.info(
            f"Calibration skipped: {nights_with_data} nights with CSI data "
            f"(need {min_nights})"
        )
        return None

    mp_arr = np.array(all_mp)
    br_arr = np.array(all_br)

    movement_low  = float(np.percentile(mp_arr, 25))
    movement_high = float(np.percentile(mp_arr, 75))

    br_mean = float(np.mean(br_arr))
    br_std  = float(np.std(br_arr))

    breathing_low  = float(max(_BR_PHYS_MIN, br_mean - 1.5 * br_std))
    breathing_high = float(min(_BR_PHYS_MAX, br_mean + 1.5 * br_std))

    computed_at = datetime.now().isoformat()

    conn = get_connection(db_path)
    try:
        conn.execute("UPDATE personal_thresholds SET is_active = 0")
        conn.execute(
            """
            INSERT INTO personal_thresholds
              (computed_at, nights_used, movement_low, movement_high,
               breathing_low, breathing_high, breathing_mean, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                computed_at, nights_with_data,
                movement_low, movement_high,
                breathing_low, breathing_high, br_mean,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    log.info(
        f"Personal thresholds computed from {nights_with_data} nights, "
        f"{len(all_mp)} movement windows, {len(all_br)} breathing windows — "
        f"movement=[{movement_low:.3f}, {movement_high:.3f}]  "
        f"breathing=[{breathing_low:.1f}, {breathing_high:.1f}] BPM "
        f"(mean={br_mean:.1f})"
    )

    return SimpleNamespace(
        computed_at=computed_at,
        nights_used=nights_with_data,
        movement_low=movement_low,
        movement_high=movement_high,
        breathing_low=breathing_low,
        breathing_high=breathing_high,
        breathing_mean=br_mean,
    )
