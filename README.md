# Basecamp

Basecamp is a fully passive, contactless sleep monitoring system that combines WiFi channel state information, 24GHz mmWave radar, I2S acoustic sensing, and environmental monitoring to estimate sleep quality and produce a personalised recovery score every morning, without wearing anything to bed.

## What it does

The system runs overnight on a Raspberry Pi 4 inside a custom 3D printed bedside enclosure. Three sensing modalities work in parallel to capture different aspects of sleep. An ESP32-S3 measures how my body disturbs ambient WiFi signals, which encodes breathing rate, movement, and a coarse sleep stage approximation. A HLK-LD2410C mmWave radar tracks presence, bed entry and exit, and micro-motion throughout the night. An INMP441 microphone captures breathing sounds, snoring, and apnea audio signatures. Six environmental sensors monitor CO2, VOC, temperature, humidity, and light.

Nothing runs during the night beyond lightweight data logging. When I get out of bed in the morning, the radar detects the bed exit and triggers a batch processing job that runs the full ML pipeline on the overnight data and pushes a recovery report to my phone within about eight minutes.

## Recovery score

The recovery score is a weighted composite across four dimensions. Sleep architecture accounts for forty percent and captures deep sleep duration, REM proportion, and overall sleep efficiency. Continuity accounts for twenty five percent and measures awakening frequency, restlessness, and sleep fragmentation. Breathing quality accounts for twenty percent and is derived from CSI breathing rate, microphone snoring detection, and apnea event counts. The remaining fifteen percent covers the environmental picture, specifically CO2 accumulation, VOC index, temperature optimality, and light intrusion.

After enough labelled nights, the fixed weights are replaced by a regression model trained on my own morning subjective labels across four dimensions: recovery, energy, mental clarity, and mood. SHAP attribution then explains each night's score in plain English, identifying which specific factors drove the result up or down.

## Sensing modalities

WiFi CSI is the primary source for breathing rate and sleep stage approximation, using the fact that chest movement during breathing creates measurable phase shifts across the 56 subcarriers the ESP32-S3 captures. The mmWave radar provides reliable presence detection and bed entry and exit timestamps, which anchor the sleep window for all other analysis. Breathing rate is not derived from the radar, which outputs presence and motion data rather than a respiration waveform. The microphone captures acoustic breathing signatures and snoring, cross-validating the CSI breathing estimate and detecting apnea events through the characteristic snore to silence to gasp pattern.

## Why I built this

I wanted to know whether sleep quality actually affects next-day cognitive performance, and whether that relationship is quantifiable from raw radio signals rather than from a wrist-worn device making assumptions about my physiology. The answer turned out to require more than WiFi CSI alone, which is how the system expanded into a multi-modal sensor fusion pipeline. The long-term goal is a personalised model that predicts my recovery from overnight sensor data and identifies which environmental and behavioural variables matter most for my specific physiology.

## Hardware

The system runs on a Raspberry Pi 4 with 4GB of RAM inside a matte black 3D printed enclosure approximately 150 by 100 by 70mm. Two ESP32-S3 N16R8 nodes are placed on opposite sides of the bed at mattress height to ensure signal coverage regardless of sleeping position. All environmental sensors share a single I2C bus. The INMP441 connects via I2S. The radar connects via UART at 256000 baud on the Pi's hardware UART. Everything is powered from a single USB-C supply with one ethernet cable out to the router.

Full bill of materials and wiring diagrams are in the /hardware folder.

## Architecture

The overnight pipeline runs three lightweight daemons. The sensor logger writes all sensor readings to a local SQLite database every thirty seconds. The presence watcher monitors the radar for bed entry and exit timestamps and fires the morning batch job on wake detection after a minimum four hour sleep duration. The audio chunker processes microphone input in thirty second chunks using an energy threshold system that discards silence, compresses ambient audio, and preserves snoring at higher quality.

The morning batch job runs feature extraction, sleep staging, anomaly detection, recovery scoring, SHAP attribution, and report generation sequentially. Total runtime is approximately five to eight minutes on the Pi 4.

## ML pipeline

The sleep stage classifier is a Random Forest trained on fused features from CSI and audio, with an LSTM upgrade planned once sufficient data is available. The anomaly detector uses Isolation Forest to flag nights that deviate significantly from my personal baseline. The recovery predictor is a regression model trained on my morning subjective labels that improves continuously as more labelled nights accumulate. The system retrains automatically when seven or more new labelled nights have been collected since the last training run.

## Accuracy vs wearables

On breathing rate, the system is more accurate than wrist-based wearables because CSI directly measures chest displacement rather than inferring breathing from heart rate variability. Apnea detection benefits from having two independent modalities in CSI and audio, which outperforms wrist PPG alone. Sleep staging sits around sixty three percent accuracy, which is an honest limitation of not having EEG ground truth or a large population dataset to train on. Heart rate is trend-only from CSI and is not reliable enough for HRV derivation, which is a deliberate and documented limitation rather than an oversight.

The more accurate framing is not that this system competes with a wearable on the same metrics, but that it measures different things, runs entirely without contact, and produces a recovery model personalised to my own physiology rather than calibrated against population averages.

## Project structure

\\\
basecamp/
+-- hardware/         Bill of materials, enclosure STL, wiring reference
+-- firmware/         ESP32 flashing scripts and CSI configuration
+-- server/           Overnight logging daemons running on the Pi
+-- pipeline/         Morning batch job, feature extraction, ML models, scoring
+-- dashboard/        React web app for sleep and recovery visualisation
+-- morning/          Flask app for daily subjective log (Recovery, Energy, Clarity, Mood)
+-- analysis/         Jupyter notebooks for correlation analysis and model evaluation
+-- docs/
    +-- adr/          Architecture Decision Records documenting every major design choice
    +-- build-log/    Weekly entries covering what was built, what failed, and what changed
\\\

## Known limitations

Concrete walls between rooms mean nodes must be in the same room as the area being sensed. Sleep staging accuracy is limited by the absence of EEG ground truth and the small size of a personal dataset. Heart rate from CSI is trend-only and HRV cannot be derived contactlessly. The LD2410C radar provides presence and motion data but not a respiration waveform, so breathing rate is derived from CSI and audio only. WiFi 7 and ESP32-S3 CSI capture requires a dedicated 2.4GHz legacy SSID as a workaround and is untested at scale. The recovery predictor improves meaningfully only after around thirty labelled nights.

## Status

Currently in active development. Hardware assembly and first data collection in progress.
