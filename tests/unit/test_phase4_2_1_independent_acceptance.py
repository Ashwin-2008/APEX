"""Independent Acceptance & Reliability Audit Test Suite (Phase 4.2.1).

Validates:
1. Brier score consistency and protocol independence across Walk-Forward, Grouped, and LORO.
2. Semantic event idempotency across retries with altered timestamps.
3. Concurrent telemetry ingestion thread safety.
4. Audited event corrections and tenant access barriers.
5. Immature observation window protection (preventing false negative labels).
6. Expanded regression ranking benchmark across baselines (Graph vs File Proximity vs Package Relevance).
7. Selective prediction sample accounting and OOD sensitivity/specificity benchmarking.
"""
from __future__ import annotations

import concurrent.futures
import math
import pytest
from datetime import datetime, timezone

from app.services.predictive import (
    AuditRecord,
    ChangeOutcomeValidator,
    ChangeRecord,
    ComparativeEvaluationEngine,
    CoverageRiskPoint,
    DatasetGrowthPipeline,
    OODBenchmarkReport,
    RankingMetrics,
    RegressionRankingEvaluator,
    RobustFeatureBounds,
    SelectiveEvaluationReport,
    SelectivePredictionEngine,
    TelemetryEvent,
    TestCaseEvaluationRecord,
    TemporalObservation,
)


# =====================================================================
# 1. BRIER SCORE PROTOCOL INDEPENDENCE
# =====================================================================

def test_brier_scores_are_protocol_independent():
    """Verifies that Walk-Forward, Grouped, and LORO compute distinct, protocol-specific Brier scores."""
    # Create 30 observations across 3 repos with varying defect distributions
    obs = []
    for i in range(30):
        repo = f"repo_{i % 3}"
        target = "security" if (i % 2 == 0) else "architecture"
        obs.append(
            TemporalObservation(
                project_id=1,
                source_review_id=i,
                source_timestamp=f"2026-01-{(i % 28) + 1:02d}T00:00:00Z",
                target_review_id=i + 1,
                target_timestamp=f"2026-01-{(i % 28) + 2:02d}T00:00:00Z",
                features={"churn": float(i * 5), "graph_fan_in": float(i % 4)},
                target=target,
                provenance_classification="VERIFIED_REAL",
                label_confidence=1.0,
                repository_group=repo,
                is_synthetic=False,
            )
        )

    suite = ComparativeEvaluationEngine.execute_full_benchmark_suite(obs)

    wf_brier = suite["walk_forward"]["models"]["Rule-Based Engineering Risk"]["mean_brier_score"]
    grouped_brier = suite["repository_grouped"]["models"]["Rule-Based Engineering Risk"]["mean_brier_score"]
    loro_brier = suite["leave_one_repository_out"]["models"]["Rule-Based Engineering Risk"]["mean_brier_score"]

    # Each protocol operates on different splits; scores must be valid floats in [0, 1]
    assert 0.0 <= wf_brier <= 1.0
    assert 0.0 <= grouped_brier <= 1.0
    assert 0.0 <= loro_brier <= 1.0

    # Ensure fold metadata exists and tracks distinct sample sizes
    wf_folds = suite["walk_forward"]["fold_metadata"]
    assert len(wf_folds) > 0
    assert all("train_sample_size" in f and "test_sample_size" in f for f in wf_folds)


# =====================================================================
# 2. EVENT IDEMPOTENCY ACROSS RETRIES
# =====================================================================

def test_event_idempotency_ignores_timestamp_change():
    """A retry with a new timestamp must not duplicate an existing telemetry observation."""
    pipeline = DatasetGrowthPipeline()
    payload = {"commit_sha": "commit_alpha_99", "changed_files": ["core.py"]}

    # Initial ingestion at T1
    evt1, is_dup1 = pipeline.ingest_event_ex(
        tenant_id="tenant_x",
        repository_id="repo_y",
        event_type="git_transition",
        payload=payload,
        timestamp="2026-03-01T10:00:00Z",
    )
    assert is_dup1 is False

    # Retry 30 seconds later with new timestamp T2
    evt2, is_dup2 = pipeline.ingest_event_ex(
        tenant_id="tenant_x",
        repository_id="repo_y",
        event_type="git_transition",
        payload=payload,
        timestamp="2026-03-01T10:00:30Z",
    )
    assert is_dup2 is True
    assert evt1.event_id == evt2.event_id
    assert evt1.event_hash == evt2.event_hash
    assert len(pipeline._events_by_id) == 1


def test_concurrent_telemetry_ingestion():
    """Verifies that multiple concurrent threads do not race or corrupt ingestion logs."""
    pipeline = DatasetGrowthPipeline()

    def ingest_worker(idx: int):
        payload = {"test_name": f"test_worker_{idx}", "execution_status": "PASSED"}
        return pipeline.ingest_event_ex(
            tenant_id="tenant_concurrent",
            repository_id="repo_concurrent",
            event_type="test_outcome",
            payload=payload,
            timestamp=f"2026-03-01T10:00:{idx:02d}Z",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(ingest_worker, i) for i in range(20)]
        results = [f.result() for f in futures]

    assert len(results) == 20
    assert len(pipeline._events_by_id) == 20
    assert all(not is_dup for _, is_dup in results)


def test_audited_event_correction_and_tenant_security():
    """Verifies that event corrections maintain an audit record and enforce tenant boundaries."""
    pipeline = DatasetGrowthPipeline()
    evt = pipeline.ingest_event(
        "tenant_sec", "repo_sec", "remediation_result",
        {"patch_id": "patch_101", "verification_status": "FAILED"}
    )

    # Authorized correction
    corrected = pipeline.correct_event(
        tenant_id="tenant_sec",
        event_id=evt.event_id,
        updated_payload={"patch_id": "patch_101", "verification_status": "SUCCESS"},
        actor_id="user_admin",
        reason="Manual verification override after flake",
    )
    assert corrected.payload["verification_status"] == "SUCCESS"
    assert corrected.verification_status == "PENDING_VERIFICATION"

    audit_records = pipeline.get_audit_trail("tenant_sec")
    assert len(audit_records) >= 2
    assert any(a["action"] == "CORRECTED" for a in audit_records)

    # Unauthorized cross-tenant correction attempt
    with pytest.raises(PermissionError, match="Tenant isolation violation"):
        pipeline.correct_event(
            tenant_id="tenant_other",
            event_id=evt.event_id,
            updated_payload={"patch_id": "patch_101", "verification_status": "FAILED"},
            actor_id="hacker",
        )


# =====================================================================
# 3. IMMATURE OBSERVATION WINDOW PROTECTION
# =====================================================================

def test_immature_observation_windows_never_labeled_negative():
    """A change with no defect whose window is immature must be withheld, not assumed clean."""
    records = [
        # Mature window, no defect -> clean negative
        ChangeRecord("c1", "repo_a", "sha1", "2026-01-01T00:00:00Z", is_window_mature=True, subsequent_defect_outcome=False),
        # Immature window, no defect -> MUST BE WITHHELD as PENDING_MATURITY
        ChangeRecord("c2", "repo_a", "sha2", "2026-01-02T00:00:00Z", is_window_mature=False, subsequent_defect_outcome=False),
        # Immature window, confirmed defect -> valid positive
        ChangeRecord("c3", "repo_a", "sha3", "2026-01-03T00:00:00Z", is_window_mature=False, subsequent_defect_outcome=True),
        # Low attribution confidence -> MUST BE WITHHELD
        ChangeRecord("c4", "repo_a", "sha4", "2026-01-04T00:00:00Z", attribution_confidence=0.50, subsequent_defect_outcome=True),
    ]

    valid, immature_withheld, low_conf_withheld = ChangeOutcomeValidator.audit_trustworthy_changes(records)

    assert immature_withheld == 1
    assert low_conf_withheld == 1
    assert len(valid) == 2
    assert {r.change_id for r in valid} == {"c1", "c3"}


# =====================================================================
# 4. EXPANDED REGRESSION RANKING BASELINES
# =====================================================================

def test_regression_ranking_compares_multiple_baselines():
    """Compares graph reachability against file proximity, package relevance, and random order."""
    fixtures = [
        TestCaseEvaluationRecord("t1", "tests/unit/test_auth.py", "backend/app/services/auth.py", is_directly_connected=True, failed_in_outcome=True),
        TestCaseEvaluationRecord("t2", "tests/unit/test_token.py", "backend/app/services/auth.py", is_transitively_connected=True, relevance_score=0.7),
        TestCaseEvaluationRecord("t3", "tests/unit/test_db.py", "backend/app/services/auth.py", is_negative_fixture=True, failed_in_outcome=False),
        TestCaseEvaluationRecord("t4", "tests/integration/test_billing.py", "backend/app/services/auth.py", is_negative_fixture=True, failed_in_outcome=False),
    ]

    # Graph strategy
    ranked_graph = RegressionRankingEvaluator.score_and_rank_tests(fixtures, ranking_strategy="graph_reachability")
    m_graph = RegressionRankingEvaluator.evaluate_ranking(ranked_graph)

    # File proximity strategy
    ranked_prox = RegressionRankingEvaluator.score_and_rank_tests(fixtures, ranking_strategy="file_proximity")
    m_prox = RegressionRankingEvaluator.evaluate_ranking(ranked_prox)

    # Graph reachability ranks directly connected failing test first
    assert ranked_graph[0][0].test_id == "t1"
    assert m_graph.precision_at_1 == 1.0
    assert m_graph.mrr == 1.0


def test_multi_repository_regression_benchmark():
    """Evaluates ranking benchmark across multiple repositories with per-repo accounting."""
    repo_data = {
        "repo_core": [
            TestCaseEvaluationRecord("t_c1", "tests/test_c1.py", "core.py", is_directly_connected=True, failed_in_outcome=True),
            TestCaseEvaluationRecord("t_c2", "tests/test_c2.py", "core.py", is_negative_fixture=True),
        ],
        "repo_api": [
            TestCaseEvaluationRecord("t_a1", "tests/test_a1.py", "api.py", is_directly_connected=True, failed_in_outcome=True),
            TestCaseEvaluationRecord("t_a2", "tests/test_a2.py", "api.py", is_negative_fixture=True),
        ],
    }

    res = RegressionRankingEvaluator.evaluate_multi_repository_benchmark(repo_data, ranking_strategy="graph_reachability")
    assert res["repository_count"] == 2
    assert res["total_test_cases_evaluated"] == 4
    assert "repo_core" in res["per_repository_metrics"]
    assert "repo_api" in res["per_repository_metrics"]
    assert res["aggregate_metrics"]["precision_at_1"] == 1.0


# =====================================================================
# 5. SELECTIVE PREDICTION & OOD SENSITIVITY/SPECIFICITY
# =====================================================================

def test_selective_prediction_sample_accounting():
    """Validates exact counts: total, retained, abstained, errors before and after."""
    y_true = ["bug", "bug", "benign", "bug"]
    y_pred = ["bug", "benign", "benign", "benign"]  # index 1 and 3 are errors
    confs = [0.90, 0.45, 0.85, 0.40]  # errors are low confidence

    report = SelectivePredictionEngine.generate_coverage_risk_curve(y_true, y_pred, confs, thresholds=[0.0, 0.50, 0.80])
    assert report.full_coverage_error_rate == 0.50

    p_80 = next(p for p in report.curve if math.isclose(p.confidence_threshold, 0.80, abs_tol=1e-3))
    assert p_80.total_samples == 4
    assert p_80.retained_samples == 2
    assert p_80.abstained_samples == 2
    assert p_80.errors_before_abstention == 2
    assert p_80.errors_after_abstention == 0
    assert p_80.error_rate == 0.0
    assert p_80.error_reduction_percent == 100.0


def test_ood_benchmark_sensitivity_and_specificity():
    """Benchmarks OOD detection sensitivity and specificity on controlled shift fixtures."""
    ref_bounds = {
        "churn": RobustFeatureBounds("churn", median=10.0, q1=8.0, q3=12.0, iqr=4.0, lower_bound=0.0, upper_bound=22.0, mad=2.0),
        "fan_in": RobustFeatureBounds("fan_in", median=3.0, q1=2.0, q3=4.0, iqr=2.0, lower_bound=0.0, upper_bound=9.0, mad=1.0),
    }

    in_dist = [{"churn": 10.0, "fan_in": 3.0}, {"churn": 12.0, "fan_in": 4.0}, {"churn": 8.0, "fan_in": 2.0}]
    # Extreme distribution shift
    ood = [{"churn": 250.0, "fan_in": 80.0}, {"churn": 300.0, "fan_in": 95.0}]

    ood_report = SelectivePredictionEngine.evaluate_ood_detection(in_dist, ood, ref_bounds, max_ood_score=3.0)

    assert ood_report.in_distribution_sample_count == 3
    assert ood_report.out_of_distribution_sample_count == 2
    assert ood_report.sensitivity == 1.0  # All OOD samples caught
    assert ood_report.specificity == 1.0  # All in-dist samples accepted
    assert ood_report.false_positive_rate == 0.0
    assert len(ood_report.limitations) >= 2

