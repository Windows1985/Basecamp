"""
Integration test — runs all three daemons in mock mode for 5 seconds each,
then verifies rows were written to the database.
"""
import os
import sys
import threading
import time

# Ensure project root is on path
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, PROJECT_ROOT)

# Force mock mode before importing anything else
import server.config as _cfg
_cfg.MOCK_HARDWARE = True

# Use a throw-away test database so we don't pollute real data
import tempfile
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
_cfg.DB_PATH = _tmp_db.name

from server.db import init_db, get_connection

RUN_SECONDS = 5
results = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_daemon(module_run, stop_flag, name):
    """Run module.run() in a thread; set module._running = False to stop."""
    try:
        module_run()
    except Exception as e:
        results[name] = f"EXCEPTION: {e}"


def _stop_after(modules, delay):
    time.sleep(delay)
    for mod in modules:
        mod._running = False


# ---------------------------------------------------------------------------
# Import daemons
# ---------------------------------------------------------------------------
print("Importing daemons...", flush=True)
try:
    import server.logger as logger_mod
    print("  server.logger — OK")
except Exception as e:
    print(f"  server.logger — IMPORT FAILED: {e}")
    sys.exit(1)

try:
    import server.presence as presence_mod
    print("  server.presence — OK")
except Exception as e:
    print(f"  server.presence — IMPORT FAILED: {e}")
    sys.exit(1)

try:
    import server.audio as audio_mod
    print("  server.audio — OK")
except Exception as e:
    print(f"  server.audio — IMPORT FAILED: {e}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Initialise DB
# ---------------------------------------------------------------------------
init_db(_cfg.DB_PATH)

# ---------------------------------------------------------------------------
# Run daemons concurrently
# ---------------------------------------------------------------------------
print(f"\nRunning all daemons for {RUN_SECONDS} seconds in mock mode...", flush=True)

logger_mod._running   = True
presence_mod._running = True
audio_mod._running    = True

# Shorten mock audio chunk to 1 second so we get multiple rows in 5 seconds
_cfg.AUDIO_CHUNK_SECONDS = 1
# Reload config values already captured by audio_mod at import time
audio_mod.AUDIO_CHUNK_SECONDS = 1

t_logger   = threading.Thread(target=logger_mod.run,   daemon=True, name="logger")
t_presence = threading.Thread(target=presence_mod.run, daemon=True, name="presence")
t_audio    = threading.Thread(target=audio_mod.run,    daemon=True, name="audio")

t_logger.start()
t_presence.start()
t_audio.start()

# Stop all after RUN_SECONDS
stopper = threading.Thread(
    target=_stop_after,
    args=([logger_mod, presence_mod, audio_mod], RUN_SECONDS),
    daemon=True,
)
stopper.start()

t_logger.join(timeout=RUN_SECONDS + 10)
t_presence.join(timeout=RUN_SECONDS + 10)
t_audio.join(timeout=RUN_SECONDS + 10)

# ---------------------------------------------------------------------------
# Verify DB rows
# ---------------------------------------------------------------------------
print("\nVerifying database rows...", flush=True)
conn = get_connection(_cfg.DB_PATH)

sensor_count = conn.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0]
radar_count  = conn.execute("SELECT COUNT(*) FROM radar_events").fetchone()[0]
audio_count  = conn.execute("SELECT COUNT(*) FROM audio_chunks").fetchone()[0]

conn.close()
os.unlink(_tmp_db.name)

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
print()
checks = [
    ("server.logger imports cleanly",           True),
    ("server.presence imports cleanly",          True),
    ("server.audio imports cleanly",             True),
    ("sensor_readings rows written by logger",   sensor_count > 0),
    ("radar_events rows written by presence",    radar_count  > 0),
    ("audio_chunks rows written by audio",       audio_count  > 0),
]

all_pass = True
for label, passed in checks:
    status = "PASS" if passed else "FAIL"
    if not passed:
        all_pass = False
    print(f"  [{status}] {label}")

print()
print(f"  sensor_readings: {sensor_count} rows")
print(f"  radar_events:    {radar_count} rows")
print(f"  audio_chunks:    {audio_count} rows")
print()

if all_pass:
    print("All checks passed.")
    sys.exit(0)
else:
    print("One or more checks FAILED.")
    sys.exit(1)
