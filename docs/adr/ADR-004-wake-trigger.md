# ADR-004: Bed exit trigger vs fixed time batch job

## Context
The morning batch job needs a trigger. The options are a fixed time (e.g. 7am) or a dynamic trigger based on detected wake time.

## Options considered
- Fixed 7am cron job
- Bed exit detected by radar triggers batch

## Decision
Radar-based bed exit trigger. Batch fires when radar detects bed exit after a minimum 4-hour sleep duration.

## Reasoning
A fixed time does not account for variable wake times. If the user sleeps until 9am, a 7am batch job runs on incomplete data. If they wake at 6am, they wait an hour for the report. The radar already runs overnight for presence detection, so bed exit is a zero-cost signal. The 4-hour minimum prevents bathroom trips at 3am from triggering the batch.

## Consequences
Requires the presence watcher daemon to remain running overnight. Adds a duration check before firing the trigger. Edge case: if the radar misses a bed exit, the batch does not run automatically and must be triggered manually.
