"""Remediation & Patch Verification Package for APEX 2.0."""
from app.services.remediation.behavioral_verifier import (
    BehavioralStatus,
    BehavioralVerificationResult,
    BehavioralVerifier,
)
from app.services.remediation.crash_recovery import CrashRecoveryEngine
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
    "AuditEvent",
    "BehavioralStatus",
    "BehavioralVerificationResult",
    "BehavioralVerifier",
    "CodePatch",
    "ConfidenceDimension",
    "CrashRecoveryEngine",
    "FunctionContract",
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
    "RepositoryLockContext",
    "RepositoryLockManager",
    "RollbackConflictError",
    "SemanticRisk",
    "SemanticVerificationResult",
    "SemanticVerifier",
    "TransactionState",
    "compute_content_sha256",
    "global_patch_manager",
]
