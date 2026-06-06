# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Basecamp is a passive overnight sleep monitoring system running on a Raspberry Pi 4. Three overnight daemons collect raw sensor data continuously; at bed-exit a morning batch pipeline runs feature extraction, recovery scoring, anomaly detection, and pushes a push notification via ntfy.sh. A Flask API and React dashboard visualise results.

## Development commands

```bash
# Install Python dependencies
pip install -r requirements.txt

# Initialise the database (creates data/basecamp.db)
python -c "from server.db import init_db; from server.config import DB_PATH; init_db(DB_PATH)"

# Generate synthetic sensor data for a test session
python pipeline/simulate.py

# Run the full morning pipeline against the most recent session
python pipeline/batch.py

# Run the pipeline against a specific session
python pipeline/batch.py --session 3 --db data/basecamp.db

# Run pipeline unit tests
python -m pytest pipeline/test_pipeline.py -v
# or directly:
python pipeline/test_pipeline.py

# Run daemon integration test (mock mode, 5-second run)
python server/test_daemons.py

# Start the Flask morning-log API (port 5000)
python morning/app.py

# Start the React dashboard dev server (port 5173)
cd dashboard && npm install && npm run dev

# Build the dashboard for production
cd dashboard && npm run build
```

## Hardware mock mode

`server/config.py` contains `MOCK_HARDWARE = True`. All three daemons check this flag and fall back to generating realistic synthetic data when it is `True`. Set to `False` on the Pi. Hardware-specific imports (`smbus2`, `pyserial`, `sounddevice`, etc.) are wrapped in `try/except` so every file imports cleanly on Windows/Mac even without the libraries installed.

## Architecture

### Data flow

```
[Hardware] → [Overnight daemons] → [SQLite DB] → [Morning pipeline] → [ntfy + Dashboard]
```

1. `server/logger.py` — every 30 s reads SHT40/BH1750/SCD40/SGP40 over I2C → `sensor_readings`
2. `server/presence.py` — continuously parses LD2410C radar binary frames → `radar_events` + `sleep_sessions`; on bed-exit with ≥ `MIN_SLEEP_HOURS`, spawns `pipeline/batch.py` as a subprocess
3. `server/audio.py` — records 30 s chunks from INMP441 I2S mic, classifies as silence/ambient/snore, saves Opus files → `audio_chunks`
4. `pipeline/csi.py` (separate process, not a daemon here) — receives raw CSI UDP from two ESP32-S3 nodes → `csi_readings`
5. `pipeline/batch.py` — 7-step morning orchestrator: features → score → attribution → anomaly → report → retrain
6. `morning/app.py` — Flask API serving the dashboard and accepting subjective morning ratings

### Database

All tables live in `data/basecamp.db` (SQLite). Schema DDL is in `server/schema.sql`. Always obtain a connection with `server/db.py::get_connection(DB_PATH)` — it sets `row_factory = sqlite3.Row`. Initialise with `init_db(DB_PATH)`. Tables: `sensor_readings`, `csi_readings`, `radar_events`, `audio_chunks`, `sleep_sessions`, `morning_log`, `recovery_scores`, `shap_values`.

### Pipeline internals

Each step is a standalone importable function that takes `(session_id, db_path)`:

| Module | Entry point | Output |
|--------|-------------|--------|
| `pipeline/features.py` | `extract_features()` | dict of 20+ metrics |
| `pipeline/score.py` | `calculate_recovery_score()` | dict with 4 subscores + total (0-100) |
| `pipeline/attribution.py` | `generate_attribution()` | (positives list, negatives list) |
| `pipeline/anomaly.py` | `detect_anomaly()` / `train_baseline()` | (bool, description) |
| `pipeline/report.py` | `generate_report()` | formatted string, also POSTs to ntfy |

`batch.py` runs all steps in order and continues on per-step failure, collecting errors in a summary dict — never abort the whole pipeline for a single step.

### Recovery scoring weights

Architecture 40 % · Continuity 25 % · Breathing 20 % · Environment 15 % — all weights live in `RECOVERY_WEIGHTS` in `server/config.py`.

### Anomaly detection

Uses scikit-learn `IsolationForest` trained on the user's own sessions. Skipped until ≥ 7 sessions exist. Model persisted at `data/anomaly_model.pkl`.

### Flask API endpoints

`GET /` — morning log form  
`POST /log` — submit subjective ratings (recovery/energy/clarity/mood 1-10 + notes)  
`GET /history` — last 30 days of logs + scores  
`GET /latest` — latest scores + attribution factors + sensor time series  
`GET /scores` — all sessions with scores for the dashboard trends view  

### Notifications

Push notifications are sent via ntfy.sh to topic `basecamp-recovery` (see `NTFY_TOPIC`/`NTFY_SERVER` in config). No API key required by default.

## Key config values (`server/config.py`)

`DB_PATH`, `I2C_BUS`, sensor I2C addresses, `RADAR_SERIAL_PORT` / `RADAR_BAUD_RATE`, `AUDIO_SAMPLE_RATE` / `AUDIO_CHUNK_SECONDS`, `SILENCE_THRESHOLD`, `SNORE_THRESHOLD`, `SNORE_FREQ_LOW/HIGH`, `MIN_SLEEP_HOURS`, `MOCK_HARDWARE`.

## Running on the Pi

```bash
# Start all three daemons (logs append to logs/*.log)
bash server/startup.sh

# Or enable systemd services (install instructions are in each .service file)
# systemd/ directory contains basecamp-logger.service, basecamp-presence.service, basecamp-audio.service
```

Logs rotate into `logs/` (`.gitkeep` keeps the directory tracked). Audio files are saved under `data/audio/`.

## Simulating a full session (no hardware)

```bash
python pipeline/simulate.py          # inserts synthetic rows for all tables
python pipeline/batch.py             # runs the morning pipeline on that data
python morning/app.py &              # serve the API
cd dashboard && npm run dev          # visualise results
```
