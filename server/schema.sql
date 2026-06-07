CREATE TABLE IF NOT EXISTS sensor_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    temperature REAL,
    humidity REAL,
    co2_ppm REAL,
    voc_index REAL,
    light_lux REAL
);

CREATE TABLE IF NOT EXISTS csi_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    breathing_rate REAL,
    movement_power REAL,
    node_id TEXT
);

CREATE TABLE IF NOT EXISTS radar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT,
    presence INTEGER,
    still_distance REAL,
    moving_distance REAL
);

CREATE TABLE IF NOT EXISTS audio_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    tier TEXT,
    duration_seconds REAL,
    file_path TEXT
);

CREATE TABLE IF NOT EXISTS sleep_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bed_entry TEXT NOT NULL,
    bed_exit TEXT,
    duration_hours REAL
);

CREATE TABLE IF NOT EXISTS morning_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    session_id INTEGER REFERENCES sleep_sessions(id),
    recovery INTEGER,
    energy INTEGER,
    clarity INTEGER,
    mood INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS recovery_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sleep_sessions(id),
    timestamp TEXT NOT NULL,
    architecture_score REAL,
    continuity_score REAL,
    breathing_score REAL,
    environment_score REAL,
    total_score REAL
);

CREATE TABLE IF NOT EXISTS shap_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sleep_sessions(id),
    timestamp TEXT NOT NULL,
    feature_name TEXT,
    shap_value REAL
);

CREATE TABLE IF NOT EXISTS csi_variance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    node_id TEXT NOT NULL,
    variance_value REAL NOT NULL
);
