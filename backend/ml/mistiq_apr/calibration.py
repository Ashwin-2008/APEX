"""Probability calibration analysis for walk-forward MISTIQ-APR predictions.

Calibration metrics (Brier score, Expected Calibration Error, reliability
curve) are only reported when the pooled walk-forward test predictions are
large enough to be meaningful. Below the threshold the result explains exactly
why calibration is not reported.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .constants import MIN_CALIBRATION_SAMPLES
from .models import MISTIQ_APR

RELIABILITY_BINS = 10


def _extract_walk_forward_predictions(evaluation: dict[str, Any]) -> tuple[np.ndarray, list[str], list[str]]:
    """Pool per-cutoff probabilities and labels for the primary model."""
    walk_forward = evaluation.get("walk_forward") or {}
    classes = list(walk_forward.get("global_classes") or [])
    probability_rows: list[list[float]] = []
    actual: list[str] = []
    for cutoff in walk_forward.get("cutoffs") or []:
        model_record = (cutoff.get("models") or {}).get(MISTIQ_APR) or {}
        probability_rows.extend(model_record.get("probabilities") or [])
        actual.extend(model_record.get("actual") or [])
    return np.asarray(probability_rows, dtype=float), actual, classes


def run_calibration(evaluation: dict[str, Any]) -> dict[str, Any]:
    """Compute Brier score, ECE, and a reliability curve when data permits."""
    probabilities, actual, classes = _extract_walk_forward_predictions(evaluation)
    n_samples = len(actual)
    distinct_outcomes = sorted(set(actual))
    if n_samples < MIN_CALIBRATION_SAMPLES or len(distinct_outcomes) < 2:
        reason = (
            f"Calibration requires at least {MIN_CALIBRATION_SAMPLES} walk-forward test "
            f"predictions across at least two outcome classes; {n_samples} predictions "
            f"with {len(distinct_outcomes)} distinct outcome(s) are available. "
            "Metrics are withheld because they would not be meaningful at this size."
        )
        return {
            "available": False,
            "reason": reason,
            "sample_count": n_samples,
            "distinct_outcomes": len(distinct_outcomes),
        }
    if probabilities.shape[1] != len(classes):
        return {
            "available": False,
            "reason": "Probability columns do not align with the class list; calibration withheld.",
            "sample_count": n_samples,
            "distinct_outcomes": len(distinct_outcomes),
        }

    predicted_indices = probabilities.argmax(axis=1)
    predicted_labels = [classes[index] for index in predicted_indices]
    confidence = probabilities.max(axis=1)
    correct = np.array([prediction == outcome for prediction, outcome in zip(predicted_labels, actual)], dtype=float)

    # Multiclass Brier score: mean squared error between one-hot outcomes and
    # the full predicted probability vector (range 0..2).
    one_hot = np.zeros_like(probabilities)
    for row_index, outcome in enumerate(actual):
        if outcome in classes:
            one_hot[row_index, classes.index(outcome)] = 1.0
    brier = float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))

    # Top-label Expected Calibration Error over 10 equal-width confidence bins.
    bin_indices = np.minimum((confidence * RELIABILITY_BINS).astype(int), RELIABILITY_BINS - 1)
    ece = 0.0
    bins: list[dict[str, Any]] = []
    for bin_index in range(RELIABILITY_BINS):
        mask = bin_indices == bin_index
        count = int(mask.sum())
        lower = bin_index / RELIABILITY_BINS
        upper = (bin_index + 1) / RELIABILITY_BINS
        if count:
            mean_predicted = float(confidence[mask].mean())
            empirical_accuracy = float(correct[mask].mean())
            ece += (count / n_samples) * abs(empirical_accuracy - mean_predicted)
        else:
            mean_predicted = None
            empirical_accuracy = None
        bins.append({
            "lower": round(lower, 3),
            "upper": round(upper, 3),
            "count": count,
            "mean_predicted_confidence": None if mean_predicted is None else round(mean_predicted, 4),
            "empirical_accuracy": None if empirical_accuracy is None else round(empirical_accuracy, 4),
        })

    return {
        "available": True,
        "sample_count": n_samples,
        "classes": classes,
        "brier_score": round(brier, 6),
        "expected_calibration_error": round(float(ece), 6),
        "reliability_bins": bins,
        "methodology": (
            "Calibrated on pooled walk-forward test predictions for the MISTIQ-APR model. "
            "Brier score is the mean multiclass squared error (0..2, lower is better); "
            "ECE is the top-label expected calibration error over 10 confidence bins "
            "(lower is better)."
        ),
    }
