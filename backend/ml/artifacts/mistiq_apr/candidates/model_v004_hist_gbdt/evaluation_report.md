# Candidate Model Evaluation Report: `model_v004_hist_gbdt`

- **Algorithm**: `hist_gradient_boosting` (Regularized HistGradientBoostingClassifier with shallow depth for small-to-medium tabular sequential datasets.)
- **Trained At**: `2026-10-28T16:26:38+00:00`
- **Dataset Version**: `v001` (`37fe20fb52fb11463924dedb9fb3d7264eaace4480a537c66542c81de2e76b9b`)
- **Curated Observations**: `129` across `9` real repository groups
- **Artifact SHA-256**: `53afa6d23e6945a5a660ea34ad5d9b78d4a15798f51ada91fbd92bf1596518c9`

## 1. Walk-Forward Temporal Comparison

| Model | Accuracy | Macro Precision | Macro Recall | Macro F1 | Weighted F1 | Top-2 Acc | Top-3 Acc | Log Loss |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Majority Class | 0.4472 | 0.1127 | 0.1281 | 0.1104 | 0.3533 | 0.5041 | 0.6098 | 19.9266 |
| Latest Failure | 0.2683 | 0.1399 | 0.1654 | 0.1078 | 0.3118 | 0.5447 | 0.5854 | 26.0982 |
| Static Logistic Regression | 0.3984 | 0.1917 | 0.1716 | 0.1686 | 0.3941 | 0.5772 | 0.6748 | 3.3993 |
| Random Forest | 0.4878 | 0.3369 | 0.2893 | 0.3077 | 0.4879 | 0.6016 | 0.6911 | 3.1509 |
| MISTIQ-APR | 0.4309 | 0.2635 | 0.2535 | 0.2560 | 0.4425 | 0.5691 | 0.6748 | 3.7585 |
| Histogram Gradient Boosting | 0.4309 | 0.2628 | 0.2305 | 0.2433 | 0.4347 | 0.5366 | 0.6585 | 3.4537 |

## 2. Unseen-Repository Generalization (Leave-One-Repository-Group-Out)

- **Sample Count**: `129`
- **Accuracy**: `0.4186`
- **Macro F1**: `0.2408`
- **Weighted F1**: `0.3910`
- **Top-2 Accuracy**: `0.5116`
- **Top-3 Accuracy**: `0.6434`

## 3. Calibration Summary

- **Status**: `None`
- **Brier Score**: `0.858998`
- **Expected Calibration Error (ECE)**: `0.319977`
