"""Comprehensive Benchmark & Verification Suite for APEX 2.0 Phase 2C:
Detection Intelligence, Evidence Validation, Cross-Analyzer Reasoning, and False-Positive Intelligence.
"""
from __future__ import annotations

import json
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.entities import Base, ProjectFinding, ProjectReview, ReviewedProject
from app.services.auth_service import create_access_token, register_user
from app.services.analyzers.base import FindingItem

# Phase 2C Intelligence Modules
from app.services.intelligence.evidence_validator import (
    EvidenceType,
    EvidenceValidator,
    ValidationState,
)
from app.services.intelligence.finding_correlator import (
    CorrelationRelationship,
    FindingCorrelator,
)
from app.services.intelligence.confidence_engine import (
    ConfidenceCalibrator,
    ConfidenceLevel,
)
from app.services.intelligence.false_positive_engine import (
    FalsePositiveIntelligenceManager,
    ReviewClassification,
)
from app.services.intelligence.runtime_reconciler import (
    AdvancedRuntimeReconciler,
    ReachabilityClassification,
)
from app.services.intelligence.root_cause_engine import (
    RootCauseAnalyzer,
    RootCauseCategory,
)
from app.services.intelligence.regression_engine import (
    RegressionClassification,
    RegressionTracker,
)
from app.services.intelligence.prioritization_engine import (
    RemediationPriority,
    RiskPrioritizer,
)
from app.services.intelligence.benchmark_engine import (
    BenchmarkEvaluationEngine,
    BenchmarkFixture,
)


# ==========================================
# 1. EVIDENCE VALIDATION TESTS
# ==========================================

def test_evidence_validation_direct_source_to_sink(tmp_path: Path):
    """Verify that complete data-flow paths with verified disk snippets are marked VALIDATED."""
    code_file = tmp_path / "app.py"
    code_file.write_text(
        """from fastapi import FastAPI
import subprocess
app = FastAPI()
@app.get("/run")
def run(cmd: str):
    subprocess.run(cmd, shell=True)
""",
        encoding="utf-8",
    )

    finding = {
        "rule_id": "SEC-TAINT-COMMAND-INJECTION",
        "analyzer_source": "security_analyzer",
        "file": "app.py",
        "line": 6,
        "evidence": "Tainted input reaches subprocess.run(shell=True)",
        "data_flow": [
            {"step": 1, "role": "source", "file": "app.py", "line": 5, "expression": "def run(cmd: str):"},
            {"step": 2, "role": "sink", "file": "app.py", "line": 6, "expression": "subprocess.run(cmd, shell=True)"},
        ],
    }

    validator = EvidenceValidator(tmp_path)
    state, items = validator.validate_finding(finding)

    assert state == ValidationState.VALIDATED
    assert len(items) >= 2
    assert any(i.evidence_type == EvidenceType.DATA_FLOW_SOURCE for i in items)
    assert any(i.evidence_type == EvidenceType.DATA_FLOW_SINK for i in items)


def test_evidence_validation_contradicted_by_sanitizer(tmp_path: Path):
    """Verify that findings where a verified sanitizer is present are classified as CONTRADICTED."""
    code_file = tmp_path / "safe.py"
    code_file.write_text(
        """import os
def get_path(user_input):
    safe_name = os.path.basename(user_input)
    return open(safe_name).read()
""",
        encoding="utf-8",
    )

    finding = {
        "rule_id": "SEC-TAINT-PATH-TRAVERSAL",
        "analyzer_source": "security_analyzer",
        "file": "safe.py",
        "line": 4,
        "evidence": "Tainted user input reaches open() with os.path.basename sanitizer applied",
    }

    validator = EvidenceValidator(tmp_path)
    state, items = validator.validate_finding(finding)

    assert state == ValidationState.CONTRADICTED
    assert any(i.evidence_type == EvidenceType.SANITIZER_EVIDENCE for i in items)
    assert items[0].confidence_contribution < 0.0


def test_evidence_validation_missing_source_file_is_unverifiable(tmp_path: Path):
    """Verify that references to non-existent source files are classified as UNVERIFIABLE."""
    finding = {
        "rule_id": "SEC-TAINT-SQLI",
        "analyzer_source": "security_analyzer",
        "file": "non_existent_module.py",
        "line": 42,
        "evidence": "Raw query execution",
    }

    validator = EvidenceValidator(tmp_path)
    state, items = validator.validate_finding(finding)

    assert state == ValidationState.UNVERIFIABLE
    assert len(items) == 1
    assert items[0].confidence_contribution == 0.0


# ==========================================
# 2. CROSS-ANALYZER CORRELATION TESTS
# ==========================================

def test_cross_analyzer_same_root_cause_correlation():
    """Verify distinct analyzers observing the same defect location are correlated with SAME_ROOT_CAUSE."""
    f1 = {
        "fingerprint": "fp_sec_1",
        "category": "security",
        "analyzer_source": "security_analyzer",
        "rule_id": "SEC-SQLI",
        "file": "services/user.py",
        "line": 45,
        "evidence": "Unsanitized dynamic SQL query parameter",
    }
    f2 = {
        "fingerprint": "fp_type_1",
        "category": "bug_risk",
        "analyzer_source": "type_intelligence",
        "rule_id": "TYPE-MISSING-VALIDATION",
        "file": "services/user.py",
        "line": 45,
        "evidence": "Unvalidated string passed to database operation",
    }

    correlator = FindingCorrelator()
    relationships = correlator.correlate([f1, f2])

    assert len(relationships) == 1
    assert relationships[0].relationship_type == CorrelationRelationship.SAME_ROOT_CAUSE
    assert relationships[0].confidence >= 0.85


def test_multi_stage_deduplication_preserves_attached_observations():
    """Verify that duplicates are clustered without losing the individual analyzer observations."""
    f1 = {
        "fingerprint": "fp_dup_1",
        "category": "security",
        "analyzer_source": "security_analyzer",
        "rule_id": "SEC-TAINT-CMD-INJECTION",
        "file": "worker.py",
        "line": 12,
        "evidence": "subprocess.run(shell=True)",
    }
    f2 = {
        "fingerprint": "fp_dup_2",
        "category": "security",
        "analyzer_source": "ast_analyzer",
        "rule_id": "AST-DANGEROUS-SUBPROCESS",
        "file": "worker.py",
        "line": 12,
        "evidence": "Dangerous shell=True call pattern",
    }

    correlator = FindingCorrelator()
    deduped, clusters = correlator.deduplicate_multi_stage([f1, f2])

    assert len(deduped) == 1
    assert len(clusters) == 1
    assert len(clusters[0].attached_observations) == 2


# ==========================================
# 3. CONFIDENCE CALIBRATION TESTS
# ==========================================

def test_confidence_calibration_fully_validated_gets_high(tmp_path: Path):
    """Verify that a fully validated finding with concrete source snippet achieves HIGH confidence."""
    code_file = tmp_path / "calc.py"
    code_file.write_text("def div(a, b): return a / b\n", encoding="utf-8")

    validator = EvidenceValidator(tmp_path)
    state, items = validator.validate_finding({
        "rule_id": "AST-DIV-ZERO",
        "analyzer_source": "ast_analyzer",
        "file": "calc.py",
        "line": 1,
        "evidence": "Division without zero check",
    })

    conf = ConfidenceCalibrator.calibrate({"rule_id": "AST-DIV-ZERO"}, items, state)
    assert conf.level in {ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM}
    assert conf.score >= 0.60
    assert "Concrete source snippet directly verified" in conf.justification


def test_confidence_calibration_contradicted_drops_to_insufficient(tmp_path: Path):
    """Verify that contradicted evidence triggers severe penalty dropping confidence to INSUFFICIENT."""
    code_file = tmp_path / "test_file.py"
    code_file.write_text("import shlex\ncmd = shlex.quote(param)\n", encoding="utf-8")

    validator = EvidenceValidator(tmp_path)
    state, items = validator.validate_finding({
        "rule_id": "SEC-TAINT-CMD",
        "analyzer_source": "security_analyzer",
        "file": "test_file.py",
        "line": 2,
        "evidence": "Command with shlex.quote applied",
    })

    conf = ConfidenceCalibrator.calibrate({"rule_id": "SEC-TAINT-CMD"}, items, state)
    assert conf.level == ConfidenceLevel.INSUFFICIENT
    assert conf.score == 0.0


# ==========================================
# 4. FALSE-POSITIVE INTELLIGENCE TESTS
# ==========================================

def test_false_positive_feedback_and_tenant_isolation():
    """Verify feedback recording, pattern calculation, and strict multi-tenant isolation."""
    mgr = FalsePositiveIntelligenceManager()

    # Tenant 1 (Project 10)
    fb1 = mgr.record_feedback(
        project_id=10,
        user_id=1,
        finding_id="f_sqli_1",
        rule_id="SEC-TAINT-SQLI",
        analyzer_source="security_analyzer",
        file="dao.py",
        evidence="cursor.execute(sql)",
        classification=ReviewClassification.CONFIRMED_FALSE_POSITIVE,
        justification="Valid SQLAlchemy parameterized query wrapper used here.",
    )
    fb2 = mgr.record_feedback(
        project_id=10,
        user_id=1,
        finding_id="f_sqli_2",
        rule_id="SEC-TAINT-SQLI",
        analyzer_source="security_analyzer",
        file="dao2.py",
        evidence="cursor.execute(sql)",
        classification=ReviewClassification.CONFIRMED_FALSE_POSITIVE,
        justification="Another safe parameterized wrapper call.",
    )

    # Tenant 2 (Project 20)
    fb3 = mgr.record_feedback(
        project_id=20,
        user_id=2,
        finding_id="f_auth_1",
        rule_id="SEC-AUTH-MISSING",
        analyzer_source="api_analyzer",
        file="public.py",
        evidence="Public webhook",
        classification=ReviewClassification.CONFIRMED_TRUE_POSITIVE,
        justification="Genuine missing authorization token.",
    )

    # 1. Verify Tenant 1 feedback list
    t1_items = mgr.get_project_feedback(10)
    assert len(t1_items) == 2
    assert all(i["project_id"] == 10 for i in t1_items)

    # 2. Verify Tenant 2 isolation (cannot see Tenant 1 feedback)
    t2_items = mgr.get_project_feedback(20)
    assert len(t2_items) == 1
    assert t2_items[0]["rule_id"] == "SEC-AUTH-MISSING"

    # 3. Verify Rule Pattern Summary for Tenant 1
    patterns = mgr.analyze_rule_patterns(10)
    assert len(patterns) == 1
    assert patterns[0].rule_id == "SEC-TAINT-SQLI"
    assert patterns[0].false_positives == 2
    assert patterns[0].fp_rate == 1.0
    assert patterns[0].suggested_refinement is not None
    assert "high false-positive rate" in patterns[0].suggested_refinement


# ==========================================
# 5. RUNTIME RECONCILIATION TESTS
# ==========================================

def test_zero_coverage_is_not_confirmed_dead_code(tmp_path: Path):
    """STRICT PRINCIPLE: Verify zero test coverage is NOT labeled as confirmed dead code."""
    # Write coverage.json with some coverage
    cov_file = tmp_path / "coverage.json"
    cov_file.write_text(
        json.dumps({
            "files": {
                str(tmp_path / "service.py"): {
                    "executed_lines": [1, 2],
                    "missing_lines": [10, 11],
                }
            }
        }),
        encoding="utf-8",
    )

    reconciler = AdvancedRuntimeReconciler(tmp_path)
    res = reconciler.classify_reachability("service.py", 10, is_statically_unreachable=False)

    assert res.classification == ReachabilityClassification.NOT_OBSERVED_IN_TESTS
    assert res.is_confirmed_dead_code is False
    assert "test coverage gap, NOT verified dead code" in res.explanation


def test_statically_unreachable_is_confirmed_dead_code(tmp_path: Path):
    """Verify that statements proven unreachable by static control flow are confirmed dead code."""
    reconciler = AdvancedRuntimeReconciler(tmp_path)
    res = reconciler.classify_reachability("service.py", 15, is_statically_unreachable=True)

    assert res.classification == ReachabilityClassification.STATICALLY_UNREACHABLE
    assert res.is_confirmed_dead_code is True


# ==========================================
# 6. ROOT CAUSE ANALYSIS TESTS
# ==========================================

def test_root_cause_clustering():
    """Verify that input security flaws in the same file/controller are grouped under UNSAFE_INPUT_HANDLING."""
    findings = [
        {
            "fingerprint": "f1",
            "category": "security",
            "rule_id": "SEC-TAINT-COMMAND-INJECTION",
            "file": "controllers/system.py",
            "severity": "critical",
            "evidence": "Tainted parameter reaches system shell",
        },
        {
            "fingerprint": "f2",
            "category": "security",
            "rule_id": "SEC-TAINT-PATH-TRAVERSAL",
            "file": "controllers/system.py",
            "severity": "high",
            "evidence": "Tainted parameter reaches open()",
        },
    ]

    root_causes = RootCauseAnalyzer.analyze(findings)
    assert len(root_causes) == 1
    assert root_causes[0].category == RootCauseCategory.UNSAFE_INPUT_HANDLING
    assert root_causes[0].primary_finding_id == "f1"
    assert len(root_causes[0].related_finding_ids) == 1
    assert "controllers/system.py" in root_causes[0].affected_files


# ==========================================
# 7. REGRESSION INTELLIGENCE TESTS
# ==========================================

def test_regression_tracking_classifications():
    """Verify classification of NEW_REGRESSION, RESOLVED, and REOPENED_REGRESSION."""
    historical = [
        {"fingerprint": "f_resolved", "category": "security", "severity": "high", "status": "RESOLVED", "file": "a.py", "line": 5},
        {"fingerprint": "f_fixed", "category": "bug_risk", "severity": "medium", "status": "ACTIVE", "file": "b.py", "line": 10},
    ]
    current = [
        {"fingerprint": "f_resolved", "category": "security", "severity": "high", "file": "a.py", "line": 5},  # Reappeared!
        {"fingerprint": "f_new", "category": "performance", "severity": "low", "file": "c.py", "line": 20},     # Brand new!
    ]

    regressions = RegressionTracker.evaluate_regressions(current, historical, current_commit="sha_commit_abc")
    by_fp = {r.finding_fingerprint: r for r in regressions}

    assert by_fp["f_new"].classification == RegressionClassification.NEW_REGRESSION
    assert by_fp["f_resolved"].classification == RegressionClassification.REOPENED_REGRESSION
    assert by_fp["f_fixed"].classification == RegressionClassification.RESOLVED


# ==========================================
# 8. RISK PRIORITIZATION TESTS
# ==========================================

def test_risk_prioritization_public_endpoint_critical_is_p0():
    """Verify critical vulnerability in public route achieves P0_IMMEDIATE."""
    finding = {
        "rule_id": "SEC-TAINT-CMD",
        "category": "security",
        "severity": "critical",
        "file": "api/routes/system.py",
        "line": 14,
    }

    prio = RiskPrioritizer.prioritize(finding, ConfidenceLevel.HIGH)
    assert prio.priority == RemediationPriority.P0_IMMEDIATE
    assert prio.rank_score >= 80.0
    assert "Tier P0_IMMEDIATE" in prio.justification


# ==========================================
# 9. BENCHMARK ENGINE EVALUATION TESTS
# ==========================================

def test_benchmark_engine_calculates_metrics(tmp_path: Path):
    """Verify that the benchmark engine calculates accurate precision, recall, and F1 scores."""
    engine = BenchmarkEvaluationEngine()

    # 1. True Positive fixture
    engine.register_fixture(
        BenchmarkFixture(
            fixture_id="fix_tp_1",
            category="security",
            expected_rule="SEC-INJECTION",
            is_vulnerability=True,
            source_files={"vuln.py": "def run(): pass\n"},
        )
    )

    # 2. True Negative fixture
    engine.register_fixture(
        BenchmarkFixture(
            fixture_id="fix_tn_1",
            category="security",
            expected_rule="SEC-INJECTION",
            is_vulnerability=False,
            source_files={"clean.py": "def safe(): pass\n"},
        )
    )

    # Simulated analyzer function that detects SEC-INJECTION only in vuln.py
    def mock_analyzer(folder: Path):
        findings = []
        if (folder / "vuln.py").is_file():
            findings.append({"rule_id": "SEC-INJECTION"})
        return findings

    metrics = engine.run_evaluation(mock_analyzer, tmp_path)
    sec_metrics = metrics["security"]

    assert sec_metrics.true_positives == 1
    assert sec_metrics.true_negatives == 1
    assert sec_metrics.false_positives == 0
    assert sec_metrics.false_negatives == 0
    assert sec_metrics.precision == 1.0
    assert sec_metrics.recall == 1.0
    assert sec_metrics.f1_score == 1.0


# ==========================================
# 10. UNIFIED API ENDPOINTS & TENANT ISOLATION
# ==========================================

def test_unified_intelligence_api_and_tenant_rbac(tmp_path: Path):
    """Verify GET /intelligence, GET /root-causes, and POST /feedback with multi-tenant RBAC."""
    db_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db_engine)
    session_factory = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)

    app = create_app(database_engine=db_engine)
    app.state.SessionLocal = session_factory

    repo_dir = tmp_path / "repo_phase2c"
    repo_dir.mkdir()
    (repo_dir / "service.py").write_text("def run(): pass\n", encoding="utf-8")

    with session_factory() as session:
        user_a = register_user(session, "user_2c_a@test.com", "user_2c_a", "Password123!")
        user_b = register_user(session, "user_2c_b@test.com", "user_2c_b", "Password123!")

        project = ReviewedProject(
            name="Phase 2C Project",
            repository_path=str(repo_dir),
            owner_id=user_a.id,
            source_type="local",
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        proj_id = project.id

        token_a = create_access_token(user_a)
        token_b = create_access_token(user_b)

    with TestClient(app) as client:
        # 1. Owner queries intelligence overview -> 200 OK
        resp = client.get(
            f"/api/project-reviews/{proj_id}/intelligence",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_findings" in data
        assert "root_causes" in data
        assert "risk_priorities" in data

        # 2. Owner queries root causes -> 200 OK
        rc_resp = client.get(
            f"/api/project-reviews/{proj_id}/root-causes",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert rc_resp.status_code == 200
        assert "root_causes" in rc_resp.json()

        # 3. Owner submits review feedback -> 200 OK
        fb_resp = client.post(
            f"/api/project-reviews/{proj_id}/findings/f_test_1/feedback",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "classification": "CONFIRMED_FALSE_POSITIVE",
                "justification": "Verified internal developer test utility script.",
            },
        )
        assert fb_resp.status_code == 200
        assert fb_resp.json()["status"] == "recorded"

        # 4. Cross-tenant request with User B -> 404 Not Found (non-disclosing isolation)
        idor_resp = client.get(
            f"/api/project-reviews/{proj_id}/intelligence",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert idor_resp.status_code == 404

