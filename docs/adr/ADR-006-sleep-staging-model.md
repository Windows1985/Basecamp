# ADR-006: Sleep staging model architecture

## Context
The sleep stage classifier needs to infer sleep stages from fused CSI, radar, and audio features. The standard clinical model uses five classes: Wake, N1, N2, N3, and REM. The question is whether five-class staging is achievable with contactless WiFi CSI sensing, and which model architecture to use.

## Research findings
The best published contactless sleep staging results use radar-based transfer learning. An LSTM pretrained on movement, HRV, and respiratory features from the MESA Sleep dataset (1,100+ participants) then fine-tuned on 44 polysomnography recordings achieved a Matthews Correlation Coefficient of 0.47 for five-class staging. The fundamental limitation of contactless staging is that N1 and N2 are nearly indistinguishable without EEG, because the differences in respiration, heartbeat, and body movement between those two stages are not apparent from radio or acoustic signals alone.

There is no pretrained WiFi CSI sleep staging model available on Hugging Face or elsewhere that can be downloaded and used directly. The RuView model on Hugging Face is a CSI embedding encoder trained on a single overnight recording, not a sleep stage classifier, and its published accuracy numbers are not meaningful for generalisation.

## Options considered
- Five-class staging (Wake, N1, N2, N3, REM) with Random Forest
- Three-class staging (Wake, Deep, Light/REM) with Random Forest, upgraded to LSTM
- Transfer learning from MESA Sleep dataset actigraphy features, fine-tuned on personal data

## Decision
Three-class staging initially, with transfer learning from MESA as a planned Phase 3 upgrade.

Three classes:
- Wake: detected by radar movement spikes and CSI motion power above threshold
- Deep sleep: sustained low movement, slow regular breathing around 12 BPM, long uninterrupted windows
- Light and REM combined: everything else, with REM indicated by irregular breathing pattern with low movement

## Reasoning
Five-class staging is not achievable at meaningful accuracy with WiFi CSI alone. N1 and N2 require EEG to distinguish reliably. Attempting five-class staging with this hardware produces noisy, untrustworthy labels that undermine the recovery score. Three-class staging plays to the genuine strengths of the sensor stack: wake detection from radar is reliable, deep sleep has a distinctive radio and acoustic signature, and the light and REM distinction matters less for recovery scoring than deep sleep duration does.

The MESA transfer learning approach is the most technically interesting upgrade path. MESA is a publicly available dataset of 2,000+ participants with actigraphy-derived movement and respiratory features, which overlap significantly with what CSI and radar can measure. Pretraining on MESA features then fine-tuning on personal labelled nights is the approach used in the best academic contactless staging papers and has not been published as an open-source pipeline. This makes it a genuinely novel contribution for Phase 3 once 25+ nights of personal data are available.

## Realistic accuracy expectations

| Stage | Expected accuracy |
|-------|------------------|
| Wake detection | ~88% |
| Deep sleep (N3) | ~75% |
| Light and REM combined | ~65% |
| Overall three-class | ~72-78% |

## Consequences
The recovery score uses deep sleep duration and proportion as its primary architecture metric, which three-class staging supports well. REM proportion is estimated from irregular breathing windows within the light and REM class rather than classified directly. This is an honest limitation documented in the README. The MESA transfer learning upgrade is tracked as a Phase 3 goal after 25+ nights of data are collected.

## Phase 3 upgrade

Access to the MESA Sleep dataset was approved under a Data Use Agreement (DAUA) with Brigham and Women's Hospital through the National Sleep Research Resource (NSRR). MESA contains 2,056 participants with simultaneous actigraphy and polysomnography annotations at 30-second epochs, which matches the window size used in this pipeline exactly.

The feature overlap between MESA actigraphy and Basecamp CSI is substantial. MESA's activity_count column maps to movement_power derived from the CSI high-pass component. The zero_crossing_rate column from MESA actigraphy maps to the breathing regularity proxy computed from cross-subcarrier variance. Epoch-level features such as epoch_position, time_since_sleep_onset, and rolling movement statistics are computable from both datasets without modification.

Pretraining a Random Forest on MESA features then fine-tuning on 30 or more personal labelled nights is the approach used in the best-performing published contactless staging work. Published results suggest this improves three-class accuracy by 5 to 8 percentage points compared to training on personal heuristic labels alone. This is the only credible path to EEG-validated ground truth in a single-subject system without attaching electrodes.

Per DAUA section 8, raw MESA data files must not be committed to the repository and must be deleted within three years of project completion. Pretrained model weights derived from MESA data may be committed. The notebook implementing this pipeline is at analysis/mesa_transfer.ipynb.

Required acknowledgement for any work using MESA data: "NSRR R24 HL114473: NHLBI National Sleep Research Resource."
