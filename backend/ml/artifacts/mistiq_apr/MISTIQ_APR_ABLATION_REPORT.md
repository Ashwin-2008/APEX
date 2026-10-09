# MISTIQ-APR Ablation Report

Generated: 2026-10-08T13:10:31+00:00

Protocol: walk-forward temporal evaluation (features removed one group at a time,
retrained on the same expanding chronological cutoffs as the full model).
Only measured results appear below; no numbers are placeholders.

Walk-forward: 188 walk-forward cutoffs

| Variant | Removed feature group | Features | Accuracy | Macro F1 | Top-3 | Δ Macro F1 vs full |
|---|---|---:|---:|---:|---:|---:|
| Static only | all sequential features | 12 | 0.3054 | 0.2187 | 0.8851 | -0.0250 |
| Full MISTIQ-APR | — | 112 | 0.3087 | 0.2437 | 0.8867 | +0.0000 |
| MISTIQ-APR without frequency | failure frequency | 96 | 0.3087 | 0.2415 | 0.8867 | -0.0022 |
| MISTIQ-APR without recency | failure recency | 96 | 0.3087 | 0.2432 | 0.8867 | -0.0005 |
| MISTIQ-APR without repetition | failure repetition | 96 | 0.3087 | 0.2353 | 0.8867 | -0.0084 |
| MISTIQ-APR without transitions | failure transitions | 96 | 0.3087 | 0.2427 | 0.8867 | -0.0011 |
| MISTIQ-APR without component history | component history | 96 | 0.3087 | 0.2437 | 0.8867 | +0.0000 |
| MISTIQ-APR without failure diversity | recent failure diversity | 111 | 0.3087 | 0.2420 | 0.8883 | -0.0017 |
| MISTIQ-APR without change intensity | change intensity | 111 | 0.3087 | 0.2347 | 0.8867 | -0.0090 |
| MISTIQ-APR without testing weakness | testing weakness | 111 | 0.3087 | 0.2416 | 0.8867 | -0.0021 |
| MISTIQ-APR without severity trajectory | severity trajectory | 111 | 0.3087 | 0.2421 | 0.8867 | -0.0016 |

Interpretation: Δ Macro F1 compares each ablated variant against the full
MISTIQ-APR model on identical cutoffs. Positive values mean the ablated model
scored higher without that feature group on this dataset.
