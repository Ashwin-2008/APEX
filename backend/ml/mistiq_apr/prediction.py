"""Online next-failure prediction from a validated saved artifact only.

This module never trains. It loads a persisted MISTIQ-APR bundle, scores the
current feature vector, and reports probabilities with supporting features,
human-readable evidence explanations, uncertainty indicators, and explicit
separation of score semantics (model score, calibrated probability, historical
frequency, deterministic risk score, and severity).
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .artifacts import MISTIQAPRModelArtifact
from .constants import ALL_FEATURE_NAMES, FAILURE_LABELS, FEATURE_BLOCKS, MODEL_NAME

PREDICTION_DISCLAIMER = (
    "Prediction is based on historical project observations and is not a certainty."
)
TOP_SUPPORTING_FEATURES = 5


def _describe_feature(feature_name: str, value: float) -> tuple[str, str]:
    """Return ``(feature_group, human_readable_description)`` for a feature."""
    group = "other"
    for g_name, g_cols in FEATURE_BLOCKS.items():
        if feature_name in g_cols:
            group = g_name
            break

    if feature_name.startswith("latest_failure_"):
        cat = feature_name.removeprefix("latest_failure_")
        lbl = FAILURE_LABELS.get(cat, cat)
        return group, f"Most recent failure category was {lbl} ({'active' if value > 0 else 'inactive'})"
    if feature_name.startswith("seq_freq_"):
        cat = feature_name.removeprefix("seq_freq_")
        lbl = FAILURE_LABELS.get(cat, cat)
        return group, f"Historical occurrence count/rate of {lbl} findings ({value:.2f})"
    if feature_name.startswith("seq_recency_"):
        cat = feature_name.removeprefix("seq_recency_")
        lbl = FAILURE_LABELS.get(cat, cat)
        return group, f"Recency distance of {lbl} across prior reviews ({value:.2f})"
    if feature_name.startswith("seq_repetition_"):
        cat = feature_name.removeprefix("seq_repetition_")
        lbl = FAILURE_LABELS.get(cat, cat)
        return group, f"Consecutive review streak of {lbl} findings ({int(round(value))} reviews)"
    if feature_name.startswith("seq_transition_"):
        cat = feature_name.removeprefix("seq_transition_")
        lbl = FAILURE_LABELS.get(cat, cat)
        return group, f"Sequential transition count involving {lbl} ({value:.2f})"
    if feature_name.startswith("seq_component_"):
        cat = feature_name.removeprefix("seq_component_")
        lbl = FAILURE_LABELS.get(cat, cat)
        return group, f"Component/file-localized {lbl} findings in history ({value:.2f})"
    if feature_name == "static_total_findings":
        return group, f"Total active deterministic findings in latest review ({int(round(value))})"
    if feature_name.startswith("static_") and feature_name.endswith("_findings"):
        sev = feature_name.removeprefix("static_").removesuffix("_findings")
        return group, f"Active {sev}-severity findings in latest review ({int(round(value))})"
    if feature_name.startswith("static_") and feature_name.endswith("_risk"):
        domain = feature_name.removeprefix("static_").removesuffix("_risk")
        return group, f"Deterministic {domain} high/critical risk signal ({value:.2f})"
    if feature_name == "seq_severity_trajectory":
        return group, f"Severity trajectory vs. previous review ({value:+.1f})"
    if feature_name == "seq_failure_diversity_recent":
        return group, f"Distinct failure categories in recent window ({value:.2f})"
    if feature_name == "seq_change_intensity":
        return group, f"Recent repository churn / changed file intensity ({value:.2f})"
    if feature_name == "seq_testing_weakness":
        return group, f"Testing weakness indicator in current review ({value:.2f})"
    return group, f"{feature_name} = {value:.3f}"


def predict_next_failure(
    artifact: MISTIQAPRModelArtifact,
    features: dict[str, float],
    top_k: int = 3,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one feature vector with the artifact's trained pipeline."""
    row = np.array([[features.get(name, 0.0) for name in ALL_FEATURE_NAMES]], dtype=float)
    probabilities = artifact.model.predict_proba(row)[0]
    classes = [str(name) for name in artifact.model.classes_]
    order = np.argsort(probabilities)[::-1][: max(1, min(top_k, len(classes)))]

    eval_meta = (artifact.metadata or {}).get("evaluation_metadata") or {}
    calibration_meta = (artifact.metadata or {}).get("calibration_summary") or {}
    is_calibrated = bool(calibration_meta.get("available", False))

    hist_freqs = (evidence or {}).get("category_frequencies") or {}
    total_hist = max(1, sum(int(v) for v in hist_freqs.values()))

    predictions: list[dict[str, Any]] = []
    for rank_idx, index in enumerate(order, start=1):
        cat = classes[index]
        raw_score = round(float(probabilities[index]), 6)
        hist_count = int(hist_freqs.get(cat, int(round(features.get(f"seq_freq_{cat}", 0.0)))))
        hist_rate = round(hist_count / float(total_hist), 4) if hist_freqs else round(float(features.get(f"seq_freq_{cat}", 0.0)), 4)
        det_risk = round(
            float(
                features.get(
                    f"static_{'config' if cat == 'configuration' else cat}_risk",
                    features.get(f"seq_component_{cat}", 0.0),
                )
            ),
            4,
        )
        predictions.append(
            {
                "rank": rank_idx,
                "category": cat,
                "label": FAILURE_LABELS.get(cat, cat),
                "probability": raw_score,
                "model_score": raw_score,
                "calibrated_probability": raw_score if is_calibrated else None,
                "historical_frequency": hist_rate,
                "historical_occurrences": hist_count,
                "deterministic_risk_score": det_risk,
            }
        )

    predicted = predictions[0]["category"] if predictions else None
    supporting = _supporting_features(artifact, row[0], predicted, classes)

    # Compute Shannon entropy and top-1 margin as honest uncertainty indicators
    clipped = np.clip(probabilities, 1e-12, 1.0)
    entropy = float(-np.sum(clipped * np.log(clipped)))
    max_entropy = float(np.log(max(len(classes), 2)))
    normalized_entropy = round(entropy / max_entropy, 4) if max_entropy > 0 else 0.0
    sorted_probs = np.sort(probabilities)[::-1]
    top1_margin = round(float(sorted_probs[0] - sorted_probs[1]), 4) if len(sorted_probs) >= 2 else 1.0
    review_count = int((evidence or {}).get("review_count", 1))
    uncertainty_level = (
        "high"
        if review_count < 2 or normalized_entropy > 0.75 or top1_margin < 0.15
        else "moderate"
        if review_count < 4 or normalized_entropy > 0.45 or top1_margin < 0.30
        else "low"
    )

    return {
        "predicted_category": predicted,
        "predicted_label": FAILURE_LABELS.get(predicted, predicted) if predicted else None,
        "predictions": predictions,
        "supporting_features": supporting,
        "uncertainty": {
            "level": uncertainty_level,
            "normalized_entropy": normalized_entropy,
            "top_1_margin": top1_margin,
            "project_review_count": review_count,
            "is_calibrated_probability": is_calibrated,
            "calibration_note": (
                "Probabilities are evaluated with empirical calibration bins."
                if is_calibrated
                else "Treat scores as relative model rankings rather than calibrated defect probabilities."
            ),
        },
        "score_semantics": {
            "model_score": "Relative class score output by the trained MISTIQ-APR classifier.",
            "calibrated_probability": "Empirically calibrated probability (only populated when calibration sample threshold >= 20 is satisfied).",
            "historical_frequency": "Observed fraction of past project findings belonging to this category.",
            "deterministic_risk_score": "Static rule-based risk signal extracted from current review findings.",
            "severity": "Impact tier (critical/high/medium/low) of verified deterministic findings; distinct from likelihood.",
        },
        "model": {
            "name": MODEL_NAME,
            "version": artifact.metadata.get("version"),
            "candidate_id": artifact.metadata.get("candidate_id"),
            "algorithm": artifact.metadata.get("algorithm", "logistic_regression"),
            "trained_at": artifact.metadata.get("trained_at"),
            "training_observations": artifact.metadata.get("training_observations"),
            "dataset_hash": artifact.metadata.get("dataset_hash"),
            "evaluation_protocol": artifact.metadata.get("evaluation_protocol"),
            "feature_count": artifact.metadata.get("feature_count"),
            "primary_metrics": eval_meta.get("primary_metrics"),
        },
        "training_metadata": artifact.metadata,
        "disclaimer": PREDICTION_DISCLAIMER,
    }


def _supporting_features(
    artifact: MISTIQAPRModelArtifact,
    row: np.ndarray,
    predicted: str | None,
    classes: list[str],
) -> list[dict[str, Any]]:
    """Top features driving the predicted class, by standardized contribution."""
    if predicted is None or predicted not in classes:
        return []
    model = artifact.model
    final = model.steps[-1][1] if getattr(model, "steps", None) else model
    scaler = model.named_steps.get("standardscaler") if getattr(model, "named_steps", None) else None

    # Support HybridSequentialClassifier which stores .linear_ and .scaler_
    if hasattr(final, "linear_") and getattr(final, "linear_", None) is not None:
        scaler = getattr(final, "scaler_", scaler)
        final = final.linear_

    if hasattr(final, "coef_"):
        coefficients = np.asarray(final.coef_, dtype=float)
        class_index = classes.index(predicted)
        coefficients = coefficients[class_index] if coefficients.ndim > 1 and class_index < coefficients.shape[0] else coefficients[0]
        scaled = (row - scaler.mean_) / scaler.scale_ if scaler is not None else row
        contributions = coefficients * scaled
    elif hasattr(final, "feature_importances_"):
        coefficients = np.asarray(final.feature_importances_, dtype=float)
        scaled = row
        contributions = coefficients * np.where(row != 0, np.sign(row), 1.0)
    else:
        coefficients = np.ones_like(row)
        scaled = row
        contributions = row

    order = np.argsort(np.abs(contributions))[::-1][:TOP_SUPPORTING_FEATURES]
    results: list[dict[str, Any]] = []
    for index in order:
        fname = ALL_FEATURE_NAMES[index]
        val = float(row[index])
        group, desc = _describe_feature(fname, val)
        results.append(
            {
                "feature": fname,
                "feature_group": group,
                "description": desc,
                "value": round(val, 6),
                "standardized_value": round(float(scaled[index]), 6),
                "coefficient": round(float(coefficients[index]), 6),
                "contribution": round(float(contributions[index]), 6),
                "direction": "increases" if contributions[index] >= 0 else "decreases",
            }
        )
    return results
