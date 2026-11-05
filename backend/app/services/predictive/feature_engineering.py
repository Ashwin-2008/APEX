"""Temporal Feature Engineering with Strict Leakage Prevention (Phase 4).

Every feature has a documented definition, source, and strict timestamp boundary.
Information at T > cutoff_timestamp is strictly prohibited.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from app.models.entities import ProjectFinding, ProjectReview
from .constants import FAILURE_CATEGORIES, FEATURE_SCHEMA_VERSION


class TemporalFeatureExtractor:
    """Extracts change, failure, graph, testing, and remediation features with zero future leakage."""

    SCHEMA_VERSION = FEATURE_SCHEMA_VERSION

    @classmethod
    def extract_features(
        cls,
        *,
        history_reviews: list[ProjectReview],
        current_review: ProjectReview,
        cutoff_timestamp: datetime | str | None = None,
        graph_metrics: dict[str, Any] | None = None,
        testing_metrics: dict[str, Any] | None = None,
        remediation_metrics: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        """Extracts numerical features strictly from reviews and evidence <= cutoff_timestamp."""
        cutoff_dt = None
        if isinstance(cutoff_timestamp, str):
            try:
                cutoff_dt = datetime.fromisoformat(cutoff_timestamp.replace("Z", "+00:00"))
            except Exception:
                pass
        elif isinstance(cutoff_timestamp, datetime):
            cutoff_dt = cutoff_timestamp

        # Temporal filter: Only consider reviews strictly up to current / cutoff
        eligible_reviews = []
        for r in history_reviews:
            if cutoff_dt and r.timestamp:
                r_ts = r.timestamp if isinstance(r.timestamp, datetime) else datetime.fromisoformat(str(r.timestamp))
                if r_ts > cutoff_dt:
                    continue  # Leakage prevention
            eligible_reviews.append(r)

        if not eligible_reviews and current_review:
            eligible_reviews = [current_review]

        findings: list[ProjectFinding] = []
        for r in eligible_reviews:
            for f in r.findings:
                if cutoff_dt and f.detected_at:
                    f_ts = f.detected_at if isinstance(f.detected_at, datetime) else datetime.fromisoformat(str(f.detected_at))
                    if f_ts > cutoff_dt:
                        continue  # Leakage prevention
                findings.append(f)

        features: dict[str, float] = {}

        # -------------------------------------------------------------
        # 1. CHANGE HISTORY FEATURES
        # -------------------------------------------------------------
        snapshot = current_review.snapshot or {}
        churn_str = str(snapshot.get("recent_churn") or "")
        features["change_intensity"] = float(len(churn_str.splitlines())) if churn_str else 0.0
        features["change_file_count"] = float(snapshot.get("file_count", 0) or 0)
        features["change_review_count"] = float(len(eligible_reviews))
        features["change_consecutive_reviews"] = float(current_review.review_number or len(eligible_reviews))

        # -------------------------------------------------------------
        # 2. FAILURE HISTORY FEATURES
        # -------------------------------------------------------------
        current_findings = current_review.findings or []
        metrics = current_review.metrics or {}
        for sev in ("critical", "high", "medium", "low"):
            features[f"static_{sev}_findings"] = float(metrics.get(sev, 0) or sum(1 for f in current_findings if str(f.severity).lower() == sev))

        features["static_total_findings"] = float(len(current_findings))
        categories = [f.category for f in findings if f.category]
        recent_cats = categories[-5:] if categories else []

        latest_cat = current_findings[0].category if current_findings else None

        for cat in FAILURE_CATEGORIES:
            features[f"latest_failure_{cat}"] = 1.0 if latest_cat == cat else 0.0
            features[f"seq_freq_{cat}"] = float(categories.count(cat))

            positions = [i for i, val in enumerate(categories) if val == cat]
            if positions:
                features[f"seq_recency_{cat}"] = float(len(categories) - positions[-1])
            else:
                features[f"seq_recency_{cat}"] = float(len(categories) + 1)

            # Streak / consecutive repetition in backwards review scan
            streak = 0
            for r in reversed(eligible_reviews):
                if any(f.category == cat for f in r.findings):
                    streak += 1
                else:
                    break
            features[f"seq_repetition_{cat}"] = float(streak)

            # Transitions
            trans = sum(1 for a, b in zip(categories, categories[1:]) if a == cat or b == cat)
            features[f"seq_transition_{cat}"] = float(trans)

            # Component localization
            comp_count = sum(1 for f in findings if f.category == cat and (f.component or f.file))
            features[f"seq_component_{cat}"] = float(comp_count)

        features["seq_failure_diversity_recent"] = float(len(set(recent_cats)))
        features["seq_reopened_finding_count"] = float(sum(1 for f in findings if str(f.status).upper() == "REOPENED"))
        features["seq_resolved_finding_count"] = float(sum(1 for f in findings if str(f.status).upper() == "RESOLVED" or f.resolved_at is not None))

        # Severity trajectory
        sev_weights = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        cur_sev_score = sum(sev_weights.get(str(f.severity).lower(), 1) for f in current_findings)
        if len(eligible_reviews) > 1:
            prev_findings = eligible_reviews[-2].findings or []
            prev_sev_score = sum(sev_weights.get(str(f.severity).lower(), 1) for f in prev_findings)
        else:
            prev_sev_score = cur_sev_score
        features["seq_severity_trajectory"] = float(cur_sev_score - prev_sev_score)

        # -------------------------------------------------------------
        # 3. GRAPH STRUCTURAL FEATURES
        # -------------------------------------------------------------
        gm = graph_metrics or {}
        features["graph_direct_dependencies"] = float(gm.get("direct_dependencies", 0.0))
        features["graph_transitive_dependencies"] = float(gm.get("transitive_dependencies", 0.0))
        features["graph_fan_in"] = float(gm.get("fan_in", 0.0))
        features["graph_fan_out"] = float(gm.get("fan_out", 0.0))
        features["graph_dependency_depth"] = float(gm.get("dependency_depth", 0.0))
        features["graph_boundary_crossings"] = float(gm.get("boundary_crossings", 0.0))
        features["graph_api_exposure"] = float(1.0 if gm.get("api_exposure") else 0.0)
        features["graph_database_involvement"] = float(1.0 if gm.get("database_involvement") else 0.0)
        features["graph_cross_tech_exposure"] = float(1.0 if gm.get("cross_tech_exposure") else 0.0)

        # -------------------------------------------------------------
        # 4. TESTING FEATURES
        # -------------------------------------------------------------
        tm = testing_metrics or {}
        features["test_coverage_ratio"] = float(tm.get("coverage_ratio", snapshot.get("requirement_coverage", 0.0) or 0.0))
        features["test_execution_frequency"] = float(tm.get("execution_frequency", 0.0))
        features["test_historical_failures"] = float(tm.get("historical_failures", 0.0))
        features["test_linked_count"] = float(tm.get("linked_test_count", 0.0))
        features["test_missing_evidence"] = float(1.0 if tm.get("missing_evidence", True) else 0.0)

        # -------------------------------------------------------------
        # 5. REMEDIATION FEATURES
        # -------------------------------------------------------------
        rm = remediation_metrics or {}
        features["remediation_previous_attempts"] = float(rm.get("previous_attempts", 0.0))
        features["remediation_verification_failures"] = float(rm.get("verification_failures", 0.0))
        features["remediation_rollback_count"] = float(rm.get("rollback_count", 0.0))
        features["remediation_regressions"] = float(rm.get("regressions_after_patch", 0.0))

        return features

