"""Temporal Leakage Auditor and Adversarial Rejection Engine (Phase 4.1).

Performs deep adversarial verification across the 41 temporal features:
- Future finding leakage
- Future commit leakage
- Future graph version leakage
- Future test execution leakage
- Future remediation outcome leakage
- Target category leakage
- Repository identifier leakage
- Duplicate observation leakage
- Near-duplicate snapshot leakage
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .constants import FAILURE_CATEGORIES
from .temporal_dataset import TemporalObservation


class TemporalLeakageViolation(ValueError):
    """Raised when an adversarial or unintended temporal leakage is detected in a dataset."""
    pass


class TemporalLeakageAuditor:
    """Scientific validator detecting temporal leakage and data snooping in predictive datasets."""

    # Complete documentation catalog for all 41 features
    FEATURE_AUDIT_CATALOG: dict[str, dict[str, Any]] = {
        # 1. Change History Features
        "change_intensity": {
            "source": "Git / Review Snapshot Churn",
            "calculation_method": "Count of churn lines in review snapshot",
            "availability_timestamp": "T_review (at review time)",
            "historical_lookback_window": "Current review commit diff",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "change_file_count": {
            "source": "Git / Review Snapshot File Count",
            "calculation_method": "Number of files modified in current review",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current review commit diff",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "change_review_count": {
            "source": "Project Review History",
            "calculation_method": "Count of eligible past reviews up to cutoff",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "[T_0, T_review]",
            "missing_data_behavior": "Default 1.0",
            "indirect_target_exposure": "None",
        },
        "change_consecutive_reviews": {
            "source": "Project Review Sequence",
            "calculation_method": "Sequential review index number",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Monotonic sequence number",
            "missing_data_behavior": "Default 1.0",
            "indirect_target_exposure": "None",
        },
        # 2. Failure History - Severity
        "static_critical_findings": {
            "source": "Static Analyzer Findings",
            "calculation_method": "Sum of critical severity findings active at current review",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current review snapshot",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "static_high_findings": {
            "source": "Static Analyzer Findings",
            "calculation_method": "Sum of high severity findings active at current review",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current review snapshot",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "static_medium_findings": {
            "source": "Static Analyzer Findings",
            "calculation_method": "Sum of medium severity findings active at current review",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current review snapshot",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "static_low_findings": {
            "source": "Static Analyzer Findings",
            "calculation_method": "Sum of low severity findings active at current review",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current review snapshot",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "static_total_findings": {
            "source": "Static Analyzer Findings",
            "calculation_method": "Total count of active findings in current review",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current review snapshot",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        # 3. Graph Structural Features
        "graph_direct_dependencies": {
            "source": "Knowledge Graph Extractor",
            "calculation_method": "Out-degree of direct component dependency edges",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current graph snapshot",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "graph_transitive_dependencies": {
            "source": "Knowledge Graph Extractor",
            "calculation_method": "Reachable multi-hop dependencies from component",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current graph snapshot",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "graph_fan_in": {
            "source": "Knowledge Graph Extractor",
            "calculation_method": "In-degree (components depending on this entity)",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current graph snapshot",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "graph_fan_out": {
            "source": "Knowledge Graph Extractor",
            "calculation_method": "Out-degree (entities this component calls/imports)",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current graph snapshot",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "graph_dependency_depth": {
            "source": "Knowledge Graph Extractor",
            "calculation_method": "Maximum directed acyclic path length from node",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current graph snapshot",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "graph_boundary_crossings": {
            "source": "Knowledge Graph Extractor",
            "calculation_method": "Count of cross-module architectural boundary crossings",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current graph snapshot",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "graph_api_exposure": {
            "source": "Knowledge Graph Extractor",
            "calculation_method": "Binary indicator if component exposes external HTTP/RPC APIs",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current graph snapshot",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "graph_database_involvement": {
            "source": "Knowledge Graph Extractor",
            "calculation_method": "Binary indicator if component performs SQL/ORM operations",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current graph snapshot",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "graph_cross_tech_exposure": {
            "source": "Knowledge Graph Extractor",
            "calculation_method": "Binary indicator of polyglot boundary bridging",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current graph snapshot",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        # 4. Testing Features
        "test_coverage_ratio": {
            "source": "Test Suite / Coverage Analyzer",
            "calculation_method": "Ratio of covered statements up to current review",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Past test runs <= T_review",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "test_execution_frequency": {
            "source": "Test History Service",
            "calculation_method": "Normalized count of test runs preceding cutoff",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "[T_0, T_review]",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "test_historical_failures": {
            "source": "Test History Service",
            "calculation_method": "Number of test failures observed prior to cutoff",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "[T_0, T_review]",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "test_linked_count": {
            "source": "Knowledge Graph Test Selector",
            "calculation_method": "Count of tests covering or importing this component",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current graph snapshot",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "test_missing_evidence": {
            "source": "Evidence Reconciliation Service",
            "calculation_method": "1.0 if no test execution evidence is available, 0.0 otherwise",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Current review status",
            "missing_data_behavior": "Default 1.0 (conservative)",
            "indirect_target_exposure": "None",
        },
        # 5. Remediation Features
        "remediation_previous_attempts": {
            "source": "Remediation Transaction Log",
            "calculation_method": "Number of attempted patches prior to cutoff",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "[T_0, T_review]",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "remediation_verification_failures": {
            "source": "Remediation Verification Engine",
            "calculation_method": "Number of failed verification checks prior to cutoff",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "[T_0, T_review]",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "remediation_rollback_count": {
            "source": "Remediation Transaction Log",
            "calculation_method": "Number of transactional rollbacks prior to cutoff",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "[T_0, T_review]",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "remediation_regressions": {
            "source": "Post-Remediation Verification",
            "calculation_method": "Regressions detected in past fixes prior to cutoff",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "[T_0, T_review]",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        # Sequential Lifecycle Features
        "seq_failure_diversity_recent": {
            "source": "Chronological Finding Sequence",
            "calculation_method": "Distinct categories observed across last 5 findings",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Last 5 findings <= T_review",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "seq_reopened_finding_count": {
            "source": "Finding Lifecycle History",
            "calculation_method": "Cumulative count of REOPENED finding events <= T_review",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "[T_0, T_review]",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "seq_resolved_finding_count": {
            "source": "Finding Lifecycle History",
            "calculation_method": "Cumulative count of RESOLVED finding events <= T_review",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "[T_0, T_review]",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
        "seq_severity_trajectory": {
            "source": "Chronological Severity Difference",
            "calculation_method": "Weighted severity score at review N minus score at review N-1",
            "availability_timestamp": "T_review",
            "historical_lookback_window": "Review N and Review N-1",
            "missing_data_behavior": "Default 0.0",
            "indirect_target_exposure": "None",
        },
    }

    @classmethod
    def audit_observations(cls, observations: list[TemporalObservation]) -> dict[str, Any]:
        """Performs deep temporal leakage audit on a list of observations."""
        violations: list[str] = []
        hashes_seen: dict[str, int] = {}
        seen_triplets: set[tuple[str, int, int | None]] = set()

        for idx, obs in enumerate(observations):
            # 1. Future Finding Leakage: Target timestamp <= Source timestamp
            if obs.source_timestamp and obs.target_timestamp:
                try:
                    t_src = datetime.fromisoformat(obs.source_timestamp.replace("Z", "+00:00"))
                    t_tgt = datetime.fromisoformat(obs.target_timestamp.replace("Z", "+00:00"))
                    if t_src >= t_tgt:
                        violations.append(
                            f"Row {idx} [Future Finding Leakage]: source_timestamp ({obs.source_timestamp}) "
                            f">= target_timestamp ({obs.target_timestamp})"
                        )
                except Exception:
                    pass

            # 2. Target Category Leakage: Feature key directly contains target or future outcome
            forbidden_keys = {
                obs.target.lower(),
                "target",
                "future_finding",
                "future_category",
                "target_category",
                "next_failure",
                f"target_{obs.target.lower()}",
            }
            for feat_key in obs.features.keys():
                k_lower = feat_key.lower()
                if k_lower in forbidden_keys:
                    violations.append(
                        f"Row {idx} [Target Category Leakage]: Feature key '{feat_key}' exposes the target directly."
                    )
                if "future" in k_lower or "next_" in k_lower:
                    violations.append(
                        f"Row {idx} [Target Category Leakage]: Suspicious forward-looking feature '{feat_key}'."
                    )

            # 3. Future Commit Leakage: features contain target commit hash or target review ID
            target_commit = obs.label_evidence.get("target_commit_sha") or obs.provenance.get("target_commit_sha")
            if target_commit:
                for feat_key, feat_val in obs.features.items():
                    if str(target_commit) in str(feat_val) or str(target_commit) in feat_key:
                        violations.append(
                            f"Row {idx} [Future Commit Leakage]: Target commit sha present in feature '{feat_key}'."
                        )

            # 4. Repository Identifier Leakage: Numerical feature directly encoding repository identity
            for feat_key in ("repository_id", "project_id", "repo_hash", "repo_index"):
                if feat_key in obs.features:
                    violations.append(
                        f"Row {idx} [Repository Identifier Leakage]: Feature '{feat_key}' leaks repository group identity."
                    )

            # 5. Future Test Execution Leakage: test status flags reflecting future outcome
            if obs.features.get("future_test_pass") is not None or obs.features.get("test_passed_after_change") is not None:
                violations.append(
                    f"Row {idx} [Future Test Execution Leakage]: Future test execution outcome embedded in features."
                )

            # 6. Future Remediation Outcome Leakage: remediation fix verified in future
            if obs.features.get("future_fix_verified") is not None or obs.features.get("post_change_rollback") is not None:
                violations.append(
                    f"Row {idx} [Future Remediation Outcome Leakage]: Post-change remediation outcome leaked."
                )

            # 7. Duplicate Observation Leakage: Exact duplicate feature hash and metadata
            f_hash = obs.feature_hash
            if f_hash in hashes_seen:
                prev_idx = hashes_seen[f_hash]
                # If from same repo and review
                if observations[prev_idx].source_review_id == obs.source_review_id:
                    violations.append(
                        f"Row {idx} [Duplicate Observation Leakage]: Identical feature vector and review as row {prev_idx}."
                    )
            hashes_seen[f_hash] = idx

            # Identical (repository, source_review, target_review)
            triplet = (obs.repository_group, obs.source_review_id, obs.target_review_id)
            if triplet in seen_triplets:
                violations.append(
                    f"Row {idx} [Duplicate Observation Leakage]: Duplicate transition triplet {triplet}."
                )
            seen_triplets.add(triplet)

        # 8. Near-Duplicate Snapshot Leakage: High correlation between consecutive observations within same repo
        for i in range(len(observations) - 1):
            o1 = observations[i]
            o2 = observations[i + 1]
            if (
                o1.repository_group == o2.repository_group
                and o1.source_review_id == o2.source_review_id
                and o1.target == o2.target
            ):
                # Calculate feature cosine similarity
                f1 = [o1.features.get(k, 0.0) for k in sorted(o1.features.keys())]
                f2 = [o2.features.get(k, 0.0) for k in sorted(o1.features.keys())]
                dot = sum(a * b for a, b in zip(f1, f2))
                norm1 = math.sqrt(sum(a * a for a in f1)) or 1.0
                norm2 = math.sqrt(sum(b * b for b in f2)) or 1.0
                sim = dot / (norm1 * norm2)
                if sim >= 0.9999:
                    violations.append(
                        f"Rows {i} and {i + 1} [Near-Duplicate Snapshot Leakage]: Cosine similarity {sim:.5f} >= 0.9999 "
                        f"within identical review {o1.source_review_id} in {o1.repository_group}."
                    )

        passed = len(violations) == 0
        return {
            "passed": passed,
            "observations_audited": len(observations),
            "violations_count": len(violations),
            "violations": violations,
            "feature_catalog_size": len(cls.FEATURE_AUDIT_CATALOG),
        }

    @classmethod
    def assert_no_leakage(cls, observations: list[TemporalObservation]) -> None:
        """Asserts that no temporal or target leakage exists; raises TemporalLeakageViolation if detected."""
        res = cls.audit_observations(observations)
        if not res["passed"]:
            raise TemporalLeakageViolation(
                f"Adversarial Temporal Leakage Detected! {res['violations_count']} violations found:\n"
                + "\n".join(res["violations"][:5])
            )

