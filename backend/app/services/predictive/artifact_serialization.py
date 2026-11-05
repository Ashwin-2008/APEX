"""Pure-JSON Model Artifact Serialization, Structural Verification & Safe Loading (Phase 4.1).

Guarantees:
- Zero untrusted pickle deserialization.
- Strict schema validation (rejects extra/unexpected fields, incompatible versions).
- Structural integrity checking for Random Forest tree DAGs and Logistic Regression coefficients.
- Detection and rejection of modified/tampered artifacts, invalid coefficients, and out-of-bounds nodes.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import math
from typing import Any
import numpy as np

from .baseline_models import LogisticRegressionBaseline, RandomForestBaseline
from .constants import FAILURE_CATEGORIES, FEATURE_SCHEMA_VERSION

HMAC_INTEGRITY_KEY = b"apex-mistiq-trusted-manifest-v2"


class ArtifactIntegrityError(ValueError):
    """Raised when artifact validation fails due to tampering, schema mismatch, or structural corruption."""
    pass


class ModelArtifactSerializer:
    """Safely serializes and deserializes ML models to/from validated JSON parameter structures."""

    REQUIRED_ARTIFACT_KEYS = {
        "model_id",
        "model_version",
        "prediction_task",
        "algorithm",
        "model_params",
        "training_dataset_id",
        "feature_schema_version",
        "saved_at",
    }

    @classmethod
    def validate_artifact_schema(cls, artifact_dict: dict[str, Any]) -> None:
        """Validates the top-level artifact dictionary against strict schema rules."""
        missing = cls.REQUIRED_ARTIFACT_KEYS - set(artifact_dict.keys())
        if missing:
            raise ArtifactIntegrityError(f"Malformed artifact: missing required fields: {missing}")

        extra = set(artifact_dict.keys()) - cls.REQUIRED_ARTIFACT_KEYS
        if extra:
            raise ArtifactIntegrityError(f"Security Error: Unexpected unknown fields in artifact: {extra}")

        if artifact_dict.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
            raise ArtifactIntegrityError(
                f"Incompatible feature schema version: expected {FEATURE_SCHEMA_VERSION}, "
                f"got {artifact_dict.get('feature_schema_version')}"
            )

        if not isinstance(artifact_dict.get("model_params"), dict):
            raise ArtifactIntegrityError("model_params must be a valid dictionary.")

    # =========================================================================
    # LOGISTIC REGRESSION JSON SERIALIZATION
    # =========================================================================
    @classmethod
    def serialize_logistic_regression(cls, lr: LogisticRegressionBaseline) -> dict[str, Any]:
        """Serializes LogisticRegressionBaseline to pure JSON."""
        if not lr.is_fitted:
            raise ValueError("Cannot serialize unfitted LogisticRegression baseline.")

        coef = lr.model.coef_.tolist()
        intercept = lr.model.intercept_.tolist()
        scaler_mean = lr.scaler.mean_.tolist() if hasattr(lr.scaler, "mean_") else [0.0] * len(lr.feature_names)
        scaler_scale = lr.scaler.scale_.tolist() if hasattr(lr.scaler, "scale_") else [1.0] * len(lr.feature_names)

        return {
            "architecture": "logistic_regression",
            "feature_names": lr.feature_names,
            "classes": lr.classes_,
            "coef": coef,
            "intercept": intercept,
            "scaler_mean": scaler_mean,
            "scaler_scale": scaler_scale,
        }

    @classmethod
    def deserialize_logistic_regression(cls, params: dict[str, Any]) -> LogisticRegressionBaseline:
        """Validates parameters and reconstructs LogisticRegressionBaseline without pickle."""
        if params.get("architecture") != "logistic_regression":
            raise ArtifactIntegrityError(f"Unsupported architecture: {params.get('architecture')}")

        feature_names = params.get("feature_names")
        classes = params.get("classes")
        coef = params.get("coef")
        intercept = params.get("intercept")
        scaler_mean = params.get("scaler_mean")
        scaler_scale = params.get("scaler_scale")

        if not isinstance(feature_names, list) or not feature_names:
            raise ArtifactIntegrityError("Invalid feature_names in model params.")
        if not isinstance(classes, list) or not classes:
            raise ArtifactIntegrityError("Invalid classes in model params.")
        if not isinstance(coef, list) or not isinstance(intercept, list):
            raise ArtifactIntegrityError("Coefficients and intercept must be lists.")

        n_classes = len(classes)
        n_features = len(feature_names)

        # Dimension checks
        if len(coef) != n_classes and not (n_classes == 2 and len(coef) == 1):
            raise ArtifactIntegrityError(f"Coefficient dimension mismatch: expected {n_classes} classes, got {len(coef)}")

        for row in coef:
            if len(row) != n_features:
                raise ArtifactIntegrityError(f"Feature count mismatch: expected {n_features}, got {len(row)}")
            for val in row:
                if not math.isfinite(val):
                    raise ArtifactIntegrityError("Non-finite coefficient detected in artifact.")

        for val in intercept:
            if not math.isfinite(val):
                raise ArtifactIntegrityError("Non-finite intercept detected in artifact.")

        # Reconstruct baseline
        lr = LogisticRegressionBaseline()
        lr.feature_names = feature_names
        lr.classes_ = classes
        lr.is_fitted = True

        # Assign weights to scikit-learn model
        lr.model.classes_ = np.array(classes)
        lr.model.coef_ = np.array(coef, dtype=float)
        lr.model.intercept_ = np.array(intercept, dtype=float)

        if scaler_mean and scaler_scale:
            lr.scaler.mean_ = np.array(scaler_mean, dtype=float)
            lr.scaler.scale_ = np.array(scaler_scale, dtype=float)
            lr.scaler.var_ = np.array([s ** 2 for s in scaler_scale], dtype=float)
            lr.scaler.n_features_in_ = n_features

        return lr

    # =========================================================================
    # RANDOM FOREST JSON SERIALIZATION
    # =========================================================================
    @classmethod
    def serialize_random_forest(cls, rf: RandomForestBaseline) -> dict[str, Any]:
        """Serializes RandomForest trees into validated pure JSON."""
        if not rf.is_fitted:
            raise ValueError("Cannot serialize unfitted RandomForest baseline.")

        trees = []
        for est in rf.model.estimators_:
            tree_obj = est.tree_
            trees.append({
                "node_count": int(tree_obj.node_count),
                "children_left": tree_obj.children_left.tolist(),
                "children_right": tree_obj.children_right.tolist(),
                "feature": tree_obj.feature.tolist(),
                "threshold": [round(float(t), 8) for t in tree_obj.threshold.tolist()],
                "value": tree_obj.value.squeeze(axis=1).tolist() if tree_obj.value.ndim == 3 else tree_obj.value.tolist(),
            })

        return {
            "architecture": "random_forest",
            "feature_names": rf.feature_names,
            "classes": rf.classes_,
            "n_estimators": len(trees),
            "trees": trees,
            "feature_importances": rf.feature_importances_,
        }

    @classmethod
    def deserialize_random_forest(cls, params: dict[str, Any]) -> RandomForestBaseline:
        """Deeply validates tree DAG structures and reconstructs RandomForest predictor."""
        if params.get("architecture") != "random_forest":
            raise ArtifactIntegrityError(f"Unsupported architecture: {params.get('architecture')}")

        feature_names = params.get("feature_names")
        classes = params.get("classes")
        trees = params.get("trees")

        if not isinstance(feature_names, list) or not feature_names:
            raise ArtifactIntegrityError("Invalid feature_names in model params.")
        if not isinstance(classes, list) or not classes:
            raise ArtifactIntegrityError("Invalid classes in model params.")
        if not isinstance(trees, list) or not trees:
            raise ArtifactIntegrityError("Invalid trees in model params.")

        n_features = len(feature_names)

        # Validate each tree
        for t_idx, tree in enumerate(trees):
            node_count = tree.get("node_count")
            children_left = tree.get("children_left")
            children_right = tree.get("children_right")
            features = tree.get("feature")
            thresholds = tree.get("threshold")
            values = tree.get("value")

            if not isinstance(node_count, int) or node_count <= 0:
                raise ArtifactIntegrityError(f"Tree {t_idx}: invalid node_count")

            for name, arr in [
                ("children_left", children_left),
                ("children_right", children_right),
                ("feature", features),
                ("threshold", thresholds),
                ("value", values),
            ]:
                if not isinstance(arr, list) or len(arr) != node_count:
                    raise ArtifactIntegrityError(f"Tree {t_idx}: {name} length mismatch with node_count {node_count}")

            for i in range(node_count):
                c_left = children_left[i]
                c_right = children_right[i]
                feat = features[i]
                thresh = thresholds[i]

                # Structural tree pointer checks
                if c_left != -1:
                    if c_left <= i or c_left >= node_count:
                        raise ArtifactIntegrityError(f"Tree {t_idx}: invalid child pointer {c_left} at node {i}")
                    if feat < 0 or feat >= n_features:
                        raise ArtifactIntegrityError(f"Tree {t_idx}: invalid feature index {feat} at node {i}")
                    if not math.isfinite(thresh):
                        raise ArtifactIntegrityError(f"Tree {t_idx}: non-finite threshold at node {i}")
                if c_right != -1:
                    if c_right <= i or c_right >= node_count:
                        raise ArtifactIntegrityError(f"Tree {t_idx}: invalid child pointer {c_right} at node {i}")

        rf = RandomForestBaseline(n_estimators=len(trees))
        rf.feature_names = feature_names
        rf.classes_ = classes
        rf.is_fitted = True
        rf.feature_importances_ = params.get("feature_importances", {})

        # Set up surrogate tree evaluator
        class SurrogateTreeEvaluator:
            def __init__(self, trees_data: list[dict[str, Any]], cls_list: list[str], f_names: list[str]):
                self.trees = trees_data
                self.classes_ = cls_list
                self.feature_names = f_names

            def predict_proba(self, X_input: list[list[float]]) -> np.ndarray:
                n_samples = len(X_input)
                n_cls = len(self.classes_)
                all_probs = np.zeros((n_samples, n_cls))

                for row_idx, row in enumerate(X_input):
                    tree_votes = np.zeros((len(self.trees), n_cls))
                    for t_idx, tree in enumerate(self.trees):
                        # Traverse tree
                        node = 0
                        while tree["children_left"][node] != -1:
                            feat_idx = tree["feature"][node]
                            thresh = tree["threshold"][node]
                            if row[feat_idx] <= thresh:
                                node = tree["children_left"][node]
                            else:
                                node = tree["children_right"][node]
                        node_val = tree["value"][node]
                        val_sum = sum(node_val) or 1.0
                        tree_votes[t_idx] = [v / val_sum for v in node_val]
                    all_probs[row_idx] = tree_votes.mean(axis=0)
                return all_probs

        rf.model = SurrogateTreeEvaluator(trees, classes, feature_names)
        return rf

    # =========================================================================
    # SIGNED MANIFEST / HMAC TAMPER PROOFING
    # =========================================================================
    @staticmethod
    def compute_manifest_signature(manifest_data: dict[str, Any]) -> str:
        """Computes HMAC-SHA256 signature for manifest data to detect external tampering."""
        canonical_bytes = json.dumps(manifest_data, sort_keys=True).encode("utf-8")
        return hmac.new(HMAC_INTEGRITY_KEY, canonical_bytes, hashlib.sha256).hexdigest()

    @staticmethod
    def verify_manifest_signature(manifest_data: dict[str, Any], expected_signature: str) -> bool:
        """Verifies HMAC signature matching."""
        computed = ModelArtifactSerializer.compute_manifest_signature(manifest_data)
        return hmac.compare_digest(computed, expected_signature)
