from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_authorized_project, get_current_user, get_db
from app.models.entities import (
    RemediationApprovalRecord,
    RemediationAuditEvent,
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
from app.services.remediation.orchestrator import (
    ApprovalValidationError,
    ConcurrencyConflictError,
    InvalidStateTransitionError,
    LeaseFencingError,
    RemediationOrchestrator,
    RemediationWorkflowState,
)
from app.services.remediation.root_cause_engine import RootCauseEngine
from app.services.remediation.strategy_planner import StrategyPlanner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/remediation", tags=["remediation"])


# =====================================================================
# Request & Response Schemas
# =====================================================================


class CreateWorkflowRequest(BaseModel):
    finding_ids: list[int] = Field(..., min_length=1, description="List of project finding IDs to remediate.")
    title: str = Field(..., min_length=3, max_length=300)
    description: str | None = Field(None, max_length=2000)
    risk_level: str = Field("MEDIUM", description="LOW, MEDIUM, HIGH, CRITICAL")
    approval_policy: str = Field("REQUIRE_HUMAN", description="REQUIRE_HUMAN or DUAL_HUMAN")
    idempotency_key: str | None = Field(None, max_length=120)


class WorkflowSummaryResponse(BaseModel):
    workflow_id: str
    project_id: int
    tenant_id: str
    state: str
    risk_level: str
    approval_policy: str
    idempotency_key: str
    title: str
    description: str | None
    version_id: int
    retry_count: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class WorkflowDetailResponse(WorkflowSummaryResponse):
    finding_ids: list[int] = []
    active_plan_id: str | None = None
    active_candidate_id: str | None = None
    active_transaction_id: str | None = None
    error_message: str | None = None
    lease_holder: str | None = None
    fencing_token: int = 0


class CancelWorkflowRequest(BaseModel):
    reason: str = Field("User requested cancellation", max_length=500)


class AuditEventResponse(BaseModel):
    event_id: str
    workflow_id: str
    from_state: str | None
    to_state: str
    action: str
    actor: str
    event_payload: dict[str, Any]
    created_at: str

    model_config = {"from_attributes": True}


class CandidateResponse(BaseModel):
    candidate_id: str
    workflow_id: str
    plan_id: str
    strategy: str
    diff_unified: str
    diff_hash: str
    files_manifest: dict[str, Any]
    lifecycle_state: str
    created_at: str

    model_config = {"from_attributes": True}


class ApprovalResponse(BaseModel):
    approval_id: str
    workflow_id: str
    candidate_id: str
    patch_content_hash: str
    approving_actor: str
    decision: str
    risk_classification: str
    approval_policy: str
    decision_rationale: str
    is_valid: bool
    created_at: str

    model_config = {"from_attributes": True}


class RecordApprovalRequest(BaseModel):
    candidate_id: str = Field(..., min_length=3)
    patch_content_hash: str = Field(..., min_length=64, max_length=64)
    decision: str = Field("APPROVED", description="APPROVED or REJECTED")
    rationale: str = Field(..., min_length=5, max_length=2000)
    candidate_version: int | None = Field(None, ge=1)
    base_commit_sha: str | None = Field(None, max_length=80)


class RevokeApprovalRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500)


class AuditChainVerifyResponse(BaseModel):
    workflow_id: str
    is_valid: bool
    errors: list[str] = []


class AuditCheckpointResponse(BaseModel):
    original_workflow_id: str
    chain_length: int
    head_event_id: str | None
    head_event_hash: str
    head_sequence_number: int
    checkpoint_timestamp: str
    checkpoint_signature: str


class AuditCheckpointVerifyRequest(BaseModel):
    checkpoint: dict[str, Any]


class AuditCheckpointVerifyResponse(BaseModel):
    workflow_id: str
    is_valid: bool
    error: str | None = None


# =====================================================================
# Phase 5.2 Root Cause & Planning Schemas
# =====================================================================


class HypothesisResponse(BaseModel):
    hypothesis_id: str
    workflow_id: str
    title: str
    category: str
    explanation: str
    confidence_score: float
    status: str
    supporting_evidence: list[dict[str, Any]]
    contradicting_evidence: list[dict[str, Any]]
    affected_symbols: list[str]
    affected_files: list[str]
    evidence_completeness_score: float
    provenance: dict[str, Any] | str = {}
    created_at: str

    model_config = {"from_attributes": True}


class FindingClusterResponse(BaseModel):
    cluster_id: str
    workflow_id: str
    cluster_name: str
    primary_finding_id: int
    thematic_category: str
    correlation_rationale: str
    confidence_score: float
    is_manually_adjusted: bool
    finding_ids: list[int]
    created_at: str

    model_config = {"from_attributes": True}


class SeparateFindingRequest(BaseModel):
    finding_id: int
    reason: str = Field(..., min_length=3, max_length=500)


class PlanResponse(BaseModel):
    plan_id: str
    workflow_id: str
    strategy_name: str
    strategy_description: str | None = None
    target_findings: list[int]
    affected_files: list[str]
    root_cause_reference: dict[str, Any]
    proposed_changes_summary: str
    regression_risks: list[str]
    required_tests: list[dict[str, Any]]
    rollback_strategy: str
    risk_assessment: dict[str, Any]
    plan_score: float
    score_breakdown: dict[str, float]
    ranking_explanation: str | None = None
    approval_tier_required: str
    estimated_complexity: str
    is_preferred: bool
    abstain_reason: str | None = None
    created_at: str

    model_config = {"from_attributes": True}


class PlanCompareResponse(BaseModel):
    workflow_id: str
    plans_count: int
    comparison_matrix: list[dict[str, Any]]


# =====================================================================
# Endpoints
# =====================================================================


@router.post(
    "/workflows",
    response_model=WorkflowDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or retrieve an idempotent remediation workflow",
)
def create_remediation_workflow(
    project_id: int,
    req: CreateWorkflowRequest,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Creates a durable remediation workflow targeting one or more findings.

    Strictly isolated to the authenticated user's tenant.
    """
    tenant_id = str(current_user.id)
    try:
        workflow, is_dup = RemediationOrchestrator.create_workflow(
            session=session,
            project_id=project_id,
            tenant_id=tenant_id,
            finding_ids=req.finding_ids,
            title=req.title,
            description=req.description,
            risk_level=req.risk_level.upper(),
            approval_policy=req.approval_policy.upper(),
            idempotency_key=req.idempotency_key,
            actor=current_user.username or current_user.email,
        )
        session.commit()
    except ValueError as e:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        session.rollback()
        logger.exception("Failed to create remediation workflow: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Workflow creation failed.")

    f_ids = [wf.finding_id for wf in workflow.workflow_findings]
    return WorkflowDetailResponse(
        workflow_id=workflow.workflow_id,
        project_id=workflow.project_id,
        tenant_id=workflow.tenant_id,
        state=workflow.state,
        risk_level=workflow.risk_level,
        approval_policy=workflow.approval_policy,
        idempotency_key=workflow.idempotency_key,
        title=workflow.title,
        description=workflow.description,
        version_id=workflow.version_id,
        retry_count=workflow.retry_count,
        finding_ids=f_ids,
        active_plan_id=workflow.active_plan_id,
        active_candidate_id=workflow.active_candidate_id,
        active_transaction_id=workflow.active_transaction_id,
        error_message=workflow.error_message,
        lease_holder=workflow.lease_holder,
        fencing_token=workflow.fencing_token,
        created_at=workflow.created_at.isoformat(),
        updated_at=workflow.updated_at.isoformat(),
    )


@router.get(
    "/workflows",
    response_model=list[WorkflowSummaryResponse],
    summary="List remediation workflows for a project",
)
def list_remediation_workflows(
    project_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    state: str | None = Query(None),
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Lists remediation workflows owned by the current tenant for this project."""
    tenant_id = str(current_user.id)
    workflows = RemediationOrchestrator.list_workflows(
        session=session,
        project_id=project_id,
        tenant_id=tenant_id,
        skip=skip,
        limit=limit,
        state=state.upper() if state else None,
    )
    return [
        WorkflowSummaryResponse(
            workflow_id=w.workflow_id,
            project_id=w.project_id,
            tenant_id=w.tenant_id,
            state=w.state,
            risk_level=w.risk_level,
            approval_policy=w.approval_policy,
            idempotency_key=w.idempotency_key,
            title=w.title,
            description=w.description,
            version_id=w.version_id,
            retry_count=w.retry_count,
            created_at=w.created_at.isoformat(),
            updated_at=w.updated_at.isoformat(),
        )
        for w in workflows
    ]


@router.get(
    "/workflows/{workflow_id}",
    response_model=WorkflowDetailResponse,
    summary="Get workflow details",
)
def get_remediation_workflow_detail(
    project_id: int,
    workflow_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Retrieves full details of a remediation workflow."""
    tenant_id = str(current_user.id)
    workflow = RemediationOrchestrator.get_workflow(session, workflow_id, tenant_id=tenant_id)
    if not workflow or workflow.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Remediation workflow not found or permission denied.",
        )

    f_ids = [wf.finding_id for wf in workflow.workflow_findings]
    return WorkflowDetailResponse(
        workflow_id=workflow.workflow_id,
        project_id=workflow.project_id,
        tenant_id=workflow.tenant_id,
        state=workflow.state,
        risk_level=workflow.risk_level,
        approval_policy=workflow.approval_policy,
        idempotency_key=workflow.idempotency_key,
        title=workflow.title,
        description=workflow.description,
        version_id=workflow.version_id,
        retry_count=workflow.retry_count,
        finding_ids=f_ids,
        active_plan_id=workflow.active_plan_id,
        active_candidate_id=workflow.active_candidate_id,
        active_transaction_id=workflow.active_transaction_id,
        error_message=workflow.error_message,
        lease_holder=workflow.lease_holder,
        fencing_token=workflow.fencing_token,
        created_at=workflow.created_at.isoformat(),
        updated_at=workflow.updated_at.isoformat(),
    )


@router.post(
    "/workflows/{workflow_id}/cancel",
    response_model=WorkflowSummaryResponse,
    summary="Cancel an active remediation workflow",
)
def cancel_remediation_workflow(
    project_id: int,
    workflow_id: str,
    req: CancelWorkflowRequest,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Safely cancels an active workflow."""
    tenant_id = str(current_user.id)
    workflow = RemediationOrchestrator.get_workflow(session, workflow_id, tenant_id=tenant_id)
    if not workflow or workflow.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")

    try:
        updated = RemediationOrchestrator.cancel_workflow(
            session=session,
            workflow_id=workflow_id,
            actor=current_user.username or current_user.email,
            reason=req.reason,
        )
        session.commit()
    except InvalidStateTransitionError as e:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    except Exception as e:
        session.rollback()
        logger.exception("Cancellation failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Cancellation failed.")

    return WorkflowSummaryResponse(
        workflow_id=updated.workflow_id,
        project_id=updated.project_id,
        tenant_id=updated.tenant_id,
        state=updated.state,
        risk_level=updated.risk_level,
        approval_policy=updated.approval_policy,
        idempotency_key=updated.idempotency_key,
        title=updated.title,
        description=updated.description,
        version_id=updated.version_id,
        retry_count=updated.retry_count,
        created_at=updated.created_at.isoformat(),
        updated_at=updated.updated_at.isoformat(),
    )


@router.get(
    "/workflows/{workflow_id}/history",
    response_model=list[AuditEventResponse],
    summary="Get workflow audit trail and state transition history",
)
def get_workflow_audit_history(
    project_id: int,
    workflow_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Returns durable audit events for the given workflow."""
    tenant_id = str(current_user.id)
    workflow = RemediationOrchestrator.get_workflow(session, workflow_id, tenant_id=tenant_id)
    if not workflow or workflow.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")

    stmt = (
        select(RemediationAuditEvent)
        .where(
            or_(
                RemediationAuditEvent.original_workflow_id == workflow_id,
                RemediationAuditEvent.workflow_id == workflow_id,
            )
        )
        .order_by(RemediationAuditEvent.sequence_number.asc())
        .offset(skip)
        .limit(limit)
    )
    events = list(session.execute(stmt).scalars().all())
    return [
        AuditEventResponse(
            event_id=e.event_id,
            workflow_id=e.workflow_id,
            from_state=e.from_state,
            to_state=e.to_state,
            action=e.action,
            actor=e.actor,
            event_payload=e.event_payload,
            created_at=e.created_at.isoformat(),
        )
        for e in events
    ]


@router.get(
    "/workflows/{workflow_id}/candidates",
    response_model=list[CandidateResponse],
    summary="List candidate patches for a workflow",
)
def list_workflow_candidates(
    project_id: int,
    workflow_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Lists all candidate patches synthesized for this workflow."""
    tenant_id = str(current_user.id)
    workflow = RemediationOrchestrator.get_workflow(session, workflow_id, tenant_id=tenant_id)
    if not workflow or workflow.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")

    stmt = select(RemediationCandidateRecord).where(RemediationCandidateRecord.workflow_id == workflow_id)
    candidates = list(session.execute(stmt).scalars().all())
    return [
        CandidateResponse(
            candidate_id=c.candidate_id,
            workflow_id=c.workflow_id,
            plan_id=c.plan_id,
            strategy=c.strategy,
            diff_unified=c.diff_unified,
            diff_hash=c.diff_hash,
            files_manifest=c.files_manifest,
            lifecycle_state=c.lifecycle_state,
            created_at=c.created_at.isoformat(),
        )
        for c in candidates
    ]


@router.get(
    "/workflows/{workflow_id}/approvals",
    response_model=list[ApprovalResponse],
    summary="List approval decisions for a workflow",
)
def list_workflow_approvals(
    project_id: int,
    workflow_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Lists approval and rejection decisions recorded for this workflow."""
    tenant_id = str(current_user.id)
    workflow = RemediationOrchestrator.get_workflow(session, workflow_id, tenant_id=tenant_id)
    if not workflow or workflow.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")

    stmt = select(RemediationApprovalRecord).where(RemediationApprovalRecord.workflow_id == workflow_id)
    approvals = list(session.execute(stmt).scalars().all())
    return [
        ApprovalResponse(
            approval_id=a.approval_id,
            workflow_id=a.workflow_id,
            candidate_id=a.candidate_id,
            patch_content_hash=a.patch_content_hash,
            approving_actor=a.approving_actor,
            decision=a.decision,
            risk_classification=a.risk_classification,
            approval_policy=a.approval_policy,
            decision_rationale=a.decision_rationale,
            is_valid=a.is_valid,
            created_at=a.created_at.isoformat(),
        )
        for a in approvals
    ]


@router.get(
    "/workflows/{workflow_id}/candidates/{candidate_id}",
    response_model=CandidateResponse,
    summary="Get single candidate patch by ID",
)
def get_workflow_candidate(
    project_id: int,
    workflow_id: str,
    candidate_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Retrieves a single candidate patch with strict project and workflow scoping."""
    tenant_id = str(current_user.id)
    workflow = RemediationOrchestrator.get_workflow(session, workflow_id, tenant_id=tenant_id)
    if not workflow or workflow.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")

    candidate = session.execute(
        select(RemediationCandidateRecord).where(
            RemediationCandidateRecord.candidate_id == candidate_id,
            RemediationCandidateRecord.workflow_id == workflow_id,
            RemediationCandidateRecord.project_id == project_id,
        )
    ).scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")

    return CandidateResponse(
        candidate_id=candidate.candidate_id,
        workflow_id=candidate.workflow_id,
        plan_id=candidate.plan_id,
        strategy=candidate.strategy,
        diff_unified=candidate.diff_unified,
        diff_hash=candidate.diff_hash,
        files_manifest=candidate.files_manifest,
        lifecycle_state=candidate.lifecycle_state,
        created_at=candidate.created_at.isoformat(),
    )


@router.get(
    "/workflows/{workflow_id}/audit-events/verify",
    response_model=AuditChainVerifyResponse,
    summary="Cryptographically verify workflow audit event chain",
)
def verify_workflow_audit_chain(
    project_id: int,
    workflow_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Validates the tamper-evident cryptographic hash chain for all audit events."""
    tenant_id = str(current_user.id)
    workflow = RemediationOrchestrator.get_workflow(session, workflow_id, tenant_id=tenant_id)
    if not workflow or workflow.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")

    is_valid, errors = RemediationOrchestrator.verify_audit_chain(session, workflow_id)
    return AuditChainVerifyResponse(
        workflow_id=workflow_id,
        is_valid=is_valid,
        errors=errors,
    )


@router.get(
    "/workflows/{workflow_id}/audit-events/checkpoint",
    response_model=AuditCheckpointResponse,
    summary="Get HMAC-signed audit chain checkpoint",
)
def get_workflow_audit_checkpoint(
    project_id: int,
    workflow_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Computes an HMAC-SHA256 authenticated checkpoint over the current chain-head."""
    tenant_id = str(current_user.id)
    workflow = RemediationOrchestrator.get_workflow(session, workflow_id, tenant_id=tenant_id)
    if not workflow or workflow.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")

    checkpoint = RemediationOrchestrator.compute_chain_checkpoint(session, workflow_id)
    return AuditCheckpointResponse(**checkpoint)


@router.post(
    "/workflows/{workflow_id}/audit-events/verify-checkpoint",
    response_model=AuditCheckpointVerifyResponse,
    summary="Verify HMAC-signed audit chain checkpoint against database state",
)
def verify_workflow_audit_checkpoint(
    project_id: int,
    workflow_id: str,
    req: AuditCheckpointVerifyRequest,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Validates an audit chain checkpoint signature and compares it to live DB records."""
    tenant_id = str(current_user.id)
    workflow = RemediationOrchestrator.get_workflow(session, workflow_id, tenant_id=tenant_id)
    if not workflow or workflow.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")

    is_valid, err = RemediationOrchestrator.verify_chain_checkpoint(session, workflow_id, req.checkpoint)
    return AuditCheckpointVerifyResponse(
        workflow_id=workflow_id,
        is_valid=is_valid,
        error=err,
    )


@router.post(
    "/workflows/{workflow_id}/approve",
    response_model=ApprovalResponse,
    summary="Record human approval or rejection decision",
)
def record_workflow_approval(
    project_id: int,
    workflow_id: str,
    req: RecordApprovalRequest,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Enforces approval hash verification and transitions workflow state."""
    tenant_id = str(current_user.id)
    workflow = RemediationOrchestrator.get_workflow(session, workflow_id, tenant_id=tenant_id)
    if not workflow or workflow.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")

    try:
        approval = RemediationOrchestrator.record_approval(
            session=session,
            workflow_id=workflow_id,
            candidate_id=req.candidate_id,
            patch_content_hash=req.patch_content_hash,
            approving_actor=current_user.username or current_user.email,
            decision=req.decision.upper(),
            decision_rationale=req.rationale,
            approver_user=current_user,
            candidate_version=req.candidate_version,
            base_commit_sha=req.base_commit_sha,
            actor_is_admin=getattr(current_user, "is_superuser", False),
        )
        session.commit()
    except ApprovalValidationError as e:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    except InvalidStateTransitionError as e:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    except Exception as e:
        session.rollback()
        logger.exception("Approval recording failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Approval recording failed.")

    return ApprovalResponse(
        approval_id=approval.approval_id,
        workflow_id=approval.workflow_id,
        candidate_id=approval.candidate_id,
        patch_content_hash=approval.patch_content_hash,
        approving_actor=approval.approving_actor,
        decision=approval.decision,
        risk_classification=approval.risk_classification,
        approval_policy=approval.approval_policy,
        decision_rationale=approval.decision_rationale,
        is_valid=approval.is_valid,
        created_at=approval.created_at.isoformat(),
    )


@router.post(
    "/workflows/{workflow_id}/approvals/{approval_id}/revoke",
    response_model=ApprovalResponse,
    summary="Revoke an existing approval decision",
)
def revoke_workflow_approval(
    project_id: int,
    workflow_id: str,
    approval_id: str,
    req: RevokeApprovalRequest,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Revokes an existing approval and updates workflow state."""
    tenant_id = str(current_user.id)
    workflow = RemediationOrchestrator.get_workflow(session, workflow_id, tenant_id=tenant_id)
    if not workflow or workflow.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")

    try:
        approval = RemediationOrchestrator.revoke_approval(
            session=session,
            workflow_id=workflow_id,
            approval_id=approval_id,
            actor=current_user.username or current_user.email,
            reason=req.reason,
        )
        session.commit()
    except ValueError as e:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        session.rollback()
        logger.exception("Approval revocation failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Approval revocation failed.")

    return ApprovalResponse(
        approval_id=approval.approval_id,
        workflow_id=approval.workflow_id,
        candidate_id=approval.candidate_id,
        patch_content_hash=approval.patch_content_hash,
        approving_actor=approval.approving_actor,
        decision=approval.decision,
        risk_classification=approval.risk_classification,
        approval_policy=approval.approval_policy,
        decision_rationale=approval.decision_rationale,
        is_valid=approval.is_valid,
        created_at=approval.created_at.isoformat(),
    )


# =====================================================================
# Phase 5.1 Safety Enforcement Endpoint
# =====================================================================


@router.post(
    "/workflows/{workflow_id}/apply",
    status_code=status.HTTP_403_FORBIDDEN,
    summary="Autonomous patch application guard",
)
def apply_remediation_workflow_guard(
    project_id: int,
    workflow_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
):
    """Strictly disabled during Phase 5.1.

    Autonomous patch application is not permitted until Phase 5.4.
    """
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Patch application is disabled in Phase 5.1. Autonomous application becomes available in Phase 5.4 under approval governance.",
    )


# =====================================================================
# Phase 5.2 Root Cause Investigation & Remediation Planning Endpoints
# =====================================================================


@router.post(
    "/workflows/{workflow_id}/investigate",
    response_model=dict[str, Any],
    summary="Trigger root cause investigation",
)
def investigate_root_causes_endpoint(
    project_id: int,
    workflow_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Executes multi-source evidence aggregation and synthesizes root cause hypotheses."""
    from pathlib import Path

    workflow = db.scalar(select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id))
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow '{workflow_id}' not found.")
    user_tenant = getattr(current_user, "tenant_id", str(current_user.id))
    if workflow.project_id != project.id or workflow.tenant_id != user_tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    repo_root = Path(project.repo_path) if project.repo_path else None
    try:
        res = RemediationOrchestrator.investigate_root_causes(
            session=db,
            workflow_id=workflow_id,
            actor=current_user.username,
            repo_root=repo_root,
        )
        return {
            "status": "completed",
            "workflow_id": workflow_id,
            "workflow_state": workflow.state,
            "hypotheses_count": len(res.get("hypotheses", [])),
            "clusters_count": len(res.get("clusters", [])),
            "evidence_sources_count": len(res.get("evidence", {})),
        }
    except Exception as e:
        logger.exception("Root cause investigation failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "/workflows/{workflow_id}/investigation",
    response_model=dict[str, Any],
    summary="Get aggregated investigation details",
)
def get_investigation_details(
    project_id: int,
    workflow_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieves all hypotheses, clusters, and evidence for a workflow."""
    workflow = db.scalar(select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id))
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow '{workflow_id}' not found.")
    user_tenant = getattr(current_user, "tenant_id", str(current_user.id))
    if workflow.project_id != project.id or workflow.tenant_id != user_tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    hypotheses = list(
        db.scalars(
            select(RemediationRootCauseHypothesisRecord)
            .where(RemediationRootCauseHypothesisRecord.workflow_id == workflow_id)
            .order_by(RemediationRootCauseHypothesisRecord.confidence_score.desc())
        ).all()
    )
    clusters = list(
        db.scalars(
            select(RemediationFindingClusterRecord)
            .where(RemediationFindingClusterRecord.workflow_id == workflow_id)
        ).all()
    )

    cluster_data = []
    for c in clusters:
        finding_ids = [cf.finding_id for cf in c.cluster_findings]
        cluster_data.append({
            "cluster_id": c.cluster_id,
            "cluster_name": c.cluster_name,
            "primary_finding_id": c.primary_finding_id,
            "thematic_category": c.thematic_category,
            "correlation_rationale": c.correlation_rationale,
            "confidence_score": c.confidence_score,
            "is_manually_adjusted": c.is_manually_adjusted,
            "finding_ids": finding_ids,
            "created_at": c.created_at.isoformat(),
        })

    hypotheses_data = [
        {
            "hypothesis_id": h.hypothesis_id,
            "title": h.title,
            "category": h.category,
            "explanation": h.explanation,
            "confidence_score": h.confidence_score,
            "status": h.status,
            "supporting_evidence": h.supporting_evidence,
            "contradicting_evidence": h.contradicting_evidence,
            "affected_symbols": h.affected_symbols,
            "affected_files": h.affected_files,
            "evidence_completeness_score": h.evidence_completeness_score,
            "provenance": h.provenance,
            "created_at": h.created_at.isoformat(),
        }
        for h in hypotheses
    ]

    return {
        "workflow_id": workflow_id,
        "workflow_state": workflow.state,
        "hypotheses": hypotheses_data,
        "clusters": cluster_data,
    }


@router.get(
    "/workflows/{workflow_id}/hypotheses",
    response_model=list[HypothesisResponse],
    summary="List root cause hypotheses",
)
def list_hypotheses_endpoint(
    project_id: int,
    workflow_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lists all formulated root cause hypotheses for the workflow."""
    workflow = db.scalar(select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id))
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow '{workflow_id}' not found.")
    user_tenant = getattr(current_user, "tenant_id", str(current_user.id))
    if workflow.project_id != project.id or workflow.tenant_id != user_tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    hypotheses = list(
        db.scalars(
            select(RemediationRootCauseHypothesisRecord)
            .where(RemediationRootCauseHypothesisRecord.workflow_id == workflow_id)
            .order_by(RemediationRootCauseHypothesisRecord.confidence_score.desc())
        ).all()
    )
    return [
        HypothesisResponse(
            hypothesis_id=h.hypothesis_id,
            workflow_id=h.workflow_id,
            title=h.title,
            category=h.category,
            explanation=h.explanation,
            confidence_score=h.confidence_score,
            status=h.status,
            supporting_evidence=h.supporting_evidence or [],
            contradicting_evidence=h.contradicting_evidence or [],
            affected_symbols=h.affected_symbols or [],
            affected_files=h.affected_files or [],
            evidence_completeness_score=h.evidence_completeness_score,
            provenance=h.provenance,
            created_at=h.created_at.isoformat(),
        )
        for h in hypotheses
    ]


@router.get(
    "/workflows/{workflow_id}/clusters",
    response_model=list[FindingClusterResponse],
    summary="List cross-finding correlation clusters",
)
def list_finding_clusters_endpoint(
    project_id: int,
    workflow_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lists all correlated finding clusters for the workflow."""
    workflow = db.scalar(select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id))
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow '{workflow_id}' not found.")
    user_tenant = getattr(current_user, "tenant_id", str(current_user.id))
    if workflow.project_id != project.id or workflow.tenant_id != user_tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    clusters = list(
        db.scalars(
            select(RemediationFindingClusterRecord)
            .where(RemediationFindingClusterRecord.workflow_id == workflow_id)
        ).all()
    )
    return [
        FindingClusterResponse(
            cluster_id=c.cluster_id,
            workflow_id=c.workflow_id,
            cluster_name=c.cluster_name,
            primary_finding_id=c.primary_finding_id,
            thematic_category=c.thematic_category,
            correlation_rationale=c.correlation_rationale,
            confidence_score=c.confidence_score,
            is_manually_adjusted=c.is_manually_adjusted,
            finding_ids=[cf.finding_id for cf in c.cluster_findings],
            created_at=c.created_at.isoformat(),
        )
        for c in clusters
    ]


@router.post(
    "/workflows/{workflow_id}/clusters/{cluster_id}/separate-finding",
    response_model=dict[str, Any],
    summary="Manually split a finding out of a cluster",
)
def separate_finding_from_cluster_endpoint(
    project_id: int,
    workflow_id: str,
    cluster_id: str,
    payload: SeparateFindingRequest,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reviewer override: splits a finding from a cluster into its own isolated cluster."""
    workflow = db.scalar(select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id))
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow '{workflow_id}' not found.")
    user_tenant = getattr(current_user, "tenant_id", str(current_user.id))
    if workflow.project_id != project.id or workflow.tenant_id != user_tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    try:
        new_cluster = RootCauseEngine.manually_separate_finding(
            session=db,
            cluster_id=cluster_id,
            finding_id=payload.finding_id,
            reason=payload.reason,
        )
        return {
            "status": "separated",
            "original_cluster_id": cluster_id,
            "new_cluster_id": new_cluster.cluster_id,
            "finding_id": payload.finding_id,
            "reason": payload.reason,
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/workflows/{workflow_id}/generate-plans",
    response_model=list[PlanResponse],
    summary="Synthesize multi-strategy remediation plans",
)
def generate_plans_endpoint(
    project_id: int,
    workflow_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Synthesizes alternative repair strategies, calculates blast-radius and 11-dimension scores."""
    from pathlib import Path

    workflow = db.scalar(select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id))
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow '{workflow_id}' not found.")
    user_tenant = getattr(current_user, "tenant_id", str(current_user.id))
    if workflow.project_id != project.id or workflow.tenant_id != user_tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    repo_root = Path(project.repo_path) if project.repo_path else None
    try:
        plans = RemediationOrchestrator.generate_remediation_plans(
            session=db,
            workflow_id=workflow_id,
            actor=current_user.username,
            repo_root=repo_root,
        )
        return [
            PlanResponse(
                plan_id=p.plan_id,
                workflow_id=p.workflow_id,
                strategy_name=p.strategy_name,
                strategy_description=p.strategy_description,
                target_findings=p.target_findings or [],
                affected_files=p.affected_files or [],
                root_cause_reference=p.root_cause_reference or {},
                proposed_changes_summary=p.proposed_changes_summary,
                regression_risks=p.regression_risks or [],
                required_tests=p.required_tests or [],
                rollback_strategy=p.rollback_strategy,
                risk_assessment=p.risk_assessment or {},
                plan_score=p.plan_score,
                score_breakdown=p.score_breakdown or {},
                ranking_explanation=p.ranking_explanation,
                approval_tier_required=p.approval_tier_required,
                estimated_complexity=p.estimated_complexity,
                is_preferred=p.is_preferred,
                abstain_reason=p.abstain_reason,
                created_at=p.created_at.isoformat(),
            )
            for p in plans
        ]
    except Exception as e:
        logger.exception("Plan generation failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "/workflows/{workflow_id}/plans",
    response_model=list[PlanResponse],
    summary="List remediation plans",
)
def list_plans_endpoint(
    project_id: int,
    workflow_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lists all generated plans for the workflow, ordered with preferred first."""
    workflow = db.scalar(select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id))
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow '{workflow_id}' not found.")
    user_tenant = getattr(current_user, "tenant_id", str(current_user.id))
    if workflow.project_id != project.id or workflow.tenant_id != user_tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    plans = list(
        db.scalars(
            select(RemediationPlanRecord)
            .where(RemediationPlanRecord.workflow_id == workflow_id)
            .order_by(RemediationPlanRecord.is_preferred.desc(), RemediationPlanRecord.plan_score.desc())
        ).all()
    )
    return [
        PlanResponse(
            plan_id=p.plan_id,
            workflow_id=p.workflow_id,
            strategy_name=p.strategy_name,
            strategy_description=p.strategy_description,
            target_findings=p.target_findings or [],
            affected_files=p.affected_files or [],
            root_cause_reference=p.root_cause_reference or {},
            proposed_changes_summary=p.proposed_changes_summary,
            regression_risks=p.regression_risks or [],
            required_tests=p.required_tests or [],
            rollback_strategy=p.rollback_strategy,
            risk_assessment=p.risk_assessment or {},
            plan_score=p.plan_score,
            score_breakdown=p.score_breakdown or {},
            ranking_explanation=p.ranking_explanation,
            approval_tier_required=p.approval_tier_required,
            estimated_complexity=p.estimated_complexity,
            is_preferred=p.is_preferred,
            abstain_reason=p.abstain_reason,
            created_at=p.created_at.isoformat(),
        )
        for p in plans
    ]


@router.get(
    "/workflows/{workflow_id}/plans/compare",
    response_model=PlanCompareResponse,
    summary="Side-by-side plan comparison matrix",
)
def compare_plans_endpoint(
    project_id: int,
    workflow_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generates comparison matrix across all candidate plans."""
    workflow = db.scalar(select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id))
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow '{workflow_id}' not found.")
    user_tenant = getattr(current_user, "tenant_id", str(current_user.id))
    if workflow.project_id != project.id or workflow.tenant_id != user_tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    plans = list(
        db.scalars(
            select(RemediationPlanRecord)
            .where(RemediationPlanRecord.workflow_id == workflow_id)
            .order_by(RemediationPlanRecord.is_preferred.desc(), RemediationPlanRecord.plan_score.desc())
        ).all()
    )

    matrix = []
    for p in plans:
        risk_info = p.risk_assessment or {}
        matrix.append({
            "plan_id": p.plan_id,
            "strategy_name": p.strategy_name,
            "score": p.plan_score,
            "is_preferred": p.is_preferred,
            "complexity": p.estimated_complexity,
            "approval_tier": p.approval_tier_required,
            "blast_radius_score": risk_info.get("blast_radius_score", 0.0),
            "affected_modules_count": len(risk_info.get("affected_modules", [])),
            "required_tests_count": len(p.required_tests or []),
            "abstained": bool(p.abstain_reason),
            "abstain_reason": p.abstain_reason,
            "score_breakdown": p.score_breakdown or {},
        })

    return PlanCompareResponse(
        workflow_id=workflow_id,
        plans_count=len(plans),
        comparison_matrix=matrix,
    )


@router.get(
    "/workflows/{workflow_id}/plans/{plan_id}",
    response_model=PlanResponse,
    summary="Get single remediation plan",
)
def get_plan_endpoint(
    project_id: int,
    workflow_id: str,
    plan_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieves full details for a single plan."""
    workflow = db.scalar(select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id))
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow '{workflow_id}' not found.")
    user_tenant = getattr(current_user, "tenant_id", str(current_user.id))
    if workflow.project_id != project.id or workflow.tenant_id != user_tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    plan = db.scalar(
        select(RemediationPlanRecord).where(
            RemediationPlanRecord.workflow_id == workflow_id,
            RemediationPlanRecord.plan_id == plan_id,
        )
    )
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Plan '{plan_id}' not found.")

    return PlanResponse(
        plan_id=plan.plan_id,
        workflow_id=plan.workflow_id,
        strategy_name=plan.strategy_name,
        strategy_description=plan.strategy_description,
        target_findings=plan.target_findings or [],
        affected_files=plan.affected_files or [],
        root_cause_reference=plan.root_cause_reference or {},
        proposed_changes_summary=plan.proposed_changes_summary,
        regression_risks=plan.regression_risks or [],
        required_tests=plan.required_tests or [],
        rollback_strategy=plan.rollback_strategy,
        risk_assessment=plan.risk_assessment or {},
        plan_score=plan.plan_score,
        score_breakdown=plan.score_breakdown or {},
        ranking_explanation=plan.ranking_explanation,
        approval_tier_required=plan.approval_tier_required,
        estimated_complexity=plan.estimated_complexity,
        is_preferred=plan.is_preferred,
        abstain_reason=plan.abstain_reason,
        created_at=plan.created_at.isoformat(),
    )


@router.post(
    "/workflows/{workflow_id}/plans/{plan_id}/select",
    response_model=dict[str, Any],
    summary="Select preferred plan and generate candidate patch",
)
def select_plan_endpoint(
    project_id: int,
    workflow_id: str,
    plan_id: str,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sets plan as preferred and transitions to PATCH_GENERATED."""
    workflow = db.scalar(select(RemediationWorkflowRecord).where(RemediationWorkflowRecord.workflow_id == workflow_id))
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow '{workflow_id}' not found.")
    user_tenant = getattr(current_user, "tenant_id", str(current_user.id))
    if workflow.project_id != project.id or workflow.tenant_id != user_tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    try:
        selected_plan = RemediationOrchestrator.select_preferred_plan(
            session=db,
            workflow_id=workflow_id,
            plan_id=plan_id,
            actor=current_user.username,
        )
        return {
            "status": "selected",
            "workflow_id": workflow_id,
            "plan_id": selected_plan.plan_id,
            "strategy_name": selected_plan.strategy_name,
            "workflow_state": workflow.state,
            "active_candidate_id": workflow.active_candidate_id,
        }
    except Exception as e:
        logger.exception("Plan selection failed: %s", e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


