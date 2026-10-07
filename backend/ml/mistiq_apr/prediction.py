"""Online next-failure prediction from a validated saved artifact only.

This module never trains. It loads a persisted MISTIQ-APR bundle, scores the
current feature vector, and reports probabilities with supporting features.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .artifacts import MISTIQAPRModelArtifact
from .constants import ALL_FEATURE_NAMES, MODEL_NAME

PREDICTION_DISCLAIMER = (
    "Prediction is based on historical project observations and is not a certainty."
)
TOP_SUPPORTING_FEATURES = 5


def predict_next_failure(
    artifact: MISTIQAPRModelArtifact,
    features: dict[str, float],
    top_k: int = 3,
) -> dict[str, Any]:
    """Score one feature vector with the artifact's trained pipeline."""
    row = np.array([[features.get(name, 0.0) for name in ALL_FEATURE_NAMES]], dtype=float)
    probabilities = artifact.model.predict_proba(row)[0]
    classes = [str(name) for name in artifact.model.classes_]
    order = np.argsort(probabilities)[::-1][: max(1, min(top_k, len(classes)))]
    predictions = [
        {"category": classes[index], "probability": round(float(probabilities[index]), 6)}
        for index in order
    ]
    predicted = predictions[0]["category"] if predictions else None
    return {
        "predicted_category": predicted,
        "predictions": predictions,
        "supporting_features": _supporting_features(artifact, row[0], predicted, classes),
        "model": {
            "name": MODEL_NAME,
            "version": artifact.metadata.get("version"),
            "trained_at": artifact.metadata.get("trained_at"),
            "training_observations": artifact.metadata.get("training_observations"),
            "dataset_hash": artifact.metadata.get("dataset_hash"),
            "evaluation_protocol": artifact.metadata.get("evaluation_protocol"),
            "feature_count": artifact.metadata.get("feature_count"),
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
    final = artifact.model.steps[-1][1] if getattr(artifact.model, "steps", None) else artifact.model
    scaler = artifact.model.named_steps.get("standardscaler") if getattr(artifact.model, "named_steps", None) else None
    coefficients = np.asarray(final.coef_, dtype=float)
    class_index = classes.index(predicted)
    coefficients = coefficients[class_index] if coefficients.ndim > 1 else coefficients
    scaled = (row - scaler.mean_) / scaler.scale_ if scaler is not None else row
    contributions = coefficients * scaled
    order = np.argsort(np.abs(contributions))[::-1][:TOP_SUPPORTING_FEATURES]
    return [
        {
            "feature": ALL_FEATURE_NAMES[index],
            "value": round(float(row[index]), 6),
            "standardized_value": round(float(scaled[index]), 6),
            "coefficient": round(float(coefficients[index]), 6),
            "contribution": round(float(contributions[index]), 6),
            "direction": "increases" if contributions[index] >= 0 else "decreases",
        }
        for index in order
    ]
