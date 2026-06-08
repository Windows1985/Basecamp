# Week 00: Software design and build (pre-hardware phase)

This entry covers the period before any hardware existed. The entire software stack was designed and built against simulated data before a single component was ordered. The goal was to arrive at hardware with a complete, tested pipeline so that the first real sensor readings could flow straight into a working system rather than into a half-finished one. That goal was mostly achieved, with a few things that will clearly need adjustment once real signals arrive.

## What was built

- `server/logger.py`: the overnight daemon that reads all four I2C environmental sensors every 30 seconds and writes to SQLite; the BH1750 runs at 1 Hz for the full 30-second window so the logger records both mean and maximum lux.
- `server/presence.py`: the overnight daemon that parses LD2410C radar UART frames, writes bed entry and exit events, and fires the morning batch job on wake detection after a minimum sleep duration.
- `server/audio.py`: the overnight audio chunker that classifies 30-second microphone windows as silence, ambient, or snoring using energy thresholds and a bandpass check in the 60 to 500 Hz snore frequency range.
- `pipeline/csi.py`: the CSI feature extraction module that reads 20 Hz cross-subcarrier variance from the database, applies bandpass and high-pass filters, and extracts breathing rate, breathing regularity, and movement power per 30-second window.
- `pipeline/features.py`: the feature engineering step that aggregates all overnight signals into a fixed-size feature vector for scoring.
- `pipeline/staging.py`: the three-class sleep stage classifier with a physics-grounded heuristic layer that runs from night one and a Random Forest personalisation layer that activates after 14 nights.
- `pipeline/score.py`: the weighted recovery score calculator (architecture 40%, continuity 25%, breathing 20%, environment 15%).
- `pipeline/attribution.py`: the SHAP-based attribution module that identifies which features drove the recovery score up or down.
- `pipeline/anomaly.py`: the anomaly detector that uses MAD z-score for the first 60 nights and switches to Isolation Forest thereafter.
- `pipeline/batch.py`: the seven-step morning orchestrator that runs the full pipeline in sequence and continues on per-step failure.
- `pipeline/simulate.py`: a synthetic data generator that inserts realistic overnight sensor data into the database, used as the development target for everything above.
- `pipeline/report.py`: the report generator that formats the morning summary and pushes it via ntfy.
- `server/sleepmode.py`: the central state machine that manages the five-state sleep lifecycle (idle, bedtime prompt, recording, morning, recovery) and drives the touchscreen.
- `server/screen.py`: the touchscreen UI controller with three layouts rendered to a 240x320 pygame surface; touch input uses hit-rects in screen coordinate space.
- `pi_setup.sh`: the Raspberry Pi setup script covering apt packages, Python venv, boot config, I2C/SPI/UART configuration, systemd service installation, and database initialisation.
- `server/calibrate_scd40.py`: a standalone calibration tool for the SCD40 CO2 sensor using direct I2C protocol with CRC-8 verification.
- A full set of architecture decision records in `docs/adr/` covering every significant design choice.

## Key decisions made

**Three-class staging instead of five-class.** The original plan included five-class staging matching clinical PSG terminology. I dropped N1 and N2 as separate classes early, after reading the literature on what WiFi CSI can and cannot distinguish. N1 and N2 differ primarily in EEG signature; their respiration and motion profiles are nearly identical. A system that claims to separate them from radio signals is presenting noise as signal. Three classes (wake, deep, light and REM combined) maps to what the hardware can actually see: movement power for wake, slow regular breathing for deep, everything else for light and REM.

**Batch processing in the morning instead of real-time inference overnight.** Running ML inference continuously during the night would heat the Pi, increase power draw, and add complexity with no benefit, since nobody reads sleep staging data until morning anyway. The entire analysis runs in a single batch job after bed exit is detected, which also means the full overnight dataset is available for context-aware processing (smoothing, run detection, session-level metrics) rather than having to process each window in isolation.

**ESP32-CSI-Tool with a custom Python layer instead of RuView.** RuView has a known JSONL model loading bug that falls back to heuristic mode silently. More importantly, using RuView would mean the processing pipeline is opaque; every layer of the CSI processing in this project is code I wrote and understand. ESP32-CSI-Tool is battle-tested firmware for raw CSI extraction, and the custom Python layer (bandpass FFT pipeline in `pipeline/csi.py`) is more straightforward to debug and extend than Rust code I did not write.

**SQLite with a single local file instead of a remote database.** The system runs overnight disconnected from any cloud service; a network outage should not affect data collection. SQLite with `row_factory = sqlite3.Row` throughout is simple, fast enough for this data volume, and produces a single file that is easy to back up. The schema is versioned via `migrate_schema()` so adding columns does not require recreating the database.

**Two-phase staging classifier with heuristic-first design.** The heuristic layer needed to produce useful output from night one, before any personal data existed to train on. This meant designing rules grounded in physiology rather than statistics: presence check, movement threshold, breathing rate range and regularity for deep sleep, breathing irregularity and snoring for REM within the light class. The Random Forest layer is additive and blends in gradually (60/40 heuristic/ML before 30 nights, 40/60 after) so there is no cliff edge where the model suddenly changes behaviour.

## What was hard

The CORS configuration between Flask and the Vite development server took longer than expected. Flask-CORS needs to allow both the development origin (localhost:5173) and the production path, and the order of middleware registration matters. The fix was straightforward once the issue was identified, but the error messages from the browser were not helpful for diagnosing the root cause.

The `simulate_night()` function in `pipeline/simulate.py` initially returned a dict of session data rather than a session ID. Several downstream tests called `classify_session(simulate_night(...))` and broke when the signature changed. This was a simple interface mismatch but it required touching every test file. The fix was to make `simulate_night()` consistently return an integer session ID and let callers query the database for anything else they need.

The CSI bandpass filter design required careful handling of null subcarriers and pilot subcarriers in the cross-subcarrier variance signal. The raw ESP32 CSI output includes subcarriers that are always zero (null) or always known (pilot), and including them inflates the variance signal and distorts the FFT. The pipeline zeros those indices before computing the variance to avoid contaminating the breathing rate extraction.

## What changed from the original plan

**Focus classifier dropped.** An early plan included a real-time attention and focus classifier for daytime use, separate from the sleep pipeline. It was dropped because it would have required a separate sensor setup and was orthogonal to the core sleep analysis goal. The project scope is now strictly overnight.

**SGP30 replaced by SGP40.** The original sensor list included the SGP30 for VOC monitoring. The SGP40 uses a proprietary Sensirion algorithm that outputs a VOC index (0 to 500) rather than raw equivalent CO2, which is more directly useful for environmental scoring. The SGP40 also has better long-term stability. The I2C address changed from 0x58 to 0x59 and the driver API is different, but the integration was straightforward.

**ADS1115 ADC removed.** An analog-to-digital converter was on the early parts list for possible analog sensor additions. Nothing in the current design uses analog inputs; the Pi has no onboard ADC and the sensors chosen are all I2C or I2S. The ADS1115 was removed to simplify the BOM.

## What the simulated data looks like

Running `pipeline/simulate.py` followed by `pipeline/batch.py` produces a complete morning report in about two seconds on a development machine. Ten integration test runs across different quality parameters produced recovery scores ranging from 68 to 88, with the environment score consistently low due to the simulated CO2 peaking above 1200 ppm (reflecting a room with poor ventilation in the simulation parameters). Deep sleep proportion in the simulated classifier comes in lower than ground truth because the synthetic movement noise uses an exponential distribution that pushes roughly half of deep-sleep windows above the movement threshold. This is a known limitation of the simulated data rather than a bug in the classifier, and is documented in the test comments.

## What comes next

When hardware arrives, the first task is calibration: verifying the SCD40 reads close to outdoor atmospheric CO2 (around 415 to 420 ppm), running the SGP40 burn-in overnight, and confirming the BH1750 and SHT40 are reading sensibly. The radar will need its presence and absence thresholds checked against real bed geometry. The CSI pipeline will almost certainly need adjustment once real subcarrier data arrives; the filter parameters were chosen based on the literature but may need tuning for the specific room geometry and mattress type. The touchscreen layout was designed for a 240x320 IPS panel but has only been tested in pygame mock mode. All of this is expected and is why the simulate-first approach was worth the investment upfront.
