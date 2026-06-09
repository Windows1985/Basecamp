CREATE TABLE IF NOT EXISTS sensor_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    temperature REAL,
    humidity REAL,
    co2_ppm REAL,
    voc_index REAL,
    light_lux REAL,
    max_lux REAL
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
    moving_distance REAL,
    pi_timestamp REAL
);

CREATE TABLE IF NOT EXISTS audio_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    tier TEXT,
    duration_seconds REAL,
    file_path TEXT,
    pi_timestamp REAL
);

CREATE TABLE IF NOT EXISTS sleep_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bed_entry TEXT NOT NULL,
    bed_exit TEXT,
    duration_hours REAL,
    status TEXT DEFAULT 'COMPLETE',
    created_at REAL
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

CREATE TABLE IF NOT EXISTS evening_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sleep_sessions(id),
    timestamp TEXT NOT NULL,
    date TEXT NOT NULL,
    caffeine_last_dose TEXT,
    exercise INTEGER,
    exercise_intensity INTEGER,
    screen_off_time TEXT,
    stress INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS feature_trends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    computed_at TEXT NOT NULL,
    session_id INTEGER REFERENCES sleep_sessions(id),
    feature_name TEXT NOT NULL,
    slope_7 REAL,
    slope_14 REAL,
    mean_7 REAL,
    z_score REAL,
    shap_direction TEXT,
    is_persistent INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS personal_thresholds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    computed_at TEXT NOT NULL,
    nights_used INTEGER NOT NULL,
    movement_low REAL NOT NULL,
    movement_high REAL NOT NULL,
    breathing_low REAL NOT NULL,
    breathing_high REAL NOT NULL,
    breathing_mean REAL NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0
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
    variance_value REAL NOT NULL,
    pi_timestamp REAL
);

CREATE TABLE IF NOT EXISTS service_heartbeats (
    service_name TEXT PRIMARY KEY,
    last_heartbeat REAL,
    status TEXT
);

CREATE TABLE IF NOT EXISTS daemon_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    state TEXT NOT NULL DEFAULT 'IDLE',
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sleep_stages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER NOT NULL,
    window_start  REAL NOT NULL,
    window_end    REAL NOT NULL,
    stage         TEXT NOT NULL,
    probable_rem  INTEGER DEFAULT 0,
    heuristic_stage TEXT NOT NULL,
    ml_stage      TEXT,
    ml_confidence REAL,
    source        TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sleep_sessions(id)
);
