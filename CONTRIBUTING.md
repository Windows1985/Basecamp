# Contributing to Basecamp

Basecamp is a single-person research project and the primary audience for this guide is the author returning to the code after a gap, or anyone reviewing the implementation for educational purposes. External contributions are welcome but this is not a maintained open-source library.

## Hardware requirements

The overnight daemons require a Raspberry Pi 4, two ESP32-S3 nodes, a 24GHz mmWave radar module, an I2S microphone, and four I2C sensors. None of this hardware is needed to develop, test, or extend the pipeline code. The `MOCK_HARDWARE = True` flag in `server/config.py` causes all three daemons and the pipeline to generate realistic synthetic data instead of reading from physical sensors.

## Development setup

These steps work on macOS, Linux, and Windows without any hardware attached.

```bash
# Clone the repository
git clone <repo-url>
cd basecamp

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Initialise the database
python -c "from server.db import init_db; from server.config import DB_PATH; init_db(DB_PATH)"

# Generate synthetic sensor data for one overnight session
python pipeline/simulate.py

# Run the full morning pipeline against that session
python pipeline/batch.py

# Start the Flask API (port 5000)
python morning/app.py

# Start the React dashboard development server (port 5173)
cd dashboard && npm install && npm run dev
```

Verify the setup is working by checking that `python pipeline/batch.py` completes without errors and prints a recovery score between 0 and 100.

## Running the tests

```bash
# Pipeline unit tests (17 assertions covering features, scoring, staging, attribution)
python -m pytest pipeline/test_pipeline.py -v

# Daemon integration test (mock mode, 5-second run, no hardware needed)
python server/test_daemons.py

# Sleep stage classifier tests
python pipeline/test_staging.py

# Touchscreen controller tests (pygame mock mode)
python server/test_screen.py

# Sleep mode state machine tests
python server/test_sleepmode.py
```

All tests should pass on a clean checkout with `MOCK_HARDWARE = True`.

## Architecture overview

Three overnight daemons write to SQLite while the subject sleeps. At bed exit, `server/presence.py` spawns `pipeline/batch.py` as a subprocess. The batch pipeline runs seven steps in sequence and continues on per-step failure so a single broken step does not suppress the morning report. The Flask app at `morning/app.py` serves the dashboard and accepts subjective morning ratings.

See `docs/adr/` for the reasoning behind every significant design choice. Reading the ADRs before making a structural change is strongly recommended.

## Architecture decision records

Significant design decisions are documented as ADRs in `docs/adr/`. Each ADR covers context, options considered, the decision made, the reasoning, and consequences. When a change affects a decision that was previously documented, update the relevant ADR or write a new one superseding it. The ADR numbering is sequential.

## Code style

- Python files follow PEP 8 with a 100-character line limit.
- All pipeline step functions take `(session_id: int, db_path: str)` and return a result dict.
- Database connections are always obtained via `server/db.py::get_connection(db_path)`, which sets `row_factory = sqlite3.Row`. Do not create connections directly with `sqlite3.connect`.
- Hardware-specific imports (`smbus2`, `pyserial`, `sounddevice`, `RPi.GPIO`) are wrapped in `try/except ImportError` so files import cleanly on non-Pi machines.
- `server/config.py` is the single source of truth for thresholds, I2C addresses, pin numbers, and other constants. Do not hardcode sensor addresses or GPIO numbers in module code.

## Data privacy

The database at `data/basecamp.db` contains personal biometric data. It is excluded from version control via `.gitignore`. Do not commit any file from `data/` unless it is a schema file or a synthetic test fixture.

MESA Sleep dataset files, if used for transfer learning, are subject to a Data Use Agreement. Raw MESA files must not be committed to this repository. Pretrained model weights derived from MESA data may be committed. See `docs/adr/ADR-010-mesa-transfer-learning.md` for the full terms.

## Acknowledgements

Sleep staging transfer learning uses the MESA Sleep dataset from the National Sleep Research Resource. Required acknowledgement: "NSRR R24 HL114473: NHLBI National Sleep Research Resource."
