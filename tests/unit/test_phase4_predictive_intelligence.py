"""Unit and Integration Tests for Phase 4 MISTIQ Predictive Engineering Intelligence.

Verifies:
1. Temporal feature generation & leakage prevention
2. Dataset provenance, label quality & synthetic detection
3. Deterministic baselines vs Machine Learning models
4. Model evaluation (F1, Brier, ECE calibration, sample size gating)
5. Calibration, uncertainty & abstention (OOD, Insufficient data)
6. Safe model persistence, SHA-256 verification & rollback
7. Prediction explainability & feedback loop isolation
8. Multi-task predictive engine (Forecast, Change Risk, Regression, Remediation)
9. Tenant security & non-disclosing 404 behavior
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.project_reviews import router as project_reviews_router
from app.db.base import Base
from app.models.entities import (
    ProjectFinding,
    ProjectReview,
    ReviewedProject,
    User,
    PredictivePredictionRecord,
    PredictiveFeedbackRecord,
    PredictiveDatasetRecord,
)
from app.services.auth_service import create_access_token
from app.services.predictive import (
    FAILURE_CATEGORIES,
    DatasetRegistry,
    FeedbackCategory,
    HistoricalFrequencyBaseline,
    LatestFailureBaseline,
    LabelQualityAssessor,
    LogisticRegressionBaseline,
    MajorityClassBaseline,
    MistiqPredictiveEngine,
    ModelStatus,
    PredictionCalibrator,
    PredictionExplanationEngine,
    PredictionFeedbackService,
    PredictionHorizon,
    PredictionState,
    PredictionTask,
    PredictiveModelEvaluator,
    ProvenanceClassification,
    RandomForestBaseline,
    RuleBasedEngineeringRiskBaseline,
    SafeModelRegistry,
    TemporalDatasetEngine,
    TemporalFeatureExtractor,
    TemporalObservation,
)


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionTesting = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionTesting()

    # Create test users
    u1 = User(id=1, email="owner@apex.org", username="owner", hashed_password="pw", is_active=True, preferences={}, must_change_password=False)
    u2 = User(id=2, email="other@apex.org", username="other", hashed_password="pw", is_active=True, preferences={}, must_change_password=False)
    session.add_all([u1, u2])
    session.commit()

    # Create reviewed projects
    p1 = ReviewedProject(id=1, name="Project Alpha", repository_path="c:/repos/p1", owner_id=1, monitoring_status="active")
    p2 = ReviewedProject(id=2, name="Project Beta", repository_path="c:/repos/p2", owner_id=2, monitoring_status="active")
    session.add_all([p1, p2])
    session.commit()

    # Create reviews and findings for Project 1
    t0 = datetime(2026, 1, 1, 10, 0, 0)
    t1 = datetime(2026, 1, 2, 10, 0, 0)

    rev1 = ProjectReview(id=1, project_id=1, review_number=1, timestamp=t0, snapshot={"file_count": 20, "recent_churn": "mod1\nmod2"}, metrics={"critical": 1, "high": 2})
    rev2 = ProjectReview(id=2, project_id=1, review_number=2, timestamp=t1, snapshot={"file_count": 22, "recent_churn": "mod3"}, metrics={"critical": 0, "high": 1})
    session.add_all([rev1, rev2])
    session.commit()

    f1 = ProjectFinding(id=1, review_id=1, title="SQLi", category="security", severity="critical", confidence=0.9, file="src/db.py", line=42, evidence="ev", analyzer_source="security_analyzer", remediation="fix", status="open", fingerprint="fp_sqli", detected_at=t0)
    f2 = ProjectFinding(id=2, review_id=1, title="Missing test", category="testing", severity="high", confidence=0.85, file="src/service.py", line=10, evidence="ev", analyzer_source="testing_analyzer", remediation="fix", status="open", fingerprint="fp_test", detected_at=t0)
    f3 = ProjectFinding(id=3, review_id=2, title="Circular dep", category="architecture", severity="high", confidence=0.88, file="src/arch.py", line=1, evidence="ev", analyzer_source="arch_analyzer", remediation="fix", status="NEW", fingerprint="fp_arch", detected_at=t1)
    session.add_all([f1, f2, f3])
    session.commit()

    yield session
    session.close()


@pytest.fixture
def api_client(test_db: Session):
    app = FastAPI()
    app.include_router(project_reviews_router, prefix="")
    app.state.SessionLocal = lambda: test_db
    return TestClient(app)


# ============================================================================
# 1. TEMPORAL FEATURE GENERATION & LEAKAGE PREVENTION
# ============================================================================

def test_temporal_feature_extraction_and_leakage_cutoff(test_db: Session):
    reviews = list(test_db.scalars(select(ProjectReview).where(ProjectReview.project_id == 1).order_by(ProjectReview.review_number)).all())
    rev1, rev2 = reviews[0], reviews[1]

    # Feature extraction with cutoff at rev1 timestamp MUST NOT see rev2 findings
    features_t0 = TemporalFeatureExtractor.extract_features(
        history_reviews=[rev1, rev2],
        current_review=rev1,
        cutoff_timestamp=rev1.timestamp,
        graph_metrics={"fan_in": 5.0, "api_exposure": True},
        testing_metrics={"coverage_ratio": 0.75, "missing_evidence": False},
    )

    assert features_t0["change_file_count"] == 20.0
    assert features_t0["static_total_findings"] == 2.0  # Only f1 and f2, NOT f3
    assert features_t0["static_critical_findings"] == 1.0
    assert features_t0["seq_freq_security"] == 1.0
    assert features_t0["seq_freq_testing"] == 1.0
    assert features_t0["seq_freq_architecture"] == 0.0  # Leakage prevented! f3 occurred at rev2
    assert features_t0["graph_fan_in"] == 5.0
    assert features_t0["graph_api_exposure"] == 1.0
    assert features_t0["test_coverage_ratio"] == 0.75


def test_temporal_dataset_leakage_validator():
    # Valid observation: target timestamp is later than source timestamp
    valid_obs = TemporalObservation(
        project_id=1,
        source_review_id=1,
        source_timestamp="2026-01-01T10:00:00",
        target_review_id=2,
        target_timestamp="2026-01-02T10:00:00",
        features={"change_intensity": 2.0},
        target="security",
        provenance_classification="VERIFIED_REAL",
        label_confidence=0.9,
        repository_group="repo:p1",
        is_synthetic=False,
    )
    val_report = TemporalDatasetEngine.validate_leakage([valid_obs])
    assert val_report["passed"] is True
    assert val_report["violations_count"] == 0

    # Invalid observation: target timestamp is earlier than source (Future Leakage)
    leaked_obs = TemporalObservation(
        project_id=1,
        source_review_id=2,
        source_timestamp="2026-01-02T10:00:00",
        target_review_id=1,
        target_timestamp="2026-01-01T10:00:00",
        features={"change_intensity": 2.0},
        target="security",
        provenance_classification="VERIFIED_REAL",
        label_confidence=0.9,
        repository_group="repo:p1",
        is_synthetic=False,
    )
    invalid_report = TemporalDatasetEngine.validate_leakage([leaked_obs])
    assert invalid_report["passed"] is False
    assert invalid_report["violations_count"] == 1


# ============================================================================
# 2. DATASET PROVENANCE, LABEL QUALITY & SYNTHETIC FILTERING
# ============================================================================

def test_label_quality_synthetic_detection():
    # Synthetic temp paths must be detected
    assert LabelQualityAssessor.is_synthetic("mistiq_live_run_99", "C:/Users/user/AppData/Local/Temp/mistiq_e2e") is True
    assert LabelQualityAssessor.is_synthetic("showcase_project", "/tmp/pytest-of-runner/test0") is True

    # Real repo paths must not be flagged as synthetic
    assert LabelQualityAssessor.is_synthetic("MISTIQ", "C:/Users/ASHWIN/Downloads/PROJECTS/MISTIQ/MISTIQ") is False
    assert LabelQualityAssessor.is_synthetic("EduMentor", "c:/repos/edumentor") is False


def test_label_quality_provenance_tiers():
    # Real repo with commits & lifecycle
    tier1, conf1, _ = LabelQualityAssessor.classify_provenance(
        name="EduMentor",
        repository_path="c:/repos/edumentor",
        has_commit_evidence=True,
        has_lifecycle_evidence=True,
        sample_count=10,
    )
    assert tier1 == ProvenanceClassification.VERIFIED_REAL
    assert conf1 >= 0.90

    # Synthetic fixture
    tier2, conf2, _ = LabelQualityAssessor.classify_provenance(
        name="mistiq_live_123",
        repository_path="/tmp/test_fixture",
        has_commit_evidence=True,
        sample_count=5,
    )
    assert tier2 == ProvenanceClassification.SYNTHETIC
    assert conf2 <= 0.35


# ============================================================================
# 3. DETERMINISTIC BASELINES VS MACHINE LEARNING MODELS
# ============================================================================

def test_deterministic_baselines_and_ml():
    # Create synthetic observations across categories
    obs_list = []
    for i in range(25):
        cat = "security" if i < 15 else ("testing" if i < 20 else "architecture")
        obs_list.append(
            TemporalObservation(
                project_id=1,
                source_review_id=i,
                source_timestamp=f"2026-01-{i+1:02d}T10:00:00",
                target_review_id=i + 1,
                target_timestamp=f"2026-01-{i+2:02d}T10:00:00",
                features={
                    "static_security_risk": 1.0 if cat == "security" else 0.0,
                    "static_testing_risk": 1.0 if cat == "testing" else 0.0,
                    "seq_freq_security": float(i),
                    f"latest_failure_{cat}": 1.0,
                },
                target=cat,
                provenance_classification="CURATED_REAL",
                label_confidence=0.85,
                repository_group="repo:p1",
                is_synthetic=False,
            )
        )

    # 1. Majority Class Baseline
    maj = MajorityClassBaseline().fit(obs_list)
    maj_pred, maj_prob = maj.predict({"seq_freq_security": 5.0})
    assert maj_pred == "security"
    assert maj_prob == 15 / 25

    # 2. Historical Frequency Baseline
    freq = HistoricalFrequencyBaseline().fit(obs_list)
    freq_probs = freq.predict_proba({"seq_freq_security": 5.0})
    assert freq_probs["security"] == 0.60
    assert freq_probs["testing"] == 0.20

    # 3. Latest Failure Baseline
    latest = LatestFailureBaseline().fit(obs_list)
    lat_pred, lat_conf = latest.predict({"latest_failure_testing": 1.0})
    assert lat_pred == "testing"
    assert lat_conf >= 0.50

    # 4. Rule-Based Engineering Risk Baseline
    rule = RuleBasedEngineeringRiskBaseline().fit(obs_list)
    rule_probs = rule.predict_proba({"static_security_risk": 1.0, "graph_api_exposure": 1.0})
    assert rule_probs["security"] > rule_probs["configuration"]

    # 5. Logistic Regression Baseline
    lr = LogisticRegressionBaseline().fit(obs_list)
    lr_pred, lr_conf = lr.predict({"static_security_risk": 1.0, "seq_freq_security": 10.0})
    assert lr_pred in ("security", "testing", "architecture")
    assert lr_conf > 0.0

    # 6. Random Forest Baseline
    rf = RandomForestBaseline().fit(obs_list)
    rf_pred, rf_conf = rf.predict({"static_security_risk": 1.0, "seq_freq_security": 10.0})
    assert rf_pred in ("security", "testing", "architecture")
    assert rf_conf > 0.0
    assert len(rf.feature_importances_) > 0


# ============================================================================
# 4. MODEL EVALUATION & SCIENTIFIC VALIDATION METRICS
# ============================================================================

def test_model_evaluation_metrics_and_calibration():
    obs_test = []
    for i in range(35):  # N >= 30 ensures statistical validity threshold is tested
        cat = "security" if i % 2 == 0 else "testing"
        obs_test.append(
            TemporalObservation(
                project_id=1,
                source_review_id=i,
                source_timestamp=f"2026-02-{i+1:02d}T10:00:00",
                target_review_id=i + 1,
                target_timestamp=f"2026-02-{i+2:02d}T10:00:00",
                features={"static_security_risk": 1.0 if cat == "security" else 0.0, f"latest_failure_{cat}": 1.0},
                target=cat,
                provenance_classification="CURATED_REAL",
                label_confidence=0.85,
                repository_group="repo:p1",
                is_synthetic=False,
            )
        )

    # 1. LatestFailure heuristic test: accuracy is 1.0, but fixed confidence (0.55) correctly produces ECE = 0.45 and is_calibrated = False
    model_uncal = LatestFailureBaseline().fit(obs_test)
    eval_uncal = PredictiveModelEvaluator.evaluate(model_uncal, obs_test, "LatestFailure")
    assert eval_uncal["sample_size"] == 35
    assert eval_uncal["is_statistically_valid"] is True
    assert eval_uncal["validity"] == "STATISTICALLY_VALID"
    assert eval_uncal["accuracy"] == 1.0
    assert eval_uncal["expected_calibration_error"] == 0.45
    assert eval_uncal["is_calibrated"] is False  # Correctly identifies uncalibrated probabilities!

    # 2. HistoricalFrequency baseline: predicted probabilities match empirical distribution
    model_cal = HistoricalFrequencyBaseline().fit(obs_test)
    eval_cal = PredictiveModelEvaluator.evaluate(model_cal, obs_test, "HistoricalFrequency")
    assert eval_cal["expected_calibration_error"] <= 0.15
    assert eval_cal["is_calibrated"] is True


# ============================================================================
# 5. CALIBRATION, UNCERTAINTY & ABSTENTION (OOD, Insufficient Data)
# ============================================================================

def test_abstention_on_insufficient_data():
    state, diag = PredictionCalibrator.evaluate_state(
        confidence=0.8,
        evidence_count=0,  # Zero observations -> MUST ABSTAIN
        is_calibrated=True,
    )
    assert state == PredictionState.INSUFFICIENT_DATA
    assert "Insufficient" in diag["reason"]


def test_abstention_on_out_of_distribution():
    state, diag = PredictionCalibrator.evaluate_state(
        confidence=0.85,
        evidence_count=10,
        is_calibrated=True,
        feature_vector={"change_intensity": 500.0},  # Normal max is 20
        feature_bounds={"change_intensity": (0.0, 25.0)},
    )
    assert state == PredictionState.OUT_OF_DISTRIBUTION
    assert "change_intensity" in diag["ood_features"]


# ============================================================================
# 6. SAFE MODEL PERSISTENCE, SHA-256 INTEGRITY & ROLLBACK
# ============================================================================

def test_safe_model_registry_lifecycle(tmp_path: Path):
    registry = SafeModelRegistry(registry_root=tmp_path)

    # 1. Save candidate artifact safely (JSON parameters, zero pickle)
    cand_record = registry.save_model_artifact(
        model_id="mistiq-rf-v1",
        model_version="1.0.0",
        prediction_task=PredictionTask.FAILURE_FORECAST,
        algorithm="RANDOM_FOREST",
        model_params={"n_estimators": 50, "classes": ["security", "testing"]},
        training_dataset_id="dataset_v001",
        evaluation_metrics={"accuracy": 0.88, "ece": 0.05},
        status=ModelStatus.CANDIDATE,
    )
    assert Path(cand_record["artifact_path"]).is_file()
    assert cand_record["artifact_sha256"] is not None

    # 2. Promote candidate to production
    prod_record = registry.promote_candidate("mistiq-rf-v1")
    assert prod_record["status"] == ModelStatus.PRODUCTION.value

    # 3. Verify retrieval
    loaded = registry.load_model_artifact("mistiq-rf-v1")
    assert loaded is not None
    assert loaded["algorithm"] == "RANDOM_FOREST"

    # 4. Tamper detection: modify artifact file content to trigger SHA-256 error
    art_file = Path(cand_record["artifact_path"])
    art_file.write_text(art_file.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="Artifact checksum mismatch"):
        registry.load_model_artifact("mistiq-rf-v1")


# ============================================================================
# 7. EXPLAINABILITY & USER FEEDBACK ISOLATION
# ============================================================================

def test_prediction_explanation_structure():
    expl = PredictionExplanationEngine.build_explanation(
        predicted_outcome="security",
        confidence=0.82,
        features={"static_security_risk": 2.0, "graph_api_exposure": 1.0, "seq_freq_security": 5.0},
        feature_importances={"static_security_risk": 0.45, "graph_api_exposure": 0.25},
        historical_findings=[{"title": "Open Redirect", "category": "security", "severity": "high", "file": "src/auth.py", "line": 20}],
    )
    assert expl["predicted_outcome"] == "security"
    assert len(expl["feature_attributions"]) >= 2
    assert len(expl["direct_observed_evidence"]) == 1
    assert len(expl["graph_structural_evidence"]) >= 1
    assert "security" in expl["summary"].lower()


def test_prediction_feedback_recording_and_isolation(test_db: Session):
    # Create prediction record
    pred = PredictivePredictionRecord(
        prediction_id="pred_test_101",
        project_id=1,
        target_entity="src/auth.py",
        prediction_task=PredictionTask.FAILURE_FORECAST.value,
        prediction_horizon=PredictionHorizon.NEXT_CHANGE.value,
        model_id="mistiq-test-v1",
        model_version="1.0.0",
        state=PredictionState.PREDICTION_AVAILABLE.value,
        predicted_outcome="security",
        probability=0.85,
        confidence=0.85,
        supporting_evidence={},
        explanation={},
        limitations=[],
    )
    test_db.add(pred)
    test_db.commit()

    # Record user feedback
    fb = PredictionFeedbackService.record_feedback(
        test_db,
        project_id=1,
        prediction_id="pred_test_101",
        user_id=1,
        feedback_category=FeedbackCategory.CORRECT,
        notes="Confirmed finding appeared in next review",
    )
    assert fb.id is not None

    metrics = PredictionFeedbackService.get_feedback_metrics(test_db, project_id=1)
    assert metrics["total_feedback_events"] == 1
    assert metrics["distribution"][FeedbackCategory.CORRECT.value] == 1
    assert metrics["user_confirmed_accuracy_rate"] == 1.0


# ============================================================================
# 8. MULTI-TASK PREDICTIVE ENGINE (Forecast, Change Risk, Regression, Remediation)
# ============================================================================

def test_engine_multi_task_execution(test_db: Session):
    engine = MistiqPredictiveEngine()

    # Task 1: Failure Forecast
    fc = engine.predict_failure_forecast(test_db, project_id=1)
    assert fc["prediction_task"] == PredictionTask.FAILURE_FORECAST.value
    assert fc["predicted_outcome"] in FAILURE_CATEGORIES
    assert fc["confidence"] > 0.0

    # Task 2: Change Risk (explicitly separate from blast radius)
    cr = engine.predict_change_risk(
        test_db,
        project_id=1,
        changed_files=["src/db.py", "src/auth.py"],
        graph_blast_radius_score=35.0,
    )
    assert cr["prediction_task"] == PredictionTask.CHANGE_RISK.value
    assert cr["predicted_outcome"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert cr["supporting_evidence"]["learned_statistical_risk_score"] > 0.0
    assert cr["supporting_evidence"]["structural_blast_radius_score"] == 35.0

    # Task 3: Regression Prediction (Strict NOT_EXECUTED state)
    rr = engine.predict_regression_risk(
        test_db,
        project_id=1,
        target_entity="src/db.py",
        graph_dependent_tests=["tests/unit/test_db.py"],
    )
    assert rr["prediction_task"] == PredictionTask.REGRESSION_RISK.value
    ranked = rr["supporting_evidence"]["ranked_tests"]
    assert len(ranked) == 1
    assert ranked[0]["execution_status"] == "NOT_EXECUTED"

    # Task 4: Remediation Outcome (Honest Abstention due to lack of historical transactions)
    rem = engine.predict_remediation_outcome(test_db, project_id=1, finding_id=1)
    assert rem["prediction_task"] == PredictionTask.REMEDIATION_OUTCOME.value
    assert rem["state"] == PredictionState.INSUFFICIENT_DATA.value
    assert rem["is_abstention"] is True


# ============================================================================
# 9. BACKEND REST APIS & MULTI-TENANT ISOLATION
# ============================================================================

def test_api_predictive_endpoints_and_tenant_security(api_client: TestClient, test_db: Session):
    user1 = test_db.get(User, 1)
    user2 = test_db.get(User, 2)
    token_p1 = create_access_token(user1)
    token_p2 = create_access_token(user2)

    headers_p1 = {"Authorization": f"Bearer {token_p1}"}
    headers_p2 = {"Authorization": f"Bearer {token_p2}"}

    # 1. GET /project-reviews/{project_id}/predictions (Authorized Owner)
    res = api_client.get("/project-reviews/1/predictions", headers=headers_p1)
    assert res.status_code == 200
    data = res.json()
    assert data["project_id"] == 1
    assert "FAILURE_FORECAST" in data["tasks"]

    # 2. POST /project-reviews/{project_id}/predictions/run (Run change risk)
    run_res = api_client.post(
        "/project-reviews/1/predictions/run",
        json={"task": "CHANGE_RISK", "changed_files": ["src/db.py"]},
        headers=headers_p1,
    )
    assert run_res.status_code == 200
    run_data = run_res.json()
    assert run_data["prediction_task"] == "CHANGE_RISK"
    assert "learned_statistical_risk_score" in run_data["supporting_evidence"]

    pred_id = run_data["prediction_id"]

    # 3. GET /project-reviews/{project_id}/predictions/{prediction_id}
    detail_res = api_client.get(f"/project-reviews/1/predictions/{pred_id}", headers=headers_p1)
    assert detail_res.status_code == 200

    # 4. POST /project-reviews/{project_id}/prediction-feedback
    fb_res = api_client.post(
        "/project-reviews/1/prediction-feedback",
        json={"prediction_id": pred_id, "feedback_category": "CORRECT", "notes": "Verified"},
        headers=headers_p1,
    )
    assert fb_res.status_code == 200
    assert fb_res.json()["status"] == "RECORDED"

    # 5. GET /project-reviews/{project_id}/prediction-metrics
    met_res = api_client.get("/project-reviews/1/prediction-metrics", headers=headers_p1)
    assert met_res.status_code == 200
    assert "feedback_metrics" in met_res.json()

    # 6. NON-DISCLOSING 404 SECURITY INVARIANT:
    # Tenant 2 queries Project 1's predictions -> MUST return 404 "Project not found"
    cross_res = api_client.get("/project-reviews/1/predictions", headers=headers_p2)
    assert cross_res.status_code == 404
    assert cross_res.json()["detail"] == "Project not found"

    cross_run = api_client.post(
        "/project-reviews/1/predictions/run",
        json={"task": "FAILURE_FORECAST"},
        headers=headers_p2,
    )
    assert cross_run.status_code == 404
    assert cross_run.json()["detail"] == "Project not found"
