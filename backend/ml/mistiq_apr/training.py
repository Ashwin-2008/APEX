"""Gated training of the persistable MISTIQ-APR model artifact.

Training is refused unless the dataset is sufficient, leakage checks pass, and
the walk-forward evaluation completed. No artifact is ever written (or marked
valid) from insufficient data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .artifacts import (
    MISTIQAPRModelArtifact,
    default_feature_groups,
    save_mistiq_apr_artifact,
)
from .constants import (
    ALL_FEATURE_NAMES,
    EVALUATION_PROTOCOL,
    MIN_OBSERVATIONS_FOR_EVALUATION,
    MODEL_NAME,
    MODEL_VERSION,
    STATUS_VALID_EVALUATION,
)
from .dataset import Observation, compute_dataset_hash
from .models import MISTIQ_APR, feature_matrix


def train_and_save_model(
    observations: list[Observation],
    leakage_report: dict[str, Any],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    """Train the deployment artifact when every gate passes; else explain why."""
    reason = _refusal_reason(observations, leakage_report, evaluation)
    if reason is not None:
        return {"trained": False, "reason": reason, "path": None, "metadata": None}

    global_classes = sorted({row.target for row in observations})
    x = feature_matrix(observations, list(ALL_FEATURE_NAMES))
    y = [row.target for row in observations]
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, random_state=42))
    model.fit(x, y)

    walk_forward = evaluation.get("walk_forward", {})
    primary_metrics = next(
        (row.get("metrics") for row in evaluation.get("results", []) if row.get("model") == MISTIQ_APR),
        None,
    )
    metadata: dict[str, Any] = {
        "model": MODEL_NAME,
        "version": MODEL_VERSION,
        "model_version": MODEL_VERSION,
        "status": "trained",
        "feature_count": len(ALL_FEATURE_NAMES),
        "feature_names": list(ALL_FEATURE_NAMES),
        "feature_groups": default_feature_groups(),
        "categories": global_classes,
        "training_observations": len(observations),
        "dataset_version": _dataset_version(),
        "dataset_hash": compute_dataset_hash(observations),
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "evaluation_protocol": EVALUATION_PROTOCOL,
        "evaluation_metadata": {
            "protocol": EVALUATION_PROTOCOL,
            "status": evaluation.get("status"),
            "n_cutoffs": walk_forward.get("n_cutoffs", 0),
            "primary_model": MISTIQ_APR,
            "primary_metrics": primary_metrics,
            "leakage_passed": bool(leakage_report.get("passed")),
        },
    }
    artifact = MISTIQAPRModelArtifact(
        model=model,
        metadata=metadata,
        preprocessing="standard_scaler",
        feature_names=list(ALL_FEATURE_NAMES),
        feature_groups=default_feature_groups(),
        category_mapping={str(index): name for index, name in enumerate(global_classes)},
    )
    try:
        target = save_mistiq_apr_artifact(artifact)
    except OSError as error:
        return {"trained": False, "reason": f"artifact could not be saved: {error}", "path": None, "metadata": None}
    return {"trained": True, "reason": None, "path": str(target), "metadata": metadata}


def _refusal_reason(
    observations: list[Observation],
    leakage_report: dict[str, Any],
    evaluation: dict[str, Any],
) -> str | None:
    if not leakage_report.get("passed"):
        return "critical data leakage was detected"
    if evaluation.get("status") != STATUS_VALID_EVALUATION:
        return "walk-forward evaluation is unavailable"
    if len(observations) < MIN_OBSERVATIONS_FOR_EVALUATION:
        return f"only {len(observations)} chronological observations; at least {MIN_OBSERVATIONS_FOR_EVALUATION} required"
    if len({row.target for row in observations}) < 2:
        return "fewer than two failure-category outcomes in the dataset"
    return None


def _dataset_version() -> str:
    from .constants import PROJECT_REVIEW_DATASET_VERSION

    return PROJECT_REVIEW_DATASET_VERSION
