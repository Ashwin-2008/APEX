# MISTIQ-APR Ablation Report

Generated: 2026-10-09T04:33:36+00:00

Protocol: walk-forward temporal evaluation (features removed one group at a time,
retrained on the same expanding chronological cutoffs as the full model).
Only measured results appear below; no numbers are placeholders.

Walk-forward: 207 walk-forward cutoffs

| Variant | Removed feature group | Features | Accuracy | Macro F1 | Top-3 | Δ Macro F1 vs full |
|---|---|---:|---:|---:|---:|---:|
| Static only | all sequential features | 12 | 0.3125 | 0.2319 | 0.8872 | -0.0194 |
| Full MISTIQ-APR | — | 112 | 0.3155 | 0.2512 | 0.8887 | +0.0000 |
| MISTIQ-APR without frequency | failure frequency | 96 | 0.3155 | 0.2492 | 0.8887 | -0.0021 |
| MISTIQ-APR without recency | failure recency | 96 | 0.3155 | 0.2511 | 0.8887 | -0.0001 |
| MISTIQ-APR without repetition | failure repetition | 96 | 0.3155 | 0.2422 | 0.8887 | -0.0091 |
| MISTIQ-APR without transitions | failure transitions | 96 | 0.3155 | 0.2498 | 0.8887 | -0.0014 |
| MISTIQ-APR without component history | component history | 96 | 0.3155 | 0.2512 | 0.8887 | +0.0000 |
| MISTIQ-APR without failure diversity | recent failure diversity | 111 | 0.3155 | 0.2487 | 0.8902 | -0.0025 |
| MISTIQ-APR without change intensity | change intensity | 111 | 0.3155 | 0.2414 | 0.8887 | -0.0099 |
| MISTIQ-APR without testing weakness | testing weakness | 111 | 0.3155 | 0.2485 | 0.8887 | -0.0027 |
| MISTIQ-APR without severity trajectory | severity trajectory | 111 | 0.3155 | 0.2489 | 0.8887 | -0.0024 |

Interpretation: Δ Macro F1 compares each ablated variant against the full
MISTIQ-APR model on identical cutoffs. Positive values mean the ablated model
scored higher without that feature group on this dataset.
