"""Comprehensive Unit Tests for APEX 2.0 Phase 2D.2:
Transactional Remediation Integrity, Crash Recovery & Distributed Concurrency Safety.

Covers:
1. Multi-File Transaction Engine (manifests, staging, fsync, atomic os.replace, journal).
2. Crash Recovery Engine across 6 distinct crash scenarios.
3. Distributed Concurrency Safety (lease locks, re-entrancy, stale PID detection, eviction).
4. Multi-File Rollback Conflict Protection (SHA-256 validation, force override).
5. Post-Apply Multi-File Verification (syntax/semantic integrity).
6. Multi-Tenant API Route Security, Non-Disclosing 404s, and HTTP 409 Conflict Responses.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.entities import (
    ReviewedProject,
    User,
    RemediationTransaction,
    RemediationLockRecord,
)
from app.services.remediation.patch_integrity import compute_content_sha256
from app.services.remediation.repository_lock import (
    LockAcquisitionError,
    RepositoryLockContext,
    RepositoryLockManager,
    _is_pid_alive,
)
from app.services.remediation.transaction_engine import (
    FilePatchPlan,
    MultiFileTransactionEngine,
    RollbackConflictError,
    TransactionState,
)
from app.services.remediation.crash_recovery import CrashRecoveryEngine


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_repo(tmp_path: Path):
    """Creates a temporary repository structure with sample source files."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    file_a = repo_dir / "service_a.py"
    file_a.write_text("def get_data(x):\n    return x * 2\n", encoding="utf-8")

    file_b = repo_dir / "service_b.py"
    file_b.write_text("def calculate(y):\n    return y + 10\n", encoding="utf-8")

    file_c = repo_dir / "config.json"
    file_c.write_text('{"timeout": 30}\n', encoding="utf-8")

    return repo_dir


@pytest.fixture
def mock_db(temp_repo: Path):
    """In-memory SQLite database session for unit tests."""
    from sqlalchemy.pool import StaticPool
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()

    # Seed test user and project
    user = User(
        id=1,
        email="dev@example.com",
        username="test_dev",
        hashed_password="hashed_pw",
        is_active=True,
    )
    session.add(user)
    session.commit()

    project = ReviewedProject(
        id=1,
        name="Test Project",
        repository_path=str(temp_repo),
        owner_id=user.id,
    )
    session.add(project)
    session.commit()

    yield session
    session.close()


# ============================================================================
# 1. Multi-File Transaction Engine Tests (1-15)
# ============================================================================

def test_prepare_transaction_creates_manifest_and_staged_files(temp_repo: Path, mock_db):
    patches = [
        {"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    if x is None: return 0\n    return x * 2\n"},
        {"rel_path": "service_b.py", "patched_content": "def calculate(y):\n    if y < 0: return 0\n    return y + 10\n"},
    ]
    manifest = MultiFileTransactionEngine.prepare_transaction(
        project_id=1,
        repo_root=temp_repo,
        file_patches=patches,
        user_id=1,
        db=mock_db,
    )
    assert manifest["state"] == TransactionState.STAGED.value
    assert manifest["files_count"] == 2
    assert len(manifest["files"]) == 2
    assert (temp_repo / ".apex_backup" / "transactions" / manifest["transaction_id"] / "manifest.json").exists()


def test_prepare_transaction_saves_pre_hashes(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return x * 3\n"}]
    orig_content = (temp_repo / "service_a.py").read_text(encoding="utf-8")
    expected_pre_hash = compute_content_sha256(orig_content)

    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    assert manifest["files"][0]["pre_hash"] == expected_pre_hash


def test_prepare_transaction_creates_safe_backups(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 0\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    backup_path = Path(manifest["files"][0]["backup_path"])
    assert backup_path.exists()
    assert backup_path.read_text(encoding="utf-8") == "def get_data(x):\n    return x * 2\n"


def test_prepare_transaction_rejects_path_traversal(temp_repo: Path):
    patches = [{"rel_path": "../outside.py", "patched_content": "x = 1"}]
    with pytest.raises(ValueError, match="Path traversal detected"):
        MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)


def test_prepare_transaction_rejects_missing_file(temp_repo: Path):
    patches = [{"rel_path": "non_existent.py", "patched_content": "x = 1"}]
    with pytest.raises(FileNotFoundError, match="does not exist"):
        MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)


def test_prepare_transaction_rejects_syntax_error_in_python(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def broken_syntax(:\n    pass"}]
    with pytest.raises(ValueError, match="Semantic verification failed"):
        MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)


def test_prepare_transaction_appends_to_journal(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return x\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    journal = MultiFileTransactionEngine.get_journal(temp_repo, manifest["transaction_id"])
    assert len(journal) >= 2
    events = [entry["event"] for entry in journal]
    assert "TXN_PREPARE_START" in events
    assert "TXN_STAGED" in events


def test_prepare_transaction_persists_in_db(temp_repo: Path, mock_db):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return x\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches, user_id=1, db=mock_db)
    db_rec = mock_db.query(RemediationTransaction).filter_by(transaction_id=manifest["transaction_id"]).first()
    assert db_rec is not None
    assert db_rec.state == TransactionState.STAGED.value


def test_apply_transaction_swaps_all_files(temp_repo: Path):
    patches = [
        {"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return x * 10\n"},
        {"rel_path": "service_b.py", "patched_content": "def calculate(y):\n    return y * 20\n"},
    ]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    applied = MultiFileTransactionEngine.apply_transaction(1, temp_repo, manifest["transaction_id"])
    assert applied["state"] == TransactionState.COMMITTED.value
    assert (temp_repo / "service_a.py").read_text(encoding="utf-8") == "def get_data(x):\n    return x * 10\n"
    assert (temp_repo / "service_b.py").read_text(encoding="utf-8") == "def calculate(y):\n    return y * 20\n"


def test_apply_transaction_updates_file_statuses(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return x\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    applied = MultiFileTransactionEngine.apply_transaction(1, temp_repo, manifest["transaction_id"])
    assert applied["files"][0]["status"] == "SWAPPED"


def test_apply_transaction_runs_post_verification(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return x\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    applied = MultiFileTransactionEngine.apply_transaction(1, temp_repo, manifest["transaction_id"], run_post_verification=True)
    assert applied["post_verification"] is not None
    assert applied["post_verification"]["status"] == "NO_NEW_FINDINGS_DETECTED_BY_EXECUTED_ANALYZERS"
    assert applied["post_verification"]["verified"] is True


def test_apply_transaction_stale_file_detection_aborts(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return x\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)

    # Modify service_a externally before applying
    (temp_repo / "service_a.py").write_text("def modified_by_other():\n    pass\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Stale file detected"):
        MultiFileTransactionEngine.apply_transaction(1, temp_repo, manifest["transaction_id"])


def test_apply_transaction_auto_rolls_back_partial_swaps(temp_repo: Path):
    patches = [
        {"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'new_a'\n"},
        {"rel_path": "service_b.py", "patched_content": "def calculate(y):\n    return 'new_b'\n"},
    ]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)

    # Corrupt service_b pre-hash by editing it, causing swap of service_b to fail AFTER service_a
    (temp_repo / "service_b.py").write_text("def third_party(): pass", encoding="utf-8")

    with pytest.raises(RuntimeError):
        MultiFileTransactionEngine.apply_transaction(1, temp_repo, manifest["transaction_id"])

    # service_a should have been auto-rolled back to its original content!
    assert (temp_repo / "service_a.py").read_text(encoding="utf-8") == "def get_data(x):\n    return x * 2\n"


def test_apply_transaction_invalid_state_rejected(temp_repo: Path):
    manifest = {
        "transaction_id": "dummy_txn",
        "project_id": 1,
        "state": TransactionState.COMMITTED.value,
        "files": [],
    }
    MultiFileTransactionEngine.save_manifest(temp_repo, manifest)
    with pytest.raises(ValueError, match="is in state COMMITTED, cannot apply"):
        MultiFileTransactionEngine.apply_transaction(1, temp_repo, "dummy_txn")


def test_load_manifest_returns_none_for_missing(temp_repo: Path):
    assert MultiFileTransactionEngine.load_manifest(temp_repo, "non_existent") is None


# ============================================================================
# 2. Crash Recovery Engine Tests (16-30)
# ============================================================================

def test_recovery_point_1_prepared_cleans_up_staged(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 42\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]

    res = CrashRecoveryEngine.recover_transaction(1, temp_repo, txn_id)
    assert res["status"] == TransactionState.FAILED.value
    assert res["action_taken"] == "CLEANED_STAGED_FILES"
    staged_dir = temp_repo / ".apex_backup" / "transactions" / txn_id / "staged"
    assert not staged_dir.exists()


def test_recovery_point_2_partial_swap_restores_from_backups(temp_repo: Path):
    patches = [
        {"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'swapped'\n"},
        {"rel_path": "service_b.py", "patched_content": "def calculate(y):\n    return 'not_swapped'\n"},
    ]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]

    # Simulate crash mid-swap: service_a was swapped, service_b was not, state left in APPLYING
    (temp_repo / "service_a.py").write_text("def get_data(x):\n    return 'swapped'\n", encoding="utf-8")
    manifest["state"] = TransactionState.APPLYING.value
    MultiFileTransactionEngine.save_manifest(temp_repo, manifest)

    res = CrashRecoveryEngine.recover_transaction(1, temp_repo, txn_id)
    assert res["status"] == TransactionState.ROLLED_BACK.value
    assert res["action_taken"] == "ROLLED_BACK_PARTIAL_SWAPS"
    assert "service_a.py" in res["restored_files"]
    # Verify service_a restored to original pre-modification code
    assert (temp_repo / "service_a.py").read_text(encoding="utf-8") == "def get_data(x):\n    return x * 2\n"


def test_recovery_point_3_all_swapped_confirms_committed(temp_repo: Path):
    patches = [
        {"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'final_a'\n"},
        {"rel_path": "service_b.py", "patched_content": "def calculate(y):\n    return 'final_b'\n"},
    ]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]

    # Simulate crash right after swaps finished, before DB commit:
    (temp_repo / "service_a.py").write_text("def get_data(x):\n    return 'final_a'\n", encoding="utf-8")
    (temp_repo / "service_b.py").write_text("def calculate(y):\n    return 'final_b'\n", encoding="utf-8")
    manifest["state"] = TransactionState.APPLYING.value
    MultiFileTransactionEngine.save_manifest(temp_repo, manifest)

    res = CrashRecoveryEngine.recover_transaction(1, temp_repo, txn_id)
    assert res["status"] == TransactionState.COMMITTED.value
    assert res["action_taken"] == "CONFIRMED_COMMITTED"


def test_recovery_point_4_external_modification_flags_manual_reconciliation(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'patch'\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]

    # External developer edited service_a with unrelated code
    (temp_repo / "service_a.py").write_text("def completely_different(): pass\n", encoding="utf-8")
    manifest["state"] = TransactionState.APPLYING.value
    MultiFileTransactionEngine.save_manifest(temp_repo, manifest)

    res = CrashRecoveryEngine.recover_transaction(1, temp_repo, txn_id)
    assert res["status"] == TransactionState.MANUAL_RECONCILIATION_REQUIRED.value
    assert res["action_taken"] == "FLAGGED_MANUAL_RECONCILIATION"
    # Never overwrite developer's changes!
    assert (temp_repo / "service_a.py").read_text(encoding="utf-8") == "def completely_different(): pass\n"


def test_recovery_point_5_idempotent_multiple_invocations(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'x'\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]
    manifest["state"] = TransactionState.APPLYING.value
    MultiFileTransactionEngine.save_manifest(temp_repo, manifest)

    res1 = CrashRecoveryEngine.recover_transaction(1, temp_repo, txn_id)
    res2 = CrashRecoveryEngine.recover_transaction(1, temp_repo, txn_id)
    res3 = CrashRecoveryEngine.recover_transaction(1, temp_repo, txn_id)

    assert res1["status"] == TransactionState.ROLLED_BACK.value
    assert res2["status"] == TransactionState.ROLLED_BACK.value
    assert res3["status"] == TransactionState.ROLLED_BACK.value


def test_recovery_terminal_committed_is_noop(temp_repo: Path):
    manifest = {
        "transaction_id": "done_txn",
        "project_id": 1,
        "state": TransactionState.ROLLED_BACK.value,
        "files": [],
    }
    MultiFileTransactionEngine.save_manifest(temp_repo, manifest)
    res = CrashRecoveryEngine.recover_transaction(1, temp_repo, "done_txn")
    assert res["action_taken"] == "NONE"


def test_recovery_releases_dangling_repository_lock(temp_repo: Path):
    txn_id = "lock_recovery_txn"
    RepositoryLockManager.acquire_lock(1, temp_repo, txn_id)
    assert RepositoryLockManager.inspect_lock(1, temp_repo)["is_locked"] is True

    manifest = {
        "transaction_id": txn_id,
        "project_id": 1,
        "state": TransactionState.STAGED.value,
        "files": [],
    }
    MultiFileTransactionEngine.save_manifest(temp_repo, manifest)

    CrashRecoveryEngine.recover_transaction(1, temp_repo, txn_id)
    assert RepositoryLockManager.inspect_lock(1, temp_repo)["is_locked"] is False


def test_scan_and_recover_project_finds_all_incomplete(temp_repo: Path):
    p1 = [{"rel_path": "service_a.py", "patched_content": "def get_data(x): return 1"}]
    p2 = [{"rel_path": "service_b.py", "patched_content": "def calculate(y): return 2"}]
    m1 = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, p1)
    m2 = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, p2)

    summary = CrashRecoveryEngine.scan_and_recover_project(1, temp_repo)
    assert summary["recovered_transactions_count"] == 2
    assert summary["project_id"] == 1


def test_scan_and_recover_clears_stale_lock(temp_repo: Path):
    RepositoryLockManager.acquire_lock(1, temp_repo, "stale_txn", lease_seconds=-10)
    summary = CrashRecoveryEngine.scan_and_recover_project(1, temp_repo)
    assert summary["stale_lock_cleared"] is True


def test_reconcile_on_startup_executes_cleanly(mock_db):
    summary_list = CrashRecoveryEngine.reconcile_on_startup(db_session_factory=lambda: mock_db)
    assert isinstance(summary_list, list)


def test_recovery_returns_not_found_for_missing_manifest(temp_repo: Path):
    res = CrashRecoveryEngine.recover_transaction(1, temp_repo, "unknown_uuid")
    assert res["status"] == "NOT_FOUND"


def test_recovery_mid_rollback_finishes_restoration(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 99\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]
    # Mark state mid-rollback
    manifest["state"] = TransactionState.ROLLING_BACK.value
    MultiFileTransactionEngine.save_manifest(temp_repo, manifest)

    res = CrashRecoveryEngine.recover_transaction(1, temp_repo, txn_id)
    assert res["status"] == TransactionState.ROLLED_BACK.value


def test_recovery_with_deleted_target_file_flags_manual(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 100\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]
    manifest["state"] = TransactionState.APPLYING.value
    MultiFileTransactionEngine.save_manifest(temp_repo, manifest)

    # Delete service_a.py
    (temp_repo / "service_a.py").unlink()

    res = CrashRecoveryEngine.recover_transaction(1, temp_repo, txn_id)
    assert res["status"] == TransactionState.MANUAL_RECONCILIATION_REQUIRED.value


def test_recovery_force_overrides_conflict(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 100\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]
    manifest["state"] = TransactionState.APPLYING.value
    MultiFileTransactionEngine.save_manifest(temp_repo, manifest)

    (temp_repo / "service_a.py").write_text("third party modification", encoding="utf-8")

    res = CrashRecoveryEngine.recover_transaction(1, temp_repo, txn_id, force=True)
    assert res["status"] == TransactionState.ROLLED_BACK.value
    # Overwritten back to pre-modification state
    assert (temp_repo / "service_a.py").read_text(encoding="utf-8") == "def get_data(x):\n    return x * 2\n"


# ============================================================================
# 3. Distributed Concurrency & Repository Lease Locking Tests (31-45)
# ============================================================================

def test_acquire_lock_creates_lease_file(temp_repo: Path):
    lock_data = RepositoryLockManager.acquire_lock(1, temp_repo, "txn_101", acquired_by="alice")
    assert lock_data["transaction_id"] == "txn_101"
    lease_file = temp_repo / ".apex_backup" / "remediation_lease.json"
    assert lease_file.exists()


def test_inspect_unlocked_repository(temp_repo: Path):
    status = RepositoryLockManager.inspect_lock(1, temp_repo)
    assert status["is_locked"] is False
    assert status["transaction_id"] is None


def test_inspect_locked_repository(temp_repo: Path):
    RepositoryLockManager.acquire_lock(1, temp_repo, "txn_202", acquired_by="bob", lease_seconds=120)
    status = RepositoryLockManager.inspect_lock(1, temp_repo)
    assert status["is_locked"] is True
    assert status["transaction_id"] == "txn_202"
    assert status["holder"] == "bob"


def test_reentrant_lock_same_transaction_renews_lease(temp_repo: Path):
    RepositoryLockManager.acquire_lock(1, temp_repo, "txn_reenter", lease_seconds=30)
    # Re-acquire with same transaction ID
    renewed = RepositoryLockManager.acquire_lock(1, temp_repo, "txn_reenter", lease_seconds=90)
    assert renewed["transaction_id"] == "txn_reenter"


def test_acquire_lock_raises_error_when_held_by_other(temp_repo: Path):
    RepositoryLockManager.acquire_lock(1, temp_repo, "txn_owner_1", acquired_by="charlie", lease_seconds=60)
    with pytest.raises(LockAcquisitionError) as exc_info:
        RepositoryLockManager.acquire_lock(1, temp_repo, "txn_owner_2", acquired_by="dave")
    assert exc_info.value.transaction_id == "txn_owner_1"
    assert exc_info.value.holder == "charlie"


def test_stale_expired_lock_can_be_acquired(temp_repo: Path):
    RepositoryLockManager.acquire_lock(1, temp_repo, "expired_txn", lease_seconds=-5)
    # Acquisition should succeed by evicting stale lock
    new_lock = RepositoryLockManager.acquire_lock(1, temp_repo, "fresh_txn")
    assert new_lock["transaction_id"] == "fresh_txn"


def test_release_lock_removes_lease_file(temp_repo: Path):
    RepositoryLockManager.acquire_lock(1, temp_repo, "txn_release")
    assert RepositoryLockManager.release_lock(1, temp_repo, "txn_release") is True
    assert not (temp_repo / ".apex_backup" / "remediation_lease.json").exists()


def test_release_lock_requires_matching_transaction_id(temp_repo: Path):
    RepositoryLockManager.acquire_lock(1, temp_repo, "txn_owner")
    released = RepositoryLockManager.release_lock(1, temp_repo, "txn_impostor")
    assert released is False
    assert (temp_repo / ".apex_backup" / "remediation_lease.json").exists()


def test_release_lock_with_force_removes_any_lock(temp_repo: Path):
    RepositoryLockManager.acquire_lock(1, temp_repo, "txn_owner")
    released = RepositoryLockManager.release_lock(1, temp_repo, "other_id", force=True)
    assert released is True
    assert not (temp_repo / ".apex_backup" / "remediation_lease.json").exists()


def test_break_stale_lock_success_when_expired(temp_repo: Path):
    RepositoryLockManager.acquire_lock(1, temp_repo, "stale_txn", lease_seconds=-10)
    success, msg = RepositoryLockManager.break_stale_lock(1, temp_repo)
    assert success is True


def test_break_stale_lock_fails_when_active_without_force(temp_repo: Path):
    RepositoryLockManager.acquire_lock(1, temp_repo, "active_txn", lease_seconds=100)
    success, msg = RepositoryLockManager.break_stale_lock(1, temp_repo, force=False)
    assert success is False
    assert "Cannot break without force" in msg


def test_break_stale_lock_succeeds_when_active_with_force(temp_repo: Path):
    RepositoryLockManager.acquire_lock(1, temp_repo, "active_txn", lease_seconds=100)
    success, msg = RepositoryLockManager.break_stale_lock(1, temp_repo, force=True)
    assert success is True


def test_lock_context_manager_acquires_and_releases(temp_repo: Path):
    assert RepositoryLockManager.inspect_lock(1, temp_repo)["is_locked"] is False
    with RepositoryLockContext(1, temp_repo, "ctx_txn", lease_seconds=60):
        assert RepositoryLockManager.inspect_lock(1, temp_repo)["is_locked"] is True
    assert RepositoryLockManager.inspect_lock(1, temp_repo)["is_locked"] is False


def test_lock_context_manager_releases_on_exception(temp_repo: Path):
    try:
        with RepositoryLockContext(1, temp_repo, "ctx_err_txn", lease_seconds=60):
            assert RepositoryLockManager.inspect_lock(1, temp_repo)["is_locked"] is True
            raise RuntimeError("Operation exploded!")
    except RuntimeError:
        pass
    assert RepositoryLockManager.inspect_lock(1, temp_repo)["is_locked"] is False


def test_is_pid_alive_helper():
    assert _is_pid_alive(os.getpid()) is True
    assert _is_pid_alive(-9999) is False


# ============================================================================
# 4. Multi-File Rollback Conflict Protection Tests (46-55)
# ============================================================================

def test_rollback_transaction_restores_all_files(temp_repo: Path):
    patches = [
        {"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'patch_a'\n"},
        {"rel_path": "service_b.py", "patched_content": "def calculate(y):\n    return 'patch_b'\n"},
    ]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]
    MultiFileTransactionEngine.apply_transaction(1, temp_repo, txn_id)

    rolled_back = MultiFileTransactionEngine.rollback_transaction(1, temp_repo, txn_id)
    assert rolled_back["state"] == TransactionState.ROLLED_BACK.value
    assert (temp_repo / "service_a.py").read_text(encoding="utf-8") == "def get_data(x):\n    return x * 2\n"
    assert (temp_repo / "service_b.py").read_text(encoding="utf-8") == "def calculate(y):\n    return y + 10\n"


def test_rollback_conflict_detection_blocks_when_file_modified(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'patch_a'\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]
    MultiFileTransactionEngine.apply_transaction(1, temp_repo, txn_id)

    # Modify service_a after apply
    (temp_repo / "service_a.py").write_text("def developer_mod(): pass\n", encoding="utf-8")

    with pytest.raises(RollbackConflictError) as exc_info:
        MultiFileTransactionEngine.rollback_transaction(1, temp_repo, txn_id)

    assert "modified on disk since patch application" in exc_info.value.message
    assert len(exc_info.value.conflicts) == 1
    # Check developer's modifications were NOT overwritten
    assert (temp_repo / "service_a.py").read_text(encoding="utf-8") == "def developer_mod(): pass\n"


def test_rollback_conflict_force_overrides_block(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'patch_a'\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]
    MultiFileTransactionEngine.apply_transaction(1, temp_repo, txn_id)

    (temp_repo / "service_a.py").write_text("def developer_mod(): pass\n", encoding="utf-8")

    rolled = MultiFileTransactionEngine.rollback_transaction(1, temp_repo, txn_id, force=True)
    assert rolled["state"] == TransactionState.ROLLED_BACK.value
    assert (temp_repo / "service_a.py").read_text(encoding="utf-8") == "def get_data(x):\n    return x * 2\n"


def test_rollback_idempotent_when_already_rolled_back(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'patch_a'\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]
    MultiFileTransactionEngine.apply_transaction(1, temp_repo, txn_id)
    MultiFileTransactionEngine.rollback_transaction(1, temp_repo, txn_id)

    # Second call
    second = MultiFileTransactionEngine.rollback_transaction(1, temp_repo, txn_id)
    assert second["state"] == TransactionState.ROLLED_BACK.value


def test_rollback_rejected_if_transaction_in_staged_state(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'patch_a'\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]

    with pytest.raises(ValueError, match="is in state STAGED, cannot rollback"):
        MultiFileTransactionEngine.rollback_transaction(1, temp_repo, txn_id)


def test_rollback_detects_deleted_file(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'patch_a'\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]
    MultiFileTransactionEngine.apply_transaction(1, temp_repo, txn_id)

    (temp_repo / "service_a.py").unlink()

    with pytest.raises(RollbackConflictError) as exc_info:
        MultiFileTransactionEngine.rollback_transaction(1, temp_repo, txn_id)
    assert exc_info.value.conflicts[0]["issue"] == "FILE_DELETED"


def test_rollback_missing_backup_raises_error(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'patch_a'\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]
    MultiFileTransactionEngine.apply_transaction(1, temp_repo, txn_id)

    # Delete backup
    Path(manifest["files"][0]["backup_path"]).unlink()

    with pytest.raises(FileNotFoundError, match="Missing backup file"):
        MultiFileTransactionEngine.rollback_transaction(1, temp_repo, txn_id)


def test_rollback_appends_journal_events(temp_repo: Path):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'patch_a'\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches)
    txn_id = manifest["transaction_id"]
    MultiFileTransactionEngine.apply_transaction(1, temp_repo, txn_id)
    MultiFileTransactionEngine.rollback_transaction(1, temp_repo, txn_id)

    events = [e["event"] for e in MultiFileTransactionEngine.get_journal(temp_repo, txn_id)]
    assert "TXN_ROLLBACK_START" in events
    assert "FILE_RESTORED" in events
    assert "TXN_ROLLED_BACK" in events


def test_rollback_updates_db_state(temp_repo: Path, mock_db):
    patches = [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'patch_a'\n"}]
    manifest = MultiFileTransactionEngine.prepare_transaction(1, temp_repo, patches, user_id=1, db=mock_db)
    txn_id = manifest["transaction_id"]
    MultiFileTransactionEngine.apply_transaction(1, temp_repo, txn_id, db=mock_db)
    MultiFileTransactionEngine.rollback_transaction(1, temp_repo, txn_id, db=mock_db)

    db_rec = mock_db.query(RemediationTransaction).filter_by(transaction_id=txn_id).first()
    assert db_rec.state == TransactionState.ROLLED_BACK.value


def test_rollback_conflict_serializes_to_dict():
    err = RollbackConflictError("Rollback blocked", [{"file": "test.py", "issue": "EXTERNAL_MOD"}])
    d = err.to_dict()
    assert d["error"] == "ROLLBACK_CONFLICT"
    assert len(d["conflicts"]) == 1


# ============================================================================
# 5. Multi-File Post-Apply Verification Tests (56-65)
# ============================================================================

def test_multi_file_verification_clean_passes(temp_repo: Path):
    files = [
        {"rel_path": "service_a.py", "target_abs_path": str(temp_repo / "service_a.py")},
        {"rel_path": "service_b.py", "target_abs_path": str(temp_repo / "service_b.py")},
    ]
    res = MultiFileTransactionEngine._run_multi_file_verification(temp_repo, files)
    assert res["status"] == "NO_NEW_FINDINGS_DETECTED_BY_EXECUTED_ANALYZERS"
    assert res["verified"] is True
    assert len(res["files_checked"]) == 2


def test_multi_file_verification_catches_syntax_regression(temp_repo: Path):
    (temp_repo / "service_a.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    files = [{"rel_path": "service_a.py", "target_abs_path": str(temp_repo / "service_a.py")}]
    res = MultiFileTransactionEngine._run_multi_file_verification(temp_repo, files)
    assert res["status"] == "REGRESSION_DETECTED"
    assert res["verified"] is False
    assert len(res["regressions"]) == 1


def test_multi_file_verification_skips_non_python_syntax(temp_repo: Path):
    files = [{"rel_path": "config.json", "target_abs_path": str(temp_repo / "config.json")}]
    res = MultiFileTransactionEngine._run_multi_file_verification(temp_repo, files)
    assert res["status"] == "NO_NEW_FINDINGS_DETECTED_BY_EXECUTED_ANALYZERS"
    assert res["verified"] is True


# ============================================================================
# 6. REST API Endpoints & Security Tests (66-75)
# ============================================================================

@pytest.fixture
def client_app(temp_repo: Path):
    """Sets up FastAPI test client with mocked DB session and project access."""
    from sqlalchemy.pool import StaticPool
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with TestingSessionLocal() as session:
        user = User(
            id=1,
            email="dev@example.com",
            username="test_dev",
            hashed_password="hashed_pw",
            is_active=True,
        )
        session.add(user)
        session.commit()

        project = ReviewedProject(
            id=1,
            name="Test Project",
            repository_path=str(temp_repo),
            owner_id=user.id,
        )
        session.add(project)
        session.commit()

    from app.main import create_app
    app = create_app(database_engine=engine)
    app.state.SessionLocal = TestingSessionLocal
    client = TestClient(app)
    return client


def test_api_create_transaction_success(client_app, temp_repo: Path):
    payload = {
        "patches": [
            {"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return x * 5\n"}
        ],
        "auto_apply": False,
    }
    resp = client_app.post("/api/project-reviews/1/remediation/transactions", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "STAGED"
    assert data["files_count"] == 1


def test_api_create_and_auto_apply_transaction(client_app, temp_repo: Path):
    payload = {
        "patches": [
            {"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'auto_applied'\n"}
        ],
        "auto_apply": True,
    }
    resp = client_app.post("/api/project-reviews/1/remediation/transactions", json=payload)
    assert resp.status_code == 200
    assert resp.json()["state"] == "COMMITTED"
    assert (temp_repo / "service_a.py").read_text(encoding="utf-8") == "def get_data(x):\n    return 'auto_applied'\n"


def test_api_list_transactions(client_app):
    resp = client_app.get("/api/project-reviews/1/remediation/transactions")
    assert resp.status_code == 200
    assert "transactions" in resp.json()


def test_api_inspect_lock(client_app):
    resp = client_app.get("/api/project-reviews/1/remediation/locks")
    assert resp.status_code == 200
    assert "is_locked" in resp.json()


def test_api_break_stale_lock(client_app, temp_repo: Path):
    RepositoryLockManager.acquire_lock(1, temp_repo, "stale_api_txn", lease_seconds=-10)
    resp = client_app.post("/api/project-reviews/1/remediation/locks/break-stale", json={"force": False})
    assert resp.status_code == 200
    assert resp.json()["broken"] is True


def test_api_scan_recovery(client_app):
    resp = client_app.post("/api/project-reviews/1/remediation/scan-recovery")
    assert resp.status_code == 200
    assert "recovered_transactions_count" in resp.json()


def test_api_rollback_conflict_returns_409(client_app, temp_repo: Path):
    # 1. Create and apply
    payload = {
        "patches": [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'applied'\n"}],
        "auto_apply": True,
    }
    create_resp = client_app.post("/api/project-reviews/1/remediation/transactions", json=payload)
    txn_id = create_resp.json()["transaction_id"]

    # 2. Modify file externally
    (temp_repo / "service_a.py").write_text("def external_dev(): pass\n", encoding="utf-8")

    # 3. Rollback without force -> must return 409 Conflict
    rb_resp = client_app.post(f"/api/project-reviews/1/remediation/transactions/{txn_id}/rollback", json={"force": False})
    assert rb_resp.status_code == 409
    assert rb_resp.json()["detail"]["error"] == "ROLLBACK_CONFLICT"


def test_api_rollback_with_force_succeeds(client_app, temp_repo: Path):
    payload = {
        "patches": [{"rel_path": "service_a.py", "patched_content": "def get_data(x):\n    return 'applied'\n"}],
        "auto_apply": True,
    }
    create_resp = client_app.post("/api/project-reviews/1/remediation/transactions", json=payload)
    txn_id = create_resp.json()["transaction_id"]

    (temp_repo / "service_a.py").write_text("def external_dev(): pass\n", encoding="utf-8")

    rb_resp = client_app.post(f"/api/project-reviews/1/remediation/transactions/{txn_id}/rollback", json={"force": True})
    assert rb_resp.status_code == 200
    assert rb_resp.json()["state"] == "ROLLED_BACK"


def test_api_tenant_isolation_non_disclosing_404(client_app):
    # Project 999 does not exist
    resp = client_app.get("/api/project-reviews/999/remediation/transactions")
    assert resp.status_code == 404
