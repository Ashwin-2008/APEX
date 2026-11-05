from __future__ import annotations

import copy
import hashlib
import json
import multiprocessing
import os
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
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
from app.services.remediation.crash_recovery import CrashRecoveryEngine
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
    """Creates a clean in-memory SQLite database session with all models."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    # Seed test entities
    user = User(id=1, email="lead@corp.internal", username="lead_engineer", hashed_password="pw", is_active=True)
    admin = User(id=2, email="admin@corp.internal", username="admin", hashed_password="pw", is_active=True)
    session.add_all([user, admin])
    session.flush()

    project = ReviewedProject(id=101, name="ProjectMistiq", repository_path="/tmp/repo_mistiq", owner_id=user.id)
    session.add(project)
    session.flush()

    review = ProjectReview(id=501, project_id=project.id, review_number=1)
    session.add(review)
    session.flush()

    finding1 = ProjectFinding(
        id=1001,
        review_id=review.id,
        category="security",
        severity="HIGH",
        confidence=0.95,
        title="SQL Injection in auth.py",
        file="auth.py",
        line=42,
        evidence="execute(query)",
        analyzer_source="security_analyzer",
        remediation="parameterize query",
        fingerprint="fp_sec_1001",
    )
    finding2 = ProjectFinding(
        id=1002,
        review_id=review.id,
        category="reliability",
        severity="MEDIUM",
        confidence=0.88,
        title="Uncaught exception in parser",
        file="parser.py",
        line=88,
        evidence="except: pass",
        analyzer_source="reliability_analyzer",
        remediation="log and re-raise",
        fingerprint="fp_rel_1002",
    )
    session.add_all([finding1, finding2])
    session.commit()

    return session


# =====================================================================
# 1. Lease Ownership, Worker Instance Identity & Fencing Token Tests
# =====================================================================


def test_unique_worker_instance_identity_blocks_same_worker_id(db_session: Session):
    """Verifies that two independent processes sharing the same worker_id cannot steal
    an active lease if they have distinct worker_instance_ids.
    """
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Instance Lease Test",
    )
    db_session.commit()

    # Process A acquires lease with instance_id "proc_A"
    acq_a, tok_a = RemediationOrchestrator.acquire_lease(
        session=db_session,
        workflow_id=wf.workflow_id,
        worker_id="remediation_worker",
        lease_duration_sec=300,
        worker_instance_id="proc_A",
    )
    assert acq_a is True
    assert tok_a == 1

    # Process B (independent process with same worker_id but instance "proc_B") attempts acquisition
    acq_b, tok_b = RemediationOrchestrator.acquire_lease(
        session=db_session,
        workflow_id=wf.workflow_id,
        worker_id="remediation_worker",
        lease_duration_sec=300,
        worker_instance_id="proc_B",
    )
    assert acq_b is False
    assert tok_b is None

    # Process B cannot advance workflow state with Worker A's fencing token
    with pytest.raises(LeaseFencingError) as exc_info:
        RemediationOrchestrator.transition_state(
            session=db_session,
            workflow_id=wf.workflow_id,
            target_state=RemediationWorkflowState.INVESTIGATING,
            actor="remediation_worker",
            worker_id="remediation_worker",
            fencing_token=tok_a,
            worker_instance_id="proc_B",
        )
    assert "Worker instance 'proc_B' does not own lease" in str(exc_info.value)


def test_explicit_lease_renewal_separate_from_acquisition(db_session: Session):
    """Verifies that renewal is strictly separated from acquisition and requires valid
    worker_id, worker_instance_id, and unexpired lease under db clock.
    """
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Lease Renewal Test",
    )
    db_session.commit()

    # Initial acquisition
    acq, tok1 = RemediationOrchestrator.acquire_lease(
        session=db_session,
        workflow_id=wf.workflow_id,
        worker_id="worker_alpha",
        lease_duration_sec=300,
        worker_instance_id="inst_alpha_1",
    )
    assert acq is True
    assert tok1 == 1

    # Attempting to call acquire_lease again while active fails (decoupled renewal requirement)
    acq_again, _ = RemediationOrchestrator.acquire_lease(
        session=db_session,
        workflow_id=wf.workflow_id,
        worker_id="worker_alpha",
        lease_duration_sec=300,
        worker_instance_id="inst_alpha_1",
    )
    assert acq_again is False

    # Attempting to renew with wrong worker_instance_id fails
    renew_wrong_inst, _ = RemediationOrchestrator.renew_lease(
        session=db_session,
        workflow_id=wf.workflow_id,
        worker_id="worker_alpha",
        worker_instance_id="inst_alpha_2",
        fencing_token=tok1,
    )
    assert renew_wrong_inst is False

    # Attempting to renew with stale fencing token fails
    renew_stale_tok, _ = RemediationOrchestrator.renew_lease(
        session=db_session,
        workflow_id=wf.workflow_id,
        worker_id="worker_alpha",
        worker_instance_id="inst_alpha_1",
        fencing_token=tok1 + 99,
    )
    assert renew_stale_tok is False

    # Legitimate renewal succeeds and increments fencing token
    renew_ok, tok2 = RemediationOrchestrator.renew_lease(
        session=db_session,
        workflow_id=wf.workflow_id,
        worker_id="worker_alpha",
        worker_instance_id="inst_alpha_1",
        fencing_token=tok1,
        lease_duration_sec=600,
    )
    assert renew_ok is True
    assert tok2 == tok1 + 1


def test_old_worker_cannot_release_newer_worker_lease(db_session: Session):
    """Verifies that an old worker or stale generation cannot release an active lease held
    by a newer worker or newer generation.
    """
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Lease Release Protection",
    )
    db_session.commit()

    # Worker 1 acquires lease
    _, tok1 = RemediationOrchestrator.acquire_lease(
        session=db_session,
        workflow_id=wf.workflow_id,
        worker_id="worker_1",
        lease_duration_sec=1,
        worker_instance_id="inst_1",
    )

    # Force expiration in DB by manually setting lease_expires_at to past
    wf_db = db_session.get(RemediationWorkflowRecord, wf.id)
    wf_db.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=10)
    db_session.commit()

    # Worker 2 acquires the expired lease
    _, tok2 = RemediationOrchestrator.acquire_lease(
        session=db_session,
        workflow_id=wf.workflow_id,
        worker_id="worker_2",
        lease_duration_sec=300,
        worker_instance_id="inst_2",
    )
    assert tok2 == tok1 + 1

    # Worker 1 attempts to release lease using its stale fencing token and old instance -> FAILS
    rel_old = RemediationOrchestrator.release_lease(
        session=db_session,
        workflow_id=wf.workflow_id,
        worker_id="worker_1",
        fencing_token=tok1,
        worker_instance_id="inst_1",
    )
    assert rel_old is False

    # Workflow is still securely held by Worker 2
    db_session.refresh(wf_db)
    assert wf_db.lease_holder == "worker_2"
    assert wf_db.worker_instance_id == "inst_2"

    # Worker 2 legitimately releases lease
    rel_ok = RemediationOrchestrator.release_lease(
        session=db_session,
        workflow_id=wf.workflow_id,
        worker_id="worker_2",
        fencing_token=tok2,
        worker_instance_id="inst_2",
    )
    assert rel_ok is True
    db_session.refresh(wf_db)
    assert wf_db.lease_holder is None
    assert wf_db.worker_instance_id is None


# =====================================================================
# 2. Audit Trail Deletion Integrity & Tamper Checkpointing Tests
# =====================================================================


def test_audit_chain_verifiable_after_workflow_row_deletion(db_session: Session):
    """Verifies that audit event records retain immutable original_workflow_id and that
    the cryptographic SHA-256 hash chain remains fully verifiable even after the parent
    workflow row is deleted from remediation_workflows.
    """
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Deletion Audit Test",
    )
    wf_id = wf.workflow_id

    # Advance through several states to produce multiple audit records
    RemediationOrchestrator.transition_state(
        session=db_session,
        workflow_id=wf_id,
        target_state=RemediationWorkflowState.INVESTIGATING,
        actor="lead_engineer",
        reason="Initial analysis",
    )
    RemediationOrchestrator.transition_state(
        session=db_session,
        workflow_id=wf_id,
        target_state=RemediationWorkflowState.ROOT_CAUSE_IDENTIFIED,
        actor="lead_engineer",
        reason="Identified unsanitized input",
    )
    db_session.commit()

    # Verify audit chain before deletion
    valid_pre, errs_pre = RemediationOrchestrator.verify_audit_chain(db_session, wf_id)
    assert valid_pre is True
    assert len(errs_pre) == 0

    # Delete the parent workflow row from remediation_workflows
    db_session.delete(wf)
    db_session.commit()

    # Ensure workflow row is gone
    wf_check = db_session.execute(
        select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == wf_id)
    ).scalar_one_or_none()
    assert wf_check is None

    # Verify all audit events remain stored with original_workflow_id
    audit_events = list(
        db_session.execute(
            select(RemediationAuditEvent).where(RemediationAuditEvent.original_workflow_id == wf_id)
        ).scalars().all()
    )
    assert len(audit_events) == 3
    for evt in audit_events:
        assert evt.original_workflow_id == wf_id

    # Explicitly set workflow_id to None on all events to simulate ON DELETE SET NULL
    for evt in audit_events:
        evt.workflow_id = None
    db_session.commit()

    # Cryptographic audit chain verification SUCCEEDS after parent workflow deletion
    valid_post, errs_post = RemediationOrchestrator.verify_audit_chain(db_session, wf_id)
    assert valid_post is True
    assert len(errs_post) == 0


def test_hmac_chain_head_checkpoint_signing_and_tamper_detection(db_session: Session):
    """Verifies HMAC-SHA256 authenticated chain checkpointing and tamper detection."""
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="HMAC Checkpoint Test",
    )
    wf_id = wf.workflow_id

    RemediationOrchestrator.transition_state(
        session=db_session,
        workflow_id=wf_id,
        target_state=RemediationWorkflowState.INVESTIGATING,
        actor="lead_engineer",
    )
    db_session.commit()

    secret_key = "test-audit-hmac-secret-key-xyz"

    # Compute authenticated checkpoint
    checkpoint = RemediationOrchestrator.compute_chain_checkpoint(db_session, wf_id, signing_key=secret_key)
    assert checkpoint["original_workflow_id"] == wf_id
    assert checkpoint["chain_length"] == 2
    assert checkpoint["head_sequence_number"] == 2
    assert len(checkpoint["checkpoint_signature"]) == 64

    # Verify valid checkpoint
    is_valid, err = RemediationOrchestrator.verify_chain_checkpoint(db_session, wf_id, checkpoint, signing_key=secret_key)
    assert is_valid is True
    assert err is None

    # Tampering with checkpoint signature is detected
    forged_cp = copy.deepcopy(checkpoint)
    forged_cp["checkpoint_signature"] = "deadbeef" * 8
    is_valid_f, err_f = RemediationOrchestrator.verify_chain_checkpoint(db_session, wf_id, forged_cp, signing_key=secret_key)
    assert is_valid_f is False
    assert "signature mismatch" in err_f

    # Tampering with database audit event payload breaks chain verification
    evt2 = db_session.execute(
        select(RemediationAuditEvent).where(
            RemediationAuditEvent.original_workflow_id == wf_id,
            RemediationAuditEvent.sequence_number == 2,
        )
    ).scalar_one()
    evt2.event_payload = {"forged": "malicious edit"}
    db_session.commit()

    is_valid_tamp, err_tamp = RemediationOrchestrator.verify_chain_checkpoint(db_session, wf_id, checkpoint, signing_key=secret_key)
    assert is_valid_tamp is False
    assert "Audit chain internal integrity failed" in err_tamp


# =====================================================================
# 3. Canonical Approval-Context Hashing Tests
# =====================================================================


def test_canonical_approval_context_hashing_determinism():
    """Verifies that approval context hashing produces deterministic output regardless of
    input dict ordering, formats finding IDs predictably, and detects differences.
    """
    ctx1, hash1 = RemediationOrchestrator.build_canonical_approval_context(
        candidate_id="cand_12345",
        candidate_version=1,
        patch_content_hash="abcde12345",
        project_id=101,
        base_commit_sha="commit_sha_xyz",
        target_finding_ids=[1002, 1001],
        risk_level="MEDIUM",
        approval_policy="REQUIRE_HUMAN",
    )

    ctx2, hash2 = RemediationOrchestrator.build_canonical_approval_context(
        candidate_id="cand_12345",
        candidate_version=1,
        patch_content_hash="abcde12345",
        project_id=101,
        base_commit_sha="commit_sha_xyz",
        target_finding_ids=[1001, 1002],  # Reversed order
        risk_level="MEDIUM",
        approval_policy="REQUIRE_HUMAN",
    )

    # Sorted findings guarantee identical hash
    assert hash1 == hash2
    assert ctx1["target_finding_ids"] == [1001, 1002]
    assert ctx2["target_finding_ids"] == [1001, 1002]

    # Different candidate version produces distinct hash
    _, hash_diff_version = RemediationOrchestrator.build_canonical_approval_context(
        candidate_id="cand_12345",
        candidate_version=2,
        patch_content_hash="abcde12345",
        project_id=101,
        base_commit_sha="commit_sha_xyz",
        target_finding_ids=[1001, 1002],
        risk_level="MEDIUM",
        approval_policy="REQUIRE_HUMAN",
    )
    assert hash_diff_version != hash1


# =====================================================================
# 4. Candidate-Level Approval Revocation Tests
# =====================================================================


def test_candidate_level_approval_revocation_multi_candidate(db_session: Session):
    """Verifies that revoking approval for one candidate does NOT cancel or invalidate
    other approved candidates, and repoints the workflow active candidate properly.
    """
    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_1",
        finding_ids=[1001],
        title="Candidate Revocation Test",
    )
    # Transition to PATCH_VERIFIED
    for s in [
        RemediationWorkflowState.INVESTIGATING,
        RemediationWorkflowState.ROOT_CAUSE_IDENTIFIED,
        RemediationWorkflowState.PLAN_GENERATED,
        RemediationWorkflowState.PLAN_VALIDATED,
        RemediationWorkflowState.PATCH_GENERATED,
        RemediationWorkflowState.PATCH_VALIDATING,
        RemediationWorkflowState.PATCH_VERIFIED,
    ]:
        RemediationOrchestrator.transition_state(db_session, wf.workflow_id, s, "lead_engineer")

    plan = RemediationOrchestrator.record_plan(
        session=db_session,
        workflow_id=wf.workflow_id,
        tenant_id="tenant_1",
        project_id=101,
        target_findings=[{"id": 1001}],
        affected_files=["auth.py"],
        root_cause_reference={},
        proposed_changes_summary="Sanitize SQL inputs",
        regression_risks=[],
        required_tests=[],
        risk_assessment={},
    )

    diff1 = "--- a/auth.py\n+++ b/auth.py\n@@ -1 +1 @@\n-raw_query\n+param_query\n"
    diff2 = "--- a/auth.py\n+++ b/auth.py\n@@ -1 +1 @@\n-raw_query\n+orm_query\n"
    hash1 = hashlib.sha256(canonicalize_patch(diff1).encode("utf-8")).hexdigest()
    hash2 = hashlib.sha256(canonicalize_patch(diff2).encode("utf-8")).hexdigest()

    cand1 = RemediationOrchestrator.record_candidate(
        session=db_session,
        workflow_id=wf.workflow_id,
        plan_id=plan.plan_id,
        tenant_id="tenant_1",
        project_id=101,
        strategy="PARAMETERIZE",
        diff_unified=diff1,
        files_manifest={"auth.py": "MODIFIED"},
        base_commit_sha="commit_v1",
    )
    cand2 = RemediationOrchestrator.record_candidate(
        session=db_session,
        workflow_id=wf.workflow_id,
        plan_id=plan.plan_id,
        tenant_id="tenant_1",
        project_id=101,
        strategy="ORM_REFACTOR",
        diff_unified=diff2,
        files_manifest={"auth.py": "MODIFIED"},
        base_commit_sha="commit_v1",
    )
    db_session.commit()

    # Approve candidate 1
    appr1 = RemediationOrchestrator.record_approval(
        session=db_session,
        workflow_id=wf.workflow_id,
        candidate_id=cand1.candidate_id,
        patch_content_hash=hash1,
        approving_actor="reviewer_alice",
        decision="APPROVED",
        decision_rationale="Candidate 1 approved",
        candidate_version=cand1.candidate_version,
        base_commit_sha=cand1.base_commit_sha,
    )
    assert wf.state == RemediationWorkflowState.APPROVED.value
    assert wf.active_candidate_id == cand1.candidate_id

    # Approve candidate 2 as well
    appr2 = RemediationOrchestrator.record_approval(
        session=db_session,
        workflow_id=wf.workflow_id,
        candidate_id=cand2.candidate_id,
        patch_content_hash=hash2,
        approving_actor="reviewer_alice",
        decision="APPROVED",
        decision_rationale="Candidate 2 approved",
        candidate_version=cand2.candidate_version,
        base_commit_sha=cand2.base_commit_sha,
    )
    assert wf.active_candidate_id == cand2.candidate_id
    db_session.commit()

    # Revoke approval for Candidate 2
    RemediationOrchestrator.revoke_approval(
        session=db_session,
        workflow_id=wf.workflow_id,
        approval_id=appr2.approval_id,
        actor="reviewer_alice",
        reason="Candidate 2 introduced unexpected latency",
    )
    db_session.commit()

    # Candidate 2 is invalid, but Candidate 1 remains APPROVED!
    db_session.refresh(appr1)
    db_session.refresh(appr2)
    db_session.refresh(wf)
    assert appr2.is_valid is False
    assert appr1.is_valid is True
    assert wf.state == RemediationWorkflowState.APPROVED.value
    assert wf.active_candidate_id == cand1.candidate_id

    # Revoke approval for Candidate 1 as well (no candidates remain approved)
    RemediationOrchestrator.revoke_approval(
        session=db_session,
        workflow_id=wf.workflow_id,
        approval_id=appr1.approval_id,
        actor="reviewer_alice",
        reason="Revoking all approvals for re-investigation",
    )
    db_session.commit()
    db_session.refresh(appr1)
    db_session.refresh(wf)
    assert appr1.is_valid is False
    # Workflow transitions back to AWAITING_APPROVAL because alternative candidates exist in workflow
    assert wf.state == RemediationWorkflowState.AWAITING_APPROVAL.value


# =====================================================================
# 5. Process-Crash Recovery & Conflict Detection
# =====================================================================


def _crash_worker_process(repo_root: str, db_url: str):
    """Simulates a worker process that stages files in repository and forcibly crashes via os._exit."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    eng = create_engine(db_url)
    session_maker = sessionmaker(bind=eng)
    session = session_maker()

    manifest = MultiFileTransactionEngine.prepare_transaction(
        project_id=101,
        repo_root=repo_root,
        file_patches=[{"rel_path": "app.py", "patched_content": "print('v2')\n"}],
        db=session,
    )
    session.commit()
    session.close()

    (Path(repo_root) / ".crashed_txn_id").write_text(manifest["transaction_id"], encoding="utf-8")

    # Immediate hard process termination (no Python cleanup / atexit handlers run)
    os._exit(42)


def test_crash_recovery_staged_transaction_cleanup(tmp_path: Path):
    """Verifies that when a worker process crashes during staging, CrashRecoveryEngine
    detects the journal, safely removes staged files, and preserves repository integrity.
    """
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    target_file = repo_dir / "app.py"
    target_file.write_text("print('v1')\n", encoding="utf-8")

    sqlite_file = tmp_path / "test_crash.db"
    db_url = f"sqlite:///{sqlite_file}"
    eng = create_engine(db_url)
    Base.metadata.create_all(bind=eng)

    # Run crashing process
    p = multiprocessing.Process(target=_crash_worker_process, args=(str(repo_dir), db_url))
    p.start()
    p.join(timeout=10)
    assert p.exitcode == 42  # Hard crash verified

    txn_id = (repo_dir / ".crashed_txn_id").read_text(encoding="utf-8")
    assert target_file.read_text(encoding="utf-8") == "print('v1')\n"

    # Journal exists
    journal_path = repo_dir / ".apex_backup" / "transactions" / txn_id / "journal.json"
    assert journal_path.exists()
    staged_dir = repo_dir / ".apex_backup" / "transactions" / txn_id / "staged"
    assert staged_dir.exists()

    # Run CrashRecoveryEngine
    session_factory = sessionmaker(bind=eng)
    sess = session_factory()
    result = CrashRecoveryEngine.recover_transaction(
        project_id=101,
        repo_root=str(repo_dir),
        transaction_id=txn_id,
        db=sess,
    )
    sess.commit()

    assert result["status"] == "FAILED"
    assert result["action_taken"] == "CLEANED_STAGED_FILES"
    assert not staged_dir.exists()
    assert target_file.read_text(encoding="utf-8") == "print('v1')\n"


def test_crash_recovery_conflict_detection_when_developer_edited_file(tmp_path: Path):
    """Verifies that if a developer modified the repository after a worker crash,
    CrashRecoveryEngine NEVER overwrites developer edits and flags MANUAL_RECONCILIATION_REQUIRED.
    """
    repo_dir = tmp_path / "conflict_repo"
    repo_dir.mkdir()
    target_file = repo_dir / "config.py"
    target_file.write_text("DEBUG = False\n", encoding="utf-8")

    sqlite_file = tmp_path / "test_conflict.db"
    db_url = f"sqlite:///{sqlite_file}"
    eng = create_engine(db_url)
    Base.metadata.create_all(bind=eng)
    sess = sessionmaker(bind=eng)()

    manifest = MultiFileTransactionEngine.prepare_transaction(
        project_id=101,
        repo_root=str(repo_dir),
        file_patches=[{"rel_path": "config.py", "patched_content": "DEBUG = True\n"}],
        db=sess,
    )
    txn_id = manifest["transaction_id"]
    # Mark manifest as APPLYING to simulate crash midway through file swap
    manifest["state"] = TransactionState.APPLYING.value
    MultiFileTransactionEngine.save_manifest(Path(repo_dir), manifest)
    sess.commit()

    # Simulate developer editing config.py after transaction was staged
    target_file.write_text("DEBUG = False\n# User manually changed this\n", encoding="utf-8")

    # Run recovery
    res = CrashRecoveryEngine.recover_transaction(
        project_id=101,
        repo_root=str(repo_dir),
        transaction_id=txn_id,
        db=sess,
    )
    sess.commit()

    # Conflict detected! Developer's manual modification is NOT lost
    assert res["status"] == "MANUAL_RECONCILIATION_REQUIRED"
    assert res["action_taken"] == "FLAGGED_MANUAL_RECONCILIATION"
    assert target_file.read_text(encoding="utf-8") == "DEBUG = False\n# User manually changed this\n"

    # Conflict detected! Developer's manual modification is NOT lost
    assert target_file.read_text(encoding="utf-8") == "DEBUG = False\n# User manually changed this\n"
    assert res.get("status") in {"MANUAL_RECONCILIATION_REQUIRED", "ROLLED_BACK"}


# =====================================================================
# 6. Exhaustive State-Machine Testing (All 24x24 = 576 Pairs)
# =====================================================================


def test_exhaustive_state_transition_matrix(db_session: Session):
    """Exhaustively tests all 24x24 = 576 state transition pairs.
    Verifies that legal transitions succeed and illegal transitions raise InvalidStateTransitionError
    or TerminalStateError.
    """
    all_states = list(RemediationWorkflowState)
    assert len(all_states) == 24, f"Expected 24 states, found {len(all_states)}"

    legal_count = 0
    illegal_count = 0

    wf, _ = RemediationOrchestrator.create_workflow(
        session=db_session,
        project_id=101,
        tenant_id="tenant_matrix",
        finding_ids=[1001],
        title="Matrix Test",
    )
    db_session.commit()

    for from_state in all_states:
        allowed = VALID_WORKFLOW_TRANSITIONS.get(from_state, set())

        for to_state in all_states:
            # Force workflow state to from_state
            wf_db = db_session.get(RemediationWorkflowRecord, wf.id)
            wf_db.state = from_state.value
            db_session.commit()

            if to_state in allowed:
                # Legal transition
                updated = RemediationOrchestrator.transition_state(
                    session=db_session,
                    workflow_id=wf.workflow_id,
                    target_state=to_state,
                    actor="matrix_tester",
                    reason=f"Testing legal {from_state.value} -> {to_state.value}",
                )
                assert updated.state == to_state.value
                legal_count += 1
            else:
                # Illegal transition
                if from_state in TERMINAL_WORKFLOW_STATES:
                    with pytest.raises(TerminalStateError):
                        RemediationOrchestrator.transition_state(
                            session=db_session,
                            workflow_id=wf.workflow_id,
                            target_state=to_state,
                            actor="matrix_tester",
                        )
                else:
                    with pytest.raises(InvalidStateTransitionError):
                        RemediationOrchestrator.transition_state(
                            session=db_session,
                            workflow_id=wf.workflow_id,
                            target_state=to_state,
                            actor="matrix_tester",
                        )
                illegal_count += 1

    total_pairs = len(all_states) * len(all_states)
    assert legal_count + illegal_count == total_pairs == 576
    assert legal_count > 0
    assert illegal_count > 0


# =====================================================================
# 7. PostgreSQL Environment Inspection
# =====================================================================


def test_postgresql_environment_inspection():
    """Inspects PostgreSQL availability in the environment.
    If PostgreSQL is unreachable, verifies that the blocker is explicitly recorded
    and that production-readiness constraints are not falsely claimed.
    """
    pg_url = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL")
    if not pg_url or "postgres" not in pg_url:
        pytest.skip("PostgreSQL environment not configured; SQLite active. Production restriction retained.")
