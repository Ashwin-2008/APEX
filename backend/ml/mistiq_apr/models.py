"""Model factories and the baseline/MISTIQ-APR specification table.

Every model is trained per walk-forward cutoff on that cutoff's training rows
only. Scaler statistics are verified numerically against a train-only refit so
the leakage validator can detect future preprocessing regressions.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .constants import ALL_FEATURE_NAMES, FAILURE_CATEGORIES, STATIC_FEATURE_NAMES
from .dataset import Observation

MAJORITY = "Majority Class"
LATEST_FAILURE = "Latest Failure"
STATIC_LOGISTIC = "Static Logistic Regression"
RANDOM_FOREST = "Random Forest"
MISTIQ_APR = "MISTIQ-APR"
HYBRID_SEQUENTIAL = "MISTIQ-APR Sequential Hybrid"
HIST_GBDT = "Histogram Gradient Boosting"


class HybridSequentialClassifier(BaseEstimator, ClassifierMixin):
    """Interpretable sequential failure transition + recency + regularized linear ensemble.

    Combines three transparent probability components estimated strictly on the
    training set:
    1. Regularized multinomial logistic regression over the 112-feature vector.
    2. First-order Laplace-smoothed Markov transition matrix P(target | latest_category).
    3. Project-history recency-weighted empirical prior extracted from the
       observation's sequential frequency (`seq_freq_*`) and repetition (`seq_repetition_*`)
       signals.
    """

    def __init__(
        self,
        c_reg: float = 0.5,
        w_linear: float = 0.55,
        w_markov: float = 0.25,
        w_history: float = 0.20,
        laplace_alpha: float = 0.5,
        random_state: int = 42,
    ) -> None:
        self.c_reg = c_reg
        self.w_linear = w_linear
        self.w_markov = w_markov
        self.w_history = w_history
        self.laplace_alpha = laplace_alpha
        self.random_state = random_state

    def fit(self, X: np.ndarray, y: list[str] | np.ndarray) -> "HybridSequentialClassifier":
        X_arr = np.asarray(X, dtype=float)
        y_arr = np.asarray([str(lbl) for lbl in y])
        classes = sorted(set(y_arr))
        self.classes_ = np.asarray(classes)
        n_classes = len(classes)
        class_to_idx = {c: i for i, c in enumerate(classes)}

        self.scaler_ = StandardScaler()
        X_scaled = self.scaler_.fit_transform(X_arr)

        if n_classes >= 2:
            self.linear_ = LogisticRegression(
                C=self.c_reg,
                max_iter=1000,
                class_weight="balanced",
                random_state=self.random_state,
            )
            self.linear_.fit(X_scaled, y_arr)
        else:
            self.linear_ = None

        # Laplace-smoothed empirical class prior
        counts = np.zeros(n_classes, dtype=float)
        for lbl in y_arr:
            counts[class_to_idx[lbl]] += 1.0
        self.prior_ = (counts + self.laplace_alpha) / float(len(y_arr) + self.laplace_alpha * n_classes)

        # Build feature indices for latest_failure_* and seq_freq_* / seq_repetition_*
        self.latest_indices_: dict[int, str] = {}
        self.freq_indices_: dict[str, int] = {}
        self.rep_indices_: dict[str, int] = {}
        if X_arr.shape[1] == len(ALL_FEATURE_NAMES):
            for idx, fname in enumerate(ALL_FEATURE_NAMES):
                if fname.startswith("latest_failure_"):
                    cat = fname.removeprefix("latest_failure_")
                    self.latest_indices_[idx] = cat
                elif fname.startswith("seq_freq_"):
                    cat = fname.removeprefix("seq_freq_")
                    self.freq_indices_[cat] = idx
                elif fname.startswith("seq_repetition_"):
                    cat = fname.removeprefix("seq_repetition_")
                    self.rep_indices_[cat] = idx

        # Estimate Markov transition matrix P(next = c | prev_latest = src_cat)
        self.transition_probs_: dict[str, np.ndarray] = {}
        for src_cat in FAILURE_CATEGORIES:
            trans_counts = np.zeros(n_classes, dtype=float)
            for row_idx, lbl in enumerate(y_arr):
                # Check if src_cat was the latest_failure in X_arr[row_idx]
                src_col = next((col for col, c in self.latest_indices_.items() if c == src_cat), None)
                if src_col is not None and X_arr[row_idx, src_col] > 0.5:
                    trans_counts[class_to_idx[lbl]] += 1.0
            total_src = float(np.sum(trans_counts))
            if total_src > 0:
                self.transition_probs_[src_cat] = (trans_counts + self.laplace_alpha) / (
                    total_src + self.laplace_alpha * n_classes
                )
            else:
                self.transition_probs_[src_cat] = self.prior_.copy()

        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X_arr = np.asarray(X, dtype=float)
        n_samples = X_arr.shape[0]
        n_classes = len(self.classes_)
        if n_classes == 1:
            return np.ones((n_samples, 1), dtype=float)

        X_scaled = self.scaler_.transform(X_arr)
        p_linear = self.linear_.predict_proba(X_scaled) if self.linear_ is not None else np.tile(self.prior_, (n_samples, 1))

        p_markov = np.zeros((n_samples, n_classes), dtype=float)
        p_history = np.zeros((n_samples, n_classes), dtype=float)

        for i in range(n_samples):
            # Markov component
            active_src = None
            for col, cat in self.latest_indices_.items():
                if col < X_arr.shape[1] and X_arr[i, col] > 0.5:
                    active_src = cat
                    break
            if active_src and active_src in self.transition_probs_:
                p_markov[i] = self.transition_probs_[active_src]
            else:
                p_markov[i] = self.prior_

            # Historical frequency + streak component for classes in self.classes_
            hist_scores = np.zeros(n_classes, dtype=float)
            for c_idx, cls_name in enumerate(self.classes_):
                f_col = self.freq_indices_.get(str(cls_name))
                r_col = self.rep_indices_.get(str(cls_name))
                freq_val = max(0.0, X_arr[i, f_col]) if f_col is not None and f_col < X_arr.shape[1] else 0.0
                rep_val = max(0.0, X_arr[i, r_col]) if r_col is not None and r_col < X_arr.shape[1] else 0.0
                hist_scores[c_idx] = freq_val + 1.5 * rep_val
            if np.sum(hist_scores) > 0:
                p_history[i] = (hist_scores + 0.25) / float(np.sum(hist_scores) + 0.25 * n_classes)
            else:
                p_history[i] = self.prior_

        combined = (
            self.w_linear * p_linear
            + self.w_markov * p_markov
            + self.w_history * p_history
        )
        row_sums = np.sum(combined, axis=1, keepdims=True)
        row_sums[row_sums == 0.0] = 1.0
        return combined / row_sums

    def predict(self, X: np.ndarray) -> np.ndarray:
        probs = self.predict_proba(X)
        indices = np.argmax(probs, axis=1)
        return np.asarray([self.classes_[i] for i in indices])


# Ordered baseline comparison table (report + Research Lab share this order).
MODEL_SPECS: list[dict[str, Any]] = [
    {"model": MAJORITY, "kind": "majority", "features": None},
    {"model": LATEST_FAILURE, "kind": "latest", "features": None},
    {"model": STATIC_LOGISTIC, "kind": "logistic", "features": list(STATIC_FEATURE_NAMES)},
    {"model": RANDOM_FOREST, "kind": "forest", "features": list(ALL_FEATURE_NAMES)},
    {"model": MISTIQ_APR, "kind": "logistic", "features": list(ALL_FEATURE_NAMES)},
]

# Candidate model specifications available for registry experimentation (Phase 5 & 7).
CANDIDATE_MODEL_SPECS: dict[str, dict[str, Any]] = {
    "logistic_regression": {
        "model": "MISTIQ-APR Logistic Regression",
        "kind": "logistic",
        "features": list(ALL_FEATURE_NAMES),
        "description": "StandardScaler + L2-regularized multinomial LogisticRegression over 112 static and sequential features.",
    },
    "hybrid_sequential": {
        "model": HYBRID_SEQUENTIAL,
        "kind": "hybrid_sequential",
        "features": list(ALL_FEATURE_NAMES),
        "description": "Ensemble of balanced regularized LogisticRegression, Laplace-smoothed Markov transition matrix, and historical recurrence prior.",
    },
    "random_forest": {
        "model": RANDOM_FOREST,
        "kind": "forest",
        "features": list(ALL_FEATURE_NAMES),
        "description": "Balanced RandomForestClassifier (100 trees) over 112 static and sequential features.",
    },
    "hist_gradient_boosting": {
        "model": HIST_GBDT,
        "kind": "hist_gbdt",
        "features": list(ALL_FEATURE_NAMES),
        "description": "Regularized HistGradientBoostingClassifier with shallow depth for small-to-medium tabular sequential datasets.",
    },
    "extra_trees": {
        "model": "Extra Trees Classifier",
        "kind": "extra_trees",
        "features": list(ALL_FEATURE_NAMES),
        "description": "Balanced ExtraTreesClassifier with randomized splits to reduce variance on correlated sequential features.",
    },
}


def feature_matrix(rows: list[Observation], names: list[str]) -> np.ndarray:
    return np.array([[row.features.get(name, 0.0) for name in names] for row in rows], dtype=float)


def make_estimator(kind: str):
    if kind == "logistic":
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=1000, random_state=42),
        )
    if kind == "hybrid_sequential":
        return HybridSequentialClassifier(random_state=42)
    if kind == "forest":
        return RandomForestClassifier(n_estimators=100, random_state=42, class_weight="balanced")
    if kind == "hist_gbdt":
        return HistGradientBoostingClassifier(
            max_iter=80,
            max_depth=4,
            min_samples_leaf=3,
            l2_regularization=1.0,
            random_state=42,
        )
    if kind == "extra_trees":
        return ExtraTreesClassifier(
            n_estimators=120,
            max_depth=6,
            random_state=42,
            class_weight="balanced",
        )
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
    if scaler is None and hasattr(estimator, "scaler_"):
        scaler = getattr(estimator, "scaler_", None)
    if scaler is not None:
        refit = StandardScaler().fit(x_train)
        scaler_fit_on_train_only = bool(np.allclose(refit.mean_, scaler.mean_, equal_nan=True))
    keys = [[row.project_id, row.review_id, row.target] for row in train]
    return {
        "model": spec["model"],
        "kind": spec["kind"],
        "fitted_objects": ["standard_scaler", spec["kind"]] if scaler is not None else [spec["kind"]],
        "scaler_fit_on_train_only": scaler_fit_on_train_only,
        "fit_observation_keys": keys,
        "train_observation_keys": keys,
    }
