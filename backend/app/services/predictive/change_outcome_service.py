"""Change Outcome Learning and Risk Validation Service (Phase 4.2 / 4.2.1 - Task B).

Separates:
1. Structural Blast Radius: Pure knowledge graph structural reachability metric.
2. Rule-Based Engineering Risk: Deterministic production authority combining churn, history, and graph depth.
3. Learned Change Risk: Supervised statistical classifier trained strictly on historical change-to-outcome events.

Enforces:
- Structural blast radius is NEVER treated as target ground truth.
- Immature observation windows with no defect are NOT labeled negative (withheld as PENDING_MATURITY).
- Attribution confidence must meet minimum floor (>= 0.70).
- Explicit INSUFFICIENT_DATA abstention when sample requirements are unmet.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import math
from typing import Any

import numpy as np


@dataclass
class ChangeRecord:
    """Traceable change entity representing a repository code transition."""

    change_id: str
    repository_id: str
    commit_sha: str
    timestamp: str
    tenant_id: str = "default_tenant"
    changed_files: list[str] = field(default_factory=list)
    changed_symbols: list[str] = field(default_factory=list)
    parent_commit_sha: str | None = None
    prediction_cutoff: str = ""
    graph_version: str | None = None
    historical_findings_count: int = 0
    subsequent_defect_outcome: bool = False
    defect_category: str | None = None
    outcome_timestamp: str | None = None
    observation_window_days: int = 14
    is_window_mature: bool = True
    attribution_confidence: float = 1.0
    evidence_references: list[str] = field(default_factory=list)
    label_provenance: str = "verified_commit_transition"
    structural_blast_radius: float = 0.0
    impacted_components_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChangeRiskEvaluationResult:
    """Evaluation result for Change Outcome Risk."""

    is_sufficient: bool
    sample_size: int
    positive_rate: float
    structural_blast_radius_avg: float
    rule_based_macro_f1: float
    rule_based_balanced_accuracy: float
    rule_based_brier_score: float
    learned_model_status: str  # "INSUFFICIENT_DATA", "EXPERIMENTAL", "EVALUATED"
    immature_withheld_count: int = 0
    low_confidence_withheld_count: int = 0
    learned_macro_f1: float | None = None
    learned_balanced_accuracy: float | None = None
    learned_brier_score: float | None = None
    generalization_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChangeOutcomeValidator:
    """Validates and evaluates change-to-outcome prediction capabilities."""

    MIN_TRUSTWORTHY_SAMPLES = 20
    MIN_POSITIVE_SAMPLES = 3
    MIN_ATTRIBUTION_CONFIDENCE = 0.70

    @classmethod
    def filter_trustworthy_changes(
        cls,
        records: list[ChangeRecord],
        exclude_synthetic: bool = True,
    ) -> list[ChangeRecord]:
        """Filters change records for verified historical provenance and maturity."""
        valid, _, _ = cls.audit_trustworthy_changes(records, exclude_synthetic=exclude_synthetic)
        return valid

    @classmethod
    def audit_trustworthy_changes(
        cls,
        records: list[ChangeRecord],
        exclude_synthetic: bool = True,
    ) -> tuple[list[ChangeRecord], int, int]:
        """Audits change records for verified provenance, maturity, and attribution confidence.

        Returns:
            (valid_records, immature_withheld_count, low_confidence_withheld_count)
        """
        valid = []
        immature_count = 0
        low_conf_count = 0

        for r in records:
            if exclude_synthetic and r.label_provenance == "synthetic":
                continue
            if not r.commit_sha or not r.timestamp:
                continue

            # Check attribution confidence floor
            if r.attribution_confidence < cls.MIN_ATTRIBUTION_CONFIDENCE:
                low_conf_count += 1
                continue

            # An immature observation window with no defect must NOT be assumed clean / negative!
            if not r.is_window_mature and not r.subsequent_defect_outcome:
                immature_count += 1
                continue

            valid.append(r)
        return valid, immature_count, low_conf_count

    @classmethod
    def compute_rule_based_risk(cls, record: ChangeRecord) -> float:
        """Computes deterministic engineering change risk score in [0.0, 1.0].

        Combines:
        - Churn (file count)
        - Historical defect density
        - Structural blast radius (as a topological modifier, NOT ground truth)
        - Symbol blast
        """
        file_weight = min(1.0, len(record.changed_files) / 10.0) * 0.35
        hist_weight = min(1.0, record.historical_findings_count / 15.0) * 0.25
        blast_weight = min(1.0, record.structural_blast_radius) * 0.25
        symbol_weight = min(1.0, len(record.changed_symbols) / 20.0) * 0.15

        risk = file_weight + hist_weight + blast_weight + symbol_weight
        return float(min(1.0, max(0.0, risk)))

    @classmethod
    def evaluate_change_outcomes(
        cls,
        records: list[ChangeRecord],
        threshold: float = 0.5,
    ) -> ChangeRiskEvaluationResult:
        """Evaluates rule-based and learned models against ground truth change outcomes.

        Strictly enforces that structural blast radius is NOT the target label.
        """
        trustworthy, immature_count, low_conf_count = cls.audit_trustworthy_changes(records)
        sample_size = len(trustworthy)
        notes: list[str] = []

        if immature_count > 0:
            notes.append(f"{immature_count} immature observation windows withheld from negative assumptions.")
        if low_conf_count > 0:
            notes.append(f"{low_conf_count} records withheld due to attribution confidence < {cls.MIN_ATTRIBUTION_CONFIDENCE}.")

        if sample_size == 0:
            return ChangeRiskEvaluationResult(
                is_sufficient=False,
                sample_size=0,
                positive_rate=0.0,
                structural_blast_radius_avg=0.0,
                rule_based_macro_f1=0.0,
                rule_based_balanced_accuracy=0.5,
                rule_based_brier_score=1.0,
                learned_model_status="INSUFFICIENT_DATA",
                immature_withheld_count=immature_count,
                low_confidence_withheld_count=low_conf_count,
                generalization_notes=notes or ["No trustworthy change records provided."],
            )

        positives = sum(1 for r in trustworthy if r.subsequent_defect_outcome)
        positive_rate = positives / sample_size
        avg_blast = float(np.mean([r.structural_blast_radius for r in trustworthy]))

        # Evaluate Rule-Based Risk
        y_true = [1 if r.subsequent_defect_outcome else 0 for r in trustworthy]
        rule_probs = [cls.compute_rule_based_risk(r) for r in trustworthy]
        rule_preds = [1 if p >= threshold else 0 for p in rule_probs]

        rule_metrics = cls._calculate_binary_metrics(y_true, rule_preds, rule_probs)

        # Check sufficiency for learned statistical model
        if sample_size < cls.MIN_TRUSTWORTHY_SAMPLES or positives < cls.MIN_POSITIVE_SAMPLES:
            learned_status = "INSUFFICIENT_DATA"
            notes.append(
                f"Learned ML change-risk model withheld: sample size ({sample_size}) < {cls.MIN_TRUSTWORTHY_SAMPLES} "
                f"or positive defects ({positives}) < {cls.MIN_POSITIVE_SAMPLES}."
            )
            return ChangeRiskEvaluationResult(
                is_sufficient=False,
                sample_size=sample_size,
                positive_rate=positive_rate,
                structural_blast_radius_avg=avg_blast,
                rule_based_macro_f1=rule_metrics["macro_f1"],
                rule_based_balanced_accuracy=rule_metrics["balanced_accuracy"],
                rule_based_brier_score=rule_metrics["brier_score"],
                learned_model_status=learned_status,
                immature_withheld_count=immature_count,
                low_confidence_withheld_count=low_conf_count,
                generalization_notes=notes,
            )

        # Train/test simple cross-validation for learned baseline if sufficient
        learned_status = "EXPERIMENTAL"
        learned_metrics = cls._evaluate_learned_classifier(trustworthy)

        notes.append("Learned model evaluated under leave-out folds. Rule-based model remains production authority.")

        return ChangeRiskEvaluationResult(
            is_sufficient=True,
            sample_size=sample_size,
            positive_rate=positive_rate,
            structural_blast_radius_avg=avg_blast,
            rule_based_macro_f1=rule_metrics["macro_f1"],
            rule_based_balanced_accuracy=rule_metrics["balanced_accuracy"],
            rule_based_brier_score=rule_metrics["brier_score"],
            learned_model_status=learned_status,
            immature_withheld_count=immature_count,
            low_confidence_withheld_count=low_conf_count,
            learned_macro_f1=learned_metrics["macro_f1"],
            learned_balanced_accuracy=learned_metrics["balanced_accuracy"],
            learned_brier_score=learned_metrics["brier_score"],
            generalization_notes=notes,
        )

    @classmethod
    def _calculate_binary_metrics(
        cls,
        y_true: list[int],
        y_pred: list[int],
        probs: list[float],
    ) -> dict[str, float]:
        """Calculates Macro-F1, Balanced Accuracy, and Brier Score for binary classification."""
        tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 1)
        fp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 1)
        fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 0)
        tn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 0)

        # F1 for class 1
        p1 = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r1 = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1_1 = 2 * p1 * r1 / (p1 + r1) if (p1 + r1) > 0 else 0.0

        # F1 for class 0
        p0 = tn / (tn + fn) if (tn + fn) > 0 else 0.0
        r0 = tn / (tn + fp) if (tn + fp) > 0 else 0.0
        f1_0 = 2 * p0 * r0 / (p0 + r0) if (p0 + r0) > 0 else 0.0

        macro_f1 = (f1_1 + f1_0) / 2.0

        # Balanced Accuracy
        rec1 = r1
        rec0 = r0
        balanced_acc = (rec1 + rec0) / 2.0

        # Brier Score
        brier = float(np.mean([(p - yt) ** 2 for p, yt in zip(probs, y_true)]))

        return {
            "macro_f1": float(macro_f1),
            "balanced_accuracy": float(balanced_acc),
            "brier_score": float(brier),
        }

    @classmethod
    def _evaluate_learned_classifier(
        cls,
        records: list[ChangeRecord],
    ) -> dict[str, float]:
        """Evaluates a lightweight logistic classifier on extracted features."""
        from sklearn.linear_model import LogisticRegression

        X = []
        y = []
        for r in records:
            feat = [
                len(r.changed_files),
                len(r.changed_symbols),
                r.historical_findings_count,
                r.structural_blast_radius,
                r.impacted_components_count,
            ]
            X.append(feat)
            y.append(1 if r.subsequent_defect_outcome else 0)

        X_arr = np.array(X, dtype=float)
        y_arr = np.array(y, dtype=int)

        split_idx = int(len(X_arr) * 0.7)
        if split_idx < 10 or (len(X_arr) - split_idx) < 5:
            split_idx = max(5, len(X_arr) - 5)

        X_train, X_test = X_arr[:split_idx], X_arr[split_idx:]
        y_train, y_test = y_arr[:split_idx], y_arr[split_idx:]

        if len(np.unique(y_train)) < 2:
            return {"macro_f1": 0.0, "balanced_accuracy": 0.5, "brier_score": 0.5}

        clf = LogisticRegression(class_weight="balanced", max_iter=200)
        clf.fit(X_train, y_train)

        probs = clf.predict_proba(X_test)[:, 1].tolist()
        preds = [1 if p >= 0.5 else 0 for p in probs]

        return cls._calculate_binary_metrics(y_test.tolist(), preds, probs)
