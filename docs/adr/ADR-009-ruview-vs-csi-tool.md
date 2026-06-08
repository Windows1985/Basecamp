# ADR-009: RuView vs ESP32-CSI-Tool for CSI extraction

## Context
The WiFi CSI layer requires firmware on the ESP32 to capture channel state information and software on the Pi to process it. Two main options exist: RuView (complete end-to-end pipeline) and ESP32-CSI-Tool (raw CSI extraction only, requiring a custom processing layer).

## Options considered
- RuView: complete pipeline including firmware, Rust sensing server, signal processing, and pre-trained models
- ESP32-CSI-Tool: battle-tested CSI extraction only, custom Python processing layer built on top

## Decision
ESP32-CSI-Tool for firmware and a custom Python processing layer for all signal analysis. RuView is referenced as a prior art implementation only.

## Reasoning
RuView has a known bug in which the JSONL model file fails to load, causing the system to fall back silently to heuristic mode for sleep staging. The bug was confirmed unpatched as of the decision date. Silent fallback to a different algorithm with no user-visible indication is not acceptable for a system where trust in the output matters.

Beyond the bug, using RuView would make the processing pipeline opaque. Every layer of CSI processing in this project is code written and understood by the author. ESP32-CSI-Tool is battle-tested firmware for raw CSI extraction from ESP32 hardware. The custom Python layer in pipeline/csi.py applies a 4th-order Butterworth bandpass filter from 0.10 to 0.50 Hz, extracts the dominant frequency via an 8192-point zero-padded FFT, and computes movement power from the high-pass component. This pipeline is straightforward to debug and extend.

CSI frames are parsed using CSIKit where available, with a CSV fallback for frames logged by ESP32-CSI-Tool's serial output format. The two parsers produce identical output structures so the rest of the pipeline is unaffected by which parser handles a given frame.

In synthetic testing against known ground-truth breathing signals, the frequency extraction achieves approximately plus or minus 0.06 BPM accuracy. This figure has not yet been validated on real overnight data.

## Consequences
The firmware flashing procedure uses ESP32-CSI-Tool scripts in the firmware/ directory. The custom processing layer adds development time compared to using RuView out of the box, but every processing decision is visible and adjustable. Filter parameters were chosen based on published literature and will likely require tuning once real subcarrier data from the specific room geometry is available. CSIKit is listed in requirements as an optional dependency; the CSV fallback ensures the pipeline runs without it.
