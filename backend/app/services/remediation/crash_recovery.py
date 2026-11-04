"""Persistent Crash Recovery Engine for APEX 2.0 Remediation Transactions.

Discovers and safely reconciles interrupted or crashed remediation transactions
across application restarts, worker crashes, and interrupted file operations:
1. Multi-point crash analysis (pre-swap, partial-swap, post-swap, mid-rollback).
2. Disk & manifest reconciliation against real SHA-256 hashes.
3. External modification protection (never overwrites third-party modifications).
4. Automated startup discovery and safe recovery.
5. Fully idempotent recovery execution.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.services.remediation.patch_integrity import compute_content_sha256
from app.services.remediation.repository_lock import RepositoryLockManager
from app.services.remediation.transaction_engine import (
    MultiFileTransactionEngine,
    TransactionState,
)

logger = logging.getLogger(__name__)


class CrashRecoveryEngine:
    """Discovers, audits, and restores consistent state for interrupted transactions."""

    @classmethod
    def recover_transaction(
        cls,
        project_id: int,
        repo_root: Path | str,
        transaction_id: str,
        db: Session | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Reconciles a single transaction from disk manifest, journal, and current disk state.
        
        Idempotent: safe to invoke repeatedly on any transaction.
        """
        repo_root_path = Path(repo_root).resolve()
        manifest = MultiFileTransactionEngine.load_manifest(repo_root_path, transaction_id)
        if not manifest:
            return {
                "transaction_id": transaction_id,
                "project_id": project_id,
                "status": "NOT_FOUND",
                "action_taken": "NONE",
                "message": f"Transaction manifest '{transaction_id}' was not found.",
            }

        current_state = manifest.get("state", "UNKNOWN")

        # 1. Already terminal and clean states
        if current_state in (TransactionState.ROLLED_BACK.value, TransactionState.FAILED.value):
            # Clean up staged files if any remain
            cls._cleanup_staged_files(repo_root_path, transaction_id)
            RepositoryLockManager.release_lock(project_id, repo_root_path, transaction_id, db=db, force=True)
            return {
                "transaction_id": transaction_id,
                "project_id": project_id,
                "status": current_state,
                "action_taken": "NONE",
                "message": f"Transaction is already in terminal state '{current_state}'.",
            }

        # 2. Crash Point 1: PREPARED or STAGED (before any file swaps)
        if current_state in (TransactionState.PREPARED.value, TransactionState.STAGED.value):
            cls._cleanup_staged_files(repo_root_path, transaction_id)
            manifest["state"] = TransactionState.FAILED.value
            manifest["error_message"] = "Interrupted during staging/preparation. Staged files cleaned up."
            manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
            MultiFileTransactionEngine.save_manifest(repo_root_path, manifest)
            MultiFileTransactionEngine._append_journal(
                repo_root_path, transaction_id, "TXN_RECOVERED_STAGED", {"action": "CLEANUP_STAGED"}
            )
            MultiFileTransactionEngine._sync_db_transaction(db, transaction_id, manifest, repo_root_path)
            RepositoryLockManager.release_lock(project_id, repo_root_path, transaction_id, db=db, force=True)
            return {
                "transaction_id": transaction_id,
                "project_id": project_id,
                "status": TransactionState.FAILED.value,
                "action_taken": "CLEANED_STAGED_FILES",
                "message": "Cleaned up staged files for unapplied transaction.",
            }

        # 3. Crash Point 2 & 3: APPLYING or ROLLING_BACK
        if current_state in (TransactionState.APPLYING.value, TransactionState.ROLLING_BACK.value, TransactionState.COMMITTED.value):
            files = manifest.get("files", [])
            swapped_files = []
            unswapped_files = []
            third_party_modified = []

            for f_info in files:
                target_p = Path(f_info["target_abs_path"])
                if not target_p.exists():
                    third_party_modified.append({
                        "file": f_info["rel_path"],
                        "issue": "FILE_DELETED",
                    })
                    continue

                curr_content = target_p.read_text(encoding="utf-8", errors="ignore")
                curr_hash = compute_content_sha256(curr_content)

                if curr_hash == f_info["post_hash"]:
                    swapped_files.append(f_info)
                elif curr_hash == f_info["pre_hash"]:
                    unswapped_files.append(f_info)
                else:
                    third_party_modified.append({
                        "file": f_info["rel_path"],
                        "issue": "EXTERNAL_MODIFICATION",
                        "current_hash": curr_hash,
                        "expected_pre_hash": f_info["pre_hash"],
                        "expected_post_hash": f_info["post_hash"],
                    })

            # Crash Point 4: Third-party modification detected
            if third_party_modified and not force:
                manifest["state"] = TransactionState.MANUAL_RECONCILIATION_REQUIRED.value
                manifest["error_message"] = (
                    f"Third-party modifications detected on {len(third_party_modified)} file(s). Manual review required."
                )
                manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
                MultiFileTransactionEngine.save_manifest(repo_root_path, manifest)
                MultiFileTransactionEngine._append_journal(
                    repo_root_path, transaction_id, "TXN_RECOVERY_CONFLICT", {"conflicts": third_party_modified}
                )
                MultiFileTransactionEngine._sync_db_transaction(db, transaction_id, manifest, repo_root_path)
                RepositoryLockManager.release_lock(project_id, repo_root_path, transaction_id, db=db, force=True)
                return {
                    "transaction_id": transaction_id,
                    "project_id": project_id,
                    "status": TransactionState.MANUAL_RECONCILIATION_REQUIRED.value,
                    "action_taken": "FLAGGED_MANUAL_RECONCILIATION",
                    "conflicts": third_party_modified,
                    "message": "Files modified outside transaction. Backups retained. Manual reconciliation required.",
                }

            # All files match post_hash: transaction actually succeeded before crash
            if len(swapped_files) == len(files) and current_state != TransactionState.ROLLING_BACK.value:
                manifest["state"] = TransactionState.COMMITTED.value
                manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
                cls._cleanup_staged_files(repo_root_path, transaction_id)
                MultiFileTransactionEngine.save_manifest(repo_root_path, manifest)
                MultiFileTransactionEngine._append_journal(
                    repo_root_path, transaction_id, "TXN_RECOVERED_COMMITTED", {"all_files_matched_post_hash": True}
                )
                MultiFileTransactionEngine._sync_db_transaction(db, transaction_id, manifest, repo_root_path)
                RepositoryLockManager.release_lock(project_id, repo_root_path, transaction_id, db=db, force=True)
                return {
                    "transaction_id": transaction_id,
                    "project_id": project_id,
                    "status": TransactionState.COMMITTED.value,
                    "action_taken": "CONFIRMED_COMMITTED",
                    "message": "All files verified to match target post-patch state. Transaction committed.",
                }

            # Partial application or rolling back: restore files from backups
            files_to_restore = files if force else swapped_files
            restored = []
            for f_info in files_to_restore:
                target_p = Path(f_info["target_abs_path"])
                backup_p = Path(f_info["backup_path"])
                if backup_p.is_file():
                    shutil.copy2(backup_p, target_p)
                    f_info["status"] = "RESTORED"
                    restored.append(f_info["rel_path"])

            cls._cleanup_staged_files(repo_root_path, transaction_id)
            manifest["state"] = TransactionState.ROLLED_BACK.value
            manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
            MultiFileTransactionEngine.save_manifest(repo_root_path, manifest)
            MultiFileTransactionEngine._append_journal(
                repo_root_path, transaction_id, "TXN_RECOVERED_ROLLED_BACK", {"restored_files": restored}
            )
            MultiFileTransactionEngine._sync_db_transaction(db, transaction_id, manifest, repo_root_path)
            RepositoryLockManager.release_lock(project_id, repo_root_path, transaction_id, db=db, force=True)
            return {
                "transaction_id": transaction_id,
                "project_id": project_id,
                "status": TransactionState.ROLLED_BACK.value,
                "action_taken": "ROLLED_BACK_PARTIAL_SWAPS",
                "restored_files": restored,
                "message": f"Safely restored {len(restored)} partially swapped files to clean pre-transaction baseline.",
            }

        return {
            "transaction_id": transaction_id,
            "project_id": project_id,
            "status": current_state,
            "action_taken": "NONE",
            "message": f"No action needed for transaction in state {current_state}.",
        }

    @classmethod
    def _cleanup_staged_files(cls, repo_root: Path, transaction_id: str) -> None:
        txn_dir = repo_root / ".apex_backup" / "transactions" / transaction_id
        staged_dir = txn_dir / "staged"
        if staged_dir.is_dir():
            try:
                shutil.rmtree(staged_dir)
            except Exception as e:
                logger.warning("Failed to remove staged dir %s: %s", staged_dir, e)

    @classmethod
    def scan_and_recover_project(
        cls,
        project_id: int,
        repo_root: Path | str,
        db: Session | None = None,
    ) -> dict[str, Any]:
        """Scans project repository and database for dangling locks and incomplete transactions."""
        repo_root_path = Path(repo_root).resolve()
        recovered = []
        conflicts = []

        # 1. Break stale locks if process dead or expired
        stale_broken = False
        lock_info = RepositoryLockManager.inspect_lock(project_id, repo_root_path, db=db)
        if lock_info.get("is_stale"):
            RepositoryLockManager.break_stale_lock(project_id, repo_root_path, db=db, force=True)
            stale_broken = True

        # 2. Check disk transactions
        txns_dir = repo_root_path / ".apex_backup" / "transactions"
        txn_ids = set()
        if txns_dir.is_dir():
            for child in txns_dir.iterdir():
                if child.is_dir() and (child / "manifest.json").is_file():
                    txn_ids.add(child.name)

        # 3. Check DB transactions
        if db is not None:
            try:
                from app.models.entities import RemediationTransaction
                db_txns = db.query(RemediationTransaction).filter(
                    RemediationTransaction.project_id == project_id,
                    RemediationTransaction.state.in_([
                        TransactionState.PREPARED.value,
                        TransactionState.STAGED.value,
                        TransactionState.APPLYING.value,
                        TransactionState.ROLLING_BACK.value,
                    ])
                ).all()
                for dt in db_txns:
                    txn_ids.add(dt.transaction_id)
            except Exception as e:
                logger.error("DB error fetching transactions for project %s: %s", project_id, e)

        for txn_id in sorted(txn_ids):
            manifest = MultiFileTransactionEngine.load_manifest(repo_root_path, txn_id)
            if not manifest:
                continue
            state = manifest.get("state")
            if state in (TransactionState.PREPARED.value, TransactionState.STAGED.value, TransactionState.APPLYING.value, TransactionState.ROLLING_BACK.value):
                res = cls.recover_transaction(project_id, repo_root_path, txn_id, db=db)
                if res.get("status") == TransactionState.MANUAL_RECONCILIATION_REQUIRED.value:
                    conflicts.append(res)
                else:
                    recovered.append(res)

        return {
            "project_id": project_id,
            "stale_lock_cleared": stale_broken,
            "recovered_transactions_count": len(recovered),
            "recovered_transactions": recovered,
            "manual_reconciliation_needed": conflicts,
        }

    @classmethod
    def reconcile_on_startup(cls, db_session_factory: Any = None) -> list[dict[str, Any]]:
        """Invoked during application boot to discover and heal any interrupted transactions."""
        logger.info("APEX 2.0 Crash Recovery: starting boot-time repository scan.")
        results = []
        if db_session_factory is None:
            from app.db.session import SessionLocal
            db_session_factory = SessionLocal

        db = db_session_factory()
        try:
            from app.models.entities import ReviewedProject
            projects = db.query(ReviewedProject).filter(ReviewedProject.is_archived == False).all()
            for proj in projects:
                repo_path = Path(proj.repository_path)
                if repo_path.is_dir():
                    try:
                        res = cls.scan_and_recover_project(proj.id, repo_path, db=db)
                        if res["recovered_transactions_count"] > 0 or res["stale_lock_cleared"]:
                            logger.warning(
                                "Recovered project %s (%s): %s transactions reconciled, lock cleared=%s",
                                proj.id, proj.name, res["recovered_transactions_count"], res["stale_lock_cleared"],
                            )
                        results.append(res)
                    except Exception as err:
                        logger.error("Failed startup recovery for project %s: %s", proj.id, err)
        except Exception as e:
            logger.error("Startup reconciliation failed: %s", e)
        finally:
            db.close()

        logger.info("APEX 2.0 Crash Recovery: boot scan completed. Scanned %s projects.", len(results))
        return results
