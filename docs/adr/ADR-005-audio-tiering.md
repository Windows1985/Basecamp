# ADR-005: Audio storage tiering strategy

## Context
Logging raw audio overnight at 16kHz mono produces approximately 115MB per hour uncompressed, or roughly 700MB for a full night. A 32GB card fills in under 50 nights. Storage needs to be managed without risking loss of meaningful data.

## Options considered
- Store all audio compressed
- Real-time ML classifier to keep only interesting chunks
- Energy threshold tiering with bandpass snore detection

## Decision
Three-tier energy threshold system. Silence: timestamp only. Ambient: compressed low quality. Snore band (60-500Hz bandpass above threshold): compressed high quality with tag.

## Reasoning
A real-time ML classifier adds CPU load and risks false negatives where interesting audio is permanently discarded. Pure compression without filtering still produces ~150MB per night. The energy threshold approach requires only signal processing (no ML), runs cheaply overnight, reduces storage by approximately 70%, and preserves all audio above the silence threshold so no meaningful data is lost.

## Consequences
The silence threshold must be calibrated to the specific bedroom environment. If set too high, quiet breathing chunks are discarded. Threshold calibration is a one-time setup step on the first night.
