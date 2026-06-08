# Basecamp

Basecamp is a passive overnight sleep monitoring system that runs on a Raspberry Pi 4 sitting on a bedside table. It combines WiFi channel state information from two ESP32-S3 nodes, 24GHz mmWave radar, an I2S microphone, and four environmental sensors to estimate sleep quality and produce a personalised recovery score each morning. Nothing touches the body. The system was built to answer a specific question: whether next-day cognitive performance is predictable from raw radio and acoustic signals, and which overnight conditions matter most for a specific person's physiology.

Three sensing modalities work in parallel during the night. Two ESP32-S3 nodes, one on each side of the bed at mattress height, measure how the body disturbs ambient WiFi signals across 56 subcarriers; chest movement during breathing creates measurable phase shifts that the system extracts via bandpass FFT in 30-second windows. A HLK-LD2410C 24GHz mmWave radar tracks bed entry, bed exit, and micro-motion throughout the night but does not output a respiration waveform, so breathing rate comes from CSI and audio only. An INMP441 I2S microphone captures breathing sounds and snoring, and four I2C environmental sensors monitor CO2, VOC, temperature, humidity, and light. The modalities were chosen because they are complementary: CSI measures fine respiratory displacement, radar provides reliable bed presence detection, audio catches acoustic breathing signatures, and environmental sensors capture conditions that affect sleep quality independently of body physiology.

The goal is a personalised recovery model, not a replacement for clinical sleep study. Sleep staging accuracy is approximately 72 to 78 percent across three classes, which is honest rather than competitive with polysomnography. Heart rate from CSI is trend-level and not reliable enough for HRV derivation. What the system does well is measure breathing rate more directly than wrist-based wearables (which infer it from optical heart rate), build a model calibrated to one person's physiology rather than population averages, and run continuously without any contact with the body.

## Hardware

The main components are listed below. See `hardware/bom.md` for the full bill of materials with prices and purchasing notes.

| Component | Quantity | Notes |
|-----------|----------|-------|
| Raspberry Pi 4 Model B | 1 | 4GB RAM; runs all daemons and the morning pipeline |
| ESP32-S3-DevKitC-1 N16R8 | 2 | One node each side of the bed at mattress height |
| SanDisk MicroSD 32GB | 1 | Class 10; all data stored locally in SQLite |
| INMP441 | 1 | I2S digital microphone; connected to GPIO 18, 19, 20 |
| HLK-LD2410C | 1 | 24GHz mmWave radar; UART at 256000 baud on hardware UART |
| SHT40 | 1 | Temperature and humidity; I2C address 0x44 |
| BH1750 | 1 | Light sensor; I2C address 0x23 |
| SCD40 | 1 | CO2 sensor; I2C address 0x62; verify chip markings before use |
| SGP40 | 1 | VOC index sensor; I2C address 0x59 |
| 2.8 inch IPS SPI touchscreen | 1 | ILI9341 or ST7789 driver, 240x320 pixels |
| Powered 4-port USB hub | 1 | Powers both ESP32 nodes independently |

The enclosure is 3D printed in matte black PLA at approximately 150 by 100 by 70mm. It mounts the Pi on M2.5 standoffs with cable grommets for a clean external profile. The prototype uses a breadboard; the enclosure is designed around the same component layout. See `hardware/wiring.md` for full GPIO assignments and `hardware/bom.md` for the complete component list.

## Architecture

Three lightweight daemons run overnight on the Pi. The sensor logger reads all I2C environmental sensors every 30 seconds and writes to SQLite. The presence watcher monitors the radar, writes bed entry and exit timestamps, and fires the morning batch job when bed exit is detected after a minimum four-hour sleep duration. The audio chunker processes microphone input in 30-second chunks, classifying each as silence, ambient, or snoring, and stores relevant chunks as Opus files. A separate CSI ingest process receives raw CSI over UDP from the ESP32 nodes and writes cross-subcarrier variance to the database at 20 Hz. Nothing runs during the night beyond lightweight logging; all analysis runs in the morning.

```
hardware/       bill of materials, wiring reference, enclosure STL
firmware/       ESP32 flashing scripts and CSI capture configuration
server/         overnight daemons: sensor logger, presence watcher, audio chunker, sleep mode state machine
pipeline/       morning batch: CSI extraction, feature engineering, staging, scoring, attribution, anomaly detection, report
dashboard/      React web app for sleep and recovery visualisation
morning/        Flask API for daily subjective log (recovery, energy, clarity, mood ratings)
analysis/       Jupyter notebooks for MESA transfer learning and model evaluation
docs/adr/       architecture decision records for every major design choice
docs/build-log/ weekly entries covering what was built, what changed, and what failed
```

## Signal processing

The CSI breathing rate extraction treats the cross-subcarrier variance signal from each ESP32 node as a 20 Hz time series. For each 30-second window (600 samples), the pipeline applies a 4th-order Butterworth bandpass filter from 0.10 to 0.50 Hz, which corresponds to 6 to 30 breaths per minute and covers the full physiological range for sleeping adults. The dominant frequency within that band is extracted via an 8192-point zero-padded FFT, giving a frequency resolution of 0.0024 Hz, which is approximately 0.06 BPM. In synthetic testing against known ground-truth signals, the extraction achieves around plus or minus 0.06 BPM accuracy. Real-world accuracy depends on signal quality, mattress thickness, and sleeping position, and has not yet been measured on real overnight data. Movement power is extracted from the same signal using a complementary high-pass filter above 0.50 Hz.

## Sleep staging

The sleep stage classifier produces three classes: wake, deep sleep, and a combined light and REM class. N1 and N2 are not distinguished because the respiratory and motion differences between them are not detectable from radio or acoustic signals without EEG; any system claiming to separate N1 from N2 using WiFi CSI alone is overclaiming. Wake is detected by movement power above threshold from radar and CSI combined. Deep sleep is characterised by sustained low movement, slow and regular breathing in the 10 to 15 BPM range, and long uninterrupted windows. REM is estimated probabilistically within the light and REM class via breathing irregularity and snoring detection, and is stored as a flag rather than a separate stage. Expected accuracy is around 88 percent for wake, 75 percent for deep sleep, and 65 percent for the combined light and REM class, for an overall three-class accuracy of approximately 72 to 78 percent. These estimates come from the published literature on similar sensor configurations and should be treated as approximate until measured on real data. A Random Forest personalisation layer activates after 14 nights and is trained on heuristic labels, not EEG ground truth. A planned Phase 3 upgrade will pretrain on the MESA Sleep dataset (actigraphy plus PSG annotations) and fine-tune on personal data, which published work suggests improves three-class accuracy by 5 to 8 percentage points.

## Recovery score

The morning recovery score is a weighted composite across four components.

| Component | Weight | What it measures |
|-----------|--------|-----------------|
| Sleep architecture | 40% | Deep sleep proportion, REM estimate, total duration, and sleep efficiency |
| Continuity | 25% | Awakening count, sleep onset latency, and fragmentation |
| Breathing quality | 20% | Breathing regularity, snoring duration, and estimated apnea events |
| Environment | 15% | Peak CO2, VOC index, temperature deviation from optimal, and light intrusion |

The fixed weights reflect published sleep science on which factors most reliably predict next-day cognitive performance. After approximately 30 labelled nights, a regression model replaces the fixed scoring formula and learns weights specific to one person's physiology, using morning ratings across four subjective dimensions: recovery, energy, mental clarity, and mood. SHAP attribution then generates a plain-language explanation of each night's result, identifying which factors drove the score up or down.

## Known limitations

- Concrete walls between the ESP32 nodes and the bed will substantially degrade CSI signal quality; both nodes must be in the same room as the sleep area.
- Heart rate variability cannot be derived from CSI at the accuracy needed for HRV analysis; the system does not attempt HRV measurement.
- No SpO2 measurement is included; oxygen saturation monitoring requires a contact sensor.
- Sleep staging accuracy is limited by the absence of EEG ground truth; the three-class classifier is trained on heuristic labels, not PSG-validated annotations.
- Heart rate from CSI is trend-level only and is not reported as a precise per-beat measurement.
- The dedicated 2.4GHz legacy SSID workaround for WiFi 7 routers is untested at scale in the CSI community and may require a fallback travel router in some environments.
- The personalised recovery predictor requires a minimum of 14 labelled nights before the machine learning layer activates; the fixed-weight model runs until then.
- The SGP40 VOC sensor requires approximately 24 hours of burn-in before its readings are reliable.

## Status

The software pipeline is complete and tested against simulated data. Hardware assembly and first real-world data collection have not yet started. All pipeline unit tests pass with simulated sensor data. No real sleep data has been collected.

## Acknowledgements

Sleep staging transfer learning uses the MESA Sleep dataset from the National Sleep Research Resource. Required acknowledgement: "NSRR R24 HL114473: NHLBI National Sleep Research Resource."
