"""Selective Prediction, Robust OOD Detection and Risk-Coverage Analysis (Phase 4.2 / 4.2.1).

Provides trustworthy abstention mechanisms:
1. Robust OOD Detection:
   - Interquartile Range (IQR) bounds [Q1 - 2.5 * IQR, Q3 + 2.5 * IQR]
   - Median Absolute Deviation (MAD) robust z-scores with variance floor
   - Multivariate distance proxy
   - Benchmarks sensitivity, specificity, and false positive rate
2. Confidence-Based Abstention:
   - Rejection below calibrated probability thresholds
3. Coverage-vs-Risk Curve Analysis:
   - Evaluates risk (error rate) as a function of coverage (1 - abstention rate)
   - Reports exact sample accounting: total, retained, abstained, errors before and after
   - Quantifies selective error reduction, per-repository, and per-category coverage
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any

import numpy as np


@dataclass
class RobustFeatureBounds:
    """Statistical reference bounds computed on in-distribution training data."""

    feature_name: str
    median: float
    q1: float
    q3: float
    iqr: float
    lower_bound: float
    upper_bound: float
    mad: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SelectivePredictionResult:
    """Result of a selective prediction check."""

    should_abstain: bool
    status: str  # "PREDICTED", "ABSTAINED_LOW_CONFIDENCE", "ABSTAINED_OOD", "ABSTAINED_INSUFFICIENT_DATA"
    confidence: float
    rejection_reasons: list[str] = field(default_factory=list)
    ood_score: float = 0.0
    outlier_features: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CoverageRiskPoint:
    """A single evaluation point on the coverage-vs-risk curve."""

    confidence_threshold: float
    coverage: float  # Fraction of predictions retained
    abstention_rate: float
    error_rate: float
    risk: float  # Alias of error_rate
    macro_f1: float
    error_reduction_percent: float
    total_samples: int = 0
    retained_samples: int = 0
    abstained_samples: int = 0
    errors_before_abstention: int = 0
    errors_after_abstention: int = 0
    per_repository_coverage: dict[str, float] = field(default_factory=dict)
    per_category_coverage: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SelectiveEvaluationReport:
    """Full coverage-risk curve and selective analysis report."""

    full_coverage_error_rate: float
    full_coverage_macro_f1: float
    recommended_confidence_threshold: float
    retained_coverage: float
    selective_error_rate: float
    relative_error_reduction: float
    curve: list[CoverageRiskPoint]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OODBenchmarkReport:
    """Empirical benchmark of OOD detector sensitivity and specificity."""

    in_distribution_sample_count: int
    out_of_distribution_sample_count: int
    true_positives: int  # OOD correctly rejected
    false_positives: int  # In-distribution falsely rejected
    true_negatives: int  # In-distribution correctly accepted
    false_negatives: int  # OOD falsely accepted
    sensitivity: float  # TP / (TP + FN)
    specificity: float  # TN / (TN + FP)
    false_positive_rate: float  # FP / (FP + TN)
    accuracy: float
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SelectivePredictionEngine:
    """Computes robust distribution bounds, evaluates OOD status, and generates coverage-risk curves."""

    IQR_MULTIPLIER = 2.5
    VARIANCE_FLOOR = 1e-6

    @classmethod
    def fit_reference_bounds(
        cls,
        training_features: list[dict[str, float]],
    ) -> dict[str, RobustFeatureBounds]:
        """Fits robust median/IQR/MAD reference bounds from in-distribution training data."""
        if not training_features:
            return {}

        feature_keys = sorted(list(training_features[0].keys()))
        bounds: dict[str, RobustFeatureBounds] = {}

        for key in feature_keys:
            vals = np.array([f.get(key, 0.0) for f in training_features], dtype=float)
            med = float(np.median(vals))
            q1 = float(np.percentile(vals, 25))
            q3 = float(np.percentile(vals, 75))
            iqr = max(float(q3 - q1), cls.VARIANCE_FLOOR)

            lower = q1 - cls.IQR_MULTIPLIER * iqr
            upper = q3 + cls.IQR_MULTIPLIER * iqr

            # Median Absolute Deviation
            mad = max(float(np.median(np.abs(vals - med))), cls.VARIANCE_FLOOR)

            bounds[key] = RobustFeatureBounds(
                feature_name=key,
                median=med,
                q1=q1,
                q3=q3,
                iqr=iqr,
                lower_bound=lower,
                upper_bound=upper,
                mad=mad,
            )

        return bounds

    @classmethod
    def evaluate_sample(
        cls,
        features: dict[str, float],
        probabilities: dict[str, float],
        reference_bounds: dict[str, RobustFeatureBounds] | None = None,
        min_confidence: float = 0.55,
        max_ood_score: float = 3.0,
    ) -> SelectivePredictionResult:
        """Determines whether to abstain based on OOD bounds and calibrated confidence."""
        if not probabilities:
            return SelectivePredictionResult(
                should_abstain=True,
                status="ABSTAINED_INSUFFICIENT_DATA",
                confidence=0.0,
                rejection_reasons=["No prediction probabilities available."],
            )

        top_prob = max(probabilities.values())
        reasons: list[str] = []
        outliers: list[str] = []
        total_z = 0.0
        feature_count = 0

        # Check OOD bounds if reference bounds are provided
        if reference_bounds:
            for k, b in reference_bounds.items():
                val = features.get(k, b.median)
                z = abs(val - b.median) / (1.4826 * b.mad)
                total_z += z
                feature_count += 1

                if val < b.lower_bound or val > b.upper_bound:
                    outliers.append(k)

        ood_score = (total_z / feature_count) if feature_count > 0 else 0.0

        is_ood = (ood_score > max_ood_score) or (len(outliers) >= 3)
        is_low_conf = top_prob < min_confidence

        if is_ood:
            reasons.append(
                f"Sample is out-of-distribution (OOD score: {ood_score:.2f} > {max_ood_score:.2f}; "
                f"{len(outliers)} outlier features: {outliers[:3]})."
            )
            return SelectivePredictionResult(
                should_abstain=True,
                status="ABSTAINED_OOD",
                confidence=top_prob,
                rejection_reasons=reasons,
                ood_score=float(ood_score),
                outlier_features=outliers,
            )

        if is_low_conf:
            reasons.append(
                f"Prediction confidence ({top_prob:.3f}) is below minimum threshold ({min_confidence:.3f})."
            )
            return SelectivePredictionResult(
                should_abstain=True,
                status="ABSTAINED_LOW_CONFIDENCE",
                confidence=top_prob,
                rejection_reasons=reasons,
                ood_score=float(ood_score),
                outlier_features=outliers,
            )

        return SelectivePredictionResult(
            should_abstain=False,
            status="PREDICTED",
            confidence=top_prob,
            rejection_reasons=[],
            ood_score=float(ood_score),
            outlier_features=outliers,
        )

    @classmethod
    def evaluate_ood_detection(
        cls,
        in_distribution_features: list[dict[str, float]],
        out_of_distribution_features: list[dict[str, float]],
        reference_bounds: dict[str, RobustFeatureBounds],
        max_ood_score: float = 3.0,
    ) -> OODBenchmarkReport:
        """Benchmarks OOD detection sensitivity, specificity, and false positive rates."""
        tp = 0  # OOD rejected
        fn = 0  # OOD accepted
        fp = 0  # In-distribution rejected
        tn = 0  # In-distribution accepted

        dummy_probs = {"category_a": 0.90, "category_b": 0.10}

        for feats in out_of_distribution_features:
            res = cls.evaluate_sample(feats, dummy_probs, reference_bounds, min_confidence=0.50, max_ood_score=max_ood_score)
            if res.should_abstain and res.status == "ABSTAINED_OOD":
                tp += 1
            else:
                fn += 1

        for feats in in_distribution_features:
            res = cls.evaluate_sample(feats, dummy_probs, reference_bounds, min_confidence=0.50, max_ood_score=max_ood_score)
            if res.should_abstain and res.status == "ABSTAINED_OOD":
                fp += 1
            else:
                tn += 1

        n_ood = len(out_of_distribution_features)
        n_in = len(in_distribution_features)
        total = n_ood + n_in

        sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        accuracy = (tp + tn) / total if total > 0 else 0.0

        limitations = [
            "Quantile IQR bounds assume continuous feature distributions; discrete counts may exhibit boundary clumping.",
            "Multivariate distance proxy ignores non-linear covariance structures between distant components.",
            "High sensitivity on synthetic shift fixtures may degrade on subtle in-domain concept drift.",
        ]

        return OODBenchmarkReport(
            in_distribution_sample_count=n_in,
            out_of_distribution_sample_count=n_ood,
            true_positives=tp,
            false_positives=fp,
            true_negatives=tn,
            false_negatives=fn,
            sensitivity=round(sensitivity, 4),
            specificity=round(specificity, 4),
            false_positive_rate=round(fpr, 4),
            accuracy=round(accuracy, 4),
            limitations=limitations,
        )

    @classmethod
    def generate_coverage_risk_curve(
        cls,
        y_true: list[str],
        predicted_classes: list[str],
        confidences: list[float],
        thresholds: list[float] | None = None,
        repository_ids: list[str] | None = None,
    ) -> SelectiveEvaluationReport:
        """Computes coverage vs risk across confidence thresholds with detailed sample accounting."""
        if not thresholds:
            thresholds = [0.0, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]

        n = len(y_true)
        if n == 0 or len(predicted_classes) != n or len(confidences) != n:
            return SelectiveEvaluationReport(
                full_coverage_error_rate=0.0,
                full_coverage_macro_f1=0.0,
                recommended_confidence_threshold=0.55,
                retained_coverage=0.0,
                selective_error_rate=0.0,
                relative_error_reduction=0.0,
                curve=[],
            )

        # Baseline metrics at threshold 0.0 (full coverage)
        baseline_errors = sum(1 for yt, yp in zip(y_true, predicted_classes) if yt != yp)
        baseline_error_rate = baseline_errors / n
        baseline_f1 = cls._calculate_macro_f1(y_true, predicted_classes)

        curve_points: list[CoverageRiskPoint] = []
        unique_categories = sorted(list(set(y_true)))
        unique_repos = sorted(list(set(repository_ids or [])))

        for th in thresholds:
            retained_indices = [i for i, c in enumerate(confidences) if c >= th]
            retained_count = len(retained_indices)
            abstained_count = n - retained_count

            if retained_count == 0:
                coverage = 0.0
                abstention_rate = 1.0
                err_rate = 0.0
                f1 = 0.0
                err_reduc = 0.0
                sub_errors = 0
                per_cat_cov = {cat: 0.0 for cat in unique_categories}
                per_repo_cov = {r: 0.0 for r in unique_repos}
            else:
                coverage = retained_count / n
                abstention_rate = 1.0 - coverage
                sub_y_true = [y_true[i] for i in retained_indices]
                sub_y_pred = [predicted_classes[i] for i in retained_indices]

                sub_errors = sum(1 for yt, yp in zip(sub_y_true, sub_y_pred) if yt != yp)
                err_rate = sub_errors / retained_count
                f1 = cls._calculate_macro_f1(sub_y_true, sub_y_pred)

                err_reduc = (
                    ((baseline_error_rate - err_rate) / baseline_error_rate * 100.0)
                    if baseline_error_rate > 0
                    else 0.0
                )

                # Per-category coverage
                per_cat_cov = {}
                for cat in unique_categories:
                    cat_total = sum(1 for yt in y_true if yt == cat)
                    cat_retained = sum(1 for i in retained_indices if y_true[i] == cat)
                    per_cat_cov[cat] = round(cat_retained / cat_total, 4) if cat_total > 0 else 1.0

                # Per-repository coverage
                per_repo_cov = {}
                if repository_ids and len(repository_ids) == n:
                    for r_id in unique_repos:
                        repo_total = sum(1 for r in repository_ids if r == r_id)
                        repo_retained = sum(1 for i in retained_indices if repository_ids[i] == r_id)
                        per_repo_cov[r_id] = round(repo_retained / repo_total, 4) if repo_total > 0 else 1.0

            curve_points.append(
                CoverageRiskPoint(
                    confidence_threshold=float(th),
                    coverage=float(coverage),
                    abstention_rate=float(abstention_rate),
                    error_rate=float(err_rate),
                    risk=float(err_rate),
                    macro_f1=float(f1),
                    error_reduction_percent=float(err_reduc),
                    total_samples=n,
                    retained_samples=retained_count,
                    abstained_samples=abstained_count,
                    errors_before_abstention=baseline_errors,
                    errors_after_abstention=sub_errors,
                    per_repository_coverage=per_repo_cov,
                    per_category_coverage=per_cat_cov,
                )
            )

        # Pick recommended threshold: maximizes F1 while retaining >= 50% coverage
        valid_candidates = [p for p in curve_points if p.coverage >= 0.50]
        if valid_candidates:
            best_point = max(valid_candidates, key=lambda p: (p.macro_f1, -p.error_rate))
        else:
            best_point = curve_points[0]

        return SelectiveEvaluationReport(
            full_coverage_error_rate=float(baseline_error_rate),
            full_coverage_macro_f1=float(baseline_f1),
            recommended_confidence_threshold=best_point.confidence_threshold,
            retained_coverage=best_point.coverage,
            selective_error_rate=best_point.error_rate,
            relative_error_reduction=best_point.error_reduction_percent,
            curve=curve_points,
        )

    @classmethod
    def _calculate_macro_f1(cls, y_true: list[str], y_pred: list[str]) -> float:
        """Computes multiclass Macro-F1."""
        classes = sorted(list(set(y_true + y_pred)))
        if not classes:
            return 0.0

        f1s = []
        for c in classes:
            tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == c and yp == c)
            fp = sum(1 for yt, yp in zip(y_true, y_pred) if yt != c and yp == c)
            fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == c and yp != c)

            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
            f1s.append(f1)

        return float(np.mean(f1s))
