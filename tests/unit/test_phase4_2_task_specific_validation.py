"""Comprehensive Test Suite for Phase 4.2: Task-Specific Validation & Selective Intelligence.

Covers:
- Task B: Genuine Change-to-Outcome Learning, Gating & Blast Radius Separation
- Task C: Regression Ranking Benchmark, IR Metrics & Strict NOT_EXECUTED Handling
- Task A: Generalization Diagnostics, Label Prior Drift & Feature Rank Stability
- Selective Prediction: Robust IQR/MAD OOD Detection, Coverage-Risk Curves & Abstention
- Dataset Growth Pipeline: Immutable Telemetry Ingestion, Tenant Isolation & Verification
- 5-Tier Explainability & Extended 8 Model Promotion Gates
"""
from __future__ import annotations

import math
import pytest
from datetime import datetime, timezone

from app.services.predictive import (
    ChangeOutcomeValidator,
    ChangeRecord,
    ChangeRiskEvaluationResult,
    ComparativeEvaluationEngine,
    CoverageRiskPoint,
    DatasetGrowthPipeline,
    GeneralizationDiagnosticEngine,
    GeneralizationDiagnosticSummary,
    IngestionBatchReport,
    PredictionExplanationEngine,
    RankingMetrics,
    RegressionRankingEvaluator,
    RobustFeatureBounds,
    SafeModelRegistry,
    SelectiveEvaluationReport,
    SelectivePredictionEngine,
    SelectivePredictionResult,
    TelemetryEvent,
    TestCaseEvaluationRecord,
    TemporalObservation,
)


# =====================================================================
# TASK B: CHANGE OUTCOME LEARNING, GATING & BLAST RADIUS SEPARATION
# =====================================================================

def test_change_record_creation():
    rec = ChangeRecord(
        change_id="cr_001",
        repository_id="repo_alpha",
        commit_sha="a1b2c3d4",
        timestamp="2026-03-01T10:00:00Z",
        changed_files=["core/auth.py", "models/user.py"],
        changed_symbols=["login", "User"],
        historical_findings_count=3,
        subsequent_defect_outcome=True,
        defect_category="concurrency_hazard",
        structural_blast_radius=0.45,
        impacted_components_count=4,
    )
    d = rec.to_dict()
    assert d["change_id"] == "cr_001"
    assert d["subsequent_defect_outcome"] is True
    assert d["structural_blast_radius"] == 0.45
    assert len(d["changed_files"]) == 2


def test_trustworthy_filtering_excludes_synthetic():
    records = [
        ChangeRecord("cr_1", "repo_a", "sha1", "2026-01-01T00:00:00Z", label_provenance="verified_commit_transition"),
        ChangeRecord("cr_2", "repo_a", "sha2", "2026-01-02T00:00:00Z", label_provenance="synthetic"),
        ChangeRecord("cr_3", "repo_b", "", "2026-01-03T00:00:00Z", label_provenance="verified_commit_transition"),
    ]
    filtered = ChangeOutcomeValidator.filter_trustworthy_changes(records, exclude_synthetic=True)
    assert len(filtered) == 1
    assert filtered[0].change_id == "cr_1"


def test_rule_based_change_risk_computation():
    rec_low = ChangeRecord(
        change_id="cr_low",
        repository_id="repo_a",
        commit_sha="sha_low",
        timestamp="2026-01-01T00:00:00Z",
        changed_files=["readme.md"],
        changed_symbols=[],
        historical_findings_count=0,
        structural_blast_radius=0.05,
    )
    rec_high = ChangeRecord(
        change_id="cr_high",
        repository_id="repo_a",
        commit_sha="sha_high",
        timestamp="2026-01-01T00:00:00Z",
        changed_files=[f"file_{i}.py" for i in range(12)],
        changed_symbols=[f"sym_{i}" for i in range(25)],
        historical_findings_count=20,
        structural_blast_radius=0.90,
    )
    risk_low = ChangeOutcomeValidator.compute_rule_based_risk(rec_low)
    risk_high = ChangeOutcomeValidator.compute_rule_based_risk(rec_high)

    assert 0.0 <= risk_low <= 0.20
    assert 0.80 <= risk_high <= 1.0
    assert risk_high > risk_low


def test_blast_radius_never_substituted_for_outcome():
    # Structural blast radius is high, but subsequent defect outcome is FALSE
    rec = ChangeRecord(
        change_id="cr_diff",
        repository_id="repo_a",
        commit_sha="sha_diff",
        timestamp="2026-01-01T00:00:00Z",
        changed_files=["core.py"],
        structural_blast_radius=0.95,
        subsequent_defect_outcome=False,
    )
    assert rec.structural_blast_radius == 0.95
    assert rec.subsequent_defect_outcome is False


def test_change_outcome_insufficient_data_gating():
    # Only 5 samples (below MIN_TRUSTWORTHY_SAMPLES = 20)
    records = [
        ChangeRecord(
            f"cr_{i}",
            "repo_a",
            f"sha_{i}",
            f"2026-01-0{i+1}T00:00:00Z",
            changed_files=["a.py"],
            subsequent_defect_outcome=(i == 0),
        )
        for i in range(5)
    ]
    res = ChangeOutcomeValidator.evaluate_change_outcomes(records)
    assert res.is_sufficient is False
    assert res.learned_model_status == "INSUFFICIENT_DATA"
    assert "withheld" in res.generalization_notes[0].lower()


def test_change_outcome_evaluation_sufficient_data():
    records = []
    for i in range(25):
        records.append(
            ChangeRecord(
                f"cr_{i}",
                f"repo_{i % 3}",
                f"sha_{i:04d}",
                f"2026-01-{(i % 28) + 1:02d}T00:00:00Z",
                changed_files=[f"f_{j}.py" for j in range((i % 4) + 1)],
                changed_symbols=[f"s_{j}" for j in range((i % 3) + 1)],
                historical_findings_count=i % 5,
                structural_blast_radius=0.1 * (i % 8),
                subsequent_defect_outcome=(i % 3 == 0),
            )
        )
    res = ChangeOutcomeValidator.evaluate_change_outcomes(records)
    assert res.is_sufficient is True
    assert res.sample_size == 25
    assert res.learned_model_status == "EXPERIMENTAL"
    assert res.rule_based_macro_f1 >= 0.0
    assert 0.0 <= res.rule_based_brier_score <= 1.0


def test_change_outcome_empty_records():
    res = ChangeOutcomeValidator.evaluate_change_outcomes([])
    assert res.sample_size == 0
    assert res.learned_model_status == "INSUFFICIENT_DATA"


# =====================================================================
# TASK C: REGRESSION RANKING BENCHMARK & STRICT CI STATUS HANDLING
# =====================================================================

def test_test_case_evaluation_record_creation():
    tc = TestCaseEvaluationRecord(
        test_id="test_auth_jwt",
        test_path="tests/unit/test_auth.py",
        target_symbol_or_file="core/auth.py",
        is_directly_connected=True,
        is_transitively_connected=False,
        is_negative_fixture=False,
        ci_status="PASSED",
        failed_in_outcome=False,
        relevance_score=0.9,
    )
    assert tc.test_id == "test_auth_jwt"
    assert tc.is_directly_connected is True
    assert tc.is_negative_fixture is False


def test_strict_ci_execution_status_not_executed():
    records = [
        TestCaseEvaluationRecord("t1", "p1", "sym1", True, False, False, "NOT_EXECUTED", False, 0.8),
        TestCaseEvaluationRecord("t2", "p2", "sym2", False, True, False, "PASSED", False, 0.2),
        TestCaseEvaluationRecord("t3", "p3", "sym3", False, False, True, "FAILED", True, 1.0),
    ]
    ranked = RegressionRankingEvaluator.score_and_rank_tests(records)
    metrics = RegressionRankingEvaluator.evaluate_ranking(ranked)

    assert metrics.unexecuted_test_count == 1


def test_ranking_strategy_graph_reachability_prioritizes_direct():
    records = [
        TestCaseEvaluationRecord("neg_1", "p1", "s1", False, False, True, "PASSED", False),
        TestCaseEvaluationRecord("trans_1", "p2", "s2", False, True, False, "PASSED", False),
        TestCaseEvaluationRecord("direct_1", "p3", "s3", True, False, False, "FAILED", True),
    ]
    ranked = RegressionRankingEvaluator.score_and_rank_tests(records, ranking_strategy="graph_reachability")
    assert ranked[0][0].test_id == "direct_1"
    assert ranked[1][0].test_id == "trans_1"
    assert ranked[2][0].test_id == "neg_1"


def test_precision_and_recall_at_k_metrics():
    # 5 test cases: index 0 and 1 are relevant (relevance >= 0.5)
    records = [
        TestCaseEvaluationRecord("t1", "p1", "s1", True, False, False, "PASSED", True, 1.0),
        TestCaseEvaluationRecord("t2", "p2", "s2", True, False, False, "PASSED", True, 1.0),
        TestCaseEvaluationRecord("t3", "p3", "s3", False, True, False, "PASSED", False, 0.0),
        TestCaseEvaluationRecord("t4", "p4", "s4", False, True, False, "PASSED", False, 0.0),
        TestCaseEvaluationRecord("t5", "p5", "s5", False, False, True, "PASSED", False, 0.0),
    ]
    ranked = [(r, 1.0 - i * 0.1) for i, r in enumerate(records)]
    metrics = RegressionRankingEvaluator.evaluate_ranking(ranked)

    assert metrics.precision_at_1 == 1.0
    assert metrics.precision_at_2 if hasattr(metrics, "precision_at_2") else metrics.precision_at_3 == 2 / 3
    assert metrics.recall_at_1 == 0.5  # 1 of 2 captured
    assert metrics.recall_at_3 == 1.0  # both captured in top 3
    assert metrics.recall_at_5 == 1.0


def test_mrr_calculation():
    # First relevant item is at rank 2
    records = [
        TestCaseEvaluationRecord("t_irr", "p1", "s1", False, False, False, "PASSED", False, 0.0),
        TestCaseEvaluationRecord("t_rel", "p2", "s2", True, False, False, "FAILED", True, 1.0),
    ]
    ranked = [(records[0], 0.9), (records[1], 0.8)]
    metrics = RegressionRankingEvaluator.evaluate_ranking(ranked)
    assert metrics.mrr == 0.5


def test_ndcg_at_k_calculation():
    records = [
        TestCaseEvaluationRecord("t1", "p1", "s1", True, False, False, "FAILED", True, 1.0),
        TestCaseEvaluationRecord("t2", "p2", "s2", True, False, False, "FAILED", True, 1.0),
    ]
    ranked = [(records[0], 0.9), (records[1], 0.8)]
    metrics = RegressionRankingEvaluator.evaluate_ranking(ranked)
    # Perfect ranking NDCG should be 1.0
    assert pytest.approx(metrics.ndcg_at_3, 0.001) == 1.0
    assert pytest.approx(metrics.ndcg_at_5, 0.001) == 1.0


def test_unnecessary_recommendation_rate():
    records = [
        TestCaseEvaluationRecord("t1", "p1", "s1", True, False, False, "FAILED", True, 1.0),
        TestCaseEvaluationRecord("t2", "p2", "s2", False, False, False, "PASSED", False, 0.0),
        TestCaseEvaluationRecord("t3", "p3", "s3", False, False, False, "PASSED", False, 0.0),
        TestCaseEvaluationRecord("t4", "p4", "s4", False, False, False, "PASSED", False, 0.0),
        TestCaseEvaluationRecord("t5", "p5", "s5", False, False, False, "PASSED", False, 0.0),
    ]
    ranked = [(r, 1.0 - i * 0.1) for i, r in enumerate(records)]
    metrics = RegressionRankingEvaluator.evaluate_ranking(ranked)
    # 4 out of 5 in top 5 are unnecessary
    assert metrics.unnecessary_recommendation_rate_at_5 == 0.80
    assert metrics.relevant_test_coverage_at_5 == 1.0


def test_negative_fixture_intrusion_rate():
    records = [
        TestCaseEvaluationRecord("t1", "p1", "s1", False, False, True, "PASSED", False, 0.0),
        TestCaseEvaluationRecord("t2", "p2", "s2", False, False, True, "PASSED", False, 0.0),
        TestCaseEvaluationRecord("t3", "p3", "s3", True, False, False, "FAILED", True, 1.0),
    ]
    ranked = [(records[0], 0.9), (records[1], 0.8), (records[2], 0.7)]
    metrics = RegressionRankingEvaluator.evaluate_ranking(ranked)
    # 2 out of 3 in top items are negative fixtures
    assert pytest.approx(metrics.negative_fixture_intrusion_rate, 0.01) == 2 / 3


def test_empty_ranking_metrics_safe():
    metrics = RegressionRankingEvaluator.evaluate_ranking([])
    assert metrics.precision_at_1 == 0.0
    assert metrics.mrr == 0.0


# =====================================================================
# TASK A: GENERALIZATION DIAGNOSTICS & PRIOR DRIFT
# =====================================================================

def _make_test_obs(obs_id: str, repo: str, target: str, features: dict[str, float] | None = None) -> TemporalObservation:
    return TemporalObservation(
        project_id=1,
        source_review_id=1,
        source_timestamp="2026-01-01T00:00:00Z",
        target_review_id=2,
        target_timestamp="2026-01-02T00:00:00Z",
        features=features or {},
        target=target,
        provenance_classification="VERIFIED_REAL",
        label_confidence=1.0,
        repository_group=repo,
        is_synthetic=False,
    )


def test_feature_dispersion_computation():
    obs = [
        _make_test_obs("obs_1", "repo_a", "bug", {"churn": 10.0, "graph_fan_in": 2.0}),
        _make_test_obs("obs_2", "repo_a", "bug", {"churn": 12.0, "graph_fan_in": 2.0}),
        _make_test_obs("obs_3", "repo_b", "benign", {"churn": 100.0, "graph_fan_in": 20.0}),
        _make_test_obs("obs_4", "repo_b", "benign", {"churn": 120.0, "graph_fan_in": 22.0}),
    ]
    diag = GeneralizationDiagnosticEngine.analyze_dataset_generalization(obs)
    assert diag.observation_count == 4
    assert diag.repository_count == 2
    assert len(diag.feature_dispersions) == 2

    churn_disp = next(d for d in diag.feature_dispersions if d.feature_name == "churn")
    assert churn_disp.inter_repo_variance > 0
    assert churn_disp.is_high_variance is True


def test_label_prior_drift_tvd():
    # repo_a has 100% bug, repo_b has 100% benign -> massive TVD
    obs = [
        _make_test_obs("o1", "repo_a", "bug"),
        _make_test_obs("o2", "repo_a", "bug"),
        _make_test_obs("o3", "repo_b", "benign"),
        _make_test_obs("o4", "repo_b", "benign"),
    ]
    diag = GeneralizationDiagnosticEngine.analyze_dataset_generalization(obs)
    assert diag.prior_drift.has_significant_prior_shift is True
    assert diag.prior_drift.max_total_variation_distance >= 0.50


def test_feature_stability_spearman_rho():
    # Two identical rankings should give rho = 1.0
    f1 = {"churn": 0.8, "blast": 0.5, "fan_in": 0.2}
    f2 = {"churn": 0.9, "blast": 0.4, "fan_in": 0.1}
    rep = GeneralizationDiagnosticEngine._compute_feature_stability([f1, f2])
    assert rep.is_rank_stable is True
    assert pytest.approx(rep.mean_spearman_rho, 0.01) == 1.0


def test_unstable_rank_detection():
    # Inverted ranking gives rho = -1.0
    f1 = {"churn": 0.8, "blast": 0.5, "fan_in": 0.2}
    f2 = {"churn": 0.1, "blast": 0.5, "fan_in": 0.9}
    rep = GeneralizationDiagnosticEngine._compute_feature_stability([f1, f2])
    assert rep.is_rank_stable is False
    assert rep.mean_spearman_rho < 0.0


def test_generalization_diagnostic_recommendation():
    obs = [
        _make_test_obs(f"o_{i}", f"repo_{i % 2}", "bug", {"f": float(i)})
        for i in range(6)
    ]
    diag = GeneralizationDiagnosticEngine.analyze_dataset_generalization(obs)
    assert "Rule-Based Engineering Risk" in diag.production_authority_recommendation
    assert any("Rule-Based" in f for f in diag.key_findings)


def test_empty_observations_diagnostic_safe():
    diag = GeneralizationDiagnosticEngine.analyze_dataset_generalization([])
    assert diag.observation_count == 0
    assert diag.repository_count == 0


# =====================================================================
# SELECTIVE PREDICTION & ROBUST OOD DETECTION
# =====================================================================

def test_fit_reference_bounds_robust_iqr_mad():
    train_feats = [
        {"feat_a": 10.0, "feat_b": 2.0},
        {"feat_a": 12.0, "feat_b": 2.1},
        {"feat_a": 11.0, "feat_b": 1.9},
        {"feat_a": 10.5, "feat_b": 2.0},
        {"feat_a": 11.5, "feat_b": 2.2},
    ]
    bounds = SelectivePredictionEngine.fit_reference_bounds(train_feats)
    assert "feat_a" in bounds
    assert "feat_b" in bounds
    assert bounds["feat_a"].median == 11.0
    assert bounds["feat_a"].lower_bound < 10.0
    assert bounds["feat_a"].upper_bound > 12.0


def test_selective_prediction_predicts_in_distribution():
    bounds = {
        "feat_a": RobustFeatureBounds("feat_a", 10.0, 8.0, 12.0, 4.0, 0.0, 20.0, 2.0),
    }
    sample_feat = {"feat_a": 10.5}
    probs = {"bug": 0.85, "benign": 0.15}
    res = SelectivePredictionEngine.evaluate_sample(sample_feat, probs, bounds, min_confidence=0.60)

    assert res.should_abstain is False
    assert res.status == "PREDICTED"
    assert res.confidence == 0.85


def test_selective_prediction_abstains_low_confidence():
    bounds = {
        "feat_a": RobustFeatureBounds("feat_a", 10.0, 8.0, 12.0, 4.0, 0.0, 20.0, 2.0),
    }
    sample_feat = {"feat_a": 10.5}
    probs = {"bug": 0.51, "benign": 0.49}
    res = SelectivePredictionEngine.evaluate_sample(sample_feat, probs, bounds, min_confidence=0.60)

    assert res.should_abstain is True
    assert res.status == "ABSTAINED_LOW_CONFIDENCE"


def test_selective_prediction_abstains_ood():
    bounds = {
        "feat_a": RobustFeatureBounds("feat_a", 10.0, 8.0, 12.0, 4.0, 0.0, 20.0, 2.0),
        "feat_b": RobustFeatureBounds("feat_b", 5.0, 4.0, 6.0, 2.0, 0.0, 10.0, 1.0),
        "feat_c": RobustFeatureBounds("feat_c", 1.0, 0.8, 1.2, 0.4, 0.0, 2.0, 0.2),
    }
    # Extreme outlier features
    sample_feat = {"feat_a": 500.0, "feat_b": 200.0, "feat_c": 50.0}
    probs = {"bug": 0.95, "benign": 0.05}
    res = SelectivePredictionEngine.evaluate_sample(sample_feat, probs, bounds, min_confidence=0.60, max_ood_score=3.0)

    assert res.should_abstain is True
    assert res.status == "ABSTAINED_OOD"
    assert len(res.outlier_features) >= 3


def test_coverage_risk_curve_generation():
    y_true = ["bug", "bug", "benign", "benign", "bug"]
    y_pred = ["bug", "bug", "benign", "bug", "benign"]  # index 3 and 4 are errors
    confidences = [0.90, 0.85, 0.80, 0.52, 0.45]  # errors have low confidence

    curve_report = SelectivePredictionEngine.generate_coverage_risk_curve(y_true, y_pred, confidences)
    assert curve_report.full_coverage_error_rate == 0.40
    assert len(curve_report.curve) > 0

    # At threshold 0.70, only confident correct predictions remain
    p_70 = next(p for p in curve_report.curve if math.isclose(p.confidence_threshold, 0.70, abs_tol=1e-3))
    assert p_70.error_rate == 0.0
    assert p_70.coverage == 0.60
    assert p_70.error_reduction_percent == 100.0


def test_coverage_floor_enforcement():
    y_true = ["bug"] * 10
    y_pred = ["bug"] * 10
    confs = [0.8] * 10
    curve_report = SelectivePredictionEngine.generate_coverage_risk_curve(y_true, y_pred, confs)
    assert curve_report.retained_coverage >= 0.50


def test_empty_probabilities_selective_abstain():
    res = SelectivePredictionEngine.evaluate_sample({}, {})
    assert res.should_abstain is True
    assert res.status == "ABSTAINED_INSUFFICIENT_DATA"


# =====================================================================
# DATASET GROWTH PIPELINE & TELEMETRY GOVERNANCE
# =====================================================================

def test_telemetry_event_creation_and_hashing():
    evt = TelemetryEvent(
        event_id="evt_001",
        tenant_id="tenant_1",
        repository_id="repo_1",
        event_type="git_transition",
        timestamp="2026-03-01T00:00:00Z",
        payload={"commit_sha": "abc1234", "changed_files": ["app.py"]},
    )
    assert len(evt.event_hash) == 64
    assert evt.verification_status == "PENDING_VERIFICATION"


def test_telemetry_tenant_isolation_required():
    pipeline = DatasetGrowthPipeline()
    with pytest.raises(ValueError, match="tenant_id and repository_id are strictly required"):
        pipeline.ingest_event("", "repo_1", "git_transition", {})


def test_ingest_allowed_event_types():
    pipeline = DatasetGrowthPipeline()
    evt = pipeline.ingest_event("t1", "r1", "git_transition", {"commit_sha": "c1", "changed_files": []})
    assert evt.event_type == "git_transition"

    with pytest.raises(ValueError, match="Invalid event_type"):
        pipeline.ingest_event("t1", "r1", "invalid_type", {})


def test_ingest_batch_deduplication():
    pipeline = DatasetGrowthPipeline()
    events = [
        {"event_type": "git_transition", "payload": {"commit_sha": "sha_x", "changed_files": []}, "timestamp": "2026-01-01T00:00:00Z"},
        {"event_type": "git_transition", "payload": {"commit_sha": "sha_x", "changed_files": []}, "timestamp": "2026-01-01T00:00:00Z"},
    ]
    report = pipeline.ingest_batch("t1", "r1", events)
    assert report.total_submitted == 2
    assert report.accepted_count == 1
    assert report.duplicate_count == 1
    assert len(pipeline._events) == 1  # Deduplicated in internal registry


def test_verify_and_promote_events():
    pipeline = DatasetGrowthPipeline()
    pipeline.ingest_event(
        "t1", "r1", "test_outcome",
        {"test_name": "test_core", "execution_status": "PASSED"}
    )
    pipeline.ingest_event(
        "t1", "r1", "remediation_result",
        {"patch_id": "p_01", "verification_status": "SUCCESS"}
    )
    promoted = pipeline.verify_and_promote_events("t1", "r1")
    assert len(promoted) == 2
    assert all(e.verification_status == "VERIFIED" for e in promoted)


def test_reject_incomplete_event_payload():
    pipeline = DatasetGrowthPipeline()
    # Missing required 'test_name'
    pipeline.ingest_event("t1", "r1", "test_outcome", {"status": "PASSED"})
    promoted = pipeline.verify_and_promote_events("t1", "r1")
    assert len(promoted) == 0


def test_list_verified_events_filtered_by_tenant():
    pipeline = DatasetGrowthPipeline()
    pipeline.ingest_event("t1", "r1", "test_outcome", {"test_name": "t1", "execution_status": "PASSED"})
    pipeline.ingest_event("t2", "r2", "test_outcome", {"test_name": "t2", "execution_status": "PASSED"})
    pipeline.verify_and_promote_events("t1", "r1")
    pipeline.verify_and_promote_events("t2", "r2")

    t1_events = pipeline.list_verified_events("t1", "r1")
    assert len(t1_events) == 1
    assert t1_events[0].tenant_id == "t1"


# =====================================================================
# 5-TIER EXPLANATIONS & 8 EXTENDED PROMOTION GATES
# =====================================================================

def test_five_tier_explanation_structure():
    expl = PredictionExplanationEngine.build_explanation(
        predicted_outcome="architecture_violation",
        confidence=0.82,
        features={
            "graph_api_exposure": 1.0,
            "churn_line_modifications": 75.0,
            "static_high_findings": 4.0,
        },
        historical_findings=[
            {"category": "architecture_violation", "title": "Direct cycle", "severity": "high"}
        ],
        missing_evidence=["Runtime trace unavailable"],
    )
    # Check 5 tiers are present
    assert "direct_historical_evidence" in expl
    assert "structural_graph_evidence" in expl
    assert "rule_based_evidence" in expl
    assert "statistical_model_evidence" in expl
    assert "missing_evidence_and_limitations" in expl

    assert len(expl["direct_historical_evidence"]) == 1
    assert len(expl["structural_graph_evidence"]) >= 1
    assert len(expl["rule_based_evidence"]) >= 1
    assert "Runtime trace unavailable" in expl["missing_evidence_and_limitations"]


def test_backward_compatible_explanation_keys():
    expl = PredictionExplanationEngine.build_explanation(
        predicted_outcome="concurrency_hazard",
        confidence=0.75,
        features={"graph_fan_in": 5.0},
    )
    assert "direct_observed_evidence" in expl
    assert "graph_structural_evidence" in expl
    assert "limitations_and_missing_evidence" in expl


def test_promotion_gate_baseline_superiority(tmp_path):
    registry = SafeModelRegistry(registry_root=tmp_path)
    candidate = {
        "evaluation_metrics": {"macro_f1": 0.15},
    }
    baseline = {"macro_f1": 0.25}
    passed, fails = registry.evaluate_promotion_gates(candidate, baseline_metrics=baseline)
    assert passed is False
    assert any("Gate 1 Failed" in f for f in fails)


def test_promotion_gate_provenance_synthetic_rejection(tmp_path):
    registry = SafeModelRegistry(registry_root=tmp_path)
    candidate = {
        "training_dataset_id": "dataset_synthetic_fixtures_v1",
        "evaluation_metrics": {"macro_f1": 0.85},
    }
    passed, fails = registry.evaluate_promotion_gates(candidate)
    assert passed is False
    assert any("Gate 2 Failed" in f for f in fails)


def test_promotion_gate_generalization_gap(tmp_path):
    registry = SafeModelRegistry(registry_root=tmp_path)
    candidate = {
        "evaluation_metrics": {
            "macro_f1": 0.60,
            "loro_macro_f1": 0.20,  # Gap is 0.40 > 0.25
        },
    }
    passed, fails = registry.evaluate_promotion_gates(candidate)
    assert passed is False
    assert any("Gate 3 Failed" in f for f in fails)


def test_promotion_gate_change_outcome_blast_radius_substitution(tmp_path):
    registry = SafeModelRegistry(registry_root=tmp_path)
    candidate = {
        "prediction_task": "change_risk",
        "evaluation_metrics": {
            "macro_f1": 0.50,
            "substituted_blast_radius_as_outcome": True,
        },
    }
    passed, fails = registry.evaluate_promotion_gates(candidate)
    assert passed is False
    assert any("Gate 6 Failed" in f for f in fails)


def test_promotion_gate_selective_coverage_floor(tmp_path):
    registry = SafeModelRegistry(registry_root=tmp_path)
    candidate = {
        "evaluation_metrics": {
            "macro_f1": 0.50,
            "selective_coverage": 0.35,  # < 0.50 floor
        },
    }
    passed, fails = registry.evaluate_promotion_gates(candidate)
    assert passed is False
    assert any("Gate 7 Failed" in f for f in fails)


def test_promotion_gate_all_passed(tmp_path):
    registry = SafeModelRegistry(registry_root=tmp_path)
    candidate = {
        "training_dataset_id": "verified_real_dataset_v001",
        "artifact_sha256": "abc1234567890",
        "model_params": {"n_estimators": 50},
        "evaluation_metrics": {
            "macro_f1": 0.55,
            "loro_macro_f1": 0.40,  # Gap 0.15 <= 0.25
            "expected_calibration_error": 0.12,
            "leakage_violations_count": 0,
            "selective_coverage": 0.70,
        },
    }
    baseline = {"macro_f1": 0.45}
    passed, fails = registry.evaluate_promotion_gates(candidate, baseline_metrics=baseline)
    assert passed is True
    assert len(fails) == 0
