# ADR-006: Random Forest vs LSTM for sleep staging

## Context
The sleep stage classifier needs to infer light, deep, and REM sleep from fused CSI, radar, and audio features. The choice of model affects interpretability, data requirements, and accuracy.

## Options considered
- Random Forest on extracted features per 30-second window
- LSTM on sequences of feature windows
- Pre-trained academic model

## Decision
Random Forest as the initial model, with LSTM as a planned upgrade after sufficient data is collected.

## Reasoning
The dataset will be small initially (under 30 nights without ground truth labels). Random Forest works well on small datasets, does not overfit easily, and is interpretable — feature importances explain which signals drive each classification. An LSTM requires more data to generalise and is harder to debug. Pre-trained academic models are not personalised and assume different hardware configurations.

## Consequences
The LSTM upgrade is planned once 30+ nights of data are available. Realistic accuracy expectation for Random Forest on personal CSI data: 63-70% on sleep staging. This is an honest limitation documented in the README.
