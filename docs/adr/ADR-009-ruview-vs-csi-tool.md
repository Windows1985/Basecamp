# ADR-009: RuView vs ESP32-CSI-Tool for CSI extraction

## Context
The WiFi CSI layer requires firmware on the ESP32 to capture channel state information and software on the Pi to process it. Two main options exist: RuView (complete end-to-end pipeline) and ESP32-CSI-Tool (raw CSI extraction only, requiring a custom processing layer).

## Options considered
- RuView: complete pipeline including firmware, Rust sensing server, signal processing, and pre-trained models
- ESP32-CSI-Tool: battle-tested CSI extraction only, custom Python processing layer built on top

## Decision
To be confirmed after checking RuView GitHub issues for JSONL model loading bug status.

## Reasoning
RuView provides faster time to first results but has a known bug where the JSONL model file fails to load, falling back to heuristic mode for sleep staging. If this bug is patched, RuView is the better starting point. If unpatched, ESP32-CSI-Tool with a custom Python processing layer built using CSIKit is the more reliable foundation and produces a stronger portfolio piece since every layer of the pipeline is original work.

## Consequences
If using RuView: faster setup, less original code, dependent on upstream bug fixes. If using ESP32-CSI-Tool: more development time, full control over processing pipeline, better for portfolio depth. Decision to be revisited once bug status is confirmed.
