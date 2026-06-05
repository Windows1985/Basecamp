# ADR-003: Batch processing vs real-time overnight inference

## Context
The system needs to process sensor data and produce a recovery score. The question is whether to run ML inference continuously overnight or log raw data and process everything in the morning.

## Options considered
- Continuous real-time inference overnight
- Hybrid; lightweight logging overnight, full batch processing in the morning
- Full batch only

## Decision
Batch processing. Three lightweight daemons log raw data overnight. All ML inference runs as a single batch job triggered by wake detection.

## Reasoning
I would be asleep during data collection and cannot act on real-time output. Running ML inference overnight burns CPU continuously, generates heat (which biases environmental sensors), and creates failure modes where a crashed process loses data mid-night. Batch processing is independently restartable, easier to debug, and produces results at the only moment they are useful, after I actually wake up.

## Consequences
No live feedback during the night. The only real-time output is bed presence detection via radar, which is a simple threshold operation rather than ML inference. Recovery score arrives approximately 5-8 minutes after waking.
