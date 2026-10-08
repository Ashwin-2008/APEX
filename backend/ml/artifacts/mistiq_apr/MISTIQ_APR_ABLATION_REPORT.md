# MISTIQ-APR Ablation Report

Generated: 2026-10-07T17:39:47+00:00

Protocol: walk-forward temporal evaluation (features removed one group at a time,
retrained on the same expanding chronological cutoffs as the full model).
Only measured results appear below; no numbers are placeholders.

Walk-forward: 129 walk-forward cutoffs

| Variant | Removed feature group | Features | Accuracy | Macro F1 | Top-3 | Δ Macro F1 vs full |
|---|---|---:|---:|---:|---:|---:|
| Static only | all sequential features | 12 | 0.2906 | 0.1806 | 0.8741 | -0.0544 |
| Full MISTIQ-APR | — | 112 | 0.2952 | 0.2350 | 0.8787 | +0.0000 |
| MISTIQ-APR without frequency | failure frequency | 96 | 0.2952 | 0.2299 | 0.8787 | -0.0051 |
| MISTIQ-APR without recency | failure recency | 96 | 0.2952 | 0.2265 | 0.8787 | -0.0084 |
| MISTIQ-APR without repetition | failure repetition | 96 | 0.2952 | 0.2318 | 0.8787 | -0.0032 |
| MISTIQ-APR without transitions | failure transitions | 96 | 0.2952 | 0.2290 | 0.8810 | -0.0060 |
| MISTIQ-APR without component history | component history | 96 | 0.2952 | 0.2350 | 0.8787 | +0.0000 |
| MISTIQ-APR without failure diversity | recent failure diversity | 111 | 0.2929 | 0.2299 | 0.8787 | -0.0050 |
| MISTIQ-APR without change intensity | change intensity | 111 | 0.2952 | 0.2336 | 0.8810 | -0.0014 |
| MISTIQ-APR without testing weakness | testing weakness | 111 | 0.2952 | 0.2320 | 0.8787 | -0.0030 |
| MISTIQ-APR without severity trajectory | severity trajectory | 111 | 0.2952 | 0.2334 | 0.8787 | -0.0016 |

Interpretation: Δ Macro F1 compares each ablated variant against the full
MISTIQ-APR model on identical cutoffs. Positive values mean the ablated model
scored higher without that feature group on this dataset.
