# ADR-008: INMP441 I2S microphone vs USB microphone

## Context
The system requires a microphone for snoring detection, breathing sounds, and apnea audio signatures. Two practical options are a USB condenser microphone and the INMP441 I2S digital microphone.

## Options considered
- USB condenser microphone (~30 RMB)
- INMP441 I2S digital microphone (~15 RMB)

## Decision
INMP441 I2S microphone.

## Reasoning
The INMP441 connects directly to the Pi via I2S (a dedicated digital audio interface), producing a clean digital signal without USB audio driver complexity. USB audio on Linux can introduce latency, requires driver configuration, and occupies a USB port needed for other peripherals. The INMP441 is also cheaper, smaller, and mounts directly on the enclosure PCB or breadboard. The I2S interface is well supported on Raspberry Pi via the built-in hardware audio clock.

## Consequences
Requires configuring the Pi's I2S interface in /boot/config.txt. Slightly more involved initial setup than plugging in a USB mic, but more reliable long-term.
