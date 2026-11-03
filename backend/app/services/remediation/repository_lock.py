"""Distributed Concurrency Safety & Repository Lease Locking for APEX 2.0.

Ensures that only one remediation transaction can modify a repository at any given
time. Implements two-level coordination across the database (RemediationLockRecord)
and the filesystem (.apex_backup/remediation_lease.json) with lease timeouts,
dead PID / stale process detection, re-entrant transaction leasing, and HTTP 409
conflict mapping.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class LockAcquisitionError(Exception):
    """Raised when repository lock acquisition fails due to an active concurrent transaction."""

    def __init__(
        self,
        message: str,
        project_id: int,
        transaction_id: str | None = None,
        holder: str | None = None,
        expires_at: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.project_id = project_id
        self.transaction_id = transaction_id
        self.holder = holder
        self.expires_at = expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "REPOSITORY_LOCKED",
            "message": self.message,
            "project_id": self.project_id,
            "transaction_id": self.transaction_id,
            "holder": self.holder,
            "expires_at": self.expires_at,
        }


def _is_pid_alive(pid: int) -> bool:
    """Checks whether the process with PID is currently alive on the host."""
    if pid <= 0:
        return False
    try:
        # On Windows / Unix:
        if os.name == "nt":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x00100000
            process = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if process != 0:
                kernel32.CloseHandle(process)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, Exception):
        return False


class RepositoryLockManager:
    """Manages lease-based repository locks with crash resilience and stale lock eviction."""

    DEFAULT_LEASE_SECONDS = 60

    @classmethod
    def _lease_file_path(cls, repo_path: Path | str) -> Path:
        p = Path(repo_path).resolve()
        lock_dir = p / ".apex_backup"
        lock_dir.mkdir(parents=True, exist_ok=True)
        return lock_dir / "remediation_lease.json"

    @classmethod
    def inspect_lock(
        cls,
        project_id: int,
        repo_path: Path | str,
        db: Session | None = None,
    ) -> dict[str, Any]:
        """Inspects lock state across both DB and filesystem."""
        now = datetime.now(timezone.utc)
        file_path = cls._lease_file_path(repo_path)
        file_data: dict[str, Any] = {}
        if file_path.exists():
            try:
                file_data = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Failed to parse filesystem lease file: %s", e)

        db_record = None
        if db is not None:
            try:
                from app.models.entities import RemediationLockRecord
                db_record = db.query(RemediationLockRecord).filter(
                    RemediationLockRecord.project_id == project_id
                ).first()
            except Exception as e:
                logger.warning("Error querying DB lock record: %s", e)

        if not file_data and not db_record:
            return {
                "is_locked": False,
                "project_id": project_id,
                "transaction_id": None,
                "holder": None,
                "expires_at": None,
                "is_stale": False,
            }

        # Resolve active data
        txn_id = file_data.get("transaction_id") or (db_record.transaction_id if db_record else None)
        holder = file_data.get("acquired_by") or (db_record.acquired_by if db_record else None)
        exp_iso = file_data.get("expires_at")
        if not exp_iso and db_record:
            exp_iso = db_record.lease_expires_at.isoformat()

        # Check expiration
        is_stale = False
        if exp_iso:
            try:
                dt = datetime.fromisoformat(exp_iso)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt <= now:
                    is_stale = True
            except Exception:
                is_stale = True

        pid = file_data.get("pid")
        if pid and not _is_pid_alive(int(pid)):
            is_stale = True

        return {
            "is_locked": not is_stale,
            "project_id": project_id,
            "transaction_id": txn_id,
            "holder": holder,
            "expires_at": exp_iso,
            "is_stale": is_stale,
            "pid": pid,
        }

    @classmethod
    def acquire_lock(
        cls,
        project_id: int,
        repo_path: Path | str,
        transaction_id: str,
        acquired_by: str = "apex_worker",
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        db: Session | None = None,
    ) -> dict[str, Any]:
        """Attempts to acquire or re-enter the repository lease lock.
        
        Raises LockAcquisitionError if an active transaction currently holds the lease.
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=lease_seconds)
        info = cls.inspect_lock(project_id, repo_path, db=db)

        if info["is_locked"]:
            # Check re-entrancy for same transaction
            if info["transaction_id"] == transaction_id:
                logger.info("Re-entering/extending lease for transaction %s", transaction_id)
            else:
                msg = (
                    f"Repository for project {project_id} is locked by active transaction "
                    f"'{info['transaction_id']}' (held by {info['holder']}) until {info['expires_at']}."
                )
                raise LockAcquisitionError(
                    message=msg,
                    project_id=project_id,
                    transaction_id=info["transaction_id"],
                    holder=info["holder"],
                    expires_at=info["expires_at"],
                )

        # Stale or unlocked: safely acquire
        lock_data = {
            "project_id": project_id,
            "transaction_id": transaction_id,
            "acquired_by": acquired_by,
            "pid": os.getpid(),
            "acquired_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

        # Write to filesystem
        file_path = cls._lease_file_path(repo_path)
        tmp_file = file_path.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(lock_data, indent=2), encoding="utf-8")
        tmp_file.replace(file_path)

        # Write to DB if session provided
        if db is not None:
            try:
                from app.models.entities import RemediationLockRecord
                rec = db.query(RemediationLockRecord).filter(
                    RemediationLockRecord.project_id == project_id
                ).first()
                if rec:
                    rec.transaction_id = transaction_id
                    rec.acquired_by = acquired_by
                    rec.lease_expires_at = expires_at.replace(tzinfo=None)
                else:
                    rec = RemediationLockRecord(
                        project_id=project_id,
                        transaction_id=transaction_id,
                        acquired_by=acquired_by,
                        lease_expires_at=expires_at.replace(tzinfo=None),
                    )
                    db.add(rec)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error("Failed to commit DB lock record: %s", e)

        return lock_data

    @classmethod
    def release_lock(
        cls,
        project_id: int,
        repo_path: Path | str,
        transaction_id: str,
        db: Session | None = None,
        force: bool = False,
    ) -> bool:
        """Releases the repository lock if held by transaction_id or if force=True."""
        file_path = cls._lease_file_path(repo_path)
        released = False

        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                if force or data.get("transaction_id") == transaction_id:
                    file_path.unlink(missing_ok=True)
                    released = True
            except Exception as e:
                logger.warning("Error releasing filesystem lock: %s", e)
                if force:
                    file_path.unlink(missing_ok=True)
                    released = True

        if db is not None:
            try:
                from app.models.entities import RemediationLockRecord
                rec = db.query(RemediationLockRecord).filter(
                    RemediationLockRecord.project_id == project_id
                ).first()
                if rec and (force or rec.transaction_id == transaction_id):
                    db.delete(rec)
                    db.commit()
                    released = True
            except Exception as e:
                db.rollback()
                logger.error("Failed to delete DB lock record: %s", e)

        return released

    @classmethod
    def break_stale_lock(
        cls,
        project_id: int,
        repo_path: Path | str,
        db: Session | None = None,
        force: bool = False,
    ) -> tuple[bool, str]:
        """Evicts a lock if stale (or forcibly if force=True)."""
        info = cls.inspect_lock(project_id, repo_path, db=db)
        if not info["is_locked"] and not force and not info["is_stale"]:
            return False, "Repository is not locked."

        if not info["is_stale"] and not force:
            return False, f"Lock is currently active (held by {info['holder']}). Cannot break without force."

        cls.release_lock(
            project_id=project_id,
            repo_path=repo_path,
            transaction_id=info["transaction_id"] or "",
            db=db,
            force=True,
        )
        return True, f"Successfully broke stale lock for project {project_id}."


class RepositoryLockContext:
    """Context manager for acquiring and releasing repository locks cleanly."""

    def __init__(
        self,
        project_id: int,
        repo_path: Path | str,
        transaction_id: str,
        acquired_by: str = "apex_worker",
        lease_seconds: int = RepositoryLockManager.DEFAULT_LEASE_SECONDS,
        db: Session | None = None,
    ):
        self.project_id = project_id
        self.repo_path = repo_path
        self.transaction_id = transaction_id
        self.acquired_by = acquired_by
        self.lease_seconds = lease_seconds
        self.db = db
        self.acquired = False

    def __enter__(self):
        RepositoryLockManager.acquire_lock(
            project_id=self.project_id,
            repo_path=self.repo_path,
            transaction_id=self.transaction_id,
            acquired_by=self.acquired_by,
            lease_seconds=self.lease_seconds,
            db=self.db,
        )
        self.acquired = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            RepositoryLockManager.release_lock(
                project_id=self.project_id,
                repo_path=self.repo_path,
                transaction_id=self.transaction_id,
                db=self.db,
            )
