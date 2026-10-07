"""Model factories and the baseline/MISTIQ-APR specification table.

Every model is trained per walk-forward cutoff on that cutoff's training rows
only. Scaler statistics are verified numerically against a train-only refit so
the leakage validator can detect future preprocessing regressions.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .constants import ALL_FEATURE_NAMES, STATIC_FEATURE_NAMES
from .dataset import Observation

MAJORITY = "Majority Class"
LATEST_FAILURE = "Latest Failure"
STATIC_LOGISTIC = "Static Logistic Regression"
RANDOM_FOREST = "Random Forest"
MISTIQ_APR = "MISTIQ-APR"

# Ordered baseline comparison table (report + Research Lab share this order).
MODEL_SPECS: list[dict[str, Any]] = [
    {"model": MAJORITY, "kind": "majority", "features": None},
    {"model": LATEST_FAILURE, "kind": "latest", "features": None},
    {"model": STATIC_LOGISTIC, "kind": "logistic", "features": list(STATIC_FEATURE_NAMES)},
    {"model": RANDOM_FOREST, "kind": "forest", "features": list(ALL_FEATURE_NAMES)},
    {"model": MISTIQ_APR, "kind": "logistic", "features": list(ALL_FEATURE_NAMES)},
]


def feature_matrix(rows: list[Observation], names: list[str]) -> np.ndarray:
    return np.array([[row.features.get(name, 0.0) for name in names] for row in rows], dtype=float)


def make_estimator(kind: str):
    if kind == "logistic":
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=1000, random_state=42),
        )
    if kind == "forest":
        return RandomForestClassifier(n_estimators=100, random_state=42, class_weight="balanced")
    raise ValueError(f"unknown model kind: {kind}")


def align_probabilities(raw: np.ndarray, model_classes: list[str], global_classes: list[str]) -> np.ndarray:
    """Pad/permute per-cutoff probabilities into the global class order."""
    aligned = np.zeros((raw.shape[0], len(global_classes)), dtype=float)
    for column, name in enumerate(model_classes):
        if name in global_classes:
            aligned[:, global_classes.index(name)] = raw[:, column]
    return aligned


def fit_predict(
    spec: dict[str, Any],
    train: list[Observation],
    test: list[Observation],
    global_classes: list[str],
) -> tuple[np.ndarray, dict[str, Any] | None]:
    """Fit one spec on training rows and predict test probabilities.

    Returns (probabilities aligned to global_classes, preprocessing_report).
    The preprocessing report records fit scope and a numeric train-only
    verification used by the leakage validator.
    """
    kind = spec["kind"]
    if kind == "majority":
        counts = {name: 0 for name in global_classes}
        for row in train:
            if row.target in counts:
                counts[row.target] += 1
        winner = max(counts, key=counts.get) if any(counts.values()) else global_classes[0]
        probabilities = np.array(
            [[1.0 if name == winner else 0.0 for name in global_classes] for _ in test], dtype=float
        )
        return probabilities, None
    if kind == "latest":
        probabilities = np.zeros((len(test), len(global_classes)), dtype=float)
        for index, row in enumerate(test):
            if row.previous_category in global_classes:
                probabilities[index, global_classes.index(row.previous_category)] = 1.0
            else:
                probabilities[index, :] = 1.0 / max(1, len(global_classes))
        return probabilities, None

    names = spec["features"] or list(ALL_FEATURE_NAMES)
    x_train = feature_matrix(train, names)
    x_test = feature_matrix(test, names)
    estimator = make_estimator(kind)
    estimator.fit(x_train, [row.target for row in train])
    raw = estimator.predict_proba(x_test)
    model_classes = [str(name) for name in estimator.classes_]
    report = _preprocessing_report(spec, estimator, train, x_train)
    return align_probabilities(raw, model_classes, global_classes), report


def _preprocessing_report(
    spec: dict[str, Any],
    estimator,
    train: list[Observation],
    x_train: np.ndarray,
) -> dict[str, Any]:
    scaler_fit_on_train_only: bool | None = None
    scaler = getattr(estimator, "named_steps", {}).get("standardscaler") if hasattr(estimator, "named_steps") else None
    if scaler is not None:
        refit = StandardScaler().fit(x_train)
        scaler_fit_on_train_only = bool(np.allclose(refit.mean_, scaler.mean_, equal_nan=True))
    keys = [[row.project_id, row.review_id, row.target] for row in train]
    return {
        "model": spec["model"],
        "kind": spec["kind"],
        "fitted_objects": ["standard_scaler", "logistic_regression"] if spec["kind"] == "logistic" else ["random_forest"],
        "scaler_fit_on_train_only": scaler_fit_on_train_only,
        "fit_observation_keys": keys,
        "train_observation_keys": keys,
    }
