"""Persisted MISTIQ-APR model artifacts.

An artifact is only ever marked valid when it was trained on sufficient data
under the walk-forward protocol. Loading validates the bundle structure,
feature schema, category mapping, and training metadata; anything else is
treated as unavailable rather than used for prediction.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

from .constants import (
    ALL_FEATURE_NAMES,
    EVALUATION_PROTOCOL,
    FEATURE_BLOCKS,
    MIN_OBSERVATIONS_FOR_EVALUATION,
)

ARTIFACTS_ROOT = Path("backend/ml/artifacts/mistiq_apr")
MODEL_FILENAME = "model.pkl"
METADATA_FILENAME = "model_metadata.json"


def artifacts_root() -> Path:
    """Resolve the artifact directory dynamically (overridable in tests)."""
    return Path(ARTIFACTS_ROOT)


def model_path() -> Path:
    return artifacts_root() / MODEL_FILENAME


def metadata_path() -> Path:
    return artifacts_root() / METADATA_FILENAME


class MISTIQAPRModelArtifact:
    """In-memory representation of a saved MISTIQ-APR model bundle."""

    def __init__(
        self,
        model: Any = None,
        metadata: dict[str, Any] | None = None,
        preprocessing: Any = None,
        feature_names: list[str] | None = None,
        feature_groups: dict[str, list[str]] | None = None,
        category_mapping: dict[str, str] | None = None,
    ) -> None:
        self.model = model
        self.metadata = metadata or {}
        self.preprocessing = preprocessing
        self.feature_names = feature_names
        self.feature_groups = feature_groups
        self.category_mapping = category_mapping


def save_mistiq_apr_artifact(artifact: MISTIQAPRModelArtifact, path: str | Path | None = None) -> Path:
    """Persist the artifact bundle plus a human-readable metadata sidecar."""
    target = Path(path) if path is not None else model_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pickle.dumps(artifact))
    sidecar = target.parent / METADATA_FILENAME
    sidecar.write_text(json.dumps(artifact.metadata, indent=2, default=str), encoding="utf-8")
    return target


def load_mistiq_apr_artifact(path: str | Path | None = None) -> MISTIQAPRModelArtifact:
    target = Path(path) if path is not None else model_path()
    if not target.exists():
        raise FileNotFoundError(f"No MISTIQ-APR model artifact at {target}")
    return pickle.loads(target.read_bytes())


def validate_artifact(artifact: Any) -> dict[str, Any]:
    """Structural + metadata validation. Returns {'valid', 'reason'}."""
    if not isinstance(artifact, MISTIQAPRModelArtifact):
        return {"valid": False, "reason": "artifact is not a MISTIQ-APR model bundle"}
    if artifact.model is None or not hasattr(artifact.model, "predict_proba"):
        return {"valid": False, "reason": "model is missing or does not support predict_proba"}
    final = artifact.model
    if getattr(artifact.model, "steps", None):
        final = artifact.model.steps[-1][1]
    if not hasattr(final, "classes_") or len(final.classes_) < 1:
        return {"valid": False, "reason": "model is not fitted"}
    if artifact.feature_names != list(ALL_FEATURE_NAMES):
        return {"valid": False, "reason": "feature schema mismatch with current dataset version"}
    if not list((artifact.category_mapping or {}).values()):
        return {"valid": False, "reason": "category mapping is empty"}
    metadata = artifact.metadata or {}
    if metadata.get("status") != "trained":
        return {"valid": False, "reason": "artifact is not marked as trained"}
    if metadata.get("evaluation_protocol") != EVALUATION_PROTOCOL:
        return {"valid": False, "reason": "artifact was not trained under the walk-forward protocol"}
    if int(metadata.get("training_observations", 0)) < MIN_OBSERVATIONS_FOR_EVALUATION:
        return {"valid": False, "reason": "training observations below the evaluation threshold"}
    return {"valid": True, "reason": None}


def load_valid_artifact(path: str | Path | None = None) -> tuple[MISTIQAPRModelArtifact | None, str]:
    """Load and validate an artifact; returns (artifact, unavailable_reason)."""
    target = Path(path) if path is not None else model_path()
    if not target.exists():
        return None, "insufficient historical training data"
    try:
        artifact = load_mistiq_apr_artifact(target)
    except Exception as error:  # corrupt or incompatible pickle
        return None, f"saved model artifact could not be loaded: {error}"
    verdict = validate_artifact(artifact)
    if not verdict["valid"]:
        return None, verdict["reason"]
    return artifact, None


def artifact_status(path: str | Path | None = None) -> dict[str, Any]:
    """Describe the current artifact state for research status responses."""
    target = Path(path) if path is not None else model_path()
    if not target.exists():
        return {"exists": False, "valid": False, "reason": "insufficient historical training data", "metadata": None}
    artifact, reason = load_valid_artifact(target)
    if artifact is None:
        return {"exists": True, "valid": False, "reason": reason, "metadata": None}
    return {"exists": True, "valid": True, "reason": None, "metadata": artifact.metadata}


def default_feature_groups() -> dict[str, list[str]]:
    return {name: list(block) for name, block in FEATURE_BLOCKS.items()}

