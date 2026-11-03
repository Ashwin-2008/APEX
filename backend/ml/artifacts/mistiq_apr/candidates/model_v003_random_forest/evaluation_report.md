# Candidate Model Evaluation Report: `model_v003_random_forest`

- **Algorithm**: `random_forest` (Balanced RandomForestClassifier (100 trees) over 112 static and sequential features.)
- **Trained At**: `2026-10-28T16:25:05+00:00`
- **Dataset Version**: `v001` (`37fe20fb52fb11463924dedb9fb3d7264eaace4480a537c66542c81de2e76b9b`)
- **Curated Observations**: `129` across `9` real repository groups
- **Artifact SHA-256**: `60fa2618cb180572207efc6986e538bb078f95c3ebb168eeff90cfd91b57d51c`

## 1. Walk-Forward Temporal Comparison

| Model | Accuracy | Macro Precision | Macro Recall | Macro F1 | Weighted F1 | Top-2 Acc | Top-3 Acc | Log Loss |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Majority Class | 0.4472 | 0.1127 | 0.1281 | 0.1104 | 0.3533 | 0.5041 | 0.6098 | 19.9266 |
| Latest Failure | 0.2683 | 0.1399 | 0.1654 | 0.1078 | 0.3118 | 0.5447 | 0.5854 | 26.0982 |
| Static Logistic Regression | 0.3984 | 0.1917 | 0.1716 | 0.1686 | 0.3941 | 0.5772 | 0.6748 | 3.3993 |
| Random Forest | 0.4878 | 0.3369 | 0.2893 | 0.3077 | 0.4879 | 0.6016 | 0.6911 | 3.1509 |
| MISTIQ-APR | 0.4309 | 0.2635 | 0.2535 | 0.2560 | 0.4425 | 0.5691 | 0.6748 | 3.7585 |

## 2. Unseen-Repository Generalization (Leave-One-Repository-Group-Out)

- **Sample Count**: `129`
- **Accuracy**: `0.4496`
- **Macro F1**: `0.2088`
- **Weighted F1**: `0.3874`
- **Top-2 Accuracy**: `0.5659`
- **Top-3 Accuracy**: `0.6589`

## 3. Calibration Summary

- **Status**: `None`
- **Brier Score**: `0.858998`
- **Expected Calibration Error (ECE)**: `0.319977`
