"""Model Drift Monitoring and Integrity Engine (Phase 4.1).

Monitors:
1. Data Drift (feature distribution shifts)
2. Concept Drift (class distribution and target relationship shifts)
3. Performance Degradation (statistically meaningful drop in accuracy)

Guarantees:
- Distinguishes data drift from concept drift.
- Strictly guards against declaring drift when sample size is insufficient (< 20).
"""
from __future__ import annotations

import math
from typing import Any
from collections import Counter
import numpy as np

MIN_MONITORING_SAMPLE_SIZE = 20


class ModelDriftMonitor:
    """Monitors live predictions and feedback for statistically genuine drift."""

    @classmethod
    def evaluate_drift(
        cls,
        *,
        reference_features: list[dict[str, float]],
        current_features: list[dict[str, float]],
        reference_classes: list[str],
        current_predictions: list[str],
        current_feedback_errors: list[bool] | None = None,
    ) -> dict[str, Any]:
        """Evaluates whether data drift, concept drift, or performance degradation has occurred."""
        n_ref = len(reference_features)
        n_cur = len(current_features)

        # Sample size guard
        if n_cur < MIN_MONITORING_SAMPLE_SIZE:
            return {
                "status": "INSUFFICIENT_MONITORING_SAMPLE",
                "sample_size": n_cur,
                "minimum_required": MIN_MONITORING_SAMPLE_SIZE,
                "data_drift_detected": False,
                "concept_drift_detected": False,
                "performance_degradation_detected": False,
                "message": (
                    f"Monitoring sample size ({n_cur} < {MIN_MONITORING_SAMPLE_SIZE}) "
                    "is statistically insufficient to establish genuine model drift."
                ),
            }

        # 1. Data Drift: Feature shift using Population Stability Index (PSI) proxy
        drifted_features = []
        feature_names = sorted(reference_features[0].keys()) if reference_features else []

        for feat in feature_names[:10]:
            ref_vals = [f.get(feat, 0.0) for f in reference_features]
            cur_vals = [f.get(feat, 0.0) for f in current_features]
            mean_ref = float(np.mean(ref_vals)) if ref_vals else 0.0
            mean_cur = float(np.mean(cur_vals)) if cur_vals else 0.0
            std_ref = float(np.std(ref_vals)) or 1.0

            # Normalized difference
            z_diff = abs(mean_cur - mean_ref) / std_ref
            if z_diff >= 2.5:  # Statistically significant mean shift
                drifted_features.append({"feature": feat, "z_score_diff": round(z_diff, 2)})

        data_drift = len(drifted_features) >= 2

        # 2. Concept Drift: Class distribution shift
        ref_dist = Counter(reference_classes)
        cur_dist = Counter(current_predictions)
        all_classes = sorted(list(set(ref_dist.keys()) | set(cur_dist.keys())))

        p_ref = [ref_dist.get(c, 0) / max(1, len(reference_classes)) for c in all_classes]
        p_cur = [cur_dist.get(c, 0) / max(1, n_cur) for c in all_classes]

        # Total Variation Distance
        tvd = 0.5 * sum(abs(p - q) for p, q in zip(p_ref, p_cur))
        concept_drift = tvd >= 0.35

        # 3. Performance Degradation (from feedback if available)
        perf_degradation = False
        if current_feedback_errors and len(current_feedback_errors) >= MIN_MONITORING_SAMPLE_SIZE:
            error_rate = sum(1 for e in current_feedback_errors if e) / len(current_feedback_errors)
            if error_rate >= 0.50:  # Excessive error rate reported by users
                perf_degradation = True

        status = "DRIFT_DETECTED" if (data_drift or concept_drift or perf_degradation) else "STABLE"

        return {
            "status": status,
            "sample_size": n_cur,
            "minimum_required": MIN_MONITORING_SAMPLE_SIZE,
            "data_drift_detected": data_drift,
            "drifted_features": drifted_features,
            "concept_drift_detected": concept_drift,
            "total_variation_distance": round(tvd, 4),
            "performance_degradation_detected": perf_degradation,
            "recommended_action": (
                "Review feature distributions and consider retraining candidate model."
                if status == "DRIFT_DETECTED"
                else "No retraining needed; predictions are within expected distribution."
            ),
        }

