"""Prediction Calibration, Uncertainty Assessment, and Abstention Engine (Phase 4.1).

Determines whether predictions are statistically trustworthy and decides when the system
must abstain:
- PREDICTION_AVAILABLE
- INSUFFICIENT_DATA
- LOW_CONFIDENCE
- OUT_OF_DISTRIBUTION
- CALIBRATION_UNCERTAIN
- MODEL_UNAVAILABLE
- NOT_SUPPORTED
"""
from __future__ import annotations

import math
from typing import Any
import numpy as np

from .constants import (
    CALIBRATION_THRESHOLD_ECE,
    DEFAULT_ABSTENTION_THRESHOLD,
    MIN_CALIBRATION_SAMPLE_SIZE,
    MIN_EVIDENCE_FOR_PREDICTION,
    PredictionState,
)


class PredictionCalibrator:
    """Manages confidence calibration, out-of-distribution detection, and abstention."""

    @classmethod
    def evaluate_state(
        cls,
        *,
        confidence: float,
        evidence_count: int,
        is_calibrated: bool = True,
        calibration_samples: int | None = None,
        feature_vector: dict[str, float] | None = None,
        feature_bounds: dict[str, tuple[float, float]] | None = None,
        min_evidence_threshold: int = MIN_EVIDENCE_FOR_PREDICTION,
        abstention_threshold: float = DEFAULT_ABSTENTION_THRESHOLD,
        model_available: bool = True,
        task_supported: bool = True,
    ) -> tuple[PredictionState, dict[str, Any]]:
        """Evaluates prediction reliability and returns state + diagnostic rationale."""
        diagnostics: dict[str, Any] = {
            "confidence": round(confidence, 4),
            "evidence_count": evidence_count,
            "is_calibrated": is_calibrated,
            "abstention_threshold": abstention_threshold,
        }

        # Check 0: Task support & Model availability
        if not task_supported:
            diagnostics["reason"] = "Task is not supported by predictive intelligence."
            return PredictionState.NOT_SUPPORTED, diagnostics

        if not model_available:
            diagnostics["reason"] = "No trained or calibrated model is available for this task."
            return PredictionState.MODEL_UNAVAILABLE, diagnostics

        # Check 1: Insufficient Data (zero findings or below minimum evidence)
        if evidence_count < min_evidence_threshold:
            diagnostics["reason"] = f"Insufficient historical observations ({evidence_count} < {min_evidence_threshold}) for reliable inference."
            return PredictionState.INSUFFICIENT_DATA, diagnostics

        # Check 2: Out of Distribution (OOD) & Extreme Feature Values
        if feature_vector and feature_bounds:
            ood_features = []
            for feat_name, val in feature_vector.items():
                if not isinstance(val, (int, float)) or not math.isfinite(val):
                    ood_features.append(f"{feat_name} (non-finite)")
                    continue
                if feat_name in feature_bounds:
                    lower, upper = feature_bounds[feat_name]
                    # Exceeds 3x bound or falls far below historical range
                    if val > upper * 3.0 and upper > 0:
                        ood_features.append(feat_name)
                    elif val < lower and lower >= 0:
                        ood_features.append(feat_name)
            if ood_features:
                diagnostics["ood_features"] = ood_features
                diagnostics["reason"] = f"Features {ood_features[:3]} fall outside training distribution."
                return PredictionState.OUT_OF_DISTRIBUTION, diagnostics

        # Check 3: Calibration Uncertainty (Small validation sample or uncalibrated probabilities)
        if calibration_samples is not None and calibration_samples < MIN_CALIBRATION_SAMPLE_SIZE:
            diagnostics["reason"] = (
                f"Calibration sample size ({calibration_samples} < {MIN_CALIBRATION_SAMPLE_SIZE}) "
                f"is insufficient to verify empirical probability calibration."
            )
            return PredictionState.CALIBRATION_UNCERTAIN, diagnostics

        # Check 4: Low Confidence / High Uncertainty
        if confidence < abstention_threshold:
            diagnostics["reason"] = f"Confidence {confidence:.2f} is below reliability threshold {abstention_threshold:.2f}."
            return PredictionState.LOW_CONFIDENCE, diagnostics

        return PredictionState.PREDICTION_AVAILABLE, diagnostics

    @staticmethod
    def platt_scale_probability(raw_prob: float, a: float = 1.0, b: float = 0.0) -> float:
        """Applies sigmoid Platt scaling to raw uncalibrated probabilities."""
        logit = np.log(max(1e-6, min(1.0 - 1e-6, raw_prob))) - np.log(1.0 - max(1e-6, min(1.0 - 1e-6, raw_prob)))
        scaled = 1.0 / (1.0 + np.exp(-(a * logit + b)))
        return round(float(scaled), 4)

    @classmethod
    def calculate_abstention_metrics(
        cls,
        eval_records: list[dict[str, Any]],
    ) -> dict[str, float]:
        """Calculates Abstention Rate, Coverage, and Error Rate among non-abstained predictions."""
        total = len(eval_records)
        if total == 0:
            return {"abstention_rate": 0.0, "coverage": 0.0, "non_abstained_error_rate": 0.0}

        abstained_count = sum(
            1 for r in eval_records
            if r.get("state") in (
                PredictionState.INSUFFICIENT_DATA.value,
                PredictionState.LOW_CONFIDENCE.value,
                PredictionState.OUT_OF_DISTRIBUTION.value,
                PredictionState.CALIBRATION_UNCERTAIN.value,
                PredictionState.MODEL_UNAVAILABLE.value,
            )
        )
        non_abstained = [
            r for r in eval_records
            if r.get("state") == PredictionState.PREDICTION_AVAILABLE.value
        ]

        coverage = len(non_abstained) / total
        abstention_rate = abstained_count / total

        if non_abstained:
            errors = sum(1 for r in non_abstained if r.get("predicted_outcome") != r.get("ground_truth"))
            error_rate = errors / len(non_abstained)
        else:
            error_rate = 0.0

        return {
            "total_evaluations": float(total),
            "abstained_count": float(abstained_count),
            "abstention_rate": round(float(abstention_rate), 4),
            "coverage": round(float(coverage), 4),
            "non_abstained_error_rate": round(float(error_rate), 4),
        }
