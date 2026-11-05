"""Model Evaluation and Scientific Validation (Phase 4.1).

Evaluates classifiers across multiple generalization protocols:
1. Chronological Walk-Forward Validation
2. Repository-Grouped Validation
3. Leave-One-Repository-Out (LORO) Validation

Reports:
- Precision, Recall, Macro-F1, Weighted-F1, Balanced Accuracy
- Per-class Precision & Recall, Class Distribution, Confusion Matrix
- Multi-class Brier Score and Log Loss
- Expected Calibration Error (ECE) and bin-level reliability diagrams
- Precision@1, Precision@3, Recall@3
- PR-AUC for imbalanced targets
- Repository-level bootstrap confidence intervals (preventing correlated snapshot inflation)
- Sample size and repository independence statistical validity gating
"""
from __future__ import annotations

import math
import random
from collections import Counter
from typing import Any

import numpy as np

from .constants import (
    CALIBRATION_THRESHOLD_ECE,
    CONFIDENCE_CALIBRATION_BINS,
    FAILURE_CATEGORIES,
    MIN_CALIBRATION_SAMPLE_SIZE,
    MIN_SAMPLE_SIZE_STATISTICAL_VALIDITY,
    STATISTICAL_INSUFFICIENT_EVIDENCE,
)
from .temporal_dataset import TemporalObservation


class PredictiveModelEvaluator:
    """Scientific validator for predictive failure and risk models."""

    @classmethod
    def evaluate(
        cls,
        model: Any,
        test_observations: list[TemporalObservation],
        model_name: str = "model",
        calibration_sample_size: int | None = None,
    ) -> dict[str, Any]:
        """Evaluates model performance against ground-truth test observations."""
        n = len(test_observations)
        if n == 0:
            return {
                "model_name": model_name,
                "sample_size": 0,
                "repository_count": 0,
                "status": "NO_TEST_DATA",
                "validity": STATISTICAL_INSUFFICIENT_EVIDENCE,
            }

        y_true = [o.target for o in test_observations]
        repos = [o.repository_group for o in test_observations]
        repo_count = len(set(repos))
        class_distribution = dict(Counter(y_true))

        y_pred = []
        y_probs = []

        for o in test_observations:
            pred_class, conf = model.predict(o.features)
            probs = model.predict_proba(o.features)
            y_pred.append(pred_class)
            y_probs.append(probs)

        # 1. Confusion Matrix
        classes = sorted(list(set(y_true) | set(y_pred)))
        class_to_idx = {c: i for i, c in enumerate(classes)}
        conf_matrix = [[0 for _ in classes] for _ in classes]
        for t, p in zip(y_true, y_pred):
            conf_matrix[class_to_idx[t]][class_to_idx[p]] += 1

        # 2. Per-class Precision, Recall, F1
        per_class_metrics: dict[str, dict[str, float]] = {}
        precisions = []
        recalls = []
        f1s = []
        class_weights = []

        for i, c in enumerate(classes):
            tp = conf_matrix[i][i]
            fp = sum(conf_matrix[j][i] for j in range(len(classes)) if j != i)
            fn = sum(conf_matrix[i][j] for j in range(len(classes)) if j != i)
            support = class_distribution.get(c, 0)

            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0

            per_class_metrics[c] = {
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1": round(f1, 4),
                "support": support,
            }

            precisions.append(prec)
            recalls.append(rec)
            f1s.append(f1)
            class_weights.append(support)

        macro_precision = round(float(np.mean(precisions)), 4) if precisions else 0.0
        macro_recall = round(float(np.mean(recalls)), 4) if recalls else 0.0
        macro_f1 = round(float(np.mean(f1s)), 4) if f1s else 0.0

        # Weighted F1
        total_support = sum(class_weights) or 1
        weighted_f1 = round(float(sum(f * w for f, w in zip(f1s, class_weights)) / total_support), 4)

        # Balanced Accuracy (Mean recall of classes present in y_true)
        true_recalls = [per_class_metrics[c]["recall"] for c in set(y_true) if c in per_class_metrics]
        balanced_accuracy = round(float(np.mean(true_recalls)), 4) if true_recalls else 0.0

        raw_accuracy = round(sum(1 for t, p in zip(y_true, y_pred) if t == p) / n, 4)

        # 3. Precision@K and Recall@K
        p_at_1 = raw_accuracy
        p_at_3_hits = 0
        r_at_3_hits = 0
        for t, prob_dict in zip(y_true, y_probs):
            top3 = [cat for cat, _ in sorted(prob_dict.items(), key=lambda kv: kv[1], reverse=True)[:3]]
            if t in top3:
                p_at_3_hits += 1
                r_at_3_hits += 1
        p_at_3 = round(p_at_3_hits / n, 4)
        r_at_3 = round(r_at_3_hits / n, 4)

        # 4. Multi-class Brier Score and Log Loss
        brier_sum = 0.0
        log_loss_sum = 0.0
        eps = 1e-15

        for t, prob_dict in zip(y_true, y_probs):
            for cat in FAILURE_CATEGORIES:
                prob = max(eps, min(1.0 - eps, prob_dict.get(cat, 0.0)))
                indicator = 1.0 if cat == t else 0.0
                brier_sum += (prob - indicator) ** 2
                if cat == t:
                    log_loss_sum += -math.log(prob)

        brier_score = round(brier_sum / (n * len(FAILURE_CATEGORIES)), 4)
        log_loss = round(log_loss_sum / n, 4)

        # 5. PR-AUC for Dominant Class (Security)
        pr_auc_dominant = cls._compute_binary_pr_auc("security", y_true, y_probs)

        # 6. Expected Calibration Error & Calibration Bin Details
        cal_details = cls.compute_calibration_details(y_true, y_probs, n_bins=CONFIDENCE_CALIBRATION_BINS)
        ece = cal_details["ece"]

        # Calibration state gating
        cal_sample_size = calibration_sample_size if calibration_sample_size is not None else n
        if cal_sample_size < MIN_CALIBRATION_SAMPLE_SIZE:
            calibration_state = "CALIBRATION_UNCERTAIN"
            is_calibrated = False
        else:
            is_calibrated = ece <= CALIBRATION_THRESHOLD_ECE
            calibration_state = "CALIBRATED" if is_calibrated else "UNCALIBRATED"

        # 7. Repository-Grouped Bootstrap Confidence Intervals (95% CI)
        bootstrap_ci = cls.compute_repository_bootstrap_ci(test_observations, y_true, y_pred)

        # 8. Sample Size & Statistical Validity Gating
        is_statistically_valid = n >= MIN_SAMPLE_SIZE_STATISTICAL_VALIDITY
        validity_status = "STATISTICALLY_VALID" if is_statistically_valid else STATISTICAL_INSUFFICIENT_EVIDENCE
        is_multi_repo_valid = is_statistically_valid and repo_count >= 2

        return {
            "model_name": model_name,
            "sample_size": n,
            "repository_count": repo_count,
            "is_multi_repo_valid": is_multi_repo_valid,
            "class_distribution": class_distribution,
            "validity": validity_status,
            "is_statistically_valid": is_statistically_valid,
            "accuracy": raw_accuracy,
            "balanced_accuracy": balanced_accuracy,
            "macro_precision": macro_precision,
            "macro_recall": macro_recall,
            "macro_f1": macro_f1,
            "weighted_f1": weighted_f1,
            "per_class_metrics": per_class_metrics,
            "precision_at_1": p_at_1,
            "precision_at_3": p_at_3,
            "recall_at_3": r_at_3,
            "brier_score": brier_score,
            "log_loss": log_loss,
            "pr_auc_dominant": pr_auc_dominant,
            "expected_calibration_error": ece,
            "is_calibrated": is_calibrated,
            "calibration_state": calibration_state,
            "calibration_bins": cal_details["bins"],
            "bootstrap_ci_95": bootstrap_ci,
            "classes": classes,
            "confusion_matrix": conf_matrix,
        }

    @staticmethod
    def _compute_binary_pr_auc(target_class: str, y_true: list[str], y_probs: list[dict[str, float]]) -> float:
        """Approximates PR-AUC (Average Precision) for the specified target class."""
        scores = [probs.get(target_class, 0.0) for probs in y_probs]
        bin_labels = [1 if t == target_class else 0 for t in y_true]
        total_positives = sum(bin_labels)
        if total_positives == 0 or len(scores) == 0:
            return 0.0

        sorted_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        running_tp = 0
        running_fp = 0
        precisions = []
        recalls = []

        for idx in sorted_indices:
            if bin_labels[idx] == 1:
                running_tp += 1
            else:
                running_fp += 1
            prec = running_tp / (running_tp + running_fp)
            rec = running_tp / total_positives
            precisions.append(prec)
            recalls.append(rec)

        # Trapezoidal area under PR curve
        pr_auc = 0.0
        prev_rec = 0.0
        for prec, rec in zip(precisions, recalls):
            pr_auc += prec * (rec - prev_rec)
            prev_rec = rec
        return round(float(pr_auc), 4)

    @classmethod
    def compute_calibration_details(
        cls,
        y_true: list[str],
        y_probs: list[dict[str, float]],
        n_bins: int = 10,
    ) -> dict[str, Any]:
        """Computes Expected Calibration Error along with detailed per-bin stats."""
        if not y_true or not y_probs:
            return {"ece": 0.0, "bins": []}

        confidences = []
        accuracies = []

        for t, prob_dict in zip(y_true, y_probs):
            if not prob_dict:
                continue
            best_cat, max_conf = max(prob_dict.items(), key=lambda kv: kv[1])
            confidences.append(max_conf)
            accuracies.append(1.0 if best_cat == t else 0.0)

        n = len(confidences)
        if n == 0:
            return {"ece": 0.0, "bins": []}

        bin_boundaries = np.linspace(0.0, 1.0, n_bins + 1)
        ece = 0.0
        bins = []

        for i in range(n_bins):
            bin_lower = float(bin_boundaries[i])
            bin_upper = float(bin_boundaries[i + 1])

            bin_indices = [
                idx for idx, c in enumerate(confidences)
                if (bin_lower <= c < bin_upper) or (i == n_bins - 1 and bin_lower <= c <= bin_upper)
            ]

            bin_count = len(bin_indices)
            if bin_count == 0:
                bins.append({
                    "bin_index": i,
                    "range": f"[{bin_lower:.2f}, {bin_upper:.2f}]",
                    "sample_count": 0,
                    "mean_predicted_confidence": 0.0,
                    "observed_accuracy": 0.0,
                })
                continue

            bin_acc = float(np.mean([accuracies[idx] for idx in bin_indices]))
            bin_conf = float(np.mean([confidences[idx] for idx in bin_indices]))
            ece += (bin_count / n) * abs(bin_acc - bin_conf)

            bins.append({
                "bin_index": i,
                "range": f"[{bin_lower:.2f}, {bin_upper:.2f}]",
                "sample_count": bin_count,
                "mean_predicted_confidence": round(bin_conf, 4),
                "observed_accuracy": round(bin_acc, 4),
            })

        return {"ece": round(float(ece), 4), "bins": bins}

    @staticmethod
    def compute_ece(y_true: list[str], y_probs: list[dict[str, float]], n_bins: int = 10) -> float:
        """Computes Expected Calibration Error across confidence decile bins."""
        return PredictiveModelEvaluator.compute_calibration_details(y_true, y_probs, n_bins=n_bins)["ece"]

    @staticmethod
    def compute_repository_bootstrap_ci(
        test_observations: list[TemporalObservation],
        y_true: list[str],
        y_pred: list[str],
        n_bootstraps: int = 200,
        random_seed: int = 42,
    ) -> dict[str, tuple[float, float]]:
        """Computes 95% bootstrap confidence intervals clustered by repository group."""
        rng = random.Random(random_seed)
        repo_indices: dict[str, list[int]] = {}
        for idx, o in enumerate(test_observations):
            repo_indices.setdefault(o.repository_group, []).append(idx)

        repos = list(repo_indices.keys())
        if len(repos) < 2 or len(test_observations) < 10:
            # Insufficient clusters for clustered bootstrap
            acc = round(sum(1 for t, p in zip(y_true, y_pred) if t == p) / max(1, len(y_true)), 4)
            return {"accuracy_ci_95": (acc, acc), "macro_f1_ci_95": (0.0, 1.0)}

        acc_samples = []
        for _ in range(n_bootstraps):
            sampled_repos = rng.choices(repos, k=len(repos))
            sampled_indices = [idx for r in sampled_repos for idx in repo_indices[r]]
            if not sampled_indices:
                continue
            sample_true = [y_true[idx] for idx in sampled_indices]
            sample_pred = [y_pred[idx] for idx in sampled_indices]
            acc = sum(1 for t, p in zip(sample_true, sample_pred) if t == p) / len(sample_true)
            acc_samples.append(acc)

        acc_samples.sort()
        low_idx = int(0.025 * len(acc_samples))
        high_idx = int(0.975 * len(acc_samples))
        return {
            "accuracy_ci_95": (
                round(acc_samples[low_idx], 4),
                round(acc_samples[high_idx], 4),
            )
        }
