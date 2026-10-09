# MISTIQ-APR Research Report

Generated: 2026-10-09T12:22:12+00:00

## Research question
Can the trajectory of software engineering failures predict the next project
failure category better than static project-quality metrics?

## Status: INSUFFICIENT DATA
There are not enough real chronological review transitions for a rigorous evaluation. No accuracy is reported because none has been measured.

## Dataset status
- Projects: 2
- Reviews: 3
- Transitions: 1
- Training observations: 4
- Failure categories observed: 4
- Date range: 2026-10-07T13:00:04.530224 → 2026-10-07T13:00:04.530224
- Sample size (observations available for modeling): 4
- Dataset status: INSUFFICIENT DATA FOR VALID MODEL EVALUATION
- Dataset version: 1.0.0

## Temporal evaluation methodology
Walk-forward temporal evaluation: observations are ordered by timestamp and scored at expanding chronological cutoffs. Training always contains strictly earlier observations than the test group it predicts; no shuffling occurs.

## Leakage checks

Verdict: **PASSED**

| Check | Status | Detail |
|---|---|---|
| temporal_leakage | passed | All 4 observations carry feature timestamps at or before their observation time. |
| target_leakage | passed | No next-review target review appears in any feature construction. |
| duplicate_observations | passed | All 4 observations are unique on (project_id, review_id, target). |
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

Only 4 chronological observations are available; at least 10 are required.

## Ablation results

Ablation evaluation unavailable: insufficient chronological observations.

## Calibration

Calibration metrics are not reported.
Reason: Calibration requires at least 20 walk-forward test predictions across at least two outcome classes; 0 predictions with 0 distinct outcome(s) are available. Metrics are withheld because they would not be meaningful at this size.

## Model artifact

No model artifact was written.
Reason: walk-forward evaluation is unavailable.

## Limitations, sample size, and confidence
- Sample size: 4 chronological observations across 2 project(s) and 3 review(s).
Confidence: none - no evaluation has been performed, so no performance confidence can be stated.
MISTIQ-APR is a project-specific sequential failure-prediction framework adapted
from the MISTIQ mistake-intelligence architecture. It is not claimed as a newly
invented universal machine-learning paradigm. Results are associations, not causal
claims, and cannot establish general software-engineering efficacy without more
real repositories with long chronological review histories.
Predictions describe historical association and are never certainties.
