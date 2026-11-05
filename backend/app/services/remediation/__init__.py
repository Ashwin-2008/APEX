"""Remediation & Patch Verification Package for APEX 2.0."""
from app.services.remediation.behavioral_verifier import (
    BehavioralStatus,
    BehavioralVerificationResult,
    BehavioralVerifier,
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
    VALID_WORKFLOW_TRANSITIONS,
)
from app.services.remediation.patch_confidence import (
    ConfidenceDimension,
    PatchConfidenceEngine,
    PatchConfidenceReport,
)
from app.services.remediation.patch_generator import CodePatch, PatchGenerator, PatchStrategy
from app.services.remediation.patch_integrity import (
    PatchIntegrityService,
    PatchProvenance,
    compute_content_sha256,
)
from app.services.remediation.patch_lifecycle import (
    AuditEvent,
    PatchLifecycleManager,
    PatchLifecycleState,
    PatchRecord,
    global_patch_manager,
)
from app.services.remediation.patch_verifier import (
    PatchVerificationResult,
    PatchVerificationStatus,
    PatchVerifier,
)
from app.services.remediation.post_apply_verifier import (
    PostApplyOutcome,
    PostApplyVerificationResult,
    PostApplyVerifier,
)
from app.services.remediation.repository_lock import (
    LockAcquisitionError,
    RepositoryLockContext,
    RepositoryLockManager,
)
from app.services.remediation.semantic_verifier import (
    FunctionContract,
    SemanticRisk,
    SemanticVerificationResult,
    SemanticVerifier,
)
from app.services.remediation.transaction_engine import (
    MultiFileTransactionEngine,
    RollbackConflictError,
    TransactionState,
)

__all__ = [
    "ApprovalValidationError",
    "AuditEvent",
    "BehavioralStatus",
    "BehavioralVerificationResult",
    "BehavioralVerifier",
    "CodePatch",
    "ConcurrencyConflictError",
    "ConfidenceDimension",
    "CrashRecoveryEngine",
    "FunctionContract",
    "InvalidStateTransitionError",
    "LeaseFencingError",
    "LockAcquisitionError",
    "MultiFileTransactionEngine",
    "PatchConfidenceEngine",
    "PatchConfidenceReport",
    "PatchGenerator",
    "PatchIntegrityService",
    "PatchLifecycleManager",
    "PatchLifecycleState",
    "PatchProvenance",
    "PatchRecord",
    "PatchStrategy",
    "PatchVerificationResult",
    "PatchVerificationStatus",
    "PatchVerifier",
    "PostApplyOutcome",
    "PostApplyVerificationResult",
    "PostApplyVerifier",
    "RemediationOrchestrator",
    "RemediationWorkflowState",
    "RepositoryLockContext",
    "RepositoryLockManager",
    "RollbackConflictError",
    "SemanticRisk",
    "SemanticVerificationResult",
    "SemanticVerifier",
    "TERMINAL_WORKFLOW_STATES",
    "TransactionState",
    "VALID_WORKFLOW_TRANSITIONS",
    "compute_content_sha256",
    "global_patch_manager",
]
