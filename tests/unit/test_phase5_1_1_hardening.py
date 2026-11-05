from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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
    TerminalStateError,
    VALID_WORKFLOW_TRANSITIONS,
    canonicalize_patch,
    sanitize_payload,
)
from app.services.remediation.transaction_engine import MultiFileTransactionEngine, TransactionState


@pytest.fixture
def db_session() -> Session:
    """Creates a thread-safe in-memory SQLite database session with all models initialized."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    # Seed test users
    user_a = User(
        id=1,
        email="alice@tenant1.com",
        username="alice",
        hashed_password="pw1",
        is_active=True,
    )
    user_b = User(
        id=2,
        email="bob@tenant2.com",
        username="bob",
        hashed_password="pw2",
        is_active=True,
    )
    admin_user = User(
        id=3,
        email="admin@apex.com",
        username="admin",
        hashed_password="pw3",
        is_active=True,
        preferences={"role": "admin"},
    )
    session.add_all([user_a, user_b, admin_user])
    session.flush()

    # Seed test projects
    project_a = ReviewedProject(
        id=101,
        name="ProjectAlpha",
        repository_path="/workspace/alpha",
        owner_id=user_a.id,
    )
    project_b = ReviewedProject(
        id=202,
        name="ProjectBeta",
        repository_path="/workspace/beta",
        owner_id=user_b.id,
    )
    session.add_all([project_a, project_b])
    session.flush()

    # Seed project reviews
    review_a = ProjectReview(id=501, project_id=project_a.id, review_number=1)
    review_b = ProjectReview(id=502, project_id=project_b.id, review_number=1)
    session.add_all([review_a, review_b])
    session.flush()

    # Seed findings
    finding_a1 = ProjectFinding(
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
        fingerprint="fp_sec_001",
    )
    finding_b1 = ProjectFinding(
        id=2001,
        review_id=review_b.id,
        category="security",
        severity="CRITICAL",
        confidence=0.99,
        title="Hardcoded API key",
        file="config.py",
        line=12,
        evidence="API_KEY = 'secret'",
        analyzer_source="security_analyzer",
        remediation="Use env var",
        fingerprint="fp_sec_002",
    )
    session.add_all([finding_a1, finding_b1])
    session.commit()

    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


# =====================================================================
# 1. Distributed Fencing Token & Stale Worker Safety
# =====================================================================


def test_stale_worker_rejection_scenario(db_session: Session):
    """Verifies that when Worker A's lease expires and Worker B acquires it with a higher fencing token,
    every protected operation from Worker A is rejected while Worker B's state remains intact.
    """
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Stale Worker Test",
    )
    db_session.commit()

    # Worker A acquires lease
    acquired_a, token_a = RemediationOrchestrator.acquire_lease(
        session=db_session,
        workflow_id=wf.workflow_id,
        worker_id="worker_a",
        lease_duration_sec=300,
    )
    assert acquired_a is True
    assert token_a == 1

    # Worker A progresses workflow to INVESTIGATING
    RemediationOrchestrator.transition_state(
        session=db_session,
        workflow_id=wf.workflow_id,
        target_state=RemediationWorkflowState.INVESTIGATING,
        actor="worker_a",
        worker_id="worker_a",
        fencing_token=token_a,
    )
    db_session.commit()

    # Simulate Worker A pausing and its lease expiring
    wf.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=10)
    db_session.commit()

    # Worker B acquires a new lease
    acquired_b, token_b = RemediationOrchestrator.acquire_lease(
        session=db_session,
        workflow_id=wf.workflow_id,
        worker_id="worker_b",
        lease_duration_sec=300,
    )
    assert acquired_b is True
    assert token_b == 2
    db_session.commit()

    # Worker A resumes and attempts state transition using stale token 1 -> MUST BE REJECTED
    with pytest.raises(LeaseFencingError) as exc_info:
        RemediationOrchestrator.transition_state(
            session=db_session,
            workflow_id=wf.workflow_id,
            target_state=RemediationWorkflowState.ROOT_CAUSE_IDENTIFIED,
            actor="worker_a",
            worker_id="worker_a",
            fencing_token=token_a,
        )
    assert "Worker 'worker_a' does not own lease; currently held by 'worker_b'" in str(exc_info.value)

    # Worker A attempts to record a plan using stale token -> MUST BE REJECTED
    with pytest.raises(LeaseFencingError):
        RemediationOrchestrator.record_plan(
            session=db_session,
            workflow_id=wf.workflow_id,
            tenant_id="tenant_1",
            project_id=101,
            target_findings=[{"id": 1001}],
            affected_files=["auth.py"],
            root_cause_reference={},
            proposed_changes_summary="Stale plan",
            regression_risks=[],
            required_tests=[],
            risk_assessment={},
            actor="worker_a",
            worker_id="worker_a",
            fencing_token=token_a,
        )

    # Worker A attempts to record a candidate using stale token -> MUST BE REJECTED
    with pytest.raises(LeaseFencingError):
        RemediationOrchestrator.record_candidate(
            session=db_session,
            workflow_id=wf.workflow_id,
            plan_id="plan_stale",
            tenant_id="tenant_1",
            project_id=101,
            strategy="AST_TRANSFORM",
            diff_unified="stale_diff",
            files_manifest={},
            actor="worker_a",
            worker_id="worker_a",
            fencing_token=token_a,
        )

    # Worker A attempts to release the lease owned by Worker B -> MUST BE REJECTED
    released = RemediationOrchestrator.release_lease(
        session=db_session,
        workflow_id=wf.workflow_id,
        worker_id="worker_a",
        fencing_token=token_a,
    )
    assert released is False
    # Verify Worker B still holds the lease
    db_session.refresh(wf)
    assert wf.lease_holder == "worker_b"
    assert wf.fencing_token == 2

    # Worker B performs valid state progression -> SUCCEEDS
    updated_b = RemediationOrchestrator.transition_state(
        session=db_session,
        workflow_id=wf.workflow_id,
        target_state=RemediationWorkflowState.ROOT_CAUSE_IDENTIFIED,
        actor="worker_b",
        worker_id="worker_b",
        fencing_token=token_b,
    )
    assert updated_b.state == RemediationWorkflowState.ROOT_CAUSE_IDENTIFIED.value


def test_concurrent_lease_acquisition_atomicity(db_session: Session):
    """Verifies atomic lease acquisition prevents concurrent workers from obtaining the same generation."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Concurrent Lease Test",
    )
    db_session.commit()

    # Worker 1 acquires lease
    acq1, tok1 = RemediationOrchestrator.acquire_lease(db_session, wf.workflow_id, "worker_1", lease_duration_sec=60)
    assert acq1 is True
    assert tok1 == 1

    # Worker 2 attempts simultaneous acquisition while Worker 1 lease is unexpired -> Fails immediately
    acq2, tok2 = RemediationOrchestrator.acquire_lease(db_session, wf.workflow_id, "worker_2", lease_duration_sec=60)
    assert acq2 is False
    assert tok2 is None

    # Worker 1 renews its lease via explicit renew_lease -> Succeeds and increments fencing generation
    wf_record = RemediationOrchestrator.get_workflow(db_session, wf.workflow_id)
    assert wf_record is not None
    renewed, tok1_new = RemediationOrchestrator.renew_lease(
        db_session, wf.workflow_id, "worker_1", wf_record.worker_instance_id, tok1, lease_duration_sec=60
    )
    assert renewed is True
    assert tok1_new == 2


# =====================================================================
# 2. Transaction-Aware Crash Recovery
# =====================================================================


def test_crash_recovery_analytical_step(db_session: Session):
    """Verifies that analytical steps (INVESTIGATING, PLAN_GENERATED, etc.) with expired leases
    are safely recovered to TIMED_OUT and RETRY_PENDING when retries remain.
    """
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Analytical Recovery Test",
    )
    RemediationOrchestrator.transition_state(
        session=db_session,
        workflow_id=wf.workflow_id,
        target_state=RemediationWorkflowState.INVESTIGATING,
        actor="system",
    )
    # Simulate worker crash and expired lease
    wf.lease_holder = "crashed_worker"
    wf.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
    db_session.commit()

    recovered = RemediationOrchestrator.recover_orphaned_workflows(db_session)
    assert len(recovered) == 1
    assert recovered[0].workflow_id == wf.workflow_id
    assert recovered[0].state == RemediationWorkflowState.RETRY_PENDING.value
    assert recovered[0].retry_count == 1
    assert recovered[0].lease_holder is None


def test_crash_recovery_exhausted_retries_fails(db_session: Session):
    """Verifies that an analytical step that exhausts max_retries transitions to FAILED."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Max Retries Recovery Test",
    )
    # Set to analytical state with exhausted retries
    wf.state = RemediationWorkflowState.PATCH_GENERATED.value
    wf.retry_count = 3  # max_retries is 3
    wf.lease_holder = "crashed_worker"
    wf.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
    db_session.commit()

    recovered = RemediationOrchestrator.recover_orphaned_workflows(db_session)
    assert len(recovered) == 1
    assert recovered[0].state == RemediationWorkflowState.FAILED.value


def test_crash_recovery_filesystem_transaction_conflict():
    """Verifies that when a worker crashes during APPLYING and external edits occurred,
    CrashRecoveryEngine detects the conflict and transitions workflow to MANUAL_RECONCILIATION_REQUIRED.
    """
    temp_dir = tempfile.mkdtemp(prefix="apex_test_repo_")
    try:
        repo_path = Path(temp_dir)
        target_file = repo_path / "auth.py"
        target_file.write_text("def auth():\n    return 'original'\n", encoding="utf-8")

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        session_factory = sessionmaker(bind=engine)
        session = session_factory()

        user = User(id=1, email="alice@test.com", username="alice", hashed_password="pw", is_active=True)
        project = ReviewedProject(id=101, name="TestProject", repository_path=str(repo_path), owner_id=user.id)
        session.add_all([user, project])
        session.flush()

        review = ProjectReview(id=501, project_id=project.id, review_number=1)
        session.add(review)
        session.flush()

        finding = ProjectFinding(
            id=1001, review_id=review.id, category="security", severity="HIGH", confidence=0.9,
            title="Finding", file="auth.py", line=1, evidence="x", analyzer_source="src", remediation="fix", fingerprint="fp1"
        )
        session.add(finding)
        session.commit()

        wf, _ = RemediationOrchestrator.create_workflow(
            session=session, project_id=101, tenant_id="1", finding_ids=[1001], title="FS Crash Test"
        )
        # Prepare transaction in transaction engine and simulate crash during APPLYING
        txn = MultiFileTransactionEngine.prepare_transaction(
            project_id=101,
            repo_root=repo_path,
            file_patches=[{"rel_path": "auth.py", "patched_content": "def auth():\n    return 'patched'\n"}],
            db=session,
        )
        txn_id = txn["transaction_id"]
        manifest = MultiFileTransactionEngine.load_manifest(repo_path, txn_id)
        manifest["state"] = TransactionState.APPLYING.value
        MultiFileTransactionEngine.save_manifest(repo_path, manifest)
        wf.active_transaction_id = txn_id

        # Move workflow to APPLYING with expired lease
        wf.state = RemediationWorkflowState.APPLYING.value
        wf.lease_holder = "worker_crashed_during_apply"
        wf.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
        session.commit()

        # Simulate developer editing file externally while transaction was staged
        target_file.write_text("def auth():\n    return 'external_modification_conflict'\n", encoding="utf-8")

        # Run recovery
        recovered = RemediationOrchestrator.recover_orphaned_workflows(session)
        assert len(recovered) == 1
        assert recovered[0].state == RemediationWorkflowState.MANUAL_RECONCILIATION_REQUIRED.value
        assert "Third-party modifications" in recovered[0].error_message
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# =====================================================================
# 3. Approval Integrity Hardening
# =====================================================================


def test_canonical_patch_diff_and_hash():
    """Verifies canonical patch formatting normalizes newlines and trailing whitespace."""
    diff_crlf = "--- a/file.py\r\n+++ b/file.py\r\n@@ -1 +1 @@\r\n-old   \r\n+new  \r\n\r\n"
    diff_lf = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n"

    canon_crlf = canonicalize_patch(diff_crlf)
    canon_lf = canonicalize_patch(diff_lf)
    assert canon_crlf == canon_lf
    assert hashlib.sha256(canon_crlf.encode("utf-8")).hexdigest() == hashlib.sha256(canon_lf.encode("utf-8")).hexdigest()


def test_approval_candidate_version_mismatch_rejected(db_session: Session):
    """Verifies that attempting to approve a candidate specifying a stale version raises ApprovalValidationError."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Version Approval Test",
    )
    cand = RemediationOrchestrator.record_candidate(
        session=db_session,
        workflow_id=wf.workflow_id,
        plan_id="plan_1",
        tenant_id="tenant_1",
        project_id=101,
        strategy="AST_TRANSFORM",
        diff_unified="diff v1",
        files_manifest={},
        candidate_version=2,
    )
    wf.state = RemediationWorkflowState.AWAITING_APPROVAL.value
    db_session.commit()

    with pytest.raises(ApprovalValidationError) as exc:
        RemediationOrchestrator.record_approval(
            session=db_session,
            workflow_id=wf.workflow_id,
            candidate_id=cand.candidate_id,
            patch_content_hash=cand.diff_hash,
            approving_actor="reviewer",
            decision="APPROVED",
            decision_rationale="Looks good",
            candidate_version=1,  # Stale version!
        )
    assert "Candidate version mismatch" in str(exc.value)


def test_approval_base_commit_sha_mismatch_rejected(db_session: Session):
    """Verifies that approval against a mismatched repository commit SHA is rejected."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Commit SHA Approval Test",
    )
    cand = RemediationOrchestrator.record_candidate(
        session=db_session,
        workflow_id=wf.workflow_id,
        plan_id="plan_1",
        tenant_id="tenant_1",
        project_id=101,
        strategy="AST_TRANSFORM",
        diff_unified="diff commit test",
        files_manifest={},
        base_commit_sha="commit_abc123",
    )
    wf.state = RemediationWorkflowState.AWAITING_APPROVAL.value
    db_session.commit()

    with pytest.raises(ApprovalValidationError) as exc:
        RemediationOrchestrator.record_approval(
            session=db_session,
            workflow_id=wf.workflow_id,
            candidate_id=cand.candidate_id,
            patch_content_hash=cand.diff_hash,
            approving_actor="reviewer",
            decision="APPROVED",
            decision_rationale="Looks good",
            base_commit_sha="commit_different_999",
        )
    assert "Base commit SHA mismatch" in str(exc.value)


def test_approval_server_side_tier_authorization(db_session: Session):
    """Verifies that critical risk or admin-required policies reject non-admin approvals."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Admin Tier Approval Test",
        risk_level="CRITICAL",
        approval_policy="ADMIN_REQUIRED",
    )
    cand = RemediationOrchestrator.record_candidate(
        session=db_session,
        workflow_id=wf.workflow_id,
        plan_id="plan_1",
        tenant_id="tenant_1",
        project_id=101,
        strategy="AST_TRANSFORM",
        diff_unified="diff critical",
        files_manifest={},
    )
    wf.state = RemediationWorkflowState.AWAITING_APPROVAL.value
    db_session.commit()

    # Standard non-admin user attempts approval -> REJECTED
    user_standard = db_session.get(User, 1)
    with pytest.raises(ApprovalValidationError) as exc:
        RemediationOrchestrator.record_approval(
            session=db_session,
            workflow_id=wf.workflow_id,
            candidate_id=cand.candidate_id,
            patch_content_hash=cand.diff_hash,
            approving_actor="alice",
            decision="APPROVED",
            decision_rationale="Attempted self approval",
            approver_user=user_standard,
            actor_is_admin=False,
        )
    assert "Administrator authorization required" in str(exc.value)

    # Superuser admin attempts approval -> SUCCEEDS
    admin_user = db_session.get(User, 3)
    appr = RemediationOrchestrator.record_approval(
        session=db_session,
        workflow_id=wf.workflow_id,
        candidate_id=cand.candidate_id,
        patch_content_hash=cand.diff_hash,
        approving_actor="admin",
        decision="APPROVED",
        decision_rationale="Admin verified",
        approver_user=admin_user,
        actor_is_admin=True,
    )
    assert appr.is_valid is True
    assert appr.decision == "APPROVED"
    assert len(appr.approval_context_hash) == 64


def test_approval_revocation_lifecycle(db_session: Session):
    """Verifies approval revocation updates record, emits audit event, and updates workflow state."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Revocation Test",
    )
    cand = RemediationOrchestrator.record_candidate(
        session=db_session,
        workflow_id=wf.workflow_id,
        plan_id="plan_1",
        tenant_id="tenant_1",
        project_id=101,
        strategy="AST",
        diff_unified="diff rev",
        files_manifest={},
    )
    wf.state = RemediationWorkflowState.AWAITING_APPROVAL.value
    appr = RemediationOrchestrator.record_approval(
        session=db_session,
        workflow_id=wf.workflow_id,
        candidate_id=cand.candidate_id,
        patch_content_hash=cand.diff_hash,
        approving_actor="lead_dev",
        decision="APPROVED",
        decision_rationale="LGTM",
    )
    assert wf.state == RemediationWorkflowState.APPROVED.value

    # Revoke approval
    revoked = RemediationOrchestrator.revoke_approval(
        session=db_session,
        workflow_id=wf.workflow_id,
        approval_id=appr.approval_id,
        actor="security_officer",
        reason="Security flaw found in diff post-approval",
    )
    assert revoked.is_valid is False
    assert revoked.revoked_by == "security_officer"
    assert wf.state == RemediationWorkflowState.REJECTED.value


# =====================================================================
# 4. Outbox Idempotency & Worker Fencing
# =====================================================================


def test_outbox_atomic_claiming_and_idempotent_delivery(db_session: Session):
    """Verifies outbox atomic claiming protects against concurrent duplicate delivery
    and consumer deduplication recognizes already processed events.
    """
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Outbox Idempotency Test",
    )
    db_session.commit()

    processed_event_ids = set()
    delivered_payloads = []

    def idempotent_consumer(evt: RemediationOutboxEvent) -> bool:
        if evt.event_id in processed_event_ids:
            # Duplicate received: return True without re-executing action
            return True
        processed_event_ids.add(evt.event_id)
        delivered_payloads.append(evt.payload)
        return True

    # Process pending events
    count = RemediationOrchestrator.process_outbox(
        session=db_session,
        worker_id="outbox_worker_1",
        deliver_fn=idempotent_consumer,
    )
    assert count >= 1
    assert len(delivered_payloads) >= 1

    # Simulate worker crash: event marked PENDING again for replay
    event_record = db_session.query(RemediationOutboxEvent).first()
    event_record.status = "PENDING"
    db_session.commit()

    # Worker 2 reclaims and delivers again
    count_replay = RemediationOrchestrator.process_outbox(
        session=db_session,
        worker_id="outbox_worker_2",
        deliver_fn=idempotent_consumer,
    )
    assert count_replay >= 1
    # Consumer recognized duplicate event_id, no duplicate side-effect payload added
    assert len(delivered_payloads) == 1


# =====================================================================
# 5. Tamper-Evident Audit Event Chaining
# =====================================================================


def test_audit_event_tamper_evident_chain_verification(db_session: Session):
    """Verifies cryptographic hash chaining across audit events and detects database tampering."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Audit Chain Test",
    )
    RemediationOrchestrator.transition_state(
        session=db_session,
        workflow_id=wf.workflow_id,
        target_state=RemediationWorkflowState.INVESTIGATING,
        actor="alice",
        reason="Started investigation",
    )
    RemediationOrchestrator.transition_state(
        session=db_session,
        workflow_id=wf.workflow_id,
        target_state=RemediationWorkflowState.ROOT_CAUSE_IDENTIFIED,
        actor="alice",
        reason="Identified flaw",
    )
    db_session.commit()

    # 1. Verify pristine chain
    is_valid, errors = RemediationOrchestrator.verify_audit_chain(db_session, wf.workflow_id)
    assert is_valid is True
    assert errors == []

    # 2. Simulate malicious attacker tampering with an audit event row
    second_event = (
        db_session.query(RemediationAuditEvent)
        .filter(RemediationAuditEvent.workflow_id == wf.workflow_id, RemediationAuditEvent.sequence_number == 2)
        .first()
    )
    second_event.action = "TAMPERED_ACTION_MALICIOUS"
    db_session.commit()

    # 3. Validation must now detect the broken chain
    is_valid_tampered, errors_tampered = RemediationOrchestrator.verify_audit_chain(db_session, wf.workflow_id)
    assert is_valid_tampered is False
    assert any("hash mismatch" in err for err in errors_tampered)


def test_audit_payload_sensitive_data_redaction():
    """Verifies that sensitive tokens, passwords, and private secrets are automatically redacted in audit logs."""
    raw_payload = {
        "finding_id": 101,
        "auth_token": "bearer_secret_xyz123",
        "nested": {
            "db_password": "super_secret_pw",
            "api_key": "secret_key_999",
            "clean_metric": 42,
        },
    }
    sanitized = sanitize_payload(raw_payload)
    assert sanitized["auth_token"] == "[REDACTED]"
    assert sanitized["nested"]["db_password"] == "[REDACTED]"
    assert sanitized["nested"]["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["clean_metric"] == 42


# =====================================================================
# 6. Tenant-Isolation & Nested-Resource Adversarial Tests
# =====================================================================


def test_cross_tenant_finding_binding_rejected(db_session: Session):
    """Verifies that Tenant A cannot create a workflow binding findings belonging to Tenant B's project."""
    with pytest.raises(ValueError) as exc:
        RemediationOrchestrator.create_workflow(
            session=db_session,
            project_id=101,  # Project Alpha (Tenant 1)
            tenant_id="tenant_1",
            finding_ids=[2001],  # Finding belongs to Project Beta (Tenant 2)!
            title="Cross Tenant Attack",
        )
    assert "does not belong to project 101" in str(exc.value)


def test_cross_tenant_workflow_detail_isolation(db_session: Session):
    """Verifies that Tenant 2 querying Tenant 1's workflow by ID receives None (404 behavior)."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Tenant 1 Workflow",
    )
    db_session.commit()

    # Tenant 1 retrieves -> Succeeds
    res_tenant1 = RemediationOrchestrator.get_workflow(db_session, wf.workflow_id, tenant_id="tenant_1")
    assert res_tenant1 is not None

    # Tenant 2 retrieves -> Returns None (isolated)
    res_tenant2 = RemediationOrchestrator.get_workflow(db_session, wf.workflow_id, tenant_id="tenant_2")
    assert res_tenant2 is None


# =====================================================================
# 7. State Machine Coverage & Terminal Protection
# =====================================================================


def test_terminal_state_protection_comprehensive(db_session: Session):
    """Verifies that terminal states (COMPLETED, REJECTED, CANCELLED) strictly reject any transitions."""
    for term_state in TERMINAL_WORKFLOW_STATES:
        wf, _ = RemediationOrchestrator.create_workflow(
            session=db_session,
            project_id=101,
            tenant_id="tenant_1",
            finding_ids=[1001],
            title=f"Terminal Test {term_state.value}",
        )
        wf.state = term_state.value
        db_session.commit()

        # Attempt to transition out of terminal state -> Must raise TerminalStateError
        with pytest.raises(TerminalStateError) as exc:
            RemediationOrchestrator.transition_state(
                session=db_session,
                workflow_id=wf.workflow_id,
                target_state=RemediationWorkflowState.INVESTIGATING,
                actor="test_actor",
            )
        assert "Terminal state protection" in str(exc.value)


def test_all_24_workflow_states_present_in_transitions():
    """Verifies all 24 enum states exist as keys in the legal transition map."""
    all_states = set(RemediationWorkflowState)
    assert len(all_states) == 24
    assert set(VALID_WORKFLOW_TRANSITIONS.keys()) == all_states
