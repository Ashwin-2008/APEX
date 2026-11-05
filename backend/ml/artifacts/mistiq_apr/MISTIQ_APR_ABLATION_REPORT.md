# MISTIQ-APR Ablation Report

Generated: 2026-11-04T13:40:13+00:00

Protocol: walk-forward temporal evaluation (features removed one group at a time,
retrained on the same expanding chronological cutoffs as the full model).
Only measured results appear below; no numbers are placeholders.

Walk-forward: 267 walk-forward cutoffs

| Variant | Removed feature group | Features | Accuracy | Macro F1 | Top-3 | Δ Macro F1 vs full |
|---|---|---:|---:|---:|---:|---:|
| Static only | all sequential features | 12 | 0.3155 | 0.2336 | 0.8881 | -0.0205 |
| Full MISTIQ-APR | — | 112 | 0.3179 | 0.2541 | 0.8893 | +0.0000 |
| MISTIQ-APR without frequency | failure frequency | 96 | 0.3179 | 0.2509 | 0.8893 | -0.0032 |
| MISTIQ-APR without recency | failure recency | 96 | 0.3179 | 0.2527 | 0.8893 | -0.0014 |
| MISTIQ-APR without repetition | failure repetition | 96 | 0.3179 | 0.2456 | 0.8893 | -0.0085 |
| MISTIQ-APR without transitions | failure transitions | 96 | 0.3179 | 0.2539 | 0.8893 | -0.0002 |
| MISTIQ-APR without component history | component history | 96 | 0.3179 | 0.2541 | 0.8893 | +0.0000 |
| MISTIQ-APR without failure diversity | recent failure diversity | 111 | 0.3179 | 0.2523 | 0.8905 | -0.0018 |
| MISTIQ-APR without change intensity | change intensity | 111 | 0.3179 | 0.2442 | 0.8893 | -0.0099 |
| MISTIQ-APR without testing weakness | testing weakness | 111 | 0.3179 | 0.2517 | 0.8893 | -0.0024 |
| MISTIQ-APR without severity trajectory | severity trajectory | 111 | 0.3179 | 0.2484 | 0.8893 | -0.0057 |

Interpretation: Δ Macro F1 compares each ablated variant against the full
MISTIQ-APR model on identical cutoffs. Positive values mean the ablated model
scored higher without that feature group on this dataset.
