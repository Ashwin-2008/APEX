"""Transactional Patch Application & Lifecycle Management for APEX 2.0.

Provides strict transactional safety, atomic file operations, pre-modification
cryptographic backups, rollback conflict protection, and state machine validation:

State Machine:
  GENERATED -> VERIFICATION_PENDING -> VERIFIED -> APPLY_PENDING -> APPLIED -> POST_APPLY_VERIFICATION -> REMEDIATION_CONFIRMED
  Failure States:
  REJECTED, FAILED, CONFLICT, STALE_PATCH, VERIFICATION_FAILED, ROLLBACK_PENDING, ROLLED_BACK, EXPIRED, ROLLBACK_CONFLICT
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from app.services.remediation.patch_generator import CodePatch
from app.services.remediation.patch_integrity import (
    PatchIntegrityService,
    PatchProvenance,
    compute_content_sha256,
)
from app.services.remediation.patch_verifier import PatchVerificationResult, PatchVerifier
from app.services.remediation.semantic_verifier import SemanticVerificationResult, SemanticVerifier

logger = logging.getLogger(__name__)


class PatchLifecycleState(str, Enum):
    GENERATED = "GENERATED"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    VERIFIED = "VERIFIED"
    APPLY_PENDING = "APPLY_PENDING"
    APPLIED = "APPLIED"
    POST_APPLY_VERIFICATION = "POST_APPLY_VERIFICATION"
    REMEDIATION_CONFIRMED = "REMEDIATION_CONFIRMED"

    # Terminal / Failure states
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CONFLICT = "CONFLICT"
    STALE_PATCH = "STALE_PATCH"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    ROLLED_BACK = "ROLLED_BACK"
    EXPIRED = "EXPIRED"
    ROLLBACK_CONFLICT = "ROLLBACK_CONFLICT"


# Allowed state transitions
VALID_TRANSITIONS: dict[PatchLifecycleState, set[PatchLifecycleState]] = {
    PatchLifecycleState.GENERATED: {
        PatchLifecycleState.VERIFICATION_PENDING,
        PatchLifecycleState.VERIFIED,
        PatchLifecycleState.APPLIED,
        PatchLifecycleState.VERIFICATION_FAILED,
        PatchLifecycleState.REJECTED,
        PatchLifecycleState.EXPIRED,
    },
    PatchLifecycleState.VERIFICATION_PENDING: {
        PatchLifecycleState.VERIFIED,
        PatchLifecycleState.VERIFICATION_FAILED,
        PatchLifecycleState.REJECTED,
    },
    PatchLifecycleState.VERIFIED: {
        PatchLifecycleState.APPLY_PENDING,
        PatchLifecycleState.APPLIED,
        PatchLifecycleState.STALE_PATCH,
        PatchLifecycleState.REJECTED,
        PatchLifecycleState.FAILED,
    },
    PatchLifecycleState.APPLY_PENDING: {
        PatchLifecycleState.APPLIED,
        PatchLifecycleState.FAILED,
        PatchLifecycleState.CONFLICT,
        PatchLifecycleState.STALE_PATCH,
    },
    PatchLifecycleState.APPLIED: {
        PatchLifecycleState.POST_APPLY_VERIFICATION,
        PatchLifecycleState.REMEDIATION_CONFIRMED,
        PatchLifecycleState.ROLLBACK_PENDING,
        PatchLifecycleState.ROLLED_BACK,
        PatchLifecycleState.ROLLBACK_CONFLICT,
    },
    PatchLifecycleState.POST_APPLY_VERIFICATION: {
        PatchLifecycleState.REMEDIATION_CONFIRMED,
        PatchLifecycleState.ROLLBACK_PENDING,
        PatchLifecycleState.ROLLED_BACK,
        PatchLifecycleState.FAILED,
    },
    PatchLifecycleState.REMEDIATION_CONFIRMED: {
        PatchLifecycleState.ROLLBACK_PENDING,
        PatchLifecycleState.ROLLED_BACK,
        PatchLifecycleState.ROLLBACK_CONFLICT,
    },
    PatchLifecycleState.ROLLBACK_PENDING: {
        PatchLifecycleState.ROLLED_BACK,
        PatchLifecycleState.ROLLBACK_CONFLICT,
        PatchLifecycleState.FAILED,
    },
    PatchLifecycleState.ROLLED_BACK: set(),
    PatchLifecycleState.REJECTED: set(),
    PatchLifecycleState.FAILED: set(),
    PatchLifecycleState.CONFLICT: set(),
    PatchLifecycleState.STALE_PATCH: set(),
    PatchLifecycleState.VERIFICATION_FAILED: set(),
    PatchLifecycleState.EXPIRED: set(),
    PatchLifecycleState.ROLLBACK_CONFLICT: set(),
}


@dataclass
class AuditEvent:
    timestamp: str
    action: str
    from_state: str
    to_state: str
    actor: str
    details: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PatchRecord:
    patch: CodePatch
    state: PatchLifecycleState
    provenance: PatchProvenance | None = None
    verification: PatchVerificationResult | None = None
    semantic_verification: SemanticVerificationResult | None = None
    behavioral_verification: dict[str, Any] | None = None
    post_apply_verification: dict[str, Any] | None = None
    backup_file_path: str | None = None
    backup_sha256: str | None = None
    applied_sha256: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    applied_at: str | None = None
    rolled_back_at: str | None = None
    audit_trail: list[AuditEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch": self.patch.to_dict(),
            "state": self.state.value,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "verification": self.verification.to_dict() if self.verification else None,
            "semantic_verification": self.semantic_verification.to_dict() if self.semantic_verification else None,
            "behavioral_verification": self.behavioral_verification,
            "post_apply_verification": self.post_apply_verification,
            "backup_file_path": self.backup_file_path,
            "backup_sha256": self.backup_sha256,
            "applied_sha256": self.applied_sha256,
            "created_at": self.created_at,
            "applied_at": self.applied_at,
            "rolled_back_at": self.rolled_back_at,
            "audit_trail": [a.to_dict() for a in self.audit_trail],
        }

    def record_transition(self, to_state: PatchLifecycleState, action: str, actor: str, details: str) -> None:
        from_state = self.state.value
        self.state = to_state
        self.audit_trail.append(
            AuditEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                action=action,
                from_state=from_state,
                to_state=to_state.value,
                actor=actor,
                details=details,
            )
        )


class PatchLifecycleManager:
    """Enterprise-grade transactional patch manager with atomic writes and rollback protection."""

    def __init__(self) -> None:
        self._patches: dict[str, PatchRecord] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def _get_lock(self, repo_key: str) -> threading.Lock:
        with self._global_lock:
            if repo_key not in self._locks:
                self._locks[repo_key] = threading.Lock()
            return self._locks[repo_key]

    def register_patch(
        self,
        patch: CodePatch,
        verification: PatchVerificationResult | None = None,
        provenance: PatchProvenance | None = None,
        semantic_verification: SemanticVerificationResult | None = None,
    ) -> PatchRecord:
        """Registers candidate patch and establishes lifecycle state."""
        state = PatchLifecycleState.GENERATED
        if verification and verification.valid:
            if semantic_verification and not semantic_verification.valid:
                state = PatchLifecycleState.VERIFICATION_FAILED
            else:
                state = PatchLifecycleState.VERIFIED
        elif verification and not verification.valid:
            state = PatchLifecycleState.VERIFICATION_FAILED

        record = PatchRecord(
            patch=patch,
            state=state,
            provenance=provenance,
            verification=verification,
            semantic_verification=semantic_verification,
        )
        record.record_transition(state, "REGISTER_PATCH", "SYSTEM", f"Patch registered in state {state.value}")
        self._patches[patch.patch_id] = record
        return record

    def get_patch_record(self, patch_id: str) -> PatchRecord | None:
        return self._patches.get(patch_id)

    def list_patches_for_project(self, project_id: int) -> list[PatchRecord]:
        return [
            rec for rec in self._patches.values()
            if rec.provenance and rec.provenance.project_id == project_id
        ]

    def apply_patch(
        self,
        patch_id: str,
        repo_root: Path,
        actor: str = "ENGINEER",
    ) -> tuple[bool, str]:
        """Atomically applies a verified code patch with pre-modification backup and fsync."""
        record = self.get_patch_record(patch_id)
        if not record:
            return False, f"Patch {patch_id} not found in registry."

        # Concurrency control per repository
        lock = self._get_lock(str(repo_root.resolve()))
        if not lock.acquire(blocking=True, timeout=10.0):
            return False, "Lock acquisition timed out: another patch operation is currently in progress."

        try:
            # Idempotency check
            if record.state == PatchLifecycleState.APPLIED:
                return True, f"Patch {patch_id} is already applied."

            patch = record.patch
            repo_root_res = repo_root.resolve()
            target_path = (repo_root / patch.file).resolve()

            # Security Check 1: Traversal Protection
            if not str(target_path).startswith(str(repo_root_res)):
                record.record_transition(PatchLifecycleState.REJECTED, "APPLY_BLOCKED", actor, "Directory traversal attempt blocked.")
                return False, "Security violation: target path traverses outside repository root."

            # Security Check 2: Symlink Escape Protection
            if os.path.islink(target_path):
                real_target = Path(os.path.realpath(target_path))
                if not str(real_target).startswith(str(repo_root_res)):
                    record.record_transition(PatchLifecycleState.REJECTED, "APPLY_BLOCKED", actor, "Symlink escape attempt blocked.")
                    return False, "Security violation: target file is an unauthorized symlink escaping project root."

            # Validate state transition
            allowed = VALID_TRANSITIONS.get(record.state, set())
            if PatchLifecycleState.APPLIED not in allowed:
                return False, f"Illegal state transition from '{record.state.value}' to 'APPLIED'."

            if not target_path.is_file():
                return False, f"Target file '{patch.file}' does not exist on disk."

            try:
                original_code = target_path.read_text(encoding="utf-8", errors="ignore")
            except OSError as e:
                return False, f"Failed reading target file: {e}"

            # Step 1: Stale Patch & Cryptographic Integrity Check
            if record.provenance:
                is_valid, msg, code = PatchIntegrityService.check_integrity(record.provenance, patch, repo_root)
                if not is_valid:
                    new_st = PatchLifecycleState.STALE_PATCH if code == "STALE_PATCH" else PatchLifecycleState.FAILED
                    record.record_transition(new_st, "INTEGRITY_FAILED", actor, msg)
                    return False, msg

            # Step 2: Semantic Verification Sandbox Check
            if not record.semantic_verification:
                patched_in_mem = PatchVerifier.apply_patch_in_memory(original_code, patch)
                if patched_in_mem is not None:
                    sem_res = SemanticVerifier.verify_semantics(
                        original_code,
                        patched_in_mem,
                        rule_id=patch.rule_id,
                        expected_strategy=patch.strategy.value,
                    )
                    record.semantic_verification = sem_res
                    if not sem_res.valid:
                        record.record_transition(PatchLifecycleState.VERIFICATION_FAILED, "SEMANTIC_CHECK_FAILED", actor, sem_res.summary)
                        return False, f"Semantic verification failed: {sem_res.summary}"

            # Step 3: Compute Patched Code Content
            patched_code = PatchVerifier.apply_patch_in_memory(original_code, patch)
            if patched_code is None:
                record.record_transition(PatchLifecycleState.FAILED, "APPLY_FAILED", actor, "Failed to apply patch diff in memory.")
                return False, "Failed to compute patched content for disk application."

            # Step 4: Atomic Backup with Verification
            backup_dir = repo_root / ".apex_backup"
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            safe_filename = f"{patch.patch_id}_{timestamp_str}_{Path(patch.file).name}.orig"
            backup_file = backup_dir / safe_filename

            orig_hash = compute_content_sha256(original_code)
            try:
                with open(backup_file, "w", encoding="utf-8") as bf:
                    bf.write(original_code)
                    bf.flush()
                    os.fsync(bf.fileno())
            except OSError as e:
                return False, f"Failed writing atomic backup snapshot: {e}"

            # Verify backup integrity
            backup_verified_hash = compute_content_sha256(backup_file.read_text(encoding="utf-8"))
            if backup_verified_hash != orig_hash:
                backup_file.unlink(missing_ok=True)
                return False, "Backup integrity verification failed: hash mismatch."

            record.backup_file_path = str(backup_file.relative_to(repo_root))
            record.backup_sha256 = orig_hash

            # Step 5: Atomic File Replacement (Write to temp file in same dir, fsync, os.replace)
            tmp_patch_file = target_path.parent / f".tmp_{patch.patch_id}_{safe_filename}.tmp"
            try:
                with open(tmp_patch_file, "w", encoding="utf-8") as tf:
                    tf.write(patched_code)
                    tf.flush()
                    os.fsync(tf.fileno())

                patched_hash = compute_content_sha256(tmp_patch_file.read_text(encoding="utf-8"))
                os.replace(tmp_patch_file, target_path)
            except OSError as e:
                if tmp_patch_file.is_file():
                    tmp_patch_file.unlink(missing_ok=True)
                record.record_transition(PatchLifecycleState.FAILED, "DISK_WRITE_FAILED", actor, str(e))
                return False, f"Failed atomic file replacement: {e}"

            record.applied_sha256 = patched_hash
            record.applied_at = datetime.now(timezone.utc).isoformat()
            record.record_transition(
                PatchLifecycleState.APPLIED,
                "APPLY_SUCCESS",
                actor,
                f"Patch applied atomically with verified backup {record.backup_file_path}",
            )
            logger.info(f"Successfully applied patch {patch_id} to {patch.file}")
            return True, "Patch applied atomically with verified cryptographic backup."

        finally:
            lock.release()

    def rollback_patch(
        self,
        patch_id: str,
        repo_root: Path,
        actor: str = "ENGINEER",
    ) -> tuple[bool, str]:
        """Safely rolls back applied patch with rollback-conflict protection."""
        record = self.get_patch_record(patch_id)
        if not record:
            return False, f"Patch {patch_id} not found in registry."

        lock = self._get_lock(str(repo_root.resolve()))
        if not lock.acquire(blocking=True, timeout=10.0):
            return False, "Lock acquisition timed out: another patch operation is currently in progress."

        try:
            if record.state != PatchLifecycleState.APPLIED and record.state != PatchLifecycleState.REMEDIATION_CONFIRMED:
                return False, f"Patch {patch_id} is in state '{record.state.value}', which cannot be rolled back."

            if not record.backup_file_path:
                return False, f"No backup file recorded for patch {patch_id}."

            backup_file = (repo_root / record.backup_file_path).resolve()
            target_path = (repo_root / record.patch.file).resolve()
            repo_root_res = repo_root.resolve()

            if not str(target_path).startswith(str(repo_root_res)) or not str(backup_file).startswith(str(repo_root_res)):
                return False, "Security violation: file path traverses outside repository root."

            if not backup_file.is_file():
                return False, f"Backup file {record.backup_file_path} is missing or deleted."

            if not target_path.is_file():
                return False, f"Target file '{record.patch.file}' does not exist on disk."

            # Verify backup integrity
            backup_code = backup_file.read_text(encoding="utf-8", errors="ignore")
            if record.backup_sha256 and compute_content_sha256(backup_code) != record.backup_sha256:
                return False, "Backup integrity violation: backup content has been tampered with."

            # ROLLBACK CONFLICT PROTECTION: Check if current file matches applied_sha256
            current_code = target_path.read_text(encoding="utf-8", errors="ignore")
            current_hash = compute_content_sha256(current_code)

            if record.applied_sha256 and current_hash != record.applied_sha256:
                msg = (
                    "ROLLBACK_CONFLICT: Target file has been modified by external changes since patch application. "
                    "Automatic rollback was halted to prevent destroying newer developer modifications."
                )
                record.record_transition(PatchLifecycleState.ROLLBACK_CONFLICT, "ROLLBACK_CONFLICT_DETECTED", actor, msg)
                return False, msg

            # Atomic restoration from backup
            tmp_restore_file = target_path.parent / f".tmp_rb_{patch_id}.tmp"
            try:
                with open(tmp_restore_file, "w", encoding="utf-8") as rf:
                    rf.write(backup_code)
                    rf.flush()
                    os.fsync(rf.fileno())
                os.replace(tmp_restore_file, target_path)
            except OSError as e:
                if tmp_restore_file.is_file():
                    tmp_restore_file.unlink(missing_ok=True)
                return False, f"Failed to restore file from backup: {e}"

            record.rolled_back_at = datetime.now(timezone.utc).isoformat()
            record.record_transition(
                PatchLifecycleState.ROLLED_BACK,
                "ROLLBACK_SUCCESS",
                actor,
                "File restored cleanly from pre-modification backup snapshot.",
            )
            logger.info(f"Successfully rolled back patch {patch_id} on {record.patch.file}")
            return True, "Patch rolled back cleanly to pre-modification state."

        finally:
            lock.release()


# Global runtime singleton
global_patch_manager = PatchLifecycleManager()
