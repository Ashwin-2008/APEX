# MISTIQ-APR Research Report

Generated: 2026-10-06T15:11:32+00:00

## Research question
Can the trajectory of software engineering failures predict the next project
failure category better than static project-quality metrics?

## Status: INSUFFICIENT DATA
There are not enough real chronological review transitions for a rigorous evaluation. No accuracy is reported because none has been measured.

## Dataset status
- Projects: 1
- Reviews: 1
- Transitions: 0
- Training observations: 0
- Failure categories observed: 0
- Date range: 2026-10-06T15:08:42.279792 → 2026-10-06T15:08:42.279792
- Sample size (observations available for modeling): 0
- Dataset status: INSUFFICIENT DATA FOR VALID MODEL EVALUATION
- Dataset version: 1.0.0

## Temporal evaluation methodology
Walk-forward temporal evaluation: observations are ordered by timestamp and scored at expanding chronological cutoffs. Training always contains strictly earlier observations than the test group it predicts; no shuffling occurs.

## Leakage checks

Verdict: **PASSED**

| Check | Status | Detail |
|---|---|---|
| temporal_leakage | passed | All 0 observations carry feature timestamps at or before their observation time. |
| target_leakage | passed | No next-review target review appears in any feature construction. |
| duplicate_observations | passed | All 0 observations are unique on (project_id, review_id, target). |
| future_preprocessing_leakage | skipped | No preprocessing objects exist at this stage; train-only fitting is verified numerically whenever the evaluation fits a model. |
| cross_project_leakage | skipped | Split-level check runs together with walk-forward split generation. |

## Baseline comparison

Pooled across all valid walk-forward cutoffs (accuracy / macro F1 / top-3 accuracy).

| Model | Accuracy | Macro F1 | Top-3 | Status |
|---|---:|---:|---:|---|
| Majority | — | — | — | INSUFFICIENT DATA |
| Latest Failure | — | — | — | INSUFFICIENT DATA |
| Static Logistic | — | — | — | INSUFFICIENT DATA |
| Random Forest | — | — | — | INSUFFICIENT DATA |
| MISTIQ-APR | — | — | — | INSUFFICIENT DATA |

## MISTIQ-APR results

INSUFFICIENT DATA FOR VALID MODEL EVALUATION

No MISTIQ-APR performance claim can be made from the current dataset.

## Walk-forward results

INSUFFICIENT DATA FOR WALK-FORWARD EVALUATION

Only 0 chronological observations are available; at least 10 are required.

## Ablation results

Ablation evaluation unavailable: insufficient chronological observations.

## Calibration

Calibration metrics are not reported.
Reason: Calibration requires at least 20 walk-forward test predictions across at least two outcome classes; 0 predictions with 0 distinct outcome(s) are available. Metrics are withheld because they would not be meaningful at this size.

## Model artifact

No model artifact was written.
Reason: walk-forward evaluation is unavailable.

## Limitations, sample size, and confidence
- Sample size: 0 chronological observations across 1 project(s) and 1 review(s).
Confidence: none - no evaluation has been performed, so no performance confidence can be stated.
MISTIQ-APR is a project-specific sequential failure-prediction framework adapted
from the MISTIQ mistake-intelligence architecture. It is not claimed as a newly
invented universal machine-learning paradigm. Results are associations, not causal
claims, and cannot establish general software-engineering efficacy without more
real repositories with long chronological review histories.
Predictions describe historical association and are never certainties.
