"""Deterministic Baselines and Machine Learning Models (Phase 4).

Establishes benchmarks before ML:
1. Majority-class baseline
2. Historical-frequency baseline
3. Latest-failure baseline
4. Rule-based engineering risk baseline
5. Logistic Regression
6. Random Forest
"""
from __future__ import annotations

from collections import Counter
from typing import Any
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

from .constants import FAILURE_CATEGORIES
from .temporal_dataset import TemporalObservation


class MajorityClassBaseline:
    """Predicts the single most prevalent failure category from training data."""

    def __init__(self):
        self.majority_class: str = FAILURE_CATEGORIES[0]
        self.class_prob: float = 1.0

    def fit(self, observations: list[TemporalObservation]) -> MajorityClassBaseline:
        if not observations:
            return self
        counts = Counter(o.target for o in observations)
        most_common, count = counts.most_common(1)[0]
        self.majority_class = most_common
        self.class_prob = count / len(observations)
        return self

    def predict_proba(self, features: dict[str, float]) -> dict[str, float]:
        probs = {cat: 0.0 for cat in FAILURE_CATEGORIES}
        probs[self.majority_class] = round(self.class_prob, 4)
        return probs

    def predict(self, features: dict[str, float]) -> tuple[str, float]:
        return self.majority_class, self.class_prob


class HistoricalFrequencyBaseline:
    """Predicts empirical class distribution based on training history frequencies."""

    def __init__(self):
        self.frequencies: dict[str, float] = {cat: 1.0 / len(FAILURE_CATEGORIES) for cat in FAILURE_CATEGORIES}

    def fit(self, observations: list[TemporalObservation]) -> HistoricalFrequencyBaseline:
        if not observations:
            return self
        counts = Counter(o.target for o in observations)
        total = len(observations)
        self.frequencies = {cat: round(counts.get(cat, 0) / total, 4) for cat in FAILURE_CATEGORIES}
        return self

    def predict_proba(self, features: dict[str, float]) -> dict[str, float]:
        return dict(self.frequencies)

    def predict(self, features: dict[str, float]) -> tuple[str, float]:
        best = max(self.frequencies.items(), key=lambda kv: kv[1])
        return best[0], best[1]


class LatestFailureBaseline:
    """Predicts whatever failure category was active most recently in the component or project."""

    def __init__(self):
        self.fallback = FAILURE_CATEGORIES[0]

    def fit(self, observations: list[TemporalObservation]) -> LatestFailureBaseline:
        if observations:
            self.fallback = observations[-1].target
        return self

    def predict_proba(self, features: dict[str, float]) -> dict[str, float]:
        # Check latest_failure_<cat> features
        for cat in FAILURE_CATEGORIES:
            if features.get(f"latest_failure_{cat}", 0.0) >= 0.5:
                probs = {c: 0.05 for c in FAILURE_CATEGORIES}
                probs[cat] = 0.55
                return probs
        probs = {c: 1.0 / len(FAILURE_CATEGORIES) for c in FAILURE_CATEGORIES}
        probs[self.fallback] = max(probs[self.fallback], 0.30)
        return probs

    def predict(self, features: dict[str, float]) -> tuple[str, float]:
        for cat in FAILURE_CATEGORIES:
            if features.get(f"latest_failure_{cat}", 0.0) >= 0.5:
                return cat, 0.70
        return self.fallback, 0.40


class RuleBasedEngineeringRiskBaseline:
    """Deterministic rule-based risk scoring using static findings and graph exposure."""

    def fit(self, observations: list[TemporalObservation]) -> RuleBasedEngineeringRiskBaseline:
        return self

    def predict_proba(self, features: dict[str, float]) -> dict[str, float]:
        scores: dict[str, float] = {}
        for cat in FAILURE_CATEGORIES:
            weight = 0.10
            # Higher weight if analyzer risk is present
            if features.get(f"static_{cat}_risk", 0.0) > 0:
                weight += 0.40
            # Graph exposure influence
            if cat in ("security", "architecture") and features.get("graph_api_exposure", 0.0) > 0:
                weight += 0.20
            if cat in ("data_integrity", "architecture") and features.get("graph_database_involvement", 0.0) > 0:
                weight += 0.20
            # Testing weakness influence
            if cat == "testing" and features.get("test_missing_evidence", 0.0) > 0:
                weight += 0.30
            # Recent frequency influence
            weight += min(0.30, features.get(f"seq_freq_{cat}", 0.0) * 0.05)
            scores[cat] = weight

        total = sum(scores.values()) or 1.0
        return {cat: round(scores[cat] / total, 4) for cat in FAILURE_CATEGORIES}

    def predict(self, features: dict[str, float]) -> tuple[str, float]:
        probs = self.predict_proba(features)
        best = max(probs.items(), key=lambda kv: kv[1])
        return best[0], best[1]


class LogisticRegressionBaseline:
    """Calibrated multivariable logistic regression baseline."""

    def __init__(self):
        self.model = LogisticRegression(max_iter=2000, random_state=42)
        self.scaler = StandardScaler()
        self.feature_names: list[str] = []
        self.classes_: list[str] = list(FAILURE_CATEGORIES)
        self.is_fitted = False

    def fit(self, observations: list[TemporalObservation]) -> LogisticRegressionBaseline:
        if not observations:
            return self
        self.feature_names = sorted(observations[0].features.keys())
        X = [[o.features.get(f, 0.0) for f in self.feature_names] for o in observations]
        y = [o.target for o in observations]

        unique_y = set(y)
        if len(unique_y) < 2:
            self.is_fitted = False
            return self

        try:
            X_scaled = self.scaler.fit_transform(X)
            self.model.fit(X_scaled, y)
            self.classes_ = list(self.model.classes_)
            self.is_fitted = True
        except Exception:
            self.is_fitted = False
        return self

    def predict_proba(self, features: dict[str, float]) -> dict[str, float]:
        if not self.is_fitted:
            return {c: 1.0 / len(FAILURE_CATEGORIES) for c in FAILURE_CATEGORIES}
        x = [[features.get(f, 0.0) for f in self.feature_names]]
        try:
            x_scaled = self.scaler.transform(x)
            probs_raw = self.model.predict_proba(x_scaled)[0]
        except Exception:
            return {c: 1.0 / len(FAILURE_CATEGORIES) for c in FAILURE_CATEGORIES}
        res = {c: 0.0 for c in FAILURE_CATEGORIES}
        for cls_name, prob in zip(self.classes_, probs_raw):
            res[cls_name] = round(float(prob), 4)
        return res

    def predict(self, features: dict[str, float]) -> tuple[str, float]:
        probs = self.predict_proba(features)
        best = max(probs.items(), key=lambda kv: kv[1])
        return best[0], best[1]


class RandomForestBaseline:
    """Random Forest classifier baseline with feature importances."""

    def __init__(self, n_estimators: int = 50, max_depth: int = 5):
        self.model = RandomForestClassifier(n_estimators=n_estimators, max_depth=max_depth, random_state=42)
        self.feature_names: list[str] = []
        self.classes_: list[str] = list(FAILURE_CATEGORIES)
        self.is_fitted = False
        self.feature_importances_: dict[str, float] = {}

    def fit(self, observations: list[TemporalObservation]) -> RandomForestBaseline:
        if not observations:
            return self
        self.feature_names = sorted(observations[0].features.keys())
        X = [[o.features.get(f, 0.0) for f in self.feature_names] for o in observations]
        y = [o.target for o in observations]

        unique_y = set(y)
        if len(unique_y) < 2:
            self.is_fitted = False
            return self

        try:
            self.model.fit(X, y)
            self.classes_ = list(self.model.classes_)
            self.is_fitted = True
            importances = self.model.feature_importances_
            self.feature_importances_ = {
                name: round(float(imp), 4)
                for name, imp in sorted(zip(self.feature_names, importances), key=lambda x: x[1], reverse=True)
            }
        except Exception:
            self.is_fitted = False
        return self

    def predict_proba(self, features: dict[str, float]) -> dict[str, float]:
        if not self.is_fitted:
            return {c: 1.0 / len(FAILURE_CATEGORIES) for c in FAILURE_CATEGORIES}
        x = [[features.get(f, 0.0) for f in self.feature_names]]
        probs_raw = self.model.predict_proba(x)[0]
        res = {c: 0.0 for c in FAILURE_CATEGORIES}
        for cls_name, prob in zip(self.classes_, probs_raw):
            res[cls_name] = round(float(prob), 4)
        return res

    def predict(self, features: dict[str, float]) -> tuple[str, float]:
        probs = self.predict_proba(features)
        best = max(probs.items(), key=lambda kv: kv[1])
        return best[0], best[1]

