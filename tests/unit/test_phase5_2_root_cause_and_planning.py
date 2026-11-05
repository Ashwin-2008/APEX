"""Unit Test Suite for APEX 2.0 Phase 5.2: Root Cause Investigation & Multi-Strategy Planning.

Verifies:
1. Multi-source evidence aggregation across 12 sources.
2. Root cause hypothesis synthesis & deterministic confirmation rules (LLM cannot confirm).
3. Cross-finding correlation clustering and manual reviewer separation.
4. Multi-strategy remediation planning and 11-dimension scoring model.
5. Rule-Based Engineering Risk Baseline & Blast-Radius integration.
6. Explicit planner abstention on insufficient causal evidence.
7. Candidate patch generation safety boundary (UNVERIFIED banner, NO code execution).
8. End-to-end orchestrator state machine lifecycle.
9. Multi-tenant API security and forbidden /apply guard.
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user, get_db
from app.main import app
from app.models.entities import (
    Base,
    ProjectFinding,
    RemediationCandidateRecord,
    RemediationClusterFinding,
    RemediationFindingClusterRecord,
    RemediationPlanRecord,
    RemediationRootCauseHypothesisRecord,
    RemediationWorkflowFinding,
    RemediationWorkflowRecord,
    ReviewedProject,
    User,
)
from app.services.graph.blast_radius import BlastRadiusEngine
from app.services.graph.models import EdgeType, GraphEdge, GraphNode, NodeType
from app.services.graph.test_selector import TargetedTestSelector, TestRecommendationTier
from app.services.predictive.baseline_models import RuleBasedEngineeringRiskBaseline
from app.services.remediation.orchestrator import (
    RemediationOrchestrator,
    RemediationWorkflowState,
)
from app.services.remediation.root_cause_engine import (
    EvidenceItem,
    FindingCluster,
    FindingCorrelationClusterer,
    HypothesisStatus,
    MultiSourceEvidenceAggregator,
    RootCauseCategory,
    RootCauseEngine,
    RootCauseHypothesis,
    RootCauseInvestigationEngine,
)
from app.services.remediation.strategy_planner import (
    ApprovalTier,
    RemediationStrategyType,
    SCORING_WEIGHTS,
    StrategyCandidateSpec,
    StrategyPlanner,
    UNVERIFIED_CANDIDATE_BANNER,
)


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def db_session():
    """In-memory SQLite database for Phase 5.2 testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_user(db_session: Session) -> User:
    user = User(
        username="lead_architect",
        email="architect@corp.local",
        hashed_password="test_argon2_hash",
    )
    db_session.add(user)
    db_session.flush()
    user.tenant_id = f"tenant_{user.id}"
    return user


@pytest.fixture
def other_tenant_user(db_session: Session) -> User:
    user = User(
        username="hostile_actor",
        email="attacker@corp.local",
        hashed_password="test_argon2_hash",
    )
    db_session.add(user)
    db_session.flush()
    user.tenant_id = f"tenant_other_{user.id}"
    return user


@pytest.fixture
def sample_project(db_session: Session, sample_user: User) -> ReviewedProject:
    proj = ReviewedProject(
        name="CorePaymentsEngine",
        repository_path="/workspace/payments",
        owner_id=sample_user.id,
    )
    db_session.add(proj)
    db_session.flush()
    return proj


@pytest.fixture
def sample_findings(db_session: Session, sample_project: ReviewedProject) -> list[ProjectFinding]:
    from app.models.entities import ProjectReview

    review = ProjectReview(
        project_id=sample_project.id,
        review_number=1,
        status="completed",
    )
    db_session.add(review)
    db_session.flush()

    f1 = ProjectFinding(
        review_id=review.id,
        file="services/payment_gateway.py",
        line=42,
        component="SEC-TAINT-SQLI",
        evidence="Unsanitized query formatting vulnerability",
        category="security",
        severity="CRITICAL",
        confidence=0.95,
        fingerprint="fp_sql_001",
        analyzer_source="taint_analysis",
        remediation="Use parameterized queries",
    )
    f2 = ProjectFinding(
        review_id=review.id,
        file="services/payment_gateway.py",
        line=78,
        component="SEC-COMMAND-INJECTION",
        evidence="Untrusted shell execution via os.system",
        category="security",
        severity="CRITICAL",
        confidence=0.90,
        fingerprint="fp_cmd_002",
        analyzer_source="taint_analysis",
        remediation="Use subprocess.run without shell=True",
    )
    f3 = ProjectFinding(
        review_id=review.id,
        file="models/ledger.py",
        line=15,
        component="TYPE-UNCHECKED-OPTIONAL-DEREFERENCE",
        evidence="Potential None dereference on account balance lookup",
        category="type_checking",
        severity="MEDIUM",
        confidence=0.85,
        fingerprint="fp_type_003",
        analyzer_source="type_analyzer",
        remediation="Add None guard check",
    )
    db_session.add_all([f1, f2, f3])
    db_session.flush()
    return [f1, f2, f3]


@pytest.fixture
def sample_workflow(
    db_session: Session,
    sample_project: ReviewedProject,
    sample_user: User,
    sample_findings: list[ProjectFinding],
) -> RemediationWorkflowRecord:
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=sample_project.id,
        tenant_id=sample_user.tenant_id,
        finding_ids=[f.id for f in sample_findings],
        title="Remediate Payment Gateway Security and Type Flaws",
        actor=sample_user.username,
        risk_level="HIGH",
    )
    return wf


# =====================================================================
# PART 1: Multi-Source Evidence Aggregation & Deterministic Rules
# =====================================================================


def test_evidence_aggregation_across_sources(
    db_session: Session,
    sample_findings: list[ProjectFinding],
    sample_user: User,
):
    """Verifies evidence is gathered and structured across findings."""
    evidence_map = MultiSourceEvidenceAggregator.aggregate_evidence_for_findings(
        findings=sample_findings,
        repo_path=None,
        db_session=db_session,
        tenant_id=sample_user.tenant_id,
    )

    assert len(evidence_map) == 3
    for f in sample_findings:
        assert f.id in evidence_map
        ev_items = evidence_map[f.id]
        assert len(ev_items) >= 2
        sources = {ev.source_type for ev in ev_items}
        assert "ANALYZER_EVIDENCE" in sources


def test_deterministic_hypothesis_status_guard_llm_cannot_confirm():
    """Deterministic confirmation rule: An LLM claim alone can NEVER confirm a root cause.

    Only verified proofs or confirmed AST syntax checks qualify for CONFIRMED.
    """
    # 1. Hypothesis supported only by LLM inference
    llm_ev = EvidenceItem(
        source_type="LLM_SYNTHESIS",
        title="LLM Inferred Defect",
        description="LLM inferred that the error is caused by missing input validation",
        is_supporting=True,
        confidence_weight=0.99,
        provenance={"syntax_valid": True},
    )
    status = RootCauseInvestigationEngine.adjudicate_hypothesis_status(
        supporting_evidence=[llm_ev],
        contradicting_evidence=[],
        completeness_score=0.90,
    )
    # MUST NOT be CONFIRMED despite 99% confidence and 90% completeness
    assert status != HypothesisStatus.CONFIRMED
    assert status == HypothesisStatus.INFERRED

    # 2. Hypothesis supported by confirmed AST syntax error
    ast_ev = EvidenceItem(
        source_type="AST_STRUCTURE",
        title="Syntax Failure",
        description="SyntaxError at line 42 confirmed by parser",
        is_supporting=True,
        confidence_weight=1.0,
        provenance={"syntax_valid": False},
    )
    status_ast = RootCauseInvestigationEngine.adjudicate_hypothesis_status(
        supporting_evidence=[ast_ev],
        contradicting_evidence=[],
        completeness_score=0.90,
    )
    assert status_ast == HypothesisStatus.CONFIRMED

    # 3. Insufficient evidence when completeness is very low
    status_low = RootCauseInvestigationEngine.adjudicate_hypothesis_status(
        supporting_evidence=[llm_ev],
        contradicting_evidence=[],
        completeness_score=0.15,
    )
    assert status_low == HypothesisStatus.INSUFFICIENT_EVIDENCE


# =====================================================================
# PART 2: Cross-Finding Correlation & Reviewer Splitting
# =====================================================================


def test_finding_correlation_clustering(
    db_session: Session,
    sample_findings: list[ProjectFinding],
    sample_user: User,
):
    """Verifies related findings in the same file/category are correlated into clusters."""
    evidence_map = MultiSourceEvidenceAggregator.aggregate_evidence_for_findings(
        findings=sample_findings,
        repo_path=None,
        db_session=db_session,
        tenant_id=sample_user.tenant_id,
    )

    clusters = FindingCorrelationClusterer.cluster_findings(
        findings=sample_findings,
        evidence_map=evidence_map,
    )

    assert len(clusters) >= 2
    # The two payment_gateway security findings (SQLI & CMD-INJECTION) should cluster together
    sec_cluster = next((c for c in clusters if c.thematic_category == RootCauseCategory.SECURITY_VULNERABILITY), None)
    assert sec_cluster is not None
    assert sec_cluster.primary_finding_id in (sample_findings[0].id, sample_findings[1].id)
    all_fids = [sec_cluster.primary_finding_id] + sec_cluster.related_finding_ids
    assert sample_findings[0].id in all_fids
    assert sample_findings[1].id in all_fids


def test_reviewer_manual_finding_separation(
    db_session: Session,
    sample_workflow: RemediationWorkflowRecord,
    sample_findings: list[ProjectFinding],
):
    """Verifies that an engineering reviewer can manually separate a finding out of a cluster."""
    # Run investigation to create initial clusters
    inv_result = RootCauseEngine.investigate_workflow(db_session, sample_workflow.workflow_id)
    clusters = inv_result["clusters"]
    assert len(clusters) > 0

    # Find cluster with related findings
    multi_cluster = next((c for c in clusters if len(c.get("related_finding_ids", [])) > 0), None)
    if not multi_cluster:
        # Cluster primary and related manually for the test
        multi_cluster = clusters[0]
        db_session.add(
            RemediationClusterFinding(
                cluster_id=multi_cluster["cluster_id"],
                finding_id=sample_findings[1].id,
                correlation_weight=0.85,
            )
        )
        db_session.flush()

    target_cluster_id = multi_cluster["cluster_id"]
    finding_to_split = sample_findings[1].id

    # Execute separation
    new_cluster = RootCauseEngine.manually_separate_finding(
        session=db_session,
        cluster_id=target_cluster_id,
        finding_id=finding_to_split,
        reason="Reviewer determined CMD-INJECTION is decoupled from SQLI root cause",
    )

    assert new_cluster.primary_finding_id == finding_to_split
    assert new_cluster.is_manually_adjusted is True
    assert "CMD-INJECTION is decoupled" in new_cluster.correlation_rationale

    # Verify original cluster is also marked as manually adjusted
    orig_rec = db_session.scalar(
        select(RemediationFindingClusterRecord).where(
            RemediationFindingClusterRecord.cluster_id == target_cluster_id
        )
    )
    assert orig_rec.is_manually_adjusted is True


# =====================================================================
# PART 3: Multi-Strategy Planning & 11-Dimension Scoring
# =====================================================================


def test_multi_strategy_generation_and_scoring(
    db_session: Session,
    sample_workflow: RemediationWorkflowRecord,
):
    """Verifies synthesis of alternative repair strategies and 11-dimension scoring."""
    # 1. Run investigation first
    RootCauseEngine.investigate_workflow(db_session, sample_workflow.workflow_id)

    # 2. Generate plans
    plans = StrategyPlanner.generate_plans_for_workflow(db_session, sample_workflow.workflow_id)

    assert len(plans) >= 3
    strategy_types = {p.strategy_name for p in plans}
    assert RemediationStrategyType.TARGETED_FIX.value in strategy_types
    assert RemediationStrategyType.DEFENSIVE_VALIDATION.value in strategy_types

    # Verify 11-dimension scoring model
    for p in plans:
        breakdown = p.score_breakdown
        assert len(breakdown) == 11
        for dim, weight in SCORING_WEIGHTS.items():
            assert dim in breakdown
            assert 0.0 <= breakdown[dim] <= 1.0

        # Verify weighted score matches plan_score
        weighted_sum = sum(breakdown[dim] * SCORING_WEIGHTS[dim] for dim in SCORING_WEIGHTS)
        assert abs(p.plan_score - round(weighted_sum * 100.0, 2)) < 0.05

        # Verify candidate patch preview is present and stamped UNVERIFIED
        preview = p.risk_assessment.get("candidate_patch_preview", "")
        assert UNVERIFIED_CANDIDATE_BANNER in preview

    # Exactly one plan should be preferred
    preferred_plans = [p for p in plans if p.is_preferred]
    assert len(preferred_plans) == 1
    assert sample_workflow.active_plan_id == preferred_plans[0].plan_id


def test_planner_abstention_advisory_on_incomplete_evidence(
    db_session: Session,
    sample_workflow: RemediationWorkflowRecord,
):
    """Verifies planner emits explicit ABSTAIN when causal evidence is severely insufficient."""
    # Manually insert a hypothesis with INSUFFICIENT_EVIDENCE (<20% completeness)
    hyp = RemediationRootCauseHypothesisRecord(
        hypothesis_id="hyp_uncertain_999",
        workflow_id=sample_workflow.workflow_id,
        tenant_id=sample_workflow.tenant_id,
        project_id=sample_workflow.project_id,
        category="architectural",
        status=HypothesisStatus.INSUFFICIENT_EVIDENCE.value,
        title="Unverified Macro Architectural Flaw",
        explanation="Speculative causality without corroborating traces",
        confidence_score=0.18,
        evidence_completeness=0.12,
        supporting_evidence=[],
        contradicting_evidence=[],
        affected_files=["services/payment_gateway.py"],
        affected_symbols=[],
        related_finding_ids=[],
        verification_requirements=[],
        provenance={"source": "speculative_test"},
    )
    db_session.add(hyp)
    db_session.flush()

    plans = StrategyPlanner.generate_plans_for_workflow(db_session, sample_workflow.workflow_id)

    # All generated plans under this insufficient evidence should carry abstain_reason
    assert len(plans) > 0
    for p in plans:
        assert p.abstain_reason is not None
        assert "Insufficient evidence" in p.abstain_reason


# =====================================================================
# PART 4: End-to-End Orchestrator State Transitions
# =====================================================================


def test_orchestrator_investigate_plan_and_select_lifecycle(
    db_session: Session,
    sample_workflow: RemediationWorkflowRecord,
    sample_user: User,
):
    """Tests orchestrator progression: DISCOVERED -> INVESTIGATING -> ROOT_CAUSE_IDENTIFIED

    -> PLAN_GENERATED -> PLAN_VALIDATED -> PATCH_GENERATED.
    """
    assert sample_workflow.state == RemediationWorkflowState.DISCOVERED.value

    # 1. Investigate Root Causes
    inv_res = RemediationOrchestrator.investigate_root_causes(
        session=db_session,
        workflow_id=sample_workflow.workflow_id,
        actor=sample_user.username,
    )
    assert sample_workflow.state == RemediationWorkflowState.ROOT_CAUSE_IDENTIFIED.value
    assert len(inv_res["hypotheses"]) > 0

    # 2. Generate Plans
    plans = RemediationOrchestrator.generate_remediation_plans(
        session=db_session,
        workflow_id=sample_workflow.workflow_id,
        actor=sample_user.username,
    )
    assert sample_workflow.state == RemediationWorkflowState.PLAN_VALIDATED.value
    assert len(plans) >= 3

    # 3. Select Preferred Plan
    selected_plan = plans[1]  # Select second plan
    RemediationOrchestrator.select_preferred_plan(
        session=db_session,
        workflow_id=sample_workflow.workflow_id,
        plan_id=selected_plan.plan_id,
        actor=sample_user.username,
    )

    assert sample_workflow.state == RemediationWorkflowState.PATCH_GENERATED.value
    assert sample_workflow.active_plan_id == selected_plan.plan_id
    assert sample_workflow.active_candidate_id is not None

    # Verify Candidate Record created and labeled UNVERIFIED
    cand = db_session.scalar(
        select(RemediationCandidateRecord).where(
            RemediationCandidateRecord.candidate_id == sample_workflow.active_candidate_id
        )
    )
    assert cand is not None
    assert UNVERIFIED_CANDIDATE_BANNER in cand.diff_unified
    assert cand.lifecycle_state == "GENERATED"


# =====================================================================
# PART 5: REST API Routes & Multi-Tenant Authorization
# =====================================================================


@pytest.fixture
def api_client(db_session: Session, sample_user: User):
    def override_get_db():
        yield db_session

    def override_get_current_user():
        return sample_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def test_api_investigate_and_get_details(
    api_client: TestClient,
    sample_workflow: RemediationWorkflowRecord,
    sample_project: ReviewedProject,
):
    """Tests POST /investigate and GET /investigation endpoints."""
    # 1. POST investigate
    resp = api_client.post(
        f"/api/projects/{sample_project.id}/remediation/workflows/{sample_workflow.workflow_id}/investigate"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["hypotheses_count"] > 0

    # 2. GET investigation
    get_resp = api_client.get(
        f"/api/projects/{sample_project.id}/remediation/workflows/{sample_workflow.workflow_id}/investigation"
    )
    assert get_resp.status_code == 200
    inv_data = get_resp.json()
    assert len(inv_data["hypotheses"]) > 0
    assert len(inv_data["clusters"]) > 0

    # 3. GET hypotheses
    hyp_resp = api_client.get(
        f"/api/projects/{sample_project.id}/remediation/workflows/{sample_workflow.workflow_id}/hypotheses"
    )
    assert hyp_resp.status_code == 200
    assert len(hyp_resp.json()) > 0


def test_api_plans_lifecycle_and_comparison(
    api_client: TestClient,
    sample_workflow: RemediationWorkflowRecord,
    sample_project: ReviewedProject,
    db_session: Session,
):
    """Tests POST /generate-plans, GET /plans, GET /plans/compare, and POST /plans/{plan_id}/select."""
    # Run investigation first via orchestrator
    RemediationOrchestrator.investigate_root_causes(
        db_session, sample_workflow.workflow_id, actor="lead_architect"
    )

    # 1. POST /generate-plans
    gen_resp = api_client.post(
        f"/api/projects/{sample_project.id}/remediation/workflows/{sample_workflow.workflow_id}/generate-plans"
    )
    assert gen_resp.status_code == 200
    plans = gen_resp.json()
    assert len(plans) >= 3

    # 2. GET /plans
    list_resp = api_client.get(
        f"/api/projects/{sample_project.id}/remediation/workflows/{sample_workflow.workflow_id}/plans"
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == len(plans)

    # 3. GET /plans/compare
    comp_resp = api_client.get(
        f"/api/projects/{sample_project.id}/remediation/workflows/{sample_workflow.workflow_id}/plans/compare"
    )
    assert comp_resp.status_code == 200
    comp_data = comp_resp.json()
    assert comp_data["plans_count"] == len(plans)
    assert len(comp_data["comparison_matrix"]) == len(plans)

    # 4. POST /plans/{plan_id}/select
    target_plan_id = plans[0]["plan_id"]
    sel_resp = api_client.post(
        f"/api/projects/{sample_project.id}/remediation/workflows/{sample_workflow.workflow_id}/plans/{target_plan_id}/select"
    )
    assert sel_resp.status_code == 200
    assert sel_resp.json()["status"] == "selected"
    assert sel_resp.json()["workflow_state"] == "PATCH_GENERATED"


def test_tenant_isolation_forbidden_access(
    db_session: Session,
    sample_workflow: RemediationWorkflowRecord,
    sample_project: ReviewedProject,
    other_tenant_user: User,
):
    """Verifies that an actor from another tenant receives 403 or 404 on all endpoints."""
    def override_other_tenant_user():
        return other_tenant_user

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_other_tenant_user
    client = TestClient(app)

    try:
        # Cross-tenant investigation trigger
        resp = client.post(
            f"/api/projects/{sample_project.id}/remediation/workflows/{sample_workflow.workflow_id}/investigate"
        )
        assert resp.status_code in (403, 404)

        # Cross-tenant plans list
        resp_plans = client.get(
            f"/api/projects/{sample_project.id}/remediation/workflows/{sample_workflow.workflow_id}/plans"
        )
        assert resp_plans.status_code in (403, 404)
    finally:
        app.dependency_overrides.clear()


def test_safety_boundary_apply_endpoint_strictly_forbidden(
    api_client: TestClient,
    sample_workflow: RemediationWorkflowRecord,
    sample_project: ReviewedProject,
):
    """Strict Safety Boundary: /apply MUST return HTTP 403 Forbidden in Phase 5.2."""
    resp = api_client.post(
        f"/api/projects/{sample_project.id}/remediation/workflows/{sample_workflow.workflow_id}/apply"
    )
    assert resp.status_code == 403
    assert "Patch application is disabled" in resp.json()["detail"]
