"""Unit & Integration Tests for APEX 2.0 Phase 2D: Automated Fix Generation & AI Remediation Verification."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import create_app
from app.models.entities import Base, ReviewedProject
from app.services.auth_service import create_access_token, register_user
from app.services.remediation.patch_generator import CodePatch, PatchGenerator, PatchStrategy
from app.services.remediation.patch_lifecycle import PatchLifecycleManager, PatchLifecycleState
from app.services.remediation.patch_verifier import (
    PatchVerificationResult,
    PatchVerificationStatus,
    PatchVerifier,
)


@pytest.fixture
def temp_project_repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        # Create sample files with known defect patterns
        opt_file = repo_path / "models.py"
        opt_file.write_text(
            "def get_user_age(user):\n    return user.age\n",
            encoding="utf-8",
        )

        async_file = repo_path / "async_service.py"
        async_file.write_text(
            "import time\n\nasync def fetch_metrics():\n    time.sleep(2)\n    return {'status': 'ok'}\n",
            encoding="utf-8",
        )

        res_file = repo_path / "file_loader.py"
        res_file.write_text(
            "def load_data(filepath):\n    f = open(filepath, 'r')\n    data = f.read()\n    return data\n",
            encoding="utf-8",
        )

        sec_file = repo_path / "runner.py"
        sec_file.write_text(
            "import subprocess\n\ndef run_cmd(cmd):\n    subprocess.run(cmd, shell=True)\n",
            encoding="utf-8",
        )

        yield repo_path


def test_fix_optional_dereference(temp_project_repo: Path):
    finding = {
        "file": "models.py",
        "line": 2,
        "rule_id": "TYPE-UNCHECKED-OPTIONAL-DEREFERENCE",
        "evidence": "Variable 'user' is dereferenced without None-guard check.",
        "fingerprint": "opt_fp_123",
    }
    patch = PatchGenerator.generate_patch(finding, temp_project_repo)
    assert patch is not None
    assert patch.rule_id == "TYPE-UNCHECKED-OPTIONAL-DEREFERENCE"
    assert "if user is not None:" in patch.patched_snippet
    assert "a/models.py" in patch.unified_diff

    # Verify AST syntax & safety
    result = PatchVerifier.verify_patch(patch, repo_root=temp_project_repo)
    assert result.valid is True
    assert result.status == PatchVerificationStatus.VERIFIED
    assert result.syntax_ok is True


def test_fix_async_blocking_io(temp_project_repo: Path):
    finding = {
        "file": "async_service.py",
        "line": 4,
        "rule_id": "ASYNC-BLOCKING-IO-CALL",
        "evidence": "Blocking call time.sleep() inside async coroutine.",
        "fingerprint": "async_fp_456",
    }
    patch = PatchGenerator.generate_patch(finding, temp_project_repo)
    assert patch is not None
    assert patch.rule_id == "ASYNC-BLOCKING-IO-CALL"
    assert "await asyncio.sleep" in patch.patched_snippet
    assert "import asyncio" in patch.patched_full_content

    result = PatchVerifier.verify_patch(patch, repo_root=temp_project_repo)
    assert result.valid is True
    assert result.status == PatchVerificationStatus.VERIFIED
    assert result.flaw_eliminated is True


def test_fix_unclosed_resource(temp_project_repo: Path):
    finding = {
        "file": "file_loader.py",
        "line": 2,
        "rule_id": "RESOURCE-UNCLOSED-HANDLE",
        "evidence": "Resource handle 'f' allocated by open() without context manager.",
        "fingerprint": "res_fp_789",
    }
    patch = PatchGenerator.generate_patch(finding, temp_project_repo)
    assert patch is not None
    assert patch.rule_id == "RESOURCE-UNCLOSED-HANDLE"
    assert "with open(filepath, 'r') as f:" in patch.patched_snippet

    result = PatchVerifier.verify_patch(patch, repo_root=temp_project_repo)
    assert result.valid is True
    assert result.status == PatchVerificationStatus.VERIFIED


def test_fix_command_injection(temp_project_repo: Path):
    finding = {
        "file": "runner.py",
        "line": 4,
        "rule_id": "SEC-TAINT-COMMAND-INJECTION",
        "evidence": "subprocess.run with shell=True receiving potential untrusted command.",
        "fingerprint": "sec_fp_012",
    }
    patch = PatchGenerator.generate_patch(finding, temp_project_repo)
    assert patch is not None
    assert patch.rule_id == "SEC-TAINT-COMMAND-INJECTION"
    assert "shell=False" in patch.patched_snippet

    result = PatchVerifier.verify_patch(patch, repo_root=temp_project_repo)
    assert result.valid is True
    assert result.status == PatchVerificationStatus.VERIFIED
    assert result.flaw_eliminated is True


def test_verifier_rejects_syntax_error(temp_project_repo: Path):
    # Create patch with corrupted syntax
    bad_patch = CodePatch(
        patch_id="bad_syn_1",
        finding_id="f1",
        rule_id="RULE-1",
        file="models.py",
        original_snippet="return user.age",
        patched_snippet="def bad_syntax((((:",
        unified_diff="--- a/models.py\n+++ b/models.py\n@@ -2 +2 @@\n-return user.age\n+def bad_syntax((((:",
        strategy=PatchStrategy.DETERMINISTIC_AST,
        summary="Bad patch",
        explanation="Testing syntax validator",
        patched_full_content="def get_user_age(user):\n    def bad_syntax((((:\n",
    )
    result = PatchVerifier.verify_patch(bad_patch, repo_root=temp_project_repo)
    assert result.valid is False
    assert result.status == PatchVerificationStatus.SYNTAX_ERROR
    assert "SyntaxError" in result.details


def test_verifier_detects_persisting_flaw(temp_project_repo: Path):
    # Patch where shell=True was not removed
    bad_patch = CodePatch(
        patch_id="bad_flaw_1",
        finding_id="f2",
        rule_id="SEC-TAINT-COMMAND-INJECTION",
        file="runner.py",
        original_snippet="subprocess.run(cmd, shell=True)",
        patched_snippet="subprocess.run(cmd, shell=True) # not fixed",
        unified_diff="--- a/runner.py\n+++ b/runner.py",
        strategy=PatchStrategy.DETERMINISTIC_AST,
        summary="Unfixed patch",
        explanation="Testing flaw persistence check",
        patched_full_content="import subprocess\n\ndef run_cmd(cmd):\n    subprocess.run(cmd, shell=True)\n",
    )
    result = PatchVerifier.verify_patch(bad_patch, repo_root=temp_project_repo)
    assert result.valid is False
    assert result.status == PatchVerificationStatus.FLAW_PERSISTS
    assert "shell=True" in result.details


def test_patch_lifecycle_apply_and_rollback(temp_project_repo: Path):
    manager = PatchLifecycleManager()
    finding = {
        "file": "async_service.py",
        "line": 4,
        "rule_id": "ASYNC-BLOCKING-IO-CALL",
        "fingerprint": "fp_lifecycle_1",
    }
    patch = PatchGenerator.generate_patch(finding, temp_project_repo)
    assert patch is not None

    record = manager.register_patch(patch)
    assert record.state == PatchLifecycleState.GENERATED

    # Apply patch
    success, msg = manager.apply_patch(patch.patch_id, temp_project_repo)
    assert success is True
    assert record.state == PatchLifecycleState.APPLIED

    # Check file content on disk has been updated
    target_content = (temp_project_repo / "async_service.py").read_text(encoding="utf-8")
    assert "await asyncio.sleep" in target_content

    # Check backup snapshot exists
    backup_file = temp_project_repo / record.backup_file_path
    assert backup_file.is_file()
    assert "time.sleep(2)" in backup_file.read_text(encoding="utf-8")

    # Roll back patch
    rb_success, rb_msg = manager.rollback_patch(patch.patch_id, temp_project_repo)
    assert rb_success is True
    assert record.state == PatchLifecycleState.ROLLED_BACK

    # Check file content on disk is restored
    restored_content = (temp_project_repo / "async_service.py").read_text(encoding="utf-8")
    assert "time.sleep(2)" in restored_content
    assert "await asyncio.sleep" not in restored_content


def test_patch_lifecycle_path_traversal_prevention(temp_project_repo: Path):
    manager = PatchLifecycleManager()
    traversal_patch = CodePatch(
        patch_id="traversal_1",
        finding_id="f_trav",
        rule_id="RULE-TRAV",
        file="../../etc/passwd",
        original_snippet="root:x:0:0",
        patched_snippet="remediated",
        unified_diff="",
        strategy=PatchStrategy.DETERMINISTIC_AST,
        summary="Traversal exploit test",
        explanation="Security verification",
    )
    manager.register_patch(traversal_patch)
    success, msg = manager.apply_patch(traversal_patch.patch_id, temp_project_repo)
    assert success is False
    assert "traverses outside repository root" in msg


def test_remediation_api_endpoints_and_isolation(temp_project_repo: Path):
    db_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db_engine)
    session_factory = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)

    app = create_app(database_engine=db_engine)
    app.state.SessionLocal = session_factory

    with session_factory() as session:
        user_a = register_user(session, "user_2d_a@test.com", "user_2d_a", "Password123!")
        user_b = register_user(session, "user_2d_b@test.com", "user_2d_b", "Password123!")

        project = ReviewedProject(
            name="Phase 2D Project",
            repository_path=str(temp_project_repo),
            owner_id=user_a.id,
            source_type="local",
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        proj_id = project.id

        token_a = create_access_token(user_a)
        token_b = create_access_token(user_b)

    with TestClient(app) as client:
        # 1. Owner generates fix for finding
        finding_payload = {
            "custom_finding": {
                "file": "models.py",
                "line": 2,
                "rule_id": "TYPE-UNCHECKED-OPTIONAL-DEREFERENCE",
                "evidence": "Variable 'user' is dereferenced without None-guard check.",
                "fingerprint": "opt_fp_123",
            }
        }
        gen_resp = client.post(
            f"/api/project-reviews/{proj_id}/findings/opt_fp_123/generate-fix",
            headers={"Authorization": f"Bearer {token_a}"},
            json=finding_payload,
        )
        assert gen_resp.status_code == 200
        patch_info = gen_resp.json()
        assert "patch" in patch_info
        assert "verification" in patch_info
        assert patch_info["verification"]["valid"] is True
        patch_id = patch_info["patch"]["patch_id"]

        # 2. Non-owner User B tries to generate fix -> 404 (multi-tenant tenant isolation)
        unauth_resp = client.post(
            f"/api/project-reviews/{proj_id}/findings/opt_fp_123/generate-fix",
            headers={"Authorization": f"Bearer {token_b}"},
            json=finding_payload,
        )
        assert unauth_resp.status_code == 404

        # 3. Owner applies patch to disk
        apply_resp = client.post(
            f"/api/project-reviews/{proj_id}/patches/{patch_id}/apply",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert apply_resp.status_code == 200
        assert apply_resp.json()["success"] is True

        # Verify disk modification
        mod_content = (temp_project_repo / "models.py").read_text(encoding="utf-8")
        assert "if user is not None:" in mod_content

        # 4. Non-owner User B tries to rollback patch -> 404 (multi-tenant tenant isolation)
        unauth_rb = client.post(
            f"/api/project-reviews/{proj_id}/patches/{patch_id}/rollback",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert unauth_rb.status_code == 404

        # 5. Owner rolls back patch
        rb_resp = client.post(
            f"/api/project-reviews/{proj_id}/patches/{patch_id}/rollback",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert rb_resp.status_code == 200
        assert rb_resp.json()["success"] is True

        # Verify restoration on disk
        restored = (temp_project_repo / "models.py").read_text(encoding="utf-8")
        assert "if user is not None:" not in restored

