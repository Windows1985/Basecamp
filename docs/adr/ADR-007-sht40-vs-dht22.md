# ADR-007: SHT40 vs DHT22 for temperature and humidity

## Context
The system needs a temperature and humidity sensor for environmental monitoring. Two common options are the DHT22 and the SHT40.

## Options considered
- DHT22: common, cheap, single-wire protocol
- SHT40: newer Sensirion sensor, I2C, higher accuracy

## Decision
SHT40.

## Reasoning
The SHT40 uses I2C, which is already used by BH1750, SCD40, and SGP40, all four environmental sensors share a single I2C bus, simplifying wiring significantly. The DHT22 uses a proprietary single-wire protocol requiring its own GPIO pin and a more complex software driver. The SHT40 also has better accuracy (+-0.2C vs +-0.5C) and faster response time, relevant for detecting subtle overnight temperature changes.

## Consequences
Marginal cost increase over DHT22. No other downsides.
