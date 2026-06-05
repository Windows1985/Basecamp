"""
Simulates a realistic night of sleep data and writes it to the database.
"""
import os
import sys
from datetime import datetime, timedelta

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.db import get_connection, init_db


def simulate_night(quality=0.8, start_time=None, db_path=None):
    """
    Generate a realistic night of sleep data and write it to the database.

    quality : float 0.0-1.0  (0 = terrible night, 1 = perfect night)
    start_time : datetime for bed entry; defaults to last night 22:30
    db_path : path to SQLite database

    Returns the session_id of the created sleep session.
    """
    if db_path is None:
        from server.config import DB_PATH
        db_path = DB_PATH

    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    init_db(db_path)

    seed = int(datetime.now().timestamp() * 1000) % (2**31)
    rng = np.random.default_rng(seed)

    # --- Session timing --------------------------------------------------
    if start_time is None:
        now = datetime.now()
        start_time = now.replace(
            hour=22, minute=30, second=0, microsecond=0
        ) - timedelta(days=1)

    bed_entry = start_time

    # Duration 7-8 h; poor-quality nights tend to be shorter
    base_hours = 7.0 + float(rng.uniform(0, 1.0))
    if quality < 0.5:
        base_hours -= (0.5 - quality) * 1.5
    base_hours = max(4.5, base_hours)

    bed_exit = bed_entry + timedelta(hours=base_hours)
    total_minutes = base_hours * 60

    # --- Timestamps at 30-second intervals --------------------------------
    n_samples = int(total_minutes * 60 / 30)
    timestamps = [bed_entry + timedelta(seconds=30 * i) for i in range(n_samples)]
    t_min = np.arange(n_samples) * 0.5  # minutes since bed entry

    # --- Sleep onset -------------------------------------------------------
    # 10-30 min from bed entry; shorter for high-quality nights
    sleep_onset_min = 10.0 + (1.0 - quality) * 20.0 + float(rng.uniform(0, 5))

    # --- Sleep cycle structure (90-min NREM/REM cycles) --------------------
    sleep_elapsed = t_min - sleep_onset_min  # negative before sleep onset
    cycle_pos = (np.clip(sleep_elapsed, 0, None) % 90.0) / 90.0  # 0..1 within cycle
    cycle_num = np.clip(sleep_elapsed, 0, None) // 90.0  # which cycle

    awake_mask = t_min < sleep_onset_min

    # Deep sleep: centre of cycle, shrinks in later cycles (realistic 15-20%)
    deep_end = 0.45 - 0.06 * np.minimum(cycle_num, 5)
    deep_sleep_mask = (~awake_mask) & (cycle_pos > 0.15) & (cycle_pos < deep_end)

    # REM: grows longer with each cycle (realistic 20-25%)
    rem_start = 0.80 - 0.03 * np.minimum(cycle_num, 4)
    rem_mask = (~awake_mask) & (cycle_pos > rem_start) & ~deep_sleep_mask

    # --- Breathing rate ----------------------------------------------------
    # Cosine formula: minimum (deep) at cycle_pos=0.35, maximum (REM) at 0.85
    # br = 14.0 - 1.5 * cos(2*pi*(x - 0.35))
    # At 0.35: 12.5 BPM (deep)   At 0.85: 15.5 BPM (REM)
    br_base = 14.0 - 1.5 * np.cos(2 * np.pi * (cycle_pos - 0.35))

    noise_scale = 0.25 + (1.0 - quality) * 0.65
    br = br_base + rng.normal(0, noise_scale, n_samples)
    br += rng.normal(0, 1.0, n_samples) * rem_mask.astype(float)  # REM irregularity
    br[awake_mask] = 16.0 + rng.normal(0, 0.5, int(np.sum(awake_mask)))
    br = np.clip(br, 8, 22)

    # --- Apnea events ------------------------------------------------------
    # quality=1 → ~0 apneas, quality=0 → ~5 apneas
    apnea_lambda = max(0.05, (1.0 - quality) * 5.0)
    n_apneas = min(int(rng.poisson(apnea_lambda)), 8)
    valid_ap = np.where(~awake_mask & (t_min > sleep_onset_min + 30))[0]
    if len(valid_ap) >= n_apneas:
        for ap_i in rng.choice(valid_ap, n_apneas, replace=False):
            ap_len = int(rng.integers(1, 3))
            for k in range(ap_len):
                if ap_i + k < n_samples:
                    br[ap_i + k] = float(rng.uniform(0, 1.5))

    # --- Movement power ----------------------------------------------------
    # Peaks at cycle transitions; near-zero during deep sleep and REM (atonia)
    mp_base = 0.18 * np.abs(np.sin(np.pi * cycle_pos))
    mp_base[deep_sleep_mask] *= 0.20
    mp_base[rem_mask] *= 0.12
    mp_base[awake_mask] = float(rng.uniform(0.2, 0.5))
    mp = np.clip(mp_base + rng.exponential(0.03, n_samples), 0, 1)

    # --- Awakenings --------------------------------------------------------
    n_aw_target = max(0, int(rng.poisson(max(0.2, (1.0 - quality) * 4))))
    valid_aw = np.where(~awake_mask & (t_min > sleep_onset_min + 60))[0]
    if len(valid_aw) >= n_aw_target and n_aw_target > 0:
        for aw_i in rng.choice(valid_aw, n_aw_target, replace=False):
            aw_len = int(rng.integers(4, 12))  # 2-6 min
            for k in range(aw_len):
                if aw_i + k < n_samples:
                    mp[aw_i + k] = float(rng.uniform(0.45, 0.9))
                    br[aw_i + k] = float(rng.uniform(15, 20))

    # --- Environmental sensors --------------------------------------------

    # CO2: rises from 420 to 1600-2000 ppm then plateaus
    co2_peak = 1600 + (1.0 - quality) * 400 + float(rng.uniform(-100, 100))
    co2 = 420.0 + (co2_peak - 420.0) * (1.0 - np.exp(-t_min / 150.0))
    # Slight drop after ~4 h (improved ventilation heuristic)
    co2[t_min > total_minutes * 0.55] -= (
        (co2[t_min > total_minutes * 0.55] - 1200.0) * 0.10
    )
    co2 += rng.normal(0, 20, n_samples)
    co2 = np.clip(co2, 400, 2500)

    # Temperature: 21 -> 19 °C
    temperature = 21.0 - 2.0 * (t_min / total_minutes) + rng.normal(0, 0.08, n_samples)

    # Humidity: ~65 %
    humidity = np.clip(65.0 + rng.normal(0, 1.5, n_samples), 50, 85)

    # VOC index: 60-120
    voc = np.clip(
        90.0 + 20.0 * np.sin(np.pi * t_min / total_minutes) + rng.normal(0, 12, n_samples),
        40, 220,
    )

    # Light: near-zero with phone-check spike ~3 h after sleep onset
    light = rng.exponential(0.15, n_samples)
    phone_idx = int((sleep_onset_min + 180.0) * 2)  # 2 samples/min
    if 0 < phone_idx < n_samples:
        light[phone_idx] = float(rng.uniform(60, 200))
        if phone_idx + 1 < n_samples:
            light[phone_idx + 1] = float(rng.uniform(8, 40))

    # --- Snoring -----------------------------------------------------------
    snore_total_min = 15.0 + (1.0 - quality) * 15.0 + float(rng.uniform(-3, 3))
    snore_total_min = max(5.0, snore_total_min)
    snore_samples_needed = int(snore_total_min * 2)

    snore_mask = np.zeros(n_samples, dtype=bool)
    valid_snore = np.where(deep_sleep_mask | (~awake_mask & ~rem_mask))[0]

    if len(valid_snore) > snore_samples_needed:
        n_periods = int(rng.integers(3, 7))
        period_len = max(2, snore_samples_needed // n_periods)
        for ps in rng.choice(valid_snore[: -period_len - 1], n_periods, replace=False):
            for k in range(period_len):
                if ps + k < n_samples:
                    snore_mask[ps + k] = True

    # --- Write to database -------------------------------------------------
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO sleep_sessions (bed_entry, bed_exit, duration_hours) VALUES (?, ?, ?)",
            (bed_entry.isoformat(), bed_exit.isoformat(), base_hours),
        )
        session_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Sensor readings
        conn.executemany(
            "INSERT INTO sensor_readings "
            "(timestamp, temperature, humidity, co2_ppm, voc_index, light_lux) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    ts.isoformat(),
                    float(temperature[i]),
                    float(humidity[i]),
                    float(co2[i]),
                    float(voc[i]),
                    float(light[i]),
                )
                for i, ts in enumerate(timestamps)
            ],
        )

        # CSI readings — four nodes with small per-node offsets
        csi_rows = []
        for node_id in ("node_01", "node_02", "node_03", "node_04"):
            offset = float(rng.uniform(-0.3, 0.3))
            for i, ts in enumerate(timestamps):
                csi_rows.append((
                    ts.isoformat(),
                    float(max(0, br[i] + offset + rng.normal(0, 0.1))),
                    float(mp[i]),
                    node_id,
                ))
        conn.executemany(
            "INSERT INTO csi_readings (timestamp, breathing_rate, movement_power, node_id) "
            "VALUES (?, ?, ?, ?)",
            csi_rows,
        )

        # Radar events
        conn.execute(
            "INSERT INTO radar_events "
            "(timestamp, event_type, presence, still_distance, moving_distance) "
            "VALUES (?, ?, ?, ?, ?)",
            (bed_entry.isoformat(), "bed_entry", 1, 0.5, 0.0),
        )
        conn.execute(
            "INSERT INTO radar_events "
            "(timestamp, event_type, presence, still_distance, moving_distance) "
            "VALUES (?, ?, ?, ?, ?)",
            (bed_exit.isoformat(), "bed_exit", 0, 0.0, 1.5),
        )

        # Audio chunks
        conn.executemany(
            "INSERT INTO audio_chunks (timestamp, tier, duration_seconds, file_path) "
            "VALUES (?, ?, ?, ?)",
            [
                (
                    ts.isoformat(),
                    "snore" if snore_mask[i]
                    else ("ambient" if (mp[i] > 0.2 or br[i] > 16) else "silence"),
                    30.0,
                    f"audio/{ts.strftime('%Y%m%d_%H%M%S')}.wav",
                )
                for i, ts in enumerate(timestamps)
            ],
        )

        conn.commit()
    finally:
        conn.close()

    return session_id
