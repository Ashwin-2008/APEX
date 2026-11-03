# Candidate Model Evaluation Report: `model_v002_extra_trees`

- **Algorithm**: `extra_trees` (Balanced ExtraTreesClassifier with randomized splits to reduce variance on correlated sequential features.)
- **Trained At**: `2026-10-28T16:22:50+00:00`
- **Dataset Version**: `v001` (`37fe20fb52fb11463924dedb9fb3d7264eaace4480a537c66542c81de2e76b9b`)
- **Curated Observations**: `129` across `9` real repository groups
- **Artifact SHA-256**: `1aae0e95c908a939836ea3fc8a2d1bf66bb7d570d7e4d6708877972845ad00e9`

## 1. Walk-Forward Temporal Comparison

| Model | Accuracy | Macro Precision | Macro Recall | Macro F1 | Weighted F1 | Top-2 Acc | Top-3 Acc | Log Loss |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Majority Class | 0.4472 | 0.1127 | 0.1281 | 0.1104 | 0.3533 | 0.5041 | 0.6098 | 19.9266 |
| Latest Failure | 0.2683 | 0.1399 | 0.1654 | 0.1078 | 0.3118 | 0.5447 | 0.5854 | 26.0982 |
| Static Logistic Regression | 0.3984 | 0.1917 | 0.1716 | 0.1686 | 0.3941 | 0.5772 | 0.6748 | 3.3993 |
| Random Forest | 0.4878 | 0.3369 | 0.2893 | 0.3077 | 0.4879 | 0.6016 | 0.6911 | 3.1509 |
| MISTIQ-APR | 0.4309 | 0.2635 | 0.2535 | 0.2560 | 0.4425 | 0.5691 | 0.6748 | 3.7585 |
| Extra Trees Classifier | 0.4472 | 0.3176 | 0.3058 | 0.3096 | 0.4736 | 0.5772 | 0.6911 | 3.5572 |

## 2. Unseen-Repository Generalization (Leave-One-Repository-Group-Out)

- **Sample Count**: `129`
- **Accuracy**: `0.3643`
- **Macro F1**: `0.1918`
- **Weighted F1**: `0.3685`
- **Top-2 Accuracy**: `0.5504`
- **Top-3 Accuracy**: `0.6434`

## 3. Calibration Summary

- **Status**: `None`
- **Brier Score**: `0.858998`
- **Expected Calibration Error (ECE)**: `0.319977`
