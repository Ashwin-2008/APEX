from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.entities import (
    ProjectFinding,
    ProjectReview,
    RemediationApprovalRecord,
    RemediationAuditEvent,
    RemediationCandidateRecord,
    RemediationClusterFinding,
    RemediationFindingClusterRecord,
    RemediationOutboxEvent,
    RemediationPlanRecord,
    RemediationRootCauseHypothesisRecord,
    RemediationVerificationRecord,
    RemediationWorkflowFinding,
    RemediationWorkflowRecord,
    ReviewedProject,
    User,
)
from app.services.remediation.crash_recovery import CrashRecoveryEngine
from app.services.remediation.root_cause_engine import RootCauseEngine
from app.services.remediation.strategy_planner import StrategyPlanner

logger = logging.getLogger(__name__)


# =====================================================================
# 1. State Machine Enums & Transition Maps
# =====================================================================


class RemediationWorkflowState(str, Enum):
    DISCOVERED = "DISCOVERED"
    INVESTIGATING = "INVESTIGATING"
    ROOT_CAUSE_IDENTIFIED = "ROOT_CAUSE_IDENTIFIED"
    PLAN_GENERATED = "PLAN_GENERATED"
    PLAN_VALIDATED = "PLAN_VALIDATED"
    PATCH_GENERATED = "PATCH_GENERATED"
    PATCH_VALIDATING = "PATCH_VALIDATING"
    PATCH_VERIFIED = "PATCH_VERIFIED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    APPLYING = "APPLYING"
    APPLIED = "APPLIED"
    POST_ANALYSIS = "POST_ANALYSIS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    ROLLED_BACK = "ROLLED_BACK"
    NEEDS_HUMAN_INTERVENTION = "NEEDS_HUMAN_INTERVENTION"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    RETRY_PENDING = "RETRY_PENDING"
    TIMED_OUT = "TIMED_OUT"
    MANUAL_RECONCILIATION_REQUIRED = "MANUAL_RECONCILIATION_REQUIRED"


TERMINAL_WORKFLOW_STATES: set[RemediationWorkflowState] = {
    RemediationWorkflowState.COMPLETED,
    RemediationWorkflowState.REJECTED,
    RemediationWorkflowState.CANCELLED,
}

VALID_WORKFLOW_TRANSITIONS: dict[RemediationWorkflowState, set[RemediationWorkflowState]] = {
    RemediationWorkflowState.DISCOVERED: {
        RemediationWorkflowState.INVESTIGATING,
        RemediationWorkflowState.REJECTED,
        RemediationWorkflowState.CANCEL_REQUESTED,
        RemediationWorkflowState.CANCELLED,
    },
    RemediationWorkflowState.INVESTIGATING: {
        RemediationWorkflowState.ROOT_CAUSE_IDENTIFIED,
        RemediationWorkflowState.FAILED,
        RemediationWorkflowState.TIMED_OUT,
        RemediationWorkflowState.CANCEL_REQUESTED,
        RemediationWorkflowState.NEEDS_HUMAN_INTERVENTION,
    },
    RemediationWorkflowState.ROOT_CAUSE_IDENTIFIED: {
        RemediationWorkflowState.PLAN_GENERATED,
        RemediationWorkflowState.FAILED,
        RemediationWorkflowState.CANCEL_REQUESTED,
        RemediationWorkflowState.NEEDS_HUMAN_INTERVENTION,
    },
    RemediationWorkflowState.PLAN_GENERATED: {
        RemediationWorkflowState.PLAN_VALIDATED,
        RemediationWorkflowState.FAILED,
        RemediationWorkflowState.REJECTED,
        RemediationWorkflowState.CANCEL_REQUESTED,
    },
    RemediationWorkflowState.PLAN_VALIDATED: {
        RemediationWorkflowState.PATCH_GENERATED,
        RemediationWorkflowState.FAILED,
        RemediationWorkflowState.REJECTED,
        RemediationWorkflowState.CANCEL_REQUESTED,
        RemediationWorkflowState.NEEDS_HUMAN_INTERVENTION,
    },
    RemediationWorkflowState.PATCH_GENERATED: {
        RemediationWorkflowState.PATCH_VALIDATING,
        RemediationWorkflowState.FAILED,
        RemediationWorkflowState.CANCEL_REQUESTED,
    },
    RemediationWorkflowState.PATCH_VALIDATING: {
        RemediationWorkflowState.PATCH_VERIFIED,
        RemediationWorkflowState.FAILED,
        RemediationWorkflowState.TIMED_OUT,
        RemediationWorkflowState.CANCEL_REQUESTED,
        RemediationWorkflowState.NEEDS_HUMAN_INTERVENTION,
    },
    RemediationWorkflowState.PATCH_VERIFIED: {
        RemediationWorkflowState.AWAITING_APPROVAL,
        RemediationWorkflowState.APPROVED,
        RemediationWorkflowState.REJECTED,
        RemediationWorkflowState.CANCEL_REQUESTED,
    },
    RemediationWorkflowState.AWAITING_APPROVAL: {
        RemediationWorkflowState.APPROVED,
        RemediationWorkflowState.REJECTED,
        RemediationWorkflowState.CANCEL_REQUESTED,
        RemediationWorkflowState.NEEDS_HUMAN_INTERVENTION,
    },
    RemediationWorkflowState.APPROVED: {
        RemediationWorkflowState.APPLYING,
        RemediationWorkflowState.REJECTED,
        RemediationWorkflowState.CANCEL_REQUESTED,
        RemediationWorkflowState.AWAITING_APPROVAL,
    },
    RemediationWorkflowState.APPLYING: {
        RemediationWorkflowState.APPLIED,
        RemediationWorkflowState.ROLLBACK_PENDING,
        RemediationWorkflowState.FAILED,
        RemediationWorkflowState.MANUAL_RECONCILIATION_REQUIRED,
        RemediationWorkflowState.TIMED_OUT,
    },
    RemediationWorkflowState.APPLIED: {
        RemediationWorkflowState.POST_ANALYSIS,
        RemediationWorkflowState.ROLLBACK_PENDING,
        RemediationWorkflowState.MANUAL_RECONCILIATION_REQUIRED,
    },
    RemediationWorkflowState.POST_ANALYSIS: {
        RemediationWorkflowState.COMPLETED,
        RemediationWorkflowState.ROLLBACK_PENDING,
        RemediationWorkflowState.NEEDS_HUMAN_INTERVENTION,
    },
    RemediationWorkflowState.ROLLBACK_PENDING: {
        RemediationWorkflowState.ROLLED_BACK,
        RemediationWorkflowState.MANUAL_RECONCILIATION_REQUIRED,
        RemediationWorkflowState.FAILED,
    },
    RemediationWorkflowState.ROLLED_BACK: {
        RemediationWorkflowState.COMPLETED,
        RemediationWorkflowState.FAILED,
        RemediationWorkflowState.NEEDS_HUMAN_INTERVENTION,
        RemediationWorkflowState.RETRY_PENDING,
    },
    RemediationWorkflowState.CANCEL_REQUESTED: {
        RemediationWorkflowState.CANCELLED,
        RemediationWorkflowState.ROLLBACK_PENDING,
        RemediationWorkflowState.NEEDS_HUMAN_INTERVENTION,
    },
    RemediationWorkflowState.RETRY_PENDING: {
        RemediationWorkflowState.INVESTIGATING,
        RemediationWorkflowState.PLAN_GENERATED,
        RemediationWorkflowState.PATCH_GENERATED,
        RemediationWorkflowState.PATCH_VALIDATING,
        RemediationWorkflowState.FAILED,
    },
    RemediationWorkflowState.TIMED_OUT: {
        RemediationWorkflowState.RETRY_PENDING,
        RemediationWorkflowState.FAILED,
        RemediationWorkflowState.NEEDS_HUMAN_INTERVENTION,
    },
    RemediationWorkflowState.FAILED: {
        RemediationWorkflowState.RETRY_PENDING,
        RemediationWorkflowState.NEEDS_HUMAN_INTERVENTION,
        RemediationWorkflowState.MANUAL_RECONCILIATION_REQUIRED,
    },
    RemediationWorkflowState.NEEDS_HUMAN_INTERVENTION: {
        RemediationWorkflowState.INVESTIGATING,
        RemediationWorkflowState.ROLLBACK_PENDING,
        RemediationWorkflowState.REJECTED,
        RemediationWorkflowState.CANCELLED,
        RemediationWorkflowState.MANUAL_RECONCILIATION_REQUIRED,
    },
    RemediationWorkflowState.MANUAL_RECONCILIATION_REQUIRED: {
        RemediationWorkflowState.COMPLETED,
        RemediationWorkflowState.ROLLED_BACK,
        RemediationWorkflowState.REJECTED,
    },
    RemediationWorkflowState.COMPLETED: set(),
    RemediationWorkflowState.REJECTED: set(),
    RemediationWorkflowState.CANCELLED: set(),
}


# =====================================================================
# 2. Exceptions
# =====================================================================


class InvalidStateTransitionError(Exception):
    """Raised when an illegal workflow state transition is attempted."""

    def __init__(self, from_state: str, to_state: str, workflow_id: str, message: str = ""):
        self.from_state = from_state
        self.to_state = to_state
        self.workflow_id = workflow_id
        self.message = message or f"Illegal transition from '{from_state}' to '{to_state}' for workflow '{workflow_id}'"
        super().__init__(self.message)


class TerminalStateError(InvalidStateTransitionError):
    """Raised when an attempt is made to transition out of a terminal state."""
    pass


class ConcurrencyConflictError(Exception):
    """Raised when an optimistic concurrency conflict occurs."""

    def __init__(self, workflow_id: str, expected_version: int, actual_version: int, message: str = ""):
        self.workflow_id = workflow_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        self.message = message or f"Optimistic concurrency conflict on workflow '{workflow_id}': expected v{expected_version}, found v{actual_version}"
        super().__init__(self.message)


class ApprovalValidationError(Exception):
    """Raised when approval validation fails (e.g. content hash mismatch, tier violation)."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class LeaseFencingError(Exception):
    """Raised when a worker attempts to advance a workflow without valid lease or fencing token."""

    def __init__(self, workflow_id: str, message: str):
        super().__init__(message)
        self.workflow_id = workflow_id
        self.message = message


# =====================================================================
# 3. Helper Functions
# =====================================================================


def sanitize_payload(payload: Any) -> Any:
    """Recursively redacts sensitive credentials, tokens, secrets, and private keys."""
    if isinstance(payload, dict):
        sanitized = {}
        sensitive_keywords = {"token", "secret", "password", "key", "authorization", "credential", "auth"}
        for k, v in payload.items():
            k_lower = str(k).lower()
            if any(sens in k_lower for sens in sensitive_keywords):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_payload(v)
        return sanitized
    elif isinstance(payload, list):
        return [sanitize_payload(item) for item in payload]
    return payload


def canonicalize_patch(diff_content: str) -> str:
    """Normalizes a patch/diff string to a deterministic canonical representation.

    1. Normalizes CRLF / CR line endings to LF.
    2. Strips trailing whitespace on each line.
    3. Ensures a single trailing newline.
    """
    lines = [line.rstrip() for line in diff_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


# =====================================================================
# 4. Durable Remediation Orchestrator Engine
# =====================================================================


class RemediationOrchestrator:
    """Core orchestration engine managing durable remediation workflows, state transitions,
    atomic distributed leases, monotonic fencing tokens, crash recovery, and audit trails.
    """

    @classmethod
    def _record_audit_event(
        cls,
        session: Session,
        workflow_id: str,
        project_id: int,
        tenant_id: str,
        from_state: str | None,
        to_state: str,
        action: str,
        actor: str,
        event_payload: dict[str, Any] | None = None,
    ) -> RemediationAuditEvent:
        """Records an immutable, cryptographically chained audit event with concurrency retry safety."""
        sanitized = sanitize_payload(event_payload or {})
        orig_wf_id = str(workflow_id)

        for attempt in range(5):
            last_event = session.execute(
                select(RemediationAuditEvent)
                .where(
                    or_(
                        RemediationAuditEvent.original_workflow_id == orig_wf_id,
                        RemediationAuditEvent.workflow_id == orig_wf_id,
                    )
                )
                .order_by(RemediationAuditEvent.sequence_number.desc())
                .limit(1)
            ).scalar_one_or_none()

            sequence_number = (last_event.sequence_number + 1) if last_event else 1
            prev_hash = last_event.event_hash if last_event else "GENESIS"

            raw_payload_str = json.dumps(sanitized, sort_keys=True)
            hash_input = f"{prev_hash}|{sequence_number}|{orig_wf_id}|{project_id}|{tenant_id}|{from_state}|{to_state}|{action}|{actor}|{raw_payload_str}"
            event_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

            event_id = f"evt_{uuid.uuid4().hex[:16]}"
            audit_evt = RemediationAuditEvent(
                event_id=event_id,
                workflow_id=workflow_id,
                original_workflow_id=orig_wf_id,
                tenant_id=tenant_id,
                project_id=project_id,
                sequence_number=sequence_number,
                prev_event_hash=prev_hash,
                event_hash=event_hash,
                from_state=from_state,
                to_state=to_state,
                action=action,
                actor=actor,
                event_payload=sanitized,
            )
            savepoint = session.begin_nested()
            try:
                session.add(audit_evt)
                session.flush()
                savepoint.commit()
                return audit_evt
            except Exception:
                savepoint.rollback()
                if attempt == 4:
                    raise

        raise RuntimeError(f"Failed to record audit event for workflow '{workflow_id}' after 5 attempts.")

    @classmethod
    def verify_audit_chain(cls, session: Session, workflow_id: str) -> tuple[bool, list[str]]:
        """Validates the cryptographic tamper-evident event chain for a workflow.

        Survives parent workflow record deletion via immutable original_workflow_id.
        """
        events = list(
            session.execute(
                select(RemediationAuditEvent)
                .where(
                    or_(
                        RemediationAuditEvent.original_workflow_id == workflow_id,
                        RemediationAuditEvent.workflow_id == workflow_id,
                    )
                )
                .order_by(RemediationAuditEvent.sequence_number.asc())
            ).scalars().all()
        )
        if not events:
            return True, []

        errors = []
        expected_prev = "GENESIS"
        for idx, evt in enumerate(events):
            expected_seq = idx + 1
            if evt.sequence_number != expected_seq:
                errors.append(f"Event {evt.event_id} sequence gap: expected {expected_seq}, found {evt.sequence_number}")

            if evt.prev_event_hash != expected_prev:
                errors.append(f"Event {evt.event_id} broken chain: expected prev {expected_prev}, found {evt.prev_event_hash}")

            raw_payload_str = json.dumps(evt.event_payload, sort_keys=True)
            wf_id_for_hash = evt.original_workflow_id or evt.workflow_id or ""
            hash_input = f"{evt.prev_event_hash}|{evt.sequence_number}|{wf_id_for_hash}|{evt.project_id}|{evt.tenant_id}|{evt.from_state}|{evt.to_state}|{evt.action}|{evt.actor}|{raw_payload_str}"
            recalculated = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
            if recalculated != evt.event_hash:
                errors.append(f"Event {evt.event_id} hash mismatch: computed {recalculated}, stored {evt.event_hash}")

            expected_prev = evt.event_hash

        return len(errors) == 0, errors

    @classmethod
    def compute_chain_checkpoint(
        cls,
        session: Session,
        workflow_id: str,
        signing_key: str | bytes | None = None,
    ) -> dict[str, Any]:
        """Computes an HMAC-SHA256 authenticated checkpoint over the current chain-head."""
        key = signing_key or os.environ.get("MISTIQ_AUDIT_SIGNING_KEY", "mistiq-remediation-audit-hmac-secret-v1")
        if isinstance(key, str):
            key = key.encode("utf-8")

        events = list(
            session.execute(
                select(RemediationAuditEvent)
                .where(
                    or_(
                        RemediationAuditEvent.original_workflow_id == workflow_id,
                        RemediationAuditEvent.workflow_id == workflow_id,
                    )
                )
                .order_by(RemediationAuditEvent.sequence_number.asc())
            ).scalars().all()
        )

        chain_length = len(events)
        head_event = events[-1] if events else None
        head_event_id = head_event.event_id if head_event else None
        head_event_hash = head_event.event_hash if head_event else "GENESIS"
        head_seq = head_event.sequence_number if head_event else 0

        checkpoint_ts = datetime.now(timezone.utc).isoformat()
        msg = f"{workflow_id}|{head_seq}|{head_event_hash}|{chain_length}".encode("utf-8")
        signature = hmac.new(key, msg, hashlib.sha256).hexdigest()

        return {
            "original_workflow_id": workflow_id,
            "chain_length": chain_length,
            "head_event_id": head_event_id,
            "head_event_hash": head_event_hash,
            "head_sequence_number": head_seq,
            "checkpoint_timestamp": checkpoint_ts,
            "checkpoint_signature": signature,
        }

    @classmethod
    def verify_chain_checkpoint(
        cls,
        session: Session,
        workflow_id: str,
        checkpoint: dict[str, Any],
        signing_key: str | bytes | None = None,
    ) -> tuple[bool, str | None]:
        """Validates that a chain checkpoint matches both the cryptographic signature and the database chain state."""
        key = signing_key or os.environ.get("MISTIQ_AUDIT_SIGNING_KEY", "mistiq-remediation-audit-hmac-secret-v1")
        if isinstance(key, str):
            key = key.encode("utf-8")

        head_seq = checkpoint.get("head_sequence_number", 0)
        head_hash = checkpoint.get("head_event_hash", "GENESIS")
        chain_len = checkpoint.get("chain_length", 0)
        expected_msg = f"{workflow_id}|{head_seq}|{head_hash}|{chain_len}".encode("utf-8")
        computed_sig = hmac.new(key, expected_msg, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed_sig, checkpoint.get("checkpoint_signature", "")):
            return False, "Checkpoint HMAC signature mismatch (forged or corrupted checkpoint)."

        events = list(
            session.execute(
                select(RemediationAuditEvent)
                .where(
                    or_(
                        RemediationAuditEvent.original_workflow_id == workflow_id,
                        RemediationAuditEvent.workflow_id == workflow_id,
                    )
                )
                .order_by(RemediationAuditEvent.sequence_number.asc())
            ).scalars().all()
        )

        if len(events) != chain_len:
            return False, f"Chain length mismatch: DB has {len(events)} events, checkpoint specified {chain_len}."

        if chain_len > 0:
            db_head = events[-1]
            if db_head.sequence_number != head_seq:
                return False, f"Head sequence mismatch: DB has {db_head.sequence_number}, checkpoint specified {head_seq}."
            if db_head.event_hash != head_hash:
                return False, f"Head hash mismatch: DB has {db_head.event_hash}, checkpoint specified {head_hash}."

        valid, chain_errs = cls.verify_audit_chain(session, workflow_id)
        if not valid:
            return False, f"Audit chain internal integrity failed: {'; '.join(chain_errs)}"

        return True, None

    @classmethod
    def build_canonical_approval_context(
        cls,
        candidate_id: str,
        candidate_version: int,
        patch_content_hash: str,
        project_id: int,
        base_commit_sha: str | None,
        target_finding_ids: list[int],
        risk_level: str,
        approval_policy: str,
        schema_version: str = "1.0",
    ) -> tuple[dict[str, Any], str]:
        """Builds a deterministic, canonical JSON representation of the approval context and its SHA-256 hash."""
        context_dict = {
            "approval_policy": str(approval_policy),
            "base_commit_sha": str(base_commit_sha or ""),
            "candidate_id": str(candidate_id),
            "candidate_version": int(candidate_version),
            "patch_content_hash": str(patch_content_hash),
            "project_id": int(project_id),
            "risk_level": str(risk_level),
            "schema_version": str(schema_version),
            "target_finding_ids": [int(fid) for fid in sorted(target_finding_ids)],
        }
        canonical_json = json.dumps(context_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        context_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        return context_dict, context_hash

    @classmethod
    def _verify_worker_guard(
        cls,
        workflow: RemediationWorkflowRecord,
        worker_id: str | None = None,
        fencing_token: int | None = None,
        worker_instance_id: str | None = None,
    ) -> None:
        """Validates that a mutating worker possesses an active, unexpired lease and matching fencing token."""
        now = datetime.now(timezone.utc)
        now_naive = now.replace(tzinfo=None)

        if workflow.lease_holder is not None:
            if workflow.lease_expires_at and workflow.lease_expires_at < now_naive:
                raise LeaseFencingError(
                    workflow_id=workflow.workflow_id,
                    message=f"Worker lease expired at {workflow.lease_expires_at.isoformat()}.",
                )

            if worker_id is None or fencing_token is None:
                raise LeaseFencingError(
                    workflow_id=workflow.workflow_id,
                    message=f"Workflow '{workflow.workflow_id}' is actively held by worker '{workflow.lease_holder}'. Mutations require worker credentials and fencing token.",
                )

            if workflow.lease_holder != worker_id:
                raise LeaseFencingError(
                    workflow_id=workflow.workflow_id,
                    message=f"Worker '{worker_id}' does not own lease; currently held by '{workflow.lease_holder}'.",
                )

            if worker_instance_id is not None and workflow.worker_instance_id is not None:
                if workflow.worker_instance_id != worker_instance_id:
                    raise LeaseFencingError(
                        workflow_id=workflow.workflow_id,
                        message=f"Worker instance '{worker_instance_id}' does not own lease; currently held by '{workflow.worker_instance_id}'.",
                    )

            if workflow.fencing_token != fencing_token:
                raise LeaseFencingError(
                    workflow_id=workflow.workflow_id,
                    message=f"Stale fencing token: expected {workflow.fencing_token}, received {fencing_token}.",
                )
        else:
            if fencing_token is not None and workflow.fencing_token != fencing_token:
                raise LeaseFencingError(
                    workflow_id=workflow.workflow_id,
                    message=f"Stale fencing token: expected {workflow.fencing_token}, received {fencing_token}.",
                )

    @classmethod
    def create_workflow(
        cls,
        session: Session,
        project_id: int,
        tenant_id: str,
        finding_ids: list[int],
        title: str,
        description: str | None = None,
        risk_level: str = "MEDIUM",
        approval_policy: str = "REQUIRE_HUMAN",
        idempotency_key: str | None = None,
        actor: str = "system",
    ) -> tuple[RemediationWorkflowRecord, bool]:
        """Creates a new durable remediation workflow with idempotency and multi-finding binding.

        Returns:
            (workflow_record, is_duplicate)
        """
        # 1. Verify project ownership and tenant boundary
        project = session.get(ReviewedProject, project_id)
        if not project:
            raise ValueError(f"Project with ID {project_id} does not exist.")

        # 2. Derive stable idempotency key if not provided
        if not idempotency_key:
            sorted_f_ids = "-".join(map(str, sorted(finding_ids)))
            raw_key = f"{tenant_id}:{project_id}:{sorted_f_ids}:{title}"
            idempotency_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:32]

        # 3. Check for existing workflow under this idempotency key
        existing = session.execute(
            select(RemediationWorkflowRecord).where(
                and_(
                    RemediationWorkflowRecord.tenant_id == tenant_id,
                    RemediationWorkflowRecord.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()

        if existing:
            return existing, True

        # 4. Verify all findings exist AND belong to the authorized project
        for fid in finding_ids:
            f_record = session.get(ProjectFinding, fid)
            if not f_record:
                raise ValueError(f"Finding with ID {fid} does not exist.")
            review = session.get(ProjectReview, f_record.review_id)
            if not review or review.project_id != project_id:
                raise ValueError(f"Finding with ID {fid} does not belong to project {project_id}.")

        # 5. Create durable workflow
        wf_id = f"wf_{uuid.uuid4().hex[:16]}"
        workflow = RemediationWorkflowRecord(
            workflow_id=wf_id,
            project_id=project_id,
            tenant_id=tenant_id,
            state=RemediationWorkflowState.DISCOVERED.value,
            risk_level=risk_level,
            approval_policy=approval_policy,
            idempotency_key=idempotency_key,
            title=title,
            description=description,
            version_id=1,
            retry_count=0,
            max_retries=3,
            fencing_token=0,
        )
        session.add(workflow)
        session.flush()

        # 6. Bind findings
        for fid in finding_ids:
            session.add(
                RemediationWorkflowFinding(
                    workflow_id=wf_id,
                    finding_id=fid,
                )
            )

        # 7. Record durable chained audit event
        cls._record_audit_event(
            session=session,
            workflow_id=wf_id,
            project_id=project_id,
            tenant_id=tenant_id,
            from_state=None,
            to_state=RemediationWorkflowState.DISCOVERED.value,
            action="WORKFLOW_CREATED",
            actor=actor,
            event_payload={"finding_ids": finding_ids, "risk_level": risk_level, "idempotency_key": idempotency_key},
        )

        # 8. Record durable outbox event
        outbox_evt = RemediationOutboxEvent(
            event_id=f"ob_{uuid.uuid4().hex[:16]}",
            workflow_id=wf_id,
            tenant_id=tenant_id,
            event_type="workflow.created",
            payload={"workflow_id": wf_id, "project_id": project_id, "state": "DISCOVERED"},
            status="PENDING",
        )
        session.add(outbox_evt)

        session.flush()
        return workflow, False

    @classmethod
    def get_workflow(
        cls,
        session: Session,
        workflow_id: str,
        tenant_id: str | None = None,
    ) -> RemediationWorkflowRecord | None:
        """Retrieves a workflow by ID, enforcing tenant isolation if tenant_id is supplied."""
        stmt = select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id)
        if tenant_id:
            stmt = stmt.where(RemediationWorkflowRecord.tenant_id == tenant_id)
        return session.execute(stmt).scalar_one_or_none()

    @classmethod
    def list_workflows(
        cls,
        session: Session,
        project_id: int,
        tenant_id: str,
        skip: int = 0,
        limit: int = 50,
        state: str | None = None,
    ) -> list[RemediationWorkflowRecord]:
        """Lists workflows for a project and tenant with optional state filtering and pagination."""
        stmt = select(RemediationWorkflowRecord).where(
            and_(
                RemediationWorkflowRecord.project_id == project_id,
                RemediationWorkflowRecord.tenant_id == tenant_id,
            )
        )
        if state:
            stmt = stmt.where(RemediationWorkflowRecord.state == state)
        stmt = stmt.order_by(RemediationWorkflowRecord.created_at.desc()).offset(skip).limit(limit)
        return list(session.execute(stmt).scalars().all())

    @classmethod
    def transition_state(
        cls,
        session: Session,
        workflow_id: str,
        target_state: RemediationWorkflowState | str,
        actor: str,
        reason: str = "",
        payload: dict[str, Any] | None = None,
        expected_version: int | None = None,
        worker_id: str | None = None,
        fencing_token: int | None = None,
        worker_instance_id: str | None = None,
    ) -> RemediationWorkflowRecord:
        """Validates and applies a state transition with optimistic concurrency and audit logging."""
        workflow = session.execute(
            select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id)
        ).scalar_one_or_none()

        if not workflow:
            raise ValueError(f"Workflow '{workflow_id}' not found.")

        # Convert string to enum for verification
        target_enum = (
            target_state
            if isinstance(target_state, RemediationWorkflowState)
            else RemediationWorkflowState(target_state)
        )
        current_enum = RemediationWorkflowState(workflow.state)

        # 1. Terminal state protection: terminal states can NEVER transition to anything
        if current_enum in TERMINAL_WORKFLOW_STATES:
            raise TerminalStateError(
                from_state=current_enum.value,
                to_state=target_enum.value,
                workflow_id=workflow_id,
                message=f"Terminal state protection: Workflow '{workflow_id}' is in terminal state '{current_enum.value}' and cannot be transitioned.",
            )

        # 2. Transition validation map check
        allowed = VALID_WORKFLOW_TRANSITIONS.get(current_enum, set())
        if target_enum not in allowed:
            raise InvalidStateTransitionError(
                from_state=current_enum.value,
                to_state=target_enum.value,
                workflow_id=workflow_id,
                message=f"Illegal transition from '{current_enum.value}' to '{target_enum.value}' for workflow '{workflow_id}'. Allowed: {[s.value for s in allowed]}",
            )

        # 3. Optimistic concurrency check
        if expected_version is not None and workflow.version_id != expected_version:
            raise ConcurrencyConflictError(
                workflow_id=workflow_id,
                expected_version=expected_version,
                actual_version=workflow.version_id,
            )

        # 4. Fencing token and worker lease check
        cls._verify_worker_guard(workflow, worker_id, fencing_token, worker_instance_id=worker_instance_id)

        # 5. Apply state update
        from_state = workflow.state
        workflow.state = target_enum.value
        workflow.version_id += 1
        if reason:
            workflow.error_message = reason if target_enum in {RemediationWorkflowState.FAILED, RemediationWorkflowState.TIMED_OUT, RemediationWorkflowState.MANUAL_RECONCILIATION_REQUIRED} else workflow.error_message

        # 6. Insert durable chained audit event
        audit_payload: dict[str, Any] = {"reason": reason, "details": payload or {}, "version_id": workflow.version_id, "fencing_token": workflow.fencing_token}
        if worker_instance_id:
            audit_payload["worker_instance_id"] = worker_instance_id
        cls._record_audit_event(
            session=session,
            workflow_id=workflow_id,
            project_id=workflow.project_id,
            tenant_id=workflow.tenant_id,
            from_state=from_state,
            to_state=target_enum.value,
            action=f"TRANSITION_{target_enum.value}",
            actor=actor,
            event_payload=audit_payload,
        )

        # 7. Insert durable outbox event
        outbox_evt = RemediationOutboxEvent(
            event_id=f"ob_{uuid.uuid4().hex[:16]}",
            workflow_id=workflow_id,
            tenant_id=workflow.tenant_id,
            event_type=f"workflow.{target_enum.value.lower()}",
            payload={"workflow_id": workflow_id, "from_state": from_state, "to_state": target_enum.value, "version_id": workflow.version_id},
            status="PENDING",
        )
        session.add(outbox_evt)

        session.flush()
        return workflow

    @classmethod
    def acquire_lease(
        cls,
        session: Session,
        workflow_id: str,
        worker_id: str,
        lease_duration_sec: int = 300,
        worker_instance_id: str | None = None,
    ) -> tuple[bool, int | None]:
        """Acquires a worker lease atomically using an atomic database update.

        Guarantees:
        - Atomic conditional acquisition against database authoritative time (func.now()).
        - Strictly forbids stealing an active lease even if worker_id matches (renewal must use renew_lease).
        - Generates or binds unique worker_instance_id.
        - Atomically increments fencing_token upon successful acquisition.
        """
        instance_id = worker_instance_id or f"{worker_id}:{uuid.uuid4().hex[:8]}"
        now_utc = datetime.now(timezone.utc)
        lease_expiry = (now_utc + timedelta(seconds=lease_duration_sec)).replace(tzinfo=None)

        # Atomic conditional update across database transactions:
        # Acquisition is strictly allowed ONLY when no lease is held OR lease has expired under DB clock (func.now())
        stmt = (
            update(RemediationWorkflowRecord)
            .where(
                RemediationWorkflowRecord.workflow_id == workflow_id,
                or_(
                    RemediationWorkflowRecord.lease_expires_at.is_(None),
                    RemediationWorkflowRecord.lease_expires_at < func.now(),
                ),
            )
            .values(
                lease_holder=worker_id,
                worker_instance_id=instance_id,
                lease_expires_at=lease_expiry,
                fencing_token=RemediationWorkflowRecord.fencing_token + 1,
                version_id=RemediationWorkflowRecord.version_id + 1,
            )
        )
        result = session.execute(stmt)
        if result.rowcount == 0:
            return False, None

        session.flush()

        # Re-read workflow to get the assigned fencing token and emit audit event
        workflow = session.execute(
            select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id)
        ).scalar_one()

        cls._record_audit_event(
            session=session,
            workflow_id=workflow_id,
            project_id=workflow.project_id,
            tenant_id=workflow.tenant_id,
            from_state=workflow.state,
            to_state=workflow.state,
            action="LEASE_ACQUIRED",
            actor=worker_id,
            event_payload={
                "worker_id": worker_id,
                "worker_instance_id": instance_id,
                "fencing_token": workflow.fencing_token,
                "lease_expires_at": lease_expiry.isoformat(),
                "lease_duration_sec": lease_duration_sec,
            },
        )
        session.flush()
        return True, workflow.fencing_token

    @classmethod
    def renew_lease(
        cls,
        session: Session,
        workflow_id: str,
        worker_id: str,
        worker_instance_id: str,
        fencing_token: int,
        lease_duration_sec: int = 300,
    ) -> tuple[bool, int | None]:
        """Explicitly renews an active lease held by worker_instance_id with matching fencing token.

        Guarantees:
        - Completely decoupled from lease acquisition.
        - Fails if the lease has expired under database clock (func.now()).
        - Validates both worker_id and worker_instance_id.
        - Increments fencing_token upon renewal to protect monotonic generation ordering.
        """
        now_utc = datetime.now(timezone.utc)
        new_expiry = (now_utc + timedelta(seconds=lease_duration_sec)).replace(tzinfo=None)

        stmt = (
            update(RemediationWorkflowRecord)
            .where(
                RemediationWorkflowRecord.workflow_id == workflow_id,
                RemediationWorkflowRecord.lease_holder == worker_id,
                RemediationWorkflowRecord.worker_instance_id == worker_instance_id,
                RemediationWorkflowRecord.fencing_token == fencing_token,
                RemediationWorkflowRecord.lease_expires_at >= func.now(),
            )
            .values(
                lease_expires_at=new_expiry,
                fencing_token=RemediationWorkflowRecord.fencing_token + 1,
                version_id=RemediationWorkflowRecord.version_id + 1,
            )
        )
        res = session.execute(stmt)
        if res.rowcount == 0:
            return False, None

        session.flush()

        workflow = session.execute(
            select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id)
        ).scalar_one()

        cls._record_audit_event(
            session=session,
            workflow_id=workflow_id,
            project_id=workflow.project_id,
            tenant_id=workflow.tenant_id,
            from_state=workflow.state,
            to_state=workflow.state,
            action="LEASE_RENEWED",
            actor=worker_id,
            event_payload={
                "worker_id": worker_id,
                "worker_instance_id": worker_instance_id,
                "fencing_token": workflow.fencing_token,
                "lease_expires_at": new_expiry.isoformat(),
            },
        )
        session.flush()
        return True, workflow.fencing_token

    @classmethod
    def release_lease(
        cls,
        session: Session,
        workflow_id: str,
        worker_id: str,
        fencing_token: int,
        worker_instance_id: str | None = None,
    ) -> bool:
        """Releases the lease if worker_id, fencing_token, and worker_instance_id match the current generation.

        Never releases a lock owned by a newer fencing generation or another worker instance.
        """
        stmt = (
            update(RemediationWorkflowRecord)
            .where(
                RemediationWorkflowRecord.workflow_id == workflow_id,
                RemediationWorkflowRecord.lease_holder == worker_id,
                RemediationWorkflowRecord.fencing_token == fencing_token,
            )
        )
        if worker_instance_id is not None:
            stmt = stmt.where(
                or_(
                    RemediationWorkflowRecord.worker_instance_id.is_(None),
                    RemediationWorkflowRecord.worker_instance_id == worker_instance_id,
                )
            )

        stmt = stmt.values(
            lease_holder=None,
            worker_instance_id=None,
            lease_expires_at=None,
            version_id=RemediationWorkflowRecord.version_id + 1,
        )
        result = session.execute(stmt)
        if result.rowcount == 0:
            return False

        session.flush()
        workflow = session.execute(
            select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id)
        ).scalar_one_or_none()
        if workflow:
            cls._record_audit_event(
                session=session,
                workflow_id=workflow_id,
                project_id=workflow.project_id,
                tenant_id=workflow.tenant_id,
                from_state=workflow.state,
                to_state=workflow.state,
                action="LEASE_RELEASED",
                actor=worker_id,
                event_payload={"fencing_token": fencing_token, "worker_instance_id": worker_instance_id},
            )
            session.flush()
        return True

    @classmethod
    def record_plan(
        cls,
        session: Session,
        workflow_id: str,
        tenant_id: str,
        project_id: int,
        target_findings: list[dict[str, Any]],
        affected_files: list[str],
        root_cause_reference: dict[str, Any],
        proposed_changes_summary: str,
        regression_risks: list[str],
        required_tests: list[str],
        risk_assessment: dict[str, Any],
        actor: str = "planning_engine",
        worker_id: str | None = None,
        fencing_token: int | None = None,
    ) -> RemediationPlanRecord:
        """Persists a generated remediation plan and binds it to the workflow."""
        workflow = session.execute(
            select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id)
        ).scalar_one_or_none()
        if not workflow:
            raise ValueError(f"Workflow '{workflow_id}' not found.")

        cls._verify_worker_guard(workflow, worker_id, fencing_token)

        plan_id = f"plan_{uuid.uuid4().hex[:16]}"
        plan = RemediationPlanRecord(
            plan_id=plan_id,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            project_id=project_id,
            target_findings=target_findings,
            affected_files=affected_files,
            root_cause_reference=root_cause_reference,
            proposed_changes_summary=proposed_changes_summary,
            regression_risks=regression_risks,
            required_tests=required_tests,
            risk_assessment=risk_assessment,
        )
        session.add(plan)
        workflow.active_plan_id = plan_id

        cls._record_audit_event(
            session=session,
            workflow_id=workflow_id,
            project_id=project_id,
            tenant_id=tenant_id,
            from_state=workflow.state,
            to_state=workflow.state,
            action="PLAN_RECORDED",
            actor=actor,
            event_payload={"plan_id": plan_id, "affected_files": affected_files},
        )

        session.flush()
        return plan

    @classmethod
    def investigate_root_causes(
        cls,
        session: Session,
        workflow_id: str,
        actor: str = "orchestrator",
        worker_id: str | None = None,
        fencing_token: int | None = None,
        worker_instance_id: str | None = None,
        repo_root: Path | None = None,
    ) -> dict[str, Any]:
        """Runs multi-source evidence aggregation and root cause hypothesis synthesis."""
        workflow = session.execute(
            select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id)
        ).scalar_one_or_none()
        if not workflow:
            raise ValueError(f"Workflow '{workflow_id}' not found.")

        # If in DISCOVERED, move to INVESTIGATING
        if workflow.state == RemediationWorkflowState.DISCOVERED.value:
            cls.transition_state(
                session=session,
                workflow_id=workflow_id,
                target_state=RemediationWorkflowState.INVESTIGATING,
                actor=actor,
                reason="Initiating root cause investigation across 12 evidence sources",
                worker_id=worker_id,
                fencing_token=fencing_token,
                worker_instance_id=worker_instance_id,
            )

        # Execute investigation
        inv_result = RootCauseEngine.investigate_workflow(session, workflow_id, repo_root=repo_root)

        # Transition to ROOT_CAUSE_IDENTIFIED
        if workflow.state == RemediationWorkflowState.INVESTIGATING.value:
            cls.transition_state(
                session=session,
                workflow_id=workflow_id,
                target_state=RemediationWorkflowState.ROOT_CAUSE_IDENTIFIED,
                actor=actor,
                reason="Root cause investigation completed and hypotheses formulated",
                payload={
                    "hypotheses_count": len(inv_result.get("hypotheses", [])),
                    "clusters_count": len(inv_result.get("clusters", [])),
                },
                worker_id=worker_id,
                fencing_token=fencing_token,
                worker_instance_id=worker_instance_id,
            )

        return inv_result

    @classmethod
    def generate_remediation_plans(
        cls,
        session: Session,
        workflow_id: str,
        actor: str = "orchestrator",
        worker_id: str | None = None,
        fencing_token: int | None = None,
        worker_instance_id: str | None = None,
        repo_root: Path | None = None,
    ) -> list[RemediationPlanRecord]:
        """Synthesizes alternative repair strategies and evaluates 11-dimension scoring model."""
        workflow = session.execute(
            select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id)
        ).scalar_one_or_none()
        if not workflow:
            raise ValueError(f"Workflow '{workflow_id}' not found.")

        # If in ROOT_CAUSE_IDENTIFIED, transition to PLAN_GENERATED
        if workflow.state == RemediationWorkflowState.ROOT_CAUSE_IDENTIFIED.value:
            cls.transition_state(
                session=session,
                workflow_id=workflow_id,
                target_state=RemediationWorkflowState.PLAN_GENERATED,
                actor=actor,
                reason="Generating multi-strategy remediation plans",
                worker_id=worker_id,
                fencing_token=fencing_token,
                worker_instance_id=worker_instance_id,
            )

        plans = StrategyPlanner.generate_plans_for_workflow(session, workflow_id, repo_root=repo_root)

        # Transition to PLAN_VALIDATED
        if workflow.state == RemediationWorkflowState.PLAN_GENERATED.value:
            cls.transition_state(
                session=session,
                workflow_id=workflow_id,
                target_state=RemediationWorkflowState.PLAN_VALIDATED,
                actor=actor,
                reason="Remediation plans validated against blast radius and risk baselines",
                payload={"plans_count": len(plans), "active_plan_id": workflow.active_plan_id},
                worker_id=worker_id,
                fencing_token=fencing_token,
                worker_instance_id=worker_instance_id,
            )

        return plans

    @classmethod
    def select_preferred_plan(
        cls,
        session: Session,
        workflow_id: str,
        plan_id: str,
        actor: str = "orchestrator",
        worker_id: str | None = None,
        fencing_token: int | None = None,
        worker_instance_id: str | None = None,
    ) -> RemediationPlanRecord:
        """Selects preferred remediation plan and drafts candidate patch strictly labeled UNVERIFIED."""
        workflow = session.execute(
            select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id)
        ).scalar_one_or_none()
        if not workflow:
            raise ValueError(f"Workflow '{workflow_id}' not found.")

        cls._verify_worker_guard(workflow, worker_id, fencing_token)

        all_plans = list(
            session.scalars(
                select(RemediationPlanRecord).where(RemediationPlanRecord.workflow_id == workflow_id)
            ).all()
        )
        target_plan: RemediationPlanRecord | None = None
        for p in all_plans:
            if p.plan_id == plan_id:
                p.is_preferred = True
                target_plan = p
            else:
                p.is_preferred = False

        if not target_plan:
            raise ValueError(f"Plan '{plan_id}' not found in workflow '{workflow_id}'.")

        workflow.active_plan_id = plan_id

        # Transition to PATCH_GENERATED if in PLAN_VALIDATED
        if workflow.state == RemediationWorkflowState.PLAN_VALIDATED.value:
            cls.transition_state(
                session=session,
                workflow_id=workflow_id,
                target_state=RemediationWorkflowState.PATCH_GENERATED,
                actor=actor,
                reason=f"Selected plan '{plan_id}' ({target_plan.strategy_name}) and generated unverified candidate patch",
                worker_id=worker_id,
                fencing_token=fencing_token,
                worker_instance_id=worker_instance_id,
            )

        # Synthesize Candidate Record labeled UNVERIFIED
        preview_diff = (target_plan.risk_assessment or {}).get("candidate_patch_preview", "")
        if not preview_diff:
            preview_diff = (
                "# ====================================================================\n"
                "# UNVERIFIED — AWAITING PHASE 5.3 VALIDATION\n"
                "# ====================================================================\n"
                f"# Strategy: {target_plan.strategy_name}\n"
                f"# Summary: {target_plan.proposed_changes_summary}\n"
            )

        manifest = {f: {"status": "unverified_modification"} for f in target_plan.affected_files}
        cls.record_candidate(
            session=session,
            workflow_id=workflow_id,
            plan_id=plan_id,
            tenant_id=workflow.tenant_id,
            project_id=workflow.project_id,
            strategy=target_plan.strategy_name,
            diff_unified=preview_diff,
            files_manifest=manifest,
            actor=actor,
            candidate_version=1,
            worker_id=worker_id,
            fencing_token=fencing_token,
        )

        session.flush()
        return target_plan

    @classmethod
    def record_candidate(
        cls,
        session: Session,
        workflow_id: str,
        plan_id: str,
        tenant_id: str,
        project_id: int,
        strategy: str,
        diff_unified: str,
        files_manifest: dict[str, Any],
        actor: str = "patch_generator",
        candidate_version: int = 1,
        base_commit_sha: str | None = None,
        worker_id: str | None = None,
        fencing_token: int | None = None,
    ) -> RemediationCandidateRecord:
        """Persists a synthesized patch candidate and computes its deterministic content hash."""
        workflow = session.execute(
            select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id)
        ).scalar_one_or_none()
        if not workflow:
            raise ValueError(f"Workflow '{workflow_id}' not found.")

        cls._verify_worker_guard(workflow, worker_id, fencing_token)

        candidate_id = f"cand_{uuid.uuid4().hex[:16]}"
        canonical_diff = canonicalize_patch(diff_unified)
        content_hash = hashlib.sha256(canonical_diff.encode("utf-8")).hexdigest()

        candidate = RemediationCandidateRecord(
            candidate_id=candidate_id,
            workflow_id=workflow_id,
            plan_id=plan_id,
            tenant_id=tenant_id,
            project_id=project_id,
            strategy=strategy,
            diff_unified=canonical_diff,
            diff_hash=content_hash,
            files_manifest=files_manifest,
            lifecycle_state="GENERATED",
            candidate_version=candidate_version,
            base_commit_sha=base_commit_sha,
        )
        session.add(candidate)
        workflow.active_candidate_id = candidate_id

        cls._record_audit_event(
            session=session,
            workflow_id=workflow_id,
            project_id=project_id,
            tenant_id=tenant_id,
            from_state=workflow.state,
            to_state=workflow.state,
            action="CANDIDATE_RECORDED",
            actor=actor,
            event_payload={
                "candidate_id": candidate_id,
                "strategy": strategy,
                "diff_hash": content_hash,
                "candidate_version": candidate_version,
            },
        )

        session.flush()
        return candidate

    @classmethod
    def record_verification(
        cls,
        session: Session,
        workflow_id: str,
        candidate_id: str,
        tenant_id: str,
        status: str,
        stages_executed: list[str],
        stage_results: dict[str, Any],
        regressions_detected: list[str],
        tests_passed: int = 0,
        tests_failed: int = 0,
        actor: str = "verification_engine",
        worker_id: str | None = None,
        fencing_token: int | None = None,
    ) -> RemediationVerificationRecord:
        """Persists a multi-stage verification report for a candidate patch."""
        workflow = session.execute(
            select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id)
        ).scalar_one_or_none()
        if not workflow:
            raise ValueError(f"Workflow '{workflow_id}' not found.")

        cls._verify_worker_guard(workflow, worker_id, fencing_token)

        v_id = f"ver_{uuid.uuid4().hex[:16]}"
        v_record = RemediationVerificationRecord(
            verification_id=v_id,
            candidate_id=candidate_id,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            status=status,
            stages_executed=stages_executed,
            stage_results=stage_results,
            regressions_detected=regressions_detected,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
        )
        session.add(v_record)

        cand = session.execute(
            select(RemediationCandidateRecord).where(RemediationCandidateRecord.candidate_id == candidate_id)
        ).scalar_one_or_none()
        if cand:
            cand.lifecycle_state = "VERIFIED" if status == "VERIFIED" else "VERIFICATION_FAILED"

        cls._record_audit_event(
            session=session,
            workflow_id=workflow_id,
            project_id=workflow.project_id,
            tenant_id=tenant_id,
            from_state=workflow.state,
            to_state=workflow.state,
            action="VERIFICATION_RECORDED",
            actor=actor,
            event_payload={
                "verification_id": v_id,
                "candidate_id": candidate_id,
                "status": status,
                "tests_passed": tests_passed,
                "tests_failed": tests_failed,
            },
        )

        session.flush()
        return v_record

    @classmethod
    def record_approval(
        cls,
        session: Session,
        workflow_id: str,
        candidate_id: str,
        patch_content_hash: str,
        approving_actor: str,
        decision: str,  # "APPROVED" or "REJECTED"
        decision_rationale: str,
        risk_classification: str | None = None,
        approval_policy: str | None = None,
        approver_user: User | None = None,
        candidate_version: int | None = None,
        base_commit_sha: str | None = None,
        actor_is_admin: bool = False,
    ) -> RemediationApprovalRecord:
        """Validates patch content integrity and records an immutable approval/rejection decision.

        Hardened Safety Controls:
        1. Canonicalizes patch diff and validates exact sha256 match.
        2. Validates candidate version binding.
        3. Validates base commit repository revision binding.
        4. Enforces server-side approval tier authorization.
        5. Computes cryptographic approval context hash binding candidate, version, diff hash, findings, policy, tier.
        6. Invalidates any prior approval records upon update.
        """
        candidate = session.execute(
            select(RemediationCandidateRecord).where(RemediationCandidateRecord.candidate_id == candidate_id)
        ).scalar_one_or_none()
        if not candidate:
            raise ApprovalValidationError(f"Candidate patch '{candidate_id}' not found.")

        if candidate.workflow_id != workflow_id:
            raise ApprovalValidationError(f"Candidate '{candidate_id}' does not belong to workflow '{workflow_id}'.")

        # 1. Canonical patch hash validation
        canonical_diff = canonicalize_patch(candidate.diff_unified)
        expected_hash = hashlib.sha256(canonical_diff.encode("utf-8")).hexdigest()
        if expected_hash != patch_content_hash or candidate.diff_hash != patch_content_hash:
            raise ApprovalValidationError(
                f"Patch content hash mismatch for candidate '{candidate_id}': "
                f"expected {candidate.diff_hash}, provided {patch_content_hash}. "
                "The patch content was modified after the approval hash was formed."
            )

        # 2. Candidate version check
        if candidate_version is not None and candidate.candidate_version != candidate_version:
            raise ApprovalValidationError(
                f"Candidate version mismatch: candidate is v{candidate.candidate_version}, "
                f"approval requested for v{candidate_version}."
            )

        # 3. Base commit SHA check
        if base_commit_sha is not None and candidate.base_commit_sha is not None:
            if candidate.base_commit_sha != base_commit_sha:
                raise ApprovalValidationError(
                    f"Base commit SHA mismatch: candidate was synthesized against {candidate.base_commit_sha}, "
                    f"target repository is at {base_commit_sha}."
                )

        if decision not in {"APPROVED", "REJECTED"}:
            raise ApprovalValidationError(f"Invalid decision '{decision}'. Must be 'APPROVED' or 'REJECTED'.")

        workflow = session.execute(
            select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id)
        ).scalar_one_or_none()
        if not workflow:
            raise ApprovalValidationError(f"Workflow '{workflow_id}' not found.")

        # 4. Server-side approval policy authorization
        is_admin = actor_is_admin or (approver_user is not None and getattr(approver_user, "is_superuser", False))

        if workflow.approval_policy == "ADMIN_REQUIRED" or workflow.risk_level == "CRITICAL":
            if not is_admin:
                raise ApprovalValidationError("Insufficient approval tier: Administrator authorization required.")

        if workflow.approval_policy == "DUAL_HUMAN":
            init_event = session.execute(
                select(RemediationAuditEvent).where(
                    RemediationAuditEvent.workflow_id == workflow_id,
                    RemediationAuditEvent.action == "WORKFLOW_CREATED",
                )
            ).scalar_one_or_none()
            if init_event and init_event.actor == approving_actor:
                raise ApprovalValidationError("DUAL_HUMAN policy violation: Workflow initiator cannot approve their own remediation workflow.")

        # 5. Invalidate previous approval records for this candidate
        for prev_appr in candidate.approvals:
            prev_appr.is_valid = False

        # 6. Retrieve target findings for immutable context binding
        findings = list(
            session.execute(
                select(RemediationWorkflowFinding.finding_id).where(
                    RemediationWorkflowFinding.workflow_id == workflow_id
                )
            ).scalars().all()
        )
        sorted_findings = sorted(findings)

        # 7. Compute cryptographic approval context hash using canonical JSON representation
        _, approval_context_hash = cls.build_canonical_approval_context(
            candidate_id=candidate_id,
            candidate_version=candidate.candidate_version,
            patch_content_hash=patch_content_hash,
            project_id=workflow.project_id,
            base_commit_sha=candidate.base_commit_sha,
            target_finding_ids=sorted_findings,
            risk_level=workflow.risk_level,
            approval_policy=workflow.approval_policy,
        )

        # 8. Create approval record
        approval_id = f"appr_{uuid.uuid4().hex[:16]}"
        approval = RemediationApprovalRecord(
            approval_id=approval_id,
            workflow_id=workflow_id,
            candidate_id=candidate_id,
            candidate_version=candidate.candidate_version,
            base_commit_sha=candidate.base_commit_sha,
            patch_content_hash=patch_content_hash,
            target_finding_ids=sorted_findings,
            approval_context_hash=approval_context_hash,
            tenant_id=workflow.tenant_id,
            project_id=workflow.project_id,
            approving_actor=approving_actor,
            decision=decision,
            risk_classification=workflow.risk_level,
            approval_policy=workflow.approval_policy,
            decision_rationale=decision_rationale,
            is_valid=True,
        )
        session.add(approval)

        if decision == "APPROVED":
            workflow.active_candidate_id = candidate_id

        # 9. Advance workflow state if not already in target state
        target_state = RemediationWorkflowState.APPROVED if decision == "APPROVED" else RemediationWorkflowState.REJECTED
        if workflow.state != target_state.value:
            cls.transition_state(
                session=session,
                workflow_id=workflow_id,
                target_state=target_state,
                actor=approving_actor,
                reason=f"Approval decision: {decision} by {approving_actor}. Rationale: {decision_rationale}",
                payload={
                    "approval_id": approval_id,
                    "candidate_id": candidate_id,
                    "decision": decision,
                    "approval_context_hash": approval_context_hash,
                },
            )
        else:
            cls._record_audit_event(
                session=session,
                workflow_id=workflow_id,
                project_id=workflow.project_id,
                tenant_id=workflow.tenant_id,
                from_state=workflow.state,
                to_state=workflow.state,
                action="APPROVAL_RECORDED",
                actor=approving_actor,
                event_payload={
                    "approval_id": approval_id,
                    "candidate_id": candidate_id,
                    "decision": decision,
                    "approval_context_hash": approval_context_hash,
                },
            )

        session.flush()
        return approval

    @classmethod
    def revoke_approval(
        cls,
        session: Session,
        workflow_id: str,
        approval_id: str,
        actor: str,
        reason: str = "Approval revoked by authorized reviewer",
    ) -> RemediationApprovalRecord:
        """Revokes an existing approval and updates candidate-level approval status.

        Candidate-Level Revocation Guarantees:
        1. Invalidates specifically the designated approval record.
        2. Evaluates other candidates for the workflow:
           - If another approved candidate exists, repoints workflow.active_candidate_id
             to that candidate and preserves APPROVED state.
           - If other candidates exist but none are approved, transitions workflow
             state back to AWAITING_APPROVAL.
           - If no alternative candidate exists, transitions to REJECTED.
        3. Records an immutable chained audit event with candidate-level context.
        """
        approval = session.execute(
            select(RemediationApprovalRecord).where(
                RemediationApprovalRecord.approval_id == approval_id,
                RemediationApprovalRecord.workflow_id == workflow_id,
            )
        ).scalar_one_or_none()
        if not approval:
            raise ValueError(f"Approval '{approval_id}' not found for workflow '{workflow_id}'.")

        if not approval.is_valid:
            raise ValueError(f"Approval '{approval_id}' is already revoked or invalid.")

        now = datetime.now(timezone.utc)
        approval.is_valid = False
        approval.revoked_at = now.replace(tzinfo=None)
        approval.revoked_by = actor
        approval.revocation_reason = reason

        workflow = session.execute(
            select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id)
        ).scalar_one()

        # Check remaining valid approvals for other candidates in this workflow
        remaining_approvals = list(
            session.execute(
                select(RemediationApprovalRecord).where(
                    RemediationApprovalRecord.workflow_id == workflow_id,
                    RemediationApprovalRecord.approval_id != approval_id,
                    RemediationApprovalRecord.is_valid == True,
                    RemediationApprovalRecord.decision == "APPROVED",
                )
            ).scalars().all()
        )

        if remaining_approvals:
            # Another candidate remains approved! Repoint active_candidate_id to that candidate
            other_candidate_id = remaining_approvals[0].candidate_id
            workflow.active_candidate_id = other_candidate_id
        else:
            # No other candidates are approved. Check if alternative candidates exist
            all_candidates = list(
                session.execute(
                    select(RemediationCandidateRecord).where(
                        RemediationCandidateRecord.workflow_id == workflow_id
                    )
                ).scalars().all()
            )
            other_candidates = [c for c in all_candidates if c.candidate_id != approval.candidate_id]
            if other_candidates and workflow.state == RemediationWorkflowState.APPROVED.value:
                workflow.active_candidate_id = other_candidates[0].candidate_id
                cls.transition_state(
                    session=session,
                    workflow_id=workflow_id,
                    target_state=RemediationWorkflowState.AWAITING_APPROVAL,
                    actor=actor,
                    reason=f"Approval for candidate '{approval.candidate_id}' revoked; awaiting decision on remaining candidates.",
                )
            elif workflow.state == RemediationWorkflowState.APPROVED.value:
                cls.transition_state(
                    session=session,
                    workflow_id=workflow_id,
                    target_state=RemediationWorkflowState.REJECTED,
                    actor=actor,
                    reason=f"Approval revoked: {reason}",
                )

        cls._record_audit_event(
            session=session,
            workflow_id=workflow_id,
            project_id=workflow.project_id,
            tenant_id=workflow.tenant_id,
            from_state=workflow.state,
            to_state=workflow.state,
            action="APPROVAL_REVOKED",
            actor=actor,
            event_payload={
                "approval_id": approval_id,
                "candidate_id": approval.candidate_id,
                "reason": reason,
                "active_candidate_id": workflow.active_candidate_id,
            },
        )
        session.flush()
        return approval

    @classmethod
    def cancel_workflow(
        cls,
        session: Session,
        workflow_id: str,
        actor: str,
        reason: str = "User requested cancellation",
    ) -> RemediationWorkflowRecord:
        """Safely requests cancellation of an active workflow."""
        workflow = session.execute(
            select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id)
        ).scalar_one_or_none()
        if not workflow:
            raise ValueError(f"Workflow '{workflow_id}' not found.")

        current_state = RemediationWorkflowState(workflow.state)
        if current_state in TERMINAL_WORKFLOW_STATES:
            raise TerminalStateError(
                from_state=current_state.value,
                to_state=RemediationWorkflowState.CANCELLED.value,
                workflow_id=workflow_id,
                message=f"Cannot cancel workflow in terminal state '{current_state.value}'.",
            )

        # Transition to CANCEL_REQUESTED
        cls.transition_state(
            session=session,
            workflow_id=workflow_id,
            target_state=RemediationWorkflowState.CANCEL_REQUESTED,
            actor=actor,
            reason=reason,
        )

        # If not applying or in recovery, finalize to CANCELLED
        cls.transition_state(
            session=session,
            workflow_id=workflow_id,
            target_state=RemediationWorkflowState.CANCELLED,
            actor=actor,
            reason=reason,
        )

        session.flush()
        return workflow

    @classmethod
    def trigger_retry(
        cls,
        session: Session,
        workflow_id: str,
        actor: str = "retry_policy_engine",
        worker_id: str | None = None,
        fencing_token: int | None = None,
    ) -> RemediationWorkflowRecord:
        """Triggers a retry if retry_count < max_retries, else transitions to FAILED."""
        workflow = session.execute(
            select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id)
        ).scalar_one_or_none()
        if not workflow:
            raise ValueError(f"Workflow '{workflow_id}' not found.")

        if workflow.retry_count < workflow.max_retries:
            workflow.retry_count += 1
            return cls.transition_state(
                session=session,
                workflow_id=workflow_id,
                target_state=RemediationWorkflowState.RETRY_PENDING,
                actor=actor,
                reason=f"Retry attempt {workflow.retry_count} of {workflow.max_retries}",
                worker_id=worker_id,
                fencing_token=fencing_token,
            )
        else:
            return cls.transition_state(
                session=session,
                workflow_id=workflow_id,
                target_state=RemediationWorkflowState.FAILED,
                actor=actor,
                reason=f"Max retries ({workflow.max_retries}) exceeded.",
                worker_id=worker_id,
                fencing_token=fencing_token,
            )

    @classmethod
    def recover_orphaned_workflows(
        cls,
        session: Session,
        now: datetime | None = None,
    ) -> list[RemediationWorkflowRecord]:
        """Detects workflows with expired worker leases and safely reconciles them.

        Guarantees:
        - Never blindly reapplies or overwrites developer modifications.
        - Inspects filesystem transaction journals and validates hashes for APPLYING / ROLLING_BACK.
        - Flags MANUAL_RECONCILIATION_REQUIRED when transaction integrity is uncertain or conflicts occur.
        - Recovers transient analytical steps safely with retries.
        - Idempotent across multiple concurrent sweeper processes.
        """
        current_time = now or datetime.now(timezone.utc)
        current_naive = current_time.replace(tzinfo=None)

        stmt = select(RemediationWorkflowRecord).where(
            and_(
                RemediationWorkflowRecord.lease_expires_at.is_not(None),
                RemediationWorkflowRecord.lease_expires_at < current_naive,
            )
        )
        orphans = list(session.execute(stmt).scalars().all())
        recovered = []

        for wf in orphans:
            c_state = RemediationWorkflowState(wf.state)
            if c_state in TERMINAL_WORKFLOW_STATES:
                wf.lease_holder = None
                wf.lease_expires_at = None
                continue

            # Atomically claim workflow for sweeper to avoid duplicate sweeper runs
            claim_stmt = (
                update(RemediationWorkflowRecord)
                .where(
                    RemediationWorkflowRecord.workflow_id == wf.workflow_id,
                    RemediationWorkflowRecord.lease_expires_at < current_naive,
                    RemediationWorkflowRecord.version_id == wf.version_id,
                )
                .values(
                    lease_holder="crash_recovery_sweeper",
                    lease_expires_at=(current_time + timedelta(seconds=120)).replace(tzinfo=None),
                    fencing_token=RemediationWorkflowRecord.fencing_token + 1,
                    version_id=RemediationWorkflowRecord.version_id + 1,
                )
            )
            claim_res = session.execute(claim_stmt)
            if claim_res.rowcount == 0:
                continue

            session.flush()
            wf = session.execute(
                select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == wf.workflow_id)
            ).scalar_one()

            logger.warning(
                "Recovering orphaned workflow '%s' in state '%s' with expired lease.",
                wf.workflow_id,
                wf.state,
            )

            # 1. State Category: Filesystem Modification In-Flight
            if c_state in {
                RemediationWorkflowState.APPLYING,
                RemediationWorkflowState.APPLIED,
                RemediationWorkflowState.POST_ANALYSIS,
                RemediationWorkflowState.ROLLBACK_PENDING,
                RemediationWorkflowState.ROLLED_BACK,
            }:
                if wf.active_transaction_id:
                    project = session.get(ReviewedProject, wf.project_id)
                    if project and project.repository_path and Path(project.repository_path).exists():
                        txn_res = CrashRecoveryEngine.recover_transaction(
                            project_id=wf.project_id,
                            repo_root=project.repository_path,
                            transaction_id=wf.active_transaction_id,
                            db=session,
                        )
                        action = txn_res.get("action_taken")
                        txn_status = txn_res.get("status")

                        if txn_status == "MANUAL_RECONCILIATION_REQUIRED" or action == "FLAGGED_MANUAL_RECONCILIATION":
                            cls.transition_state(
                                session=session,
                                workflow_id=wf.workflow_id,
                                target_state=RemediationWorkflowState.MANUAL_RECONCILIATION_REQUIRED,
                                actor="crash_recovery_sweeper",
                                reason=f"Third-party modifications or transaction conflict: {txn_res.get('message')}",
                                payload={"conflicts": txn_res.get("conflicts", [])},
                                worker_id="crash_recovery_sweeper",
                                fencing_token=wf.fencing_token,
                            )
                        elif txn_status == "COMMITTED":
                            if c_state == RemediationWorkflowState.APPLYING:
                                cls.transition_state(
                                    session=session,
                                    workflow_id=wf.workflow_id,
                                    target_state=RemediationWorkflowState.APPLIED,
                                    actor="crash_recovery_sweeper",
                                    reason="Verified all files cleanly applied before worker crash.",
                                    worker_id="crash_recovery_sweeper",
                                    fencing_token=wf.fencing_token,
                                )
                        elif txn_status == "ROLLED_BACK" or action == "ROLLED_BACK":
                            if wf.retry_count < wf.max_retries:
                                cls.transition_state(
                                    session=session,
                                    workflow_id=wf.workflow_id,
                                    target_state=RemediationWorkflowState.TIMED_OUT,
                                    actor="crash_recovery_sweeper",
                                    reason="Transaction safely rolled back to pre-swap state.",
                                    worker_id="crash_recovery_sweeper",
                                    fencing_token=wf.fencing_token,
                                )
                                cls.trigger_retry(session, wf.workflow_id, actor="crash_recovery_sweeper", worker_id="crash_recovery_sweeper", fencing_token=wf.fencing_token)
                            else:
                                cls.transition_state(
                                    session=session,
                                    workflow_id=wf.workflow_id,
                                    target_state=RemediationWorkflowState.FAILED,
                                    actor="crash_recovery_sweeper",
                                    reason="Transaction safely rolled back and retry limit reached.",
                                    worker_id="crash_recovery_sweeper",
                                    fencing_token=wf.fencing_token,
                                )
                        elif action == "CLEANED_STAGED_FILES":
                            if wf.retry_count < wf.max_retries:
                                cls.transition_state(
                                    session=session,
                                    workflow_id=wf.workflow_id,
                                    target_state=RemediationWorkflowState.TIMED_OUT,
                                    actor="crash_recovery_sweeper",
                                    reason="Crashed before file swap; staged files cleaned.",
                                    worker_id="crash_recovery_sweeper",
                                    fencing_token=wf.fencing_token,
                                )
                                cls.trigger_retry(session, wf.workflow_id, actor="crash_recovery_sweeper", worker_id="crash_recovery_sweeper", fencing_token=wf.fencing_token)
                            else:
                                cls.transition_state(
                                    session=session,
                                    workflow_id=wf.workflow_id,
                                    target_state=RemediationWorkflowState.FAILED,
                                    actor="crash_recovery_sweeper",
                                    reason="Crashed before file swap and retry limit reached.",
                                    worker_id="crash_recovery_sweeper",
                                    fencing_token=wf.fencing_token,
                                )
                        else:
                            cls.transition_state(
                                session=session,
                                workflow_id=wf.workflow_id,
                                target_state=RemediationWorkflowState.MANUAL_RECONCILIATION_REQUIRED,
                                actor="crash_recovery_sweeper",
                                reason=f"Uncertain filesystem recovery outcome: {txn_res.get('message')}",
                                worker_id="crash_recovery_sweeper",
                                fencing_token=wf.fencing_token,
                            )
                    else:
                        cls.transition_state(
                            session=session,
                            workflow_id=wf.workflow_id,
                            target_state=RemediationWorkflowState.MANUAL_RECONCILIATION_REQUIRED,
                            actor="crash_recovery_sweeper",
                            reason="Repository path missing or inaccessible during crash recovery.",
                            worker_id="crash_recovery_sweeper",
                            fencing_token=wf.fencing_token,
                        )
                else:
                    cls.transition_state(
                        session=session,
                        workflow_id=wf.workflow_id,
                        target_state=RemediationWorkflowState.MANUAL_RECONCILIATION_REQUIRED,
                        actor="crash_recovery_sweeper",
                        reason="Worker crashed in applying state without tracked transaction ID.",
                        worker_id="crash_recovery_sweeper",
                        fencing_token=wf.fencing_token,
                    )
            # 2. State Category: Transient Analytical Steps (Safe to retry)
            elif c_state in {
                RemediationWorkflowState.INVESTIGATING,
                RemediationWorkflowState.ROOT_CAUSE_IDENTIFIED,
                RemediationWorkflowState.PLAN_GENERATED,
                RemediationWorkflowState.PLAN_VALIDATED,
                RemediationWorkflowState.PATCH_GENERATED,
                RemediationWorkflowState.PATCH_VALIDATING,
            }:
                allowed_transitions = VALID_WORKFLOW_TRANSITIONS.get(c_state, set())
                if RemediationWorkflowState.TIMED_OUT in allowed_transitions:
                    cls.transition_state(
                        session=session,
                        workflow_id=wf.workflow_id,
                        target_state=RemediationWorkflowState.TIMED_OUT,
                        actor="crash_recovery_sweeper",
                        reason=f"Worker lease expired during {wf.state}.",
                        worker_id="crash_recovery_sweeper",
                        fencing_token=wf.fencing_token,
                    )
                    if wf.retry_count < wf.max_retries:
                        cls.trigger_retry(session, wf.workflow_id, actor="crash_recovery_sweeper", worker_id="crash_recovery_sweeper", fencing_token=wf.fencing_token)
                    else:
                        cls.transition_state(
                            session=session,
                            workflow_id=wf.workflow_id,
                            target_state=RemediationWorkflowState.FAILED,
                            actor="crash_recovery_sweeper",
                            reason="Worker lease expired and retry limit reached.",
                            worker_id="crash_recovery_sweeper",
                            fencing_token=wf.fencing_token,
                        )
                else:
                    cls.transition_state(
                        session=session,
                        workflow_id=wf.workflow_id,
                        target_state=RemediationWorkflowState.FAILED,
                        actor="crash_recovery_sweeper",
                        reason=f"Worker lease expired during {wf.state}.",
                        worker_id="crash_recovery_sweeper",
                        fencing_token=wf.fencing_token,
                    )
                    if wf.retry_count < wf.max_retries:
                        cls.trigger_retry(session, wf.workflow_id, actor="crash_recovery_sweeper", worker_id="crash_recovery_sweeper", fencing_token=wf.fencing_token)
            else:
                # Other states (e.g. AWAITING_APPROVAL, NEEDS_HUMAN_INTERVENTION)
                pass

            wf.lease_holder = None
            wf.lease_expires_at = None
            recovered.append(wf)

        session.flush()
        return recovered

    @classmethod
    def process_outbox(
        cls,
        session: Session,
        worker_id: str = "outbox_processor",
        lease_duration_sec: int = 60,
        max_events: int = 50,
        deliver_fn: Callable[[RemediationOutboxEvent], bool] | None = None,
    ) -> int:
        """Processes pending outbox events with atomic claiming, lease fencing, and bounded exponential backoff."""
        now = datetime.now(timezone.utc)
        now_naive = now.replace(tzinfo=None)
        lease_expiry = (now + timedelta(seconds=lease_duration_sec)).replace(tzinfo=None)

        # 1. Identify eligible events
        stmt_eligible = (
            select(RemediationOutboxEvent.id)
            .where(
                and_(
                    or_(
                        RemediationOutboxEvent.status == "PENDING",
                        and_(
                            RemediationOutboxEvent.status == "PROCESSING",
                            RemediationOutboxEvent.locked_until < now_naive,
                        ),
                    ),
                    or_(
                        RemediationOutboxEvent.next_retry_at.is_(None),
                        RemediationOutboxEvent.next_retry_at <= now_naive,
                    ),
                )
            )
            .order_by(RemediationOutboxEvent.created_at.asc())
            .limit(max_events)
        )
        candidate_ids = list(session.execute(stmt_eligible).scalars().all())
        if not candidate_ids:
            return 0

        # 2. Atomically claim events for worker_id
        claim_stmt = (
            update(RemediationOutboxEvent)
            .where(
                RemediationOutboxEvent.id.in_(candidate_ids),
                or_(
                    RemediationOutboxEvent.status == "PENDING",
                    RemediationOutboxEvent.locked_until < now_naive,
                ),
            )
            .values(
                status="PROCESSING",
                locked_by=worker_id,
                locked_until=lease_expiry,
                attempts=RemediationOutboxEvent.attempts + 1,
            )
        )
        session.execute(claim_stmt)
        session.flush()

        # 3. Retrieve only claimed events owned by this worker
        claimed_events = list(
            session.execute(
                select(RemediationOutboxEvent).where(
                    RemediationOutboxEvent.id.in_(candidate_ids),
                    RemediationOutboxEvent.locked_by == worker_id,
                    RemediationOutboxEvent.status == "PROCESSING",
                )
            ).scalars().all()
        )

        delivered_count = 0

        for evt in claimed_events:
            success = True
            error_msg = None
            if deliver_fn:
                try:
                    success = bool(deliver_fn(evt))
                except Exception as e:
                    success = False
                    error_msg = str(e)

            if success:
                evt.status = "DELIVERED"
                evt.delivered_at = datetime.now(timezone.utc).replace(tzinfo=None)
                evt.locked_by = None
                evt.locked_until = None
                delivered_count += 1
            else:
                if evt.attempts >= evt.max_attempts:
                    evt.status = "FAILED"
                    evt.last_error = error_msg or "Max delivery attempts exceeded."
                    evt.locked_by = None
                    evt.locked_until = None
                else:
                    evt.status = "PENDING"
                    base_delay = 2 ** min(evt.attempts, 6)
                    jitter = random.uniform(0.1, 1.0)
                    evt.next_retry_at = (datetime.now(timezone.utc) + timedelta(seconds=min(300.0, base_delay + jitter))).replace(tzinfo=None)
                    evt.last_error = error_msg
                    evt.locked_by = None
                    evt.locked_until = None

            session.flush()

        return delivered_count

    @classmethod
    def replay_failed_outbox(
        cls,
        session: Session,
        event_ids: list[str] | None = None,
        workflow_id: str | None = None,
        actor: str = "system",
    ) -> int:
        """Safely replays permanently failed outbox events by resetting status to PENDING."""
        stmt = update(RemediationOutboxEvent).where(RemediationOutboxEvent.status == "FAILED")
        if event_ids:
            stmt = stmt.where(RemediationOutboxEvent.event_id.in_(event_ids))
        if workflow_id:
            stmt = stmt.where(RemediationOutboxEvent.workflow_id == workflow_id)

        stmt = stmt.values(
            status="PENDING",
            attempts=0,
            next_retry_at=None,
            last_error=None,
            locked_by=None,
            locked_until=None,
        )
        res = session.execute(stmt)
        session.flush()
        return res.rowcount
