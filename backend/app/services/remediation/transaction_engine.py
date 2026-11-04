"""Multi-File Remediation Transaction Engine for APEX 2.0.

Provides atomic multi-file patch transactions with:
1. Transaction manifests and persistent journal logging.
2. Pre-modification cryptographic backups with SHA-256 verification.
3. Multi-file staging with atomic per-file os.replace swaps.
4. Auto-rollback of partially swapped files if any step fails during application.
5. Hardened rollback with conflict detection (never overwrites third-party modifications).
6. Multi-file post-apply verification and state persistence across DB and disk.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.services.remediation.patch_generator import CodePatch
from app.services.remediation.patch_integrity import compute_content_sha256
from app.services.remediation.repository_lock import RepositoryLockContext, RepositoryLockManager
from app.services.remediation.semantic_verifier import SemanticVerifier

logger = logging.getLogger(__name__)


class TransactionState(str, Enum):
    PREPARED = "PREPARED"
    STAGED = "STAGED"
    APPLYING = "APPLYING"
    COMMITTED = "COMMITTED"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"
    MANUAL_RECONCILIATION_REQUIRED = "MANUAL_RECONCILIATION_REQUIRED"


class RollbackConflictError(Exception):
    """Raised when attempting to roll back a transaction whose files were modified after application."""

    def __init__(self, message: str, conflicts: list[dict[str, Any]]):
        super().__init__(message)
        self.message = message
        self.conflicts = conflicts

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "ROLLBACK_CONFLICT",
            "message": self.message,
            "conflicts": self.conflicts,
        }


@dataclass
class FilePatchPlan:
    rel_path: str
    target_abs_path: str
    pre_content: str
    pre_hash: str
    post_content: str
    post_hash: str
    staged_path: str = ""
    backup_path: str = ""
    status: str = "PENDING"  # PENDING, STAGED, SWAPPED, RESTORED, CONFLICT

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MultiFileTransactionEngine:
    """Orchestrates atomic multi-file code modifications with rollback & journal safety."""

    @classmethod
    def _txn_dir(cls, repo_root: Path, transaction_id: str) -> Path:
        p = repo_root.resolve() / ".apex_backup" / "transactions" / transaction_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    @classmethod
    def _manifest_file(cls, repo_root: Path, transaction_id: str) -> Path:
        return cls._txn_dir(repo_root, transaction_id) / "manifest.json"

    @classmethod
    def _journal_file(cls, repo_root: Path, transaction_id: str) -> Path:
        return cls._txn_dir(repo_root, transaction_id) / "journal.json"

    @classmethod
    def _append_journal(cls, repo_root: Path, transaction_id: str, event_type: str, payload: dict[str, Any]) -> None:
        jf = cls._journal_file(repo_root, transaction_id)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "data": payload,
        }
        journal_entries = []
        if jf.exists():
            try:
                journal_entries = json.loads(jf.read_text(encoding="utf-8"))
            except Exception:
                journal_entries = []
        journal_entries.append(entry)
        tmp = jf.with_suffix(".tmp")
        tmp.write_text(json.dumps(journal_entries, indent=2), encoding="utf-8")
        tmp.replace(jf)

    @classmethod
    def get_journal(cls, repo_root: Path, transaction_id: str) -> list[dict[str, Any]]:
        jf = cls._journal_file(repo_root, transaction_id)
        if jf.exists():
            try:
                return json.loads(jf.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    @classmethod
    def save_manifest(cls, repo_root: Path, manifest: dict[str, Any]) -> None:
        mf = cls._manifest_file(repo_root, manifest["transaction_id"])
        tmp = mf.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        tmp.replace(mf)

    @classmethod
    def load_manifest(cls, repo_root: Path, transaction_id: str) -> dict[str, Any] | None:
        mf = cls._manifest_file(repo_root, transaction_id)
        if mf.exists():
            try:
                return json.loads(mf.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error("Error reading manifest %s: %s", transaction_id, e)
                return None
        return None

    @classmethod
    def prepare_transaction(
        cls,
        project_id: int,
        repo_root: Path | str,
        file_patches: list[dict[str, Any]],  # list of {"rel_path": str, "patched_content": str, finding_id: ...}
        user_id: int | None = None,
        db: Session | None = None,
    ) -> dict[str, Any]:
        """Validates all candidate files, pre-calculates hashes, creates pre-modification backups, and stages candidate files.
        
        Returns the transaction manifest dictionary.
        """
        repo_root_path = Path(repo_root).resolve()
        transaction_id = str(uuid.uuid4())
        txn_dir = cls._txn_dir(repo_root_path, transaction_id)
        staged_dir = txn_dir / "staged"
        backup_dir = txn_dir / "backups"
        staged_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.mkdir(parents=True, exist_ok=True)

        cls._append_journal(repo_root_path, transaction_id, "TXN_PREPARE_START", {"files_count": len(file_patches)})

        planned_files: list[dict[str, Any]] = []
        finding_ids: list[str] = []

        for item in file_patches:
            rel_path = item["rel_path"]
            patched_content = item["patched_content"]
            finding_id = item.get("finding_id", "unspecified")
            finding_ids.append(str(finding_id))

            target_abs = (repo_root_path / rel_path).resolve()
            # Directory traversal prevention
            if not str(target_abs).startswith(str(repo_root_path)):
                raise ValueError(f"Path traversal detected for file '{rel_path}'")

            if not target_abs.is_file():
                raise FileNotFoundError(f"Target file '{rel_path}' does not exist in repository.")

            # Read current content and calculate hash
            current_content = target_abs.read_text(encoding="utf-8", errors="ignore")
            pre_hash = compute_content_sha256(current_content)
            post_hash = compute_content_sha256(patched_content)

            # Check semantic validity of patched content if python file
            if rel_path.endswith(".py"):
                sem_res = SemanticVerifier.verify_semantics(
                    original_code=current_content,
                    patched_code=patched_content,
                )
                if not sem_res.valid:
                    raise ValueError(f"Semantic verification failed for '{rel_path}': {sem_res.summary}")

            # Backup original file to backup dir
            safe_rel = rel_path.replace("/", "_").replace("\\", "_")
            backup_file = backup_dir / f"{safe_rel}.bak"
            backup_file.write_text(current_content, encoding="utf-8")

            # Stage patched content to staging dir with fsync
            staged_file = staged_dir / f"{safe_rel}.staged"
            with open(staged_file, "w", encoding="utf-8") as f:
                f.write(patched_content)
                f.flush()
                os.fsync(f.fileno())

            planned_files.append({
                "rel_path": rel_path,
                "target_abs_path": str(target_abs),
                "pre_hash": pre_hash,
                "post_hash": post_hash,
                "staged_path": str(staged_file),
                "backup_path": str(backup_file),
                "status": "STAGED",
                "finding_id": str(finding_id),
            })

        manifest = {
            "transaction_id": transaction_id,
            "project_id": project_id,
            "user_id": user_id,
            "state": TransactionState.STAGED.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "files_count": len(planned_files),
            "files": planned_files,
            "finding_ids": finding_ids,
            "error_message": None,
            "post_verification": None,
        }

        cls.save_manifest(repo_root_path, manifest)
        cls._append_journal(repo_root_path, transaction_id, "TXN_STAGED", {"files_count": len(planned_files)})

        # Save to DB if available
        if db is not None:
            try:
                from app.models.entities import RemediationTransaction
                db_txn = RemediationTransaction(
                    transaction_id=transaction_id,
                    project_id=project_id,
                    user_id=user_id,
                    state=TransactionState.STAGED.value,
                    files_count=len(planned_files),
                    manifest=manifest,
                    journal=cls.get_journal(repo_root_path, transaction_id),
                )
                db.add(db_txn)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error("Failed to persist RemediationTransaction in DB: %s", e)

        return manifest

    @classmethod
    def apply_transaction(
        cls,
        project_id: int,
        repo_root: Path | str,
        transaction_id: str,
        acquired_by: str = "apex_remediation",
        db: Session | None = None,
        run_post_verification: bool = True,
    ) -> dict[str, Any]:
        """Atomically applies all staged files in the transaction under a repository lease lock.
        
        If an error occurs while replacing any file, all already swapped files are
        immediately rolled back using pre-modification backups.
        """
        repo_root_path = Path(repo_root).resolve()
        manifest = cls.load_manifest(repo_root_path, transaction_id)
        if not manifest:
            raise ValueError(f"Transaction manifest '{transaction_id}' not found.")

        if manifest["state"] not in (TransactionState.STAGED.value, TransactionState.PREPARED.value):
            raise ValueError(f"Transaction '{transaction_id}' is in state {manifest['state']}, cannot apply.")

        # Acquire repository lock
        with RepositoryLockContext(
            project_id=project_id,
            repo_path=repo_root_path,
            transaction_id=transaction_id,
            acquired_by=acquired_by,
            db=db,
        ):
            manifest["state"] = TransactionState.APPLYING.value
            manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
            cls.save_manifest(repo_root_path, manifest)
            cls._append_journal(repo_root_path, transaction_id, "TXN_APPLYING_START", {})

            swapped_files: list[dict[str, Any]] = []

            try:
                for file_info in manifest["files"]:
                    target_path = Path(file_info["target_abs_path"])
                    staged_path = Path(file_info["staged_path"])

                    # Re-verify stale patch check before replacement
                    current_content = target_path.read_text(encoding="utf-8", errors="ignore")
                    current_hash = compute_content_sha256(current_content)
                    if current_hash != file_info["pre_hash"]:
                        raise RuntimeError(
                            f"Stale file detected: '{file_info['rel_path']}' modified on disk "
                            f"(expected {file_info['pre_hash'][:8]}, found {current_hash[:8]})."
                        )

                    cls._append_journal(
                        repo_root_path,
                        transaction_id,
                        "FILE_SWAP_BEGIN",
                        {"file": file_info["rel_path"], "post_hash": file_info["post_hash"]},
                    )

                    # Atomic file swap
                    os.replace(staged_path, target_path)

                    file_info["status"] = "SWAPPED"
                    swapped_files.append(file_info)

                    cls._append_journal(
                        repo_root_path,
                        transaction_id,
                        "FILE_SWAP_SUCCESS",
                        {"file": file_info["rel_path"], "post_hash": file_info["post_hash"]},
                    )

                # All files swapped successfully: COMMIT
                manifest["state"] = TransactionState.COMMITTED.value
                manifest["updated_at"] = datetime.now(timezone.utc).isoformat()

                if run_post_verification:
                    # Multi-file verification
                    pv_result = cls._run_multi_file_verification(repo_root_path, manifest["files"])
                    manifest["post_verification"] = pv_result

                cls.save_manifest(repo_root_path, manifest)
                cls._append_journal(repo_root_path, transaction_id, "TXN_COMMITTED", {
                    "swapped_files_count": len(swapped_files),
                    "post_verification": manifest.get("post_verification"),
                })

                cls._sync_db_transaction(db, transaction_id, manifest, repo_root_path)
                return manifest

            except Exception as e:
                logger.error("Transaction %s failed during application: %s. Initiating auto-rollback.", transaction_id, e)
                manifest["state"] = TransactionState.ROLLING_BACK.value
                manifest["error_message"] = str(e)
                cls.save_manifest(repo_root_path, manifest)
                cls._append_journal(repo_root_path, transaction_id, "TXN_AUTO_ROLLBACK_START", {"error": str(e)})

                # Roll back already swapped files
                rollback_errors = []
                for swapped in reversed(swapped_files):
                    try:
                        target_p = Path(swapped["target_abs_path"])
                        backup_p = Path(swapped["backup_path"])
                        shutil.copy2(backup_p, target_p)
                        swapped["status"] = "RESTORED"
                        cls._append_journal(repo_root_path, transaction_id, "FILE_RESTORED", {"file": swapped["rel_path"]})
                    except Exception as rb_err:
                        rollback_errors.append(f"{swapped['rel_path']}: {rb_err}")

                manifest["state"] = TransactionState.FAILED.value
                if rollback_errors:
                    manifest["state"] = TransactionState.MANUAL_RECONCILIATION_REQUIRED.value
                    manifest["error_message"] = (
                        f"Application failed: {e}. Subsequent auto-rollback encountered errors: {'; '.join(rollback_errors)}"
                    )

                manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
                cls.save_manifest(repo_root_path, manifest)
                cls._append_journal(repo_root_path, transaction_id, "TXN_FAILED", {"state": manifest["state"]})
                cls._sync_db_transaction(db, transaction_id, manifest, repo_root_path)

                raise RuntimeError(f"Transaction application failed and was rolled back: {e}")

    @classmethod
    def rollback_transaction(
        cls,
        project_id: int,
        repo_root: Path | str,
        transaction_id: str,
        force: bool = False,
        acquired_by: str = "apex_rollback",
        db: Session | None = None,
    ) -> dict[str, Any]:
        """Rolls back a committed or partially applied transaction with SHA-256 conflict hardening.
        
        If any file was modified on disk since transaction application (hash != post_hash),
        raises RollbackConflictError without altering files unless force=True.
        """
        repo_root_path = Path(repo_root).resolve()
        manifest = cls.load_manifest(repo_root_path, transaction_id)
        if not manifest:
            raise ValueError(f"Transaction manifest '{transaction_id}' not found.")

        if manifest["state"] not in (TransactionState.COMMITTED.value, TransactionState.APPLYING.value):
            if manifest["state"] == TransactionState.ROLLED_BACK.value:
                return manifest  # Idempotent
            raise ValueError(f"Transaction '{transaction_id}' is in state {manifest['state']}, cannot rollback.")

        with RepositoryLockContext(
            project_id=project_id,
            repo_path=repo_root_path,
            transaction_id=transaction_id,
            acquired_by=acquired_by,
            db=db,
        ):
            # 1. Conflict detection phase
            conflicts: list[dict[str, Any]] = []
            for file_info in manifest["files"]:
                target_path = Path(file_info["target_abs_path"])
                if not target_path.exists():
                    conflicts.append({
                        "file": file_info["rel_path"],
                        "issue": "FILE_DELETED",
                        "expected_hash": file_info["post_hash"],
                        "current_hash": None,
                    })
                    continue

                curr_content = target_path.read_text(encoding="utf-8", errors="ignore")
                curr_hash = compute_content_sha256(curr_content)
                if curr_hash != file_info["post_hash"]:
                    conflicts.append({
                        "file": file_info["rel_path"],
                        "issue": "EXTERNAL_MODIFICATION",
                        "expected_hash": file_info["post_hash"],
                        "current_hash": curr_hash,
                    })

            if conflicts and not force:
                cls._append_journal(repo_root_path, transaction_id, "ROLLBACK_CONFLICT_DETECTED", {"conflicts": conflicts})
                raise RollbackConflictError(
                    message=f"Rollback rejected: {len(conflicts)} file(s) modified on disk since patch application.",
                    conflicts=conflicts,
                )

            # 2. Restoration phase
            manifest["state"] = TransactionState.ROLLING_BACK.value
            cls.save_manifest(repo_root_path, manifest)
            cls._append_journal(repo_root_path, transaction_id, "TXN_ROLLBACK_START", {"force": force})

            restored_files = []
            for file_info in manifest["files"]:
                target_path = Path(file_info["target_abs_path"])
                backup_path = Path(file_info["backup_path"])

                if not backup_path.exists():
                    raise FileNotFoundError(f"Missing backup file for '{file_info['rel_path']}'")

                # Restore backup
                shutil.copy2(backup_path, target_path)
                file_info["status"] = "RESTORED"
                restored_files.append(file_info["rel_path"])
                cls._append_journal(repo_root_path, transaction_id, "FILE_RESTORED", {"file": file_info["rel_path"]})

            manifest["state"] = TransactionState.ROLLED_BACK.value
            manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
            cls.save_manifest(repo_root_path, manifest)
            cls._append_journal(repo_root_path, transaction_id, "TXN_ROLLED_BACK", {"restored_files": restored_files})

            cls._sync_db_transaction(db, transaction_id, manifest, repo_root_path)
            return manifest

    @classmethod
    def _run_multi_file_verification(
        cls,
        repo_root: Path,
        files: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Runs post-apply verification across all modified files."""
        checked_files = []
        syntax_errors = []

        for f_info in files:
            rel = f_info["rel_path"]
            abs_p = Path(f_info["target_abs_path"])
            checked_files.append(rel)

            if rel.endswith(".py") and abs_p.is_file():
                try:
                    import ast
                    ast.parse(abs_p.read_text(encoding="utf-8", errors="ignore"))
                except SyntaxError as se:
                    syntax_errors.append(f"{rel}: SyntaxError at line {se.lineno}: {se.msg}")

        if syntax_errors:
            return {
                "status": "REGRESSION_DETECTED",
                "verified": False,
                "regressions": syntax_errors,
                "files_checked": checked_files,
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }

        return {
            "status": "NO_NEW_FINDINGS_DETECTED_BY_EXECUTED_ANALYZERS",
            "verified": True,
            "regressions": [],
            "files_checked": checked_files,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def _sync_db_transaction(
        cls,
        db: Session | None,
        transaction_id: str,
        manifest: dict[str, Any],
        repo_root: Path,
    ) -> None:
        if db is None:
            return
        try:
            from app.models.entities import RemediationTransaction
            db_txn = db.query(RemediationTransaction).filter(
                RemediationTransaction.transaction_id == transaction_id
            ).first()
            if db_txn:
                db_txn.state = manifest["state"]
                db_txn.files_count = manifest["files_count"]
                db_txn.manifest = manifest
                db_txn.journal = cls.get_journal(repo_root, transaction_id)
                db_txn.post_verification = manifest.get("post_verification")
                db_txn.error_message = manifest.get("error_message")
                db.commit()
        except Exception as e:
            db.rollback()
            logger.error("Failed to sync RemediationTransaction to DB: %s", e)
