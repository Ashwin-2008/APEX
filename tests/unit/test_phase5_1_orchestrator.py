from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.entities import (
    ProjectFinding,
    ProjectReview,
    RemediationApprovalRecord,
    RemediationAuditEvent,
    RemediationCandidateRecord,
    RemediationOutboxEvent,
    RemediationPlanRecord,
    RemediationVerificationRecord,
    RemediationWorkflowFinding,
    RemediationWorkflowRecord,
    ReviewedProject,
    User,
)
from app.services.remediation.orchestrator import (
    ApprovalValidationError,
    ConcurrencyConflictError,
    InvalidStateTransitionError,
    LeaseFencingError,
    RemediationOrchestrator,
    RemediationWorkflowState,
    TERMINAL_WORKFLOW_STATES,
    VALID_WORKFLOW_TRANSITIONS,
)


@pytest.fixture
def db_session() -> Session:
    """Creates an in-memory SQLite database session with all APEX models initialized."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    # Seed test users, projects, and findings
    user_a = User(
        id=1,
        email="alice@company.com",
        username="alice",
        hashed_password="hashed_pw_alice",
        is_active=True,
    )
    user_b = User(
        id=2,
        email="bob@competitor.com",
        username="bob",
        hashed_password="hashed_pw_bob",
        is_active=True,
    )
    session.add_all([user_a, user_b])
    session.flush()

    project_a = ReviewedProject(
        id=101,
        name="PaymentGateway",
        repository_path="/workspace/payments",
        owner_id=user_a.id,
    )
    project_b = ReviewedProject(
        id=202,
        name="SecretService",
        repository_path="/workspace/secrets",
        owner_id=user_b.id,
    )
    session.add_all([project_a, project_b])
    session.flush()

    review_a = ProjectReview(
        id=501,
        project_id=project_a.id,
        review_number=1,
    )
    session.add(review_a)
    session.flush()

    finding_1 = ProjectFinding(
        id=1001,
        review_id=review_a.id,
        category="security",
        severity="HIGH",
        confidence=0.95,
        title="SQL Injection in auth handler",
        file="auth.py",
        line=42,
        evidence="cursor.execute(f'SELECT...')",
        analyzer_source="security_analyzer",
        remediation="Use parameterized queries",
        fingerprint="fp_auth_sql_injection_001",
    )
    finding_2 = ProjectFinding(
        id=1002,
        review_id=review_a.id,
        category="architecture",
        severity="MEDIUM",
        confidence=0.88,
        title="Circular dependency between models and services",
        file="services.py",
        line=10,
        evidence="import models",
        analyzer_source="architecture_analyzer",
        remediation="Decouple models from services via interface",
        fingerprint="fp_circular_dep_002",
    )
    session.add_all([finding_1, finding_2])
    session.commit()

    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


# =====================================================================
# 1. State Machine Transitions & Validation
# =====================================================================


def test_legal_workflow_lifecycle_transitions(db_session: Session):
    """Verifies standard progressive happy-path workflow state transitions."""
    wf, is_dup = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Fix SQL injection",
        risk_level="HIGH",
    )
    assert not is_dup
    assert wf.state == RemediationWorkflowState.DISCOVERED.value
    assert wf.version_id == 1

    # Progression through stages
    stages = [
        RemediationWorkflowState.INVESTIGATING,
        RemediationWorkflowState.ROOT_CAUSE_IDENTIFIED,
        RemediationWorkflowState.PLAN_GENERATED,
        RemediationWorkflowState.PLAN_VALIDATED,
        RemediationWorkflowState.PATCH_GENERATED,
        RemediationWorkflowState.PATCH_VALIDATING,
        RemediationWorkflowState.PATCH_VERIFIED,
        RemediationWorkflowState.AWAITING_APPROVAL,
        RemediationWorkflowState.APPROVED,
        RemediationWorkflowState.APPLYING,
        RemediationWorkflowState.APPLIED,
        RemediationWorkflowState.POST_ANALYSIS,
        RemediationWorkflowState.COMPLETED,
    ]

    for expected_ver, stage in enumerate(stages, start=1):
        updated = RemediationOrchestrator.transition_state(
            session=db_session,
            workflow_id=wf.workflow_id,
            target_state=stage,
            actor="test_runner",
            expected_version=expected_ver,
        )
        assert updated.state == stage.value
        assert updated.version_id == expected_ver + 1

    assert updated.state == RemediationWorkflowState.COMPLETED.value


def test_illegal_state_transition_rejected(db_session: Session):
    """Verifies that an illegal transition raises InvalidStateTransitionError without mutating state."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Fix SQL injection",
    )
    # Attempting to jump directly from DISCOVERED to APPLIED
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        RemediationOrchestrator.transition_state(
            session=db_session,
            workflow_id=wf.workflow_id,
            target_state=RemediationWorkflowState.APPLIED,
            actor="attacker",
        )
    assert "Illegal transition from 'DISCOVERED' to 'APPLIED'" in str(exc_info.value)
    db_session.refresh(wf)
    assert wf.state == RemediationWorkflowState.DISCOVERED.value
    assert wf.version_id == 1


def test_terminal_state_protection(db_session: Session):
    """Verifies that terminal states (COMPLETED, REJECTED, CANCELLED) can never be transitioned."""
    for terminal_state in TERMINAL_WORKFLOW_STATES:
        wf, _ = RemediationOrchestrator.create_workflow(
            session=db_session,
            project_id=101,
            tenant_id="tenant_1",
            finding_ids=[1001],
            title=f"Terminal test {terminal_state.value}",
            idempotency_key=f"terminal_key_{terminal_state.value}",
        )
        # Directly advance to terminal state if allowed or set it
        wf.state = terminal_state.value
        db_session.flush()

        for attempt_target in RemediationWorkflowState:
            with pytest.raises(InvalidStateTransitionError) as exc_info:
                RemediationOrchestrator.transition_state(
                    session=db_session,
                    workflow_id=wf.workflow_id,
                    target_state=attempt_target,
                    actor="operator",
                )
            assert "Terminal state protection" in str(exc_info.value)


# =====================================================================
# 2. Persistence & Multi-Entity Binding
# =====================================================================


def test_multiple_findings_and_candidates_per_workflow(db_session: Session):
    """Verifies that a single workflow can bind multiple findings, plans, and patch candidates."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001, 1002],
        title="Multi-finding remediation",
    )
    db_session.commit()

    # Verify findings association
    wf_findings = db_session.query(RemediationWorkflowFinding).filter_by(workflow_id=wf.workflow_id).all()
    assert len(wf_findings) == 2
    assert {wf.finding_id for wf in wf_findings} == {1001, 1002}

    # Record plan
    plan = RemediationOrchestrator.record_plan(
        session=db_session,
        workflow_id=wf.workflow_id,
        tenant_id="tenant_1",
        project_id=101,
        target_findings=[{"id": 1001}, {"id": 1002}],
        affected_files=["auth.py", "services.py"],
        root_cause_reference={"cause": "coupled dependencies"},
        proposed_changes_summary="Decouple and sanitize",
        regression_risks=["low"],
        required_tests=["tests/test_auth.py"],
        risk_assessment={"score": 0.3},
    )
    assert plan.plan_id.startswith("plan_")

    # Record 2 candidate patches
    cand_1 = RemediationOrchestrator.record_candidate(
        session=db_session,
        workflow_id=wf.workflow_id,
        plan_id=plan.plan_id,
        tenant_id="tenant_1",
        project_id=101,
        strategy="AST_TRANSFORM",
        diff_unified="--- a/auth.py\n+++ b/auth.py\n@@ -1 +1 @@\n-raw\n+param",
        files_manifest={"auth.py": {"pre_hash": "a1", "post_hash": "b2"}},
    )
    cand_2 = RemediationOrchestrator.record_candidate(
        session=db_session,
        workflow_id=wf.workflow_id,
        plan_id=plan.plan_id,
        tenant_id="tenant_1",
        project_id=101,
        strategy="CONTEXT_AWARE",
        diff_unified="--- a/auth.py\n+++ b/auth.py\n@@ -1 +1 @@\n-raw\n+orm_query",
        files_manifest={"auth.py": {"pre_hash": "a1", "post_hash": "c3"}},
    )
    db_session.commit()

    candidates = db_session.query(RemediationCandidateRecord).filter_by(workflow_id=wf.workflow_id).all()
    assert len(candidates) == 2
    assert candidates[0].diff_hash != candidates[1].diff_hash
    # Candidate retains its own lifecycle state independent of workflow
    assert candidates[0].lifecycle_state == "GENERATED"


# =====================================================================
# 3. Idempotency & Concurrency Guarantees
# =====================================================================


def test_workflow_creation_idempotency(db_session: Session):
    """Verifies that duplicate workflow creation with identical idempotency key returns existing."""
    wf1, is_dup1 = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Idempotent Workflow",
        idempotency_key="stable_key_999",
    )
    assert not is_dup1

    wf2, is_dup2 = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Idempotent Workflow",
        idempotency_key="stable_key_999",
    )
    assert is_dup2
    assert wf1.workflow_id == wf2.workflow_id


def test_optimistic_concurrency_conflict(db_session: Session):
    """Verifies that an outdated expected_version raises ConcurrencyConflictError."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Concurrency Test",
    )
    assert wf.version_id == 1

    # First update advances version to 2
    RemediationOrchestrator.transition_state(
        session=db_session,
        workflow_id=wf.workflow_id,
        target_state=RemediationWorkflowState.INVESTIGATING,
        actor="worker_1",
        expected_version=1,
    )
    assert wf.version_id == 2

    # Second worker still expects version 1
    with pytest.raises(ConcurrencyConflictError) as exc_info:
        RemediationOrchestrator.transition_state(
            session=db_session,
            workflow_id=wf.workflow_id,
            target_state=RemediationWorkflowState.ROOT_CAUSE_IDENTIFIED,
            actor="worker_2",
            expected_version=1,
        )
    assert "Optimistic concurrency conflict" in str(exc_info.value)
    assert wf.state == RemediationWorkflowState.INVESTIGATING.value


# =====================================================================
# 4. Leases, Fencing Tokens & Crash Recovery
# =====================================================================


def test_worker_lease_acquisition_and_fencing(db_session: Session):
    """Verifies worker lease acquisition, renewal, and rejection of stale fencing tokens."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Lease Test",
    )

    # Worker 1 acquires lease
    acquired, token1 = RemediationOrchestrator.acquire_lease(
        session=db_session, workflow_id=wf.workflow_id, worker_id="worker_1", lease_duration_sec=300
    )
    assert acquired
    assert token1 == 1
    assert wf.lease_holder == "worker_1"

    # Worker 2 attempts to acquire lease while active
    acquired_2, token2 = RemediationOrchestrator.acquire_lease(
        session=db_session, workflow_id=wf.workflow_id, worker_id="worker_2", lease_duration_sec=300
    )
    assert not acquired_2
    assert token2 is None

    # Worker 1 advances state with valid lease and token
    RemediationOrchestrator.transition_state(
        session=db_session,
        workflow_id=wf.workflow_id,
        target_state=RemediationWorkflowState.INVESTIGATING,
        actor="worker_1",
        worker_id="worker_1",
        fencing_token=token1,
    )

    # Attempting to advance with stale token
    with pytest.raises(LeaseFencingError) as exc_info:
        RemediationOrchestrator.transition_state(
            session=db_session,
            workflow_id=wf.workflow_id,
            target_state=RemediationWorkflowState.ROOT_CAUSE_IDENTIFIED,
            actor="worker_1",
            worker_id="worker_1",
            fencing_token=999,  # Stale token
        )
    assert "Stale fencing token" in str(exc_info.value)


def test_orphaned_workflow_recovery(db_session: Session):
    """Verifies recovery sweeper recovers workflows whose worker lease expired."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Orphan Test",
    )
    # Transition to INVESTIGATING and simulate lease expiration in the past
    RemediationOrchestrator.transition_state(
        session=db_session,
        workflow_id=wf.workflow_id,
        target_state=RemediationWorkflowState.INVESTIGATING,
        actor="worker_died",
    )
    wf.lease_holder = "worker_died"
    wf.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
    db_session.commit()

    recovered = RemediationOrchestrator.recover_orphaned_workflows(session=db_session)
    assert len(recovered) == 1
    assert recovered[0].workflow_id == wf.workflow_id
    assert recovered[0].lease_holder is None
    # Transitioned to RETRY_PENDING or FAILED
    assert recovered[0].state in {RemediationWorkflowState.RETRY_PENDING.value, RemediationWorkflowState.FAILED.value}


# =====================================================================
# 5. Approval Content Hash Verification
# =====================================================================


def test_approval_patch_hash_mismatch_rejected(db_session: Session):
    """Verifies that approval is strictly rejected if patch content hash does not match."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Approval Hash Test",
    )
    cand = RemediationOrchestrator.record_candidate(
        session=db_session,
        workflow_id=wf.workflow_id,
        plan_id="plan_1",
        tenant_id="tenant_1",
        project_id=101,
        strategy="AST_TRANSFORM",
        diff_unified="diff_content_alpha",
        files_manifest={},
    )
    # Advance workflow to AWAITING_APPROVAL
    wf.state = RemediationWorkflowState.AWAITING_APPROVAL.value
    db_session.flush()

    correct_hash = cand.diff_hash
    tampered_hash = hashlib.sha256(b"diff_content_tampered").hexdigest()

    # Mismatched hash attempt
    with pytest.raises(ApprovalValidationError) as exc_info:
        RemediationOrchestrator.record_approval(
            session=db_session,
            workflow_id=wf.workflow_id,
            candidate_id=cand.candidate_id,
            patch_content_hash=tampered_hash,
            approving_actor="security_lead",
            decision="APPROVED",
            risk_classification="HIGH",
            approval_policy="REQUIRE_HUMAN",
            decision_rationale="Approved after review",
        )
    assert "Patch content hash mismatch" in str(exc_info.value)
    assert wf.state == RemediationWorkflowState.AWAITING_APPROVAL.value

    # Legitimate hash approval
    approval = RemediationOrchestrator.record_approval(
        session=db_session,
        workflow_id=wf.workflow_id,
        candidate_id=cand.candidate_id,
        patch_content_hash=correct_hash,
        approving_actor="security_lead",
        decision="APPROVED",
        risk_classification="HIGH",
        approval_policy="REQUIRE_HUMAN",
        decision_rationale="Approved after review",
    )
    assert approval.is_valid
    assert wf.state == RemediationWorkflowState.APPROVED.value


# =====================================================================
# 6. Outbox Event Persistence & Delivery
# =====================================================================


def test_outbox_event_processing_and_retry(db_session: Session):
    """Verifies that outbox events are committed transactionally and processed reliably."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Outbox Test",
    )
    db_session.commit()

    # Query outbox
    pending = db_session.query(RemediationOutboxEvent).filter_by(workflow_id=wf.workflow_id).all()
    assert len(pending) == 1
    assert pending[0].status == "PENDING"
    assert pending[0].event_type == "workflow.created"

    # Process outbox with a successful delivery function
    delivered = RemediationOrchestrator.process_outbox(
        session=db_session,
        deliver_fn=lambda evt: True,
    )
    assert delivered == 1
    db_session.refresh(pending[0])
    assert pending[0].status == "DELIVERED"
    assert pending[0].delivered_at is not None


# =====================================================================
# 7. Cancellation & Timeout Semantics
# =====================================================================


def test_workflow_cancellation_semantics(db_session: Session):
    """Verifies workflow cancellation from active states."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Cancel Test",
    )
    RemediationOrchestrator.transition_state(
        session=db_session,
        workflow_id=wf.workflow_id,
        target_state=RemediationWorkflowState.INVESTIGATING,
        actor="operator",
    )

    cancelled_wf = RemediationOrchestrator.cancel_workflow(
        session=db_session,
        workflow_id=wf.workflow_id,
        actor="operator",
        reason="Aborted by user",
    )
    assert cancelled_wf.state == RemediationWorkflowState.CANCELLED.value

    # Verify audit trail contains CANCEL_REQUESTED and CANCELLED
    audits = db_session.query(RemediationAuditEvent).filter_by(workflow_id=wf.workflow_id).all()
    actions = [a.action for a in audits]
    assert "TRANSITION_CANCEL_REQUESTED" in actions
    assert "TRANSITION_CANCELLED" in actions


# =====================================================================
# 8. Tenant & Project Isolation Checks
# =====================================================================


def test_tenant_isolation_boundary(db_session: Session):
    """Verifies that workflows from tenant_1 cannot be retrieved with tenant_2 scope."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Tenant Isolation Test",
    )
    db_session.commit()

    # Query with correct tenant
    found = RemediationOrchestrator.get_workflow(db_session, wf.workflow_id, tenant_id="tenant_1")
    assert found is not None

    # Query with unauthorized tenant
    blocked = RemediationOrchestrator.get_workflow(db_session, wf.workflow_id, tenant_id="tenant_2")
    assert blocked is None


# =====================================================================
# 9. API Integration & Security Tests
# =====================================================================


def test_remediation_api_routes_and_security():
    """Verifies API endpoints for workflow creation, detail, history, cancel, apply guard, and tenant isolation."""
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool
    from app.main import create_app
    from app.services.auth_service import create_access_token

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()

    user_a = User(id=1, email="alice@corp.com", username="alice", hashed_password="pw", is_active=True)
    user_b = User(id=2, email="bob@other.com", username="bob", hashed_password="pw", is_active=True)
    session.add_all([user_a, user_b])
    session.flush()

    project_a = ReviewedProject(id=101, name="ProjectA", repository_path="/repoA", owner_id=user_a.id)
    project_b = ReviewedProject(id=202, name="ProjectB", repository_path="/repoB", owner_id=user_b.id)
    session.add_all([project_a, project_b])
    session.flush()

    review_a = ProjectReview(id=501, project_id=project_a.id, review_number=1)
    session.add(review_a)
    session.flush()

    finding_1 = ProjectFinding(
        id=1001,
        review_id=review_a.id,
        category="security",
        severity="HIGH",
        confidence=0.95,
        title="SQL Injection",
        file="auth.py",
        line=42,
        evidence="raw query",
        analyzer_source="security_analyzer",
        remediation="use parameters",
        fingerprint="fp_sec_1001",
    )
    session.add(finding_1)
    session.commit()

    token_a = create_access_token(user=user_a)
    headers_a = {"Authorization": f"Bearer {token_a}"}

    token_b = create_access_token(user=user_b)
    headers_b = {"Authorization": f"Bearer {token_b}"}

    session.close()

    app = create_app(database_engine=engine)
    app.state.SessionLocal = session_factory

    client = TestClient(app)

    # 1. Create workflow as User A
    create_payload = {
        "finding_ids": [1001],
        "title": "API Remediation Test",
        "description": "Fixing SQL injection via API",
        "risk_level": "HIGH",
        "approval_policy": "REQUIRE_HUMAN",
        "idempotency_key": "api_idem_101",
    }
    resp = client.post("/api/projects/101/remediation/workflows", json=create_payload, headers=headers_a)
    assert resp.status_code == 201, resp.text
    wf_data = resp.json()
    wf_id = wf_data["workflow_id"]
    assert wf_data["state"] == "DISCOVERED"
    assert wf_data["finding_ids"] == [1001]

    # 2. Idempotent re-creation returns 201 with identical workflow_id
    resp_dup = client.post("/api/projects/101/remediation/workflows", json=create_payload, headers=headers_a)
    assert resp_dup.status_code == 201
    assert resp_dup.json()["workflow_id"] == wf_id

    # 3. List workflows for Project 101
    list_resp = client.get("/api/projects/101/remediation/workflows", headers=headers_a)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["workflow_id"] == wf_id

    # 4. Get workflow detail
    detail_resp = client.get(f"/api/projects/101/remediation/workflows/{wf_id}", headers=headers_a)
    assert detail_resp.status_code == 200
    assert detail_resp.json()["workflow_id"] == wf_id

    # 5. History audit trail
    hist_resp = client.get(f"/api/projects/101/remediation/workflows/{wf_id}/history", headers=headers_a)
    assert hist_resp.status_code == 200
    assert len(hist_resp.json()) >= 1
    assert hist_resp.json()[0]["action"] == "WORKFLOW_CREATED"

    # 6. Safety check: Apply endpoint is strictly disabled (403 Forbidden)
    apply_resp = client.post(f"/api/projects/101/remediation/workflows/{wf_id}/apply", headers=headers_a)
    assert apply_resp.status_code == 403
    assert "Patch application is disabled in Phase 5.1" in apply_resp.json()["detail"]

    # 7. Cancel workflow
    cancel_resp = client.post(
        f"/api/projects/101/remediation/workflows/{wf_id}/cancel",
        json={"reason": "Testing cancellation API"},
        headers=headers_a,
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["state"] == "CANCELLED"

    # 8. Tenant isolation: User B attempting to access User A's workflow returns 404
    cross_resp = client.get(f"/api/projects/101/remediation/workflows/{wf_id}", headers=headers_b)
    assert cross_resp.status_code == 404

