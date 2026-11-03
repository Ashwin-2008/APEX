"""Comprehensive Test Suite for APEX 2.0 Phase 2D.1:
Semantic Patch Safety, Transactional Integrity & Behavioral Verification Engine.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import create_app
from app.models.entities import Base, ReviewedProject
from app.services.auth_service import create_access_token, register_user
from app.services.remediation.behavioral_verifier import (
    BehavioralStatus,
    BehavioralVerifier,
)
from app.services.remediation.patch_confidence import PatchConfidenceEngine
from app.services.remediation.patch_generator import CodePatch, PatchGenerator, PatchStrategy
from app.services.remediation.patch_integrity import (
    PatchIntegrityService,
    compute_content_sha256,
)
from app.services.remediation.patch_lifecycle import (
    PatchLifecycleManager,
    PatchLifecycleState,
)
from app.services.remediation.post_apply_verifier import (
    PostApplyOutcome,
    PostApplyVerifier,
)
from app.services.remediation.semantic_verifier import (
    SemanticRisk,
    SemanticVerifier,
)


@pytest.fixture
def temp_repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "calc.py").write_text(
            "def add(a, b):\n    return a + b\n\ndef divide(a, b):\n    return a / b\n",
            encoding="utf-8",
        )
        (repo / "model.py").write_text(
            "def get_user_name(user):\n    return user.name\n",
            encoding="utf-8",
        )
        (repo / "reader.py").write_text(
            "def read_file(path):\n    f = open(path, 'r')\n    data = f.read()\n    return data\n",
            encoding="utf-8",
        )
        (repo / "async_worker.py").write_text(
            "import time\n\nasync def process():\n    time.sleep(1)\n    return 'done'\n",
            encoding="utf-8",
        )
        (repo / "command_runner.py").write_text(
            "import subprocess\n\ndef run(cmd):\n    subprocess.run(cmd, shell=True)\n",
            encoding="utf-8",
        )
        (repo / "db_service.py").write_text(
            "def find_user(cursor, user_id):\n    cursor.execute(f\"SELECT * FROM users WHERE id = {user_id}\")\n",
            encoding="utf-8",
        )
        yield repo


# ==============================================================================
# GROUP 1: Semantic Verification Tests (15 tests)
# ==============================================================================

def test_semantic_signature_args_modified_fails():
    orig = "def compute(x, y):\n    return x + y\n"
    patched = "def compute(x, y, z):\n    return x + y + z\n"
    res = SemanticVerifier.verify_semantics(orig, patched)
    assert res.valid is False
    assert res.risk_level == SemanticRisk.HIGH_RISK_TRANSFORMATION
    assert any("parameters changed" in c for c in res.contract_changes)


def test_semantic_signature_defaults_modified_fails():
    orig = "def connect(host, port=80):\n    pass\n"
    patched = "def connect(host, port):\n    pass\n"
    res = SemanticVerifier.verify_semantics(orig, patched)
    assert res.valid is False
    assert any("parameter defaults changed" in c for c in res.contract_changes)


def test_semantic_signature_return_annotation_fails():
    orig = "def total(items: list[int]) -> int:\n    return sum(items)\n"
    patched = "def total(items: list[int]) -> str:\n    return str(sum(items))\n"
    res = SemanticVerifier.verify_semantics(orig, patched)
    assert res.valid is False
    assert any("return type annotation altered" in c for c in res.contract_changes)


def test_semantic_function_deleted_fails():
    orig = "def foo(): pass\ndef bar(): pass\n"
    patched = "def foo(): pass\n"
    res = SemanticVerifier.verify_semantics(orig, patched)
    assert res.valid is False
    assert any("Function 'bar' was deleted" in c for c in res.contract_changes)


def test_semantic_unexpected_async_change_fails():
    orig = "def fetch():\n    return 42\n"
    patched = "async def fetch():\n    return 42\n"
    res = SemanticVerifier.verify_semantics(orig, patched, rule_id="GENERAL-RULE")
    assert res.valid is False
    assert any("async status modified" in c for c in res.contract_changes)


def test_semantic_removed_return_fails():
    orig = "def get_status():\n    return 'OK'\n"
    patched = "def get_status():\n    pass\n"
    res = SemanticVerifier.verify_semantics(orig, patched)
    assert res.valid is False
    assert any("return statement which was removed" in c for c in res.contract_changes)


def test_semantic_removed_try_except_fails():
    orig = "def parse(s):\n    try:\n        return int(s)\n    except ValueError:\n        return 0\n"
    patched = "def parse(s):\n    return int(s)\n"
    res = SemanticVerifier.verify_semantics(orig, patched)
    assert res.valid is False
    assert res.risk_level == SemanticRisk.MEDIUM_RISK_TRANSFORMATION
    assert any("weakening exception handling" in c for c in res.control_flow_changes)


def test_semantic_removed_loop_fails():
    orig = "def process(items):\n    for item in items:\n        print(item)\n"
    patched = "def process(items):\n    print(items)\n"
    res = SemanticVerifier.verify_semantics(orig, patched)
    assert res.valid is False
    assert any("removed loop structure" in c for c in res.control_flow_changes)


def test_semantic_undefined_variable_fails():
    orig = "def add(x):\n    return x + 1\n"
    patched = "def add(x):\n    return x + undefined_variable\n"
    res = SemanticVerifier.verify_semantics(orig, patched)
    assert res.valid is False
    assert "undefined_variable" in res.undefined_names


def test_semantic_valid_none_guard_succeeds():
    orig = "def get_name(user):\n    return user.name\n"
    patched = "def get_name(user):\n    if user is not None:\n        return user.name\n    return None\n"
    res = SemanticVerifier.verify_semantics(orig, patched, rule_id="TYPE-UNCHECKED-OPTIONAL-DEREFERENCE")
    assert res.valid is True
    assert res.risk_level in {SemanticRisk.SAFE_TRANSFORMATION, SemanticRisk.LOW_RISK_TRANSFORMATION}
    assert any("None-guard" in d for d in res.details)


def test_semantic_valid_context_manager_succeeds():
    orig = "def load(p):\n    f = open(p)\n    return f.read()\n"
    patched = "def load(p):\n    with open(p) as f:\n        return f.read()\n"
    res = SemanticVerifier.verify_semantics(orig, patched, rule_id="RESOURCE-UNCLOSED-HANDLE")
    assert res.valid is True
    assert any("context manager" in d for d in res.details)


def test_semantic_valid_async_sleep_succeeds():
    orig = "import time\n\nasync def wait():\n    time.sleep(1)\n"
    patched = "import asyncio\n\nasync def wait():\n    await asyncio.sleep(1)\n"
    res = SemanticVerifier.verify_semantics(orig, patched, rule_id="ASYNC-BLOCKING-IO-CALL")
    assert res.valid is True
    assert any("await expression" in d for d in res.details)


def test_semantic_syntax_error_in_patch_fails():
    orig = "def run():\n    return 1\n"
    patched = "def run():\n    ret urn 1\n"
    res = SemanticVerifier.verify_semantics(orig, patched)
    assert res.valid is False
    assert res.risk_level == SemanticRisk.HIGH_RISK_TRANSFORMATION
    assert "SyntaxError" in res.summary


def test_semantic_syntax_error_in_original_unverifiable():
    orig = "def broken(:\n    pass\n"
    patched = "def fixed():\n    pass\n"
    res = SemanticVerifier.verify_semantics(orig, patched)
    assert res.valid is False
    assert res.risk_level == SemanticRisk.SEMANTICALLY_UNVERIFIABLE


def test_semantic_decorator_modified_fails():
    orig = "@cache\ndef compute(): pass\n"
    patched = "def compute(): pass\n"
    res = SemanticVerifier.verify_semantics(orig, patched)
    assert res.valid is False
    assert any("decorators modified" in c for c in res.contract_changes)


# ==============================================================================
# GROUP 2: Behavioral Verification Tests (8 tests)
# ==============================================================================

def test_behavioral_no_tests_available_unverifiable(temp_repo: Path):
    finding = {"file": "calc.py", "line": 2, "rule_id": "RULE-1", "fingerprint": "fp1"}
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    res = BehavioralVerifier.verify_patch_behavior(temp_repo, patch, patch.patched_full_content)
    assert res.status == BehavioralStatus.UNVERIFIABLE
    assert res.valid is False


def test_behavioral_baseline_clean_patch_passes(temp_repo: Path):
    # Add a passing test file
    (temp_repo / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    finding = {"file": "calc.py", "line": 2, "rule_id": "GENERAL", "fingerprint": "fp_calc"}
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    res = BehavioralVerifier.verify_patch_behavior(temp_repo, patch, patch.patched_full_content)
    assert res.status == BehavioralStatus.PASSED
    assert res.valid is True


def test_behavioral_detects_newly_failing_regression(temp_repo: Path):
    (temp_repo / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    finding = {"file": "calc.py", "line": 2, "rule_id": "GENERAL", "fingerprint": "fp_calc_reg"}
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    # Intentionally broken patch that breaks the test
    broken_code = "def add(a, b):\n    return a * b  # Regression!\n"
    res = BehavioralVerifier.verify_patch_behavior(temp_repo, patch, broken_code)
    assert res.status == BehavioralStatus.REGRESSION_DETECTED
    assert res.valid is False
    assert len(res.newly_failing_tests) >= 1


def test_behavioral_preexisting_failure_partially_passes(temp_repo: Path):
    # Test suite with an already failing test
    (temp_repo / "test_calc.py").write_text(
        "from calc import add\n\ndef test_broken():\n    assert False, 'preexisting failure'\n",
        encoding="utf-8",
    )
    finding = {"file": "calc.py", "line": 2, "rule_id": "GENERAL", "fingerprint": "fp_prefail"}
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    res = BehavioralVerifier.verify_patch_behavior(temp_repo, patch, patch.patched_full_content)
    assert res.status == BehavioralStatus.PARTIALLY_PASSED
    assert res.valid is True
    assert len(res.newly_failing_tests) == 0


def test_behavioral_timeout_handled_cleanly(temp_repo: Path):
    (temp_repo / "test_calc.py").write_text(
        "import time\n\ndef test_slow():\n    time.sleep(2)\n",
        encoding="utf-8",
    )
    finding = {"file": "calc.py", "line": 2, "rule_id": "GENERAL", "fingerprint": "fp_slow"}
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    # Set timeout to 1 second
    res = BehavioralVerifier.verify_patch_behavior(temp_repo, patch, patch.patched_full_content, timeout=1)
    assert res.status == BehavioralStatus.TIMED_OUT
    assert res.valid is False


def test_behavioral_execution_error_handled(temp_repo: Path):
    # Syntax error in test file
    (temp_repo / "test_calc.py").write_text(
        "def broken_syntax(:::\n",
        encoding="utf-8",
    )
    finding = {"file": "calc.py", "line": 2, "rule_id": "GENERAL", "fingerprint": "fp_exec_err"}
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    res = BehavioralVerifier.verify_patch_behavior(temp_repo, patch, patch.patched_full_content)
    assert res.status in {BehavioralStatus.EXECUTION_FAILED, BehavioralStatus.PARTIALLY_PASSED}


def test_behavioral_affected_symbols_extracted():
    code = "def process_data(val):\n    return val * 2\n"
    patch = CodePatch(
        patch_id="p1",
        finding_id="f1",
        rule_id="R1",
        file="worker.py",
        original_snippet="return val * 2",
        patched_snippet="return val * 3",
        unified_diff="",
        strategy=PatchStrategy.DETERMINISTIC_AST,
        summary="",
        explanation="",
    )
    symbols = BehavioralVerifier.identify_affected_symbols(code, patch)
    assert "process_data" in symbols


def test_behavioral_discover_relevant_tests(temp_repo: Path):
    (temp_repo / "test_reader.py").write_text("from reader import read_file\n", encoding="utf-8")
    patch = CodePatch(
        patch_id="p2",
        finding_id="f2",
        rule_id="R2",
        file="reader.py",
        original_snippet="",
        patched_snippet="",
        unified_diff="",
        strategy=PatchStrategy.DETERMINISTIC_AST,
        summary="",
        explanation="",
    )
    tests = BehavioralVerifier.discover_relevant_tests(temp_repo, patch, ["read_file"])
    assert len(tests) >= 1
    assert "test_reader.py" in str(tests[0])


# ==============================================================================
# GROUP 3: Remediation Strategy Safety Tests (12 tests)
# ==============================================================================

def test_strategy_optional_dereference_return_fallback(temp_repo: Path):
    finding = {
        "file": "model.py",
        "line": 2,
        "rule_id": "TYPE-UNCHECKED-OPTIONAL-DEREFERENCE",
        "evidence": "Variable 'user' is dereferenced without None-guard check.",
        "fingerprint": "fp_opt_ret",
    }
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    assert "if user is not None:" in patch.patched_snippet
    assert "return None" in patch.patched_snippet
    assert patch.risk_classification == "LOW"


def test_strategy_optional_dereference_non_return(temp_repo: Path):
    (temp_repo / "service.py").write_text(
        "def notify(user):\n    user.send_email('hello')\n",
        encoding="utf-8",
    )
    finding = {
        "file": "service.py",
        "line": 2,
        "rule_id": "TYPE-UNCHECKED-OPTIONAL-DEREFERENCE",
        "evidence": "Variable 'user' is dereferenced.",
        "fingerprint": "fp_opt_nonret",
    }
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    assert "if user is not None:" in patch.patched_snippet
    assert "user.send_email" in patch.patched_snippet


def test_strategy_resource_unclosed_wraps_with(temp_repo: Path):
    finding = {
        "file": "reader.py",
        "line": 2,
        "rule_id": "RESOURCE-UNCLOSED-HANDLE",
        "evidence": "Resource 'f' unclosed.",
        "fingerprint": "fp_res",
    }
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    assert "with open(path, 'r') as f:" in patch.patched_snippet


def test_strategy_resource_escape_return_rejected(temp_repo: Path):
    # Handle returned from function -> escaping scope!
    (temp_repo / "escape.py").write_text(
        "def get_handle(path):\n    f = open(path, 'r')\n    return f\n",
        encoding="utf-8",
    )
    finding = {
        "file": "escape.py",
        "line": 2,
        "rule_id": "RESOURCE-UNCLOSED-HANDLE",
        "fingerprint": "fp_esc_ret",
    }
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is None  # Must reject ambiguous transformation where handle escapes!


def test_strategy_resource_escape_self_attribute_rejected(temp_repo: Path):
    (temp_repo / "obj_escape.py").write_text(
        "class Loader:\n    def open(self, path):\n        f = open(path, 'r')\n        self.f = f\n",
        encoding="utf-8",
    )
    finding = {
        "file": "obj_escape.py",
        "line": 3,
        "rule_id": "RESOURCE-UNCLOSED-HANDLE",
        "fingerprint": "fp_esc_self",
    }
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is None


def test_strategy_async_sleep_replaces_and_imports(temp_repo: Path):
    finding = {
        "file": "async_worker.py",
        "line": 4,
        "rule_id": "ASYNC-BLOCKING-IO-CALL",
        "fingerprint": "fp_async",
    }
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    assert "await asyncio.sleep" in patch.patched_snippet
    assert "import asyncio" in patch.patched_full_content


def test_strategy_async_sleep_preserves_existing_import(temp_repo: Path):
    (temp_repo / "existing_async.py").write_text(
        "import asyncio\nimport time\n\nasync def poll():\n    time.sleep(1)\n",
        encoding="utf-8",
    )
    finding = {
        "file": "existing_async.py",
        "line": 5,
        "rule_id": "ASYNC-BLOCKING-IO-CALL",
        "fingerprint": "fp_existing_import",
    }
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    assert patch.patched_full_content.count("import asyncio") == 1


def test_strategy_command_injection_shell_false(temp_repo: Path):
    finding = {
        "file": "command_runner.py",
        "line": 4,
        "rule_id": "SEC-TAINT-COMMAND-INJECTION",
        "fingerprint": "fp_cmd",
    }
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    assert "shell=False" in patch.patched_snippet
    assert patch.risk_classification == "MEDIUM"


def test_strategy_sql_injection_fstring_parameterized(temp_repo: Path):
    finding = {
        "file": "db_service.py",
        "line": 2,
        "rule_id": "SEC-TAINT-SQLI",
        "fingerprint": "fp_sqli",
    }
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    assert "%s" in patch.patched_snippet
    assert "(user_id,)" in patch.patched_snippet


def test_strategy_generic_guard_fallback(temp_repo: Path):
    finding = {
        "file": "calc.py",
        "line": 2,
        "rule_id": "CUSTOM-UNKNOWN-RULE",
        "fingerprint": "fp_generic",
    }
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    assert "APEX Remediated" in patch.patched_snippet


def test_strategy_unsupported_transformation_handled(temp_repo: Path):
    finding = {
        "file": "nonexistent.py",
        "line": 1,
        "rule_id": "RULE-1",
        "fingerprint": "fp_none",
    }
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is None


def test_strategy_patch_metadata_populated(temp_repo: Path):
    finding = {
        "file": "calc.py",
        "line": 2,
        "rule_id": "TYPE-UNCHECKED-OPTIONAL-DEREFERENCE",
        "fingerprint": "fp_meta",
    }
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    d = patch.to_dict()
    assert "known_limitations" in d
    assert "risk_classification" in d
    assert "affected_symbols" in d


# ==============================================================================
# GROUP 4: Patch Integrity & Stale Patch Tests (6 tests)
# ==============================================================================

def test_integrity_provenance_generation():
    orig = "x = 1\n"
    patched = "x = 2\n"
    patch = CodePatch(
        patch_id="p_int_1",
        finding_id="f1",
        rule_id="R1",
        file="app.py",
        original_snippet="x = 1",
        patched_snippet="x = 2",
        unified_diff="--- a\n+++ b",
        strategy=PatchStrategy.DETERMINISTIC_AST,
        summary="",
        explanation="",
    )
    prov = PatchIntegrityService.generate_provenance(patch, orig, patched, project_id=1, repo_revision="abc1234")
    assert prov.patch_id == "p_int_1"
    assert prov.original_source_sha256 == compute_content_sha256(orig)
    assert prov.patched_source_sha256 == compute_content_sha256(patched)
    assert prov.repo_revision == "abc1234"


def test_integrity_valid_patch_passes(temp_repo: Path):
    orig = (temp_repo / "calc.py").read_text(encoding="utf-8")
    patched = orig.replace("return a + b", "return a + b + 0")
    patch = CodePatch(
        patch_id="p_valid",
        finding_id="f1",
        rule_id="R1",
        file="calc.py",
        original_snippet="",
        patched_snippet="",
        unified_diff="diff_clean",
        strategy=PatchStrategy.DETERMINISTIC_AST,
        summary="",
        explanation="",
    )
    prov = PatchIntegrityService.generate_provenance(patch, orig, patched, project_id=1)
    is_valid, msg, code = PatchIntegrityService.check_integrity(prov, patch, temp_repo)
    assert is_valid is True
    assert code == "OK"


def test_integrity_stale_patch_detected_when_file_modified(temp_repo: Path):
    orig = (temp_repo / "calc.py").read_text(encoding="utf-8")
    patched = orig + "# patch\n"
    patch = CodePatch(
        patch_id="p_stale",
        finding_id="f1",
        rule_id="R1",
        file="calc.py",
        original_snippet="",
        patched_snippet="",
        unified_diff="diff",
        strategy=PatchStrategy.DETERMINISTIC_AST,
        summary="",
        explanation="",
    )
    prov = PatchIntegrityService.generate_provenance(patch, orig, patched, project_id=1)

    # Modify file on disk -> makes patch STALE!
    (temp_repo / "calc.py").write_text(orig + "# developer modification\n", encoding="utf-8")

    is_valid, msg, code = PatchIntegrityService.check_integrity(prov, patch, temp_repo)
    assert is_valid is False
    assert code == "STALE_PATCH"
    assert "Stale patch detected" in msg


def test_integrity_tampered_patch_detected_when_diff_altered(temp_repo: Path):
    orig = (temp_repo / "calc.py").read_text(encoding="utf-8")
    patched = orig + "# clean\n"
    patch = CodePatch(
        patch_id="p_tampered",
        finding_id="f1",
        rule_id="R1",
        file="calc.py",
        original_snippet="",
        patched_snippet="",
        unified_diff="diff_original",
        strategy=PatchStrategy.DETERMINISTIC_AST,
        summary="",
        explanation="",
    )
    prov = PatchIntegrityService.generate_provenance(patch, orig, patched, project_id=1)

    # Alter patch diff after verification
    tampered_patch = CodePatch(
        patch_id=patch.patch_id,
        finding_id=patch.finding_id,
        rule_id=patch.rule_id,
        file=patch.file,
        original_snippet=patch.original_snippet,
        patched_snippet=patch.patched_snippet,
        unified_diff="diff_tampered_malicious",
        strategy=patch.strategy,
        summary=patch.summary,
        explanation=patch.explanation,
    )
    is_valid, msg, code = PatchIntegrityService.check_integrity(prov, tampered_patch, temp_repo)
    assert is_valid is False
    assert code == "TAMPERED_PATCH"


def test_integrity_missing_file_rejected(temp_repo: Path):
    patch = CodePatch(
        patch_id="p_missing",
        finding_id="f1",
        rule_id="R1",
        file="does_not_exist.py",
        original_snippet="",
        patched_snippet="",
        unified_diff="",
        strategy=PatchStrategy.DETERMINISTIC_AST,
        summary="",
        explanation="",
    )
    prov = PatchIntegrityService.generate_provenance(patch, "a", "b", project_id=1)
    is_valid, msg, code = PatchIntegrityService.check_integrity(prov, patch, temp_repo)
    assert is_valid is False
    assert code == "FILE_NOT_FOUND"


def test_integrity_traversal_path_rejected(temp_repo: Path):
    patch = CodePatch(
        patch_id="p_trav",
        finding_id="f1",
        rule_id="R1",
        file="../../etc/shadow",
        original_snippet="",
        patched_snippet="",
        unified_diff="",
        strategy=PatchStrategy.DETERMINISTIC_AST,
        summary="",
        explanation="",
    )
    prov = PatchIntegrityService.generate_provenance(patch, "a", "b", project_id=1)
    is_valid, msg, code = PatchIntegrityService.check_integrity(prov, patch, temp_repo)
    assert is_valid is False
    assert code == "TRAVERSAL_DETECTED"


# ==============================================================================
# GROUP 5: Transactional Lifecycle Tests (10 tests)
# ==============================================================================

def test_lifecycle_state_machine_valid_transitions(temp_repo: Path):
    manager = PatchLifecycleManager()
    finding = {"file": "calc.py", "line": 2, "rule_id": "RULE-1", "fingerprint": "fp_sm"}
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    record = manager.register_patch(patch)
    assert record.state == PatchLifecycleState.GENERATED

    # Move to VERIFIED
    record.record_transition(PatchLifecycleState.VERIFIED, "VERIFY", "TEST", "Passed")
    assert record.state == PatchLifecycleState.VERIFIED

    # Apply patch
    success, msg = manager.apply_patch(patch.patch_id, temp_repo)
    assert success is True
    assert record.state == PatchLifecycleState.APPLIED


def test_lifecycle_state_machine_illegal_transition_rejected(temp_repo: Path):
    manager = PatchLifecycleManager()
    finding = {"file": "calc.py", "line": 2, "rule_id": "RULE-1", "fingerprint": "fp_illegal"}
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    record = manager.register_patch(patch)
    # Directly set to ROLLED_BACK (terminal state)
    record.state = PatchLifecycleState.ROLLED_BACK

    # Try applying from ROLLED_BACK -> illegal transition!
    success, msg = manager.apply_patch(patch.patch_id, temp_repo)
    assert success is False
    assert "Illegal state transition" in msg


def test_lifecycle_atomic_backup_created_with_hash(temp_repo: Path):
    manager = PatchLifecycleManager()
    finding = {"file": "model.py", "line": 2, "rule_id": "TYPE-UNCHECKED-OPTIONAL-DEREFERENCE", "fingerprint": "fp_bk"}
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None

    record = manager.register_patch(patch)
    record.state = PatchLifecycleState.VERIFIED
    success, msg = manager.apply_patch(patch.patch_id, temp_repo)
    assert success is True
    assert record.backup_file_path is not None

    bk_path = temp_repo / record.backup_file_path
    assert bk_path.is_file()
    assert record.backup_sha256 == compute_content_sha256(bk_path.read_text(encoding="utf-8"))


def test_lifecycle_atomic_replace_modifies_target_file(temp_repo: Path):
    manager = PatchLifecycleManager()
    finding = {"file": "model.py", "line": 2, "rule_id": "TYPE-UNCHECKED-OPTIONAL-DEREFERENCE", "fingerprint": "fp_rep"}
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None

    record = manager.register_patch(patch)
    record.state = PatchLifecycleState.VERIFIED
    manager.apply_patch(patch.patch_id, temp_repo)

    current_code = (temp_repo / "model.py").read_text(encoding="utf-8")
    assert "if user is not None:" in current_code
    assert compute_content_sha256(current_code) == record.applied_sha256


def test_lifecycle_idempotent_apply(temp_repo: Path):
    manager = PatchLifecycleManager()
    finding = {"file": "calc.py", "line": 2, "rule_id": "GENERAL", "fingerprint": "fp_idem"}
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None

    record = manager.register_patch(patch)
    record.state = PatchLifecycleState.VERIFIED
    s1, _ = manager.apply_patch(patch.patch_id, temp_repo)
    assert s1 is True

    # Repeated apply -> returns True idempotently
    s2, msg2 = manager.apply_patch(patch.patch_id, temp_repo)
    assert s2 is True
    assert "already applied" in msg2


def test_lifecycle_rollback_restores_original_file(temp_repo: Path):
    manager = PatchLifecycleManager()
    orig = (temp_repo / "calc.py").read_text(encoding="utf-8")
    finding = {"file": "calc.py", "line": 2, "rule_id": "GENERAL", "fingerprint": "fp_rb"}
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None

    record = manager.register_patch(patch)
    record.state = PatchLifecycleState.VERIFIED
    manager.apply_patch(patch.patch_id, temp_repo)

    # Roll back
    rb_ok, rb_msg = manager.rollback_patch(patch.patch_id, temp_repo)
    assert rb_ok is True
    assert record.state == PatchLifecycleState.ROLLED_BACK
    assert (temp_repo / "calc.py").read_text(encoding="utf-8") == orig


def test_lifecycle_rollback_conflict_prevents_destroying_newer_changes(temp_repo: Path):
    manager = PatchLifecycleManager()
    finding = {"file": "calc.py", "line": 2, "rule_id": "GENERAL", "fingerprint": "fp_rb_conf"}
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None

    record = manager.register_patch(patch)
    record.state = PatchLifecycleState.VERIFIED
    manager.apply_patch(patch.patch_id, temp_repo)

    # Developer makes changes on disk AFTER patch was applied!
    (temp_repo / "calc.py").write_text("def newer_code(): pass\n", encoding="utf-8")

    # Rollback must DETECT CONFLICT and ABORT to prevent destroying newer code!
    rb_ok, rb_msg = manager.rollback_patch(patch.patch_id, temp_repo)
    assert rb_ok is False
    assert "ROLLBACK_CONFLICT" in rb_msg
    assert record.state == PatchLifecycleState.ROLLBACK_CONFLICT
    assert (temp_repo / "calc.py").read_text(encoding="utf-8") == "def newer_code(): pass\n"


def test_lifecycle_concurrency_lock_enforced():
    manager = PatchLifecycleManager()
    lock = manager._get_lock("repo_test_key")
    assert lock.acquire(blocking=False) is True
    # Second acquisition fails
    assert lock.acquire(blocking=False) is False
    lock.release()


def test_lifecycle_symlink_escape_blocked(temp_repo: Path):
    manager = PatchLifecycleManager()
    # Create symlink pointing outside repo if OS supports it
    try:
        external_file = temp_repo.parent / "outside.py"
        external_file.write_text("outside = True\n", encoding="utf-8")
        symlink_target = temp_repo / "sym_link.py"
        os.symlink(external_file, symlink_target)

        patch = CodePatch(
            patch_id="p_sym",
            finding_id="f1",
            rule_id="R1",
            file="sym_link.py",
            original_snippet="",
            patched_snippet="",
            unified_diff="",
            strategy=PatchStrategy.DETERMINISTIC_AST,
            summary="",
            explanation="",
            patched_full_content="evil = True\n",
        )
        record = manager.register_patch(patch)
        record.state = PatchLifecycleState.VERIFIED
        success, msg = manager.apply_patch(patch.patch_id, temp_repo)
        assert success is False
        assert "symlink" in msg.lower()
    except (OSError, NotImplementedError):
        pass  # Skip if symlinks not permitted for current user on Windows


def test_lifecycle_audit_trail_recorded(temp_repo: Path):
    manager = PatchLifecycleManager()
    finding = {"file": "calc.py", "line": 2, "rule_id": "GENERAL", "fingerprint": "fp_audit"}
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None

    record = manager.register_patch(patch)
    record.state = PatchLifecycleState.VERIFIED
    manager.apply_patch(patch.patch_id, temp_repo)

    assert len(record.audit_trail) >= 2
    actions = [a.action for a in record.audit_trail]
    assert "REGISTER_PATCH" in actions
    assert "APPLY_SUCCESS" in actions


# ==============================================================================
# GROUP 6: Post-Apply Verification Tests (4 tests)
# ==============================================================================

def test_post_apply_remediation_confirmed(temp_repo: Path):
    patch = CodePatch(
        patch_id="p_post_1",
        finding_id="fp_test",
        rule_id="ASYNC-BLOCKING-IO-CALL",
        file="async_worker.py",
        original_snippet="",
        patched_snippet="",
        unified_diff="",
        strategy=PatchStrategy.DETERMINISTIC_AST,
        summary="",
        explanation="",
    )
    # File does not have time.sleep -> flaw eliminated
    (temp_repo / "async_worker.py").write_text("async def process():\n    return 'clean'\n", encoding="utf-8")
    res = PostApplyVerifier.verify_application(temp_repo, patch)
    assert res.flaw_eliminated is True
    assert res.outcome in {PostApplyOutcome.REMEDIATION_CONFIRMED, PostApplyOutcome.REMEDIATION_PARTIAL}


def test_post_apply_original_flaw_persists(temp_repo: Path):
    patch = CodePatch(
        patch_id="p_post_2",
        finding_id="fp_test_2",
        rule_id="ASYNC-BLOCKING-IO-CALL",
        file="async_worker.py",
        original_snippet="",
        patched_snippet="",
        unified_diff="",
        strategy=PatchStrategy.DETERMINISTIC_AST,
        summary="",
        explanation="",
    )
    # File still has blocking time.sleep call in async function!
    (temp_repo / "async_worker.py").write_text("import time\n\nasync def process():\n    time.sleep(1)\n", encoding="utf-8")
    res = PostApplyVerifier.verify_application(temp_repo, patch)
    assert res.flaw_eliminated is False
    assert res.outcome == PostApplyOutcome.REMEDIATION_FAILED


def test_post_apply_unverifiable_on_missing_file(temp_repo: Path):
    patch = CodePatch(
        patch_id="p_post_3",
        finding_id="fp_test_3",
        rule_id="RULE-1",
        file="missing_post.py",
        original_snippet="",
        patched_snippet="",
        unified_diff="",
        strategy=PatchStrategy.DETERMINISTIC_AST,
        summary="",
        explanation="",
    )
    res = PostApplyVerifier.verify_application(temp_repo, patch)
    assert res.outcome == PostApplyOutcome.POST_APPLY_UNVERIFIABLE


def test_confidence_engine_dimensions_evaluation(temp_repo: Path):
    finding = {"file": "calc.py", "line": 2, "rule_id": "GENERAL", "fingerprint": "fp_conf_eval"}
    patch = PatchGenerator.generate_patch(finding, temp_repo)
    assert patch is not None
    manager = PatchLifecycleManager()
    record = manager.register_patch(patch)
    report = PatchConfidenceEngine.evaluate_patch(record)
    assert report.patch_id == patch.patch_id
    assert len(report.dimensions) == 6
    names = [d.name for d in report.dimensions]
    assert "Detection Confidence" in names
    assert "Transformation Confidence" in names
    assert "Semantic Confidence" in names
    assert "Behavioral Verification" in names
    assert "Application Integrity" in names
    assert "Remediation Confirmation" in names


# ==============================================================================
# GROUP 7: Multi-Tenant Security & REST API Tests (10 tests)
# ==============================================================================

@pytest.fixture
def api_test_setup(temp_repo: Path):
    db_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db_engine)
    session_factory = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)

    app = create_app(database_engine=db_engine)
    app.state.SessionLocal = session_factory

    with session_factory() as session:
        user_a = register_user(session, "tenant_a@apex.test", "tenant_a", "Password123!")
        user_b = register_user(session, "tenant_b@apex.test", "tenant_b", "Password123!")

        project = ReviewedProject(
            name="Tenant A Project",
            repository_path=str(temp_repo),
            owner_id=user_a.id,
            source_type="local",
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        proj_id = project.id

        token_a = create_access_token(user_a)
        token_b = create_access_token(user_b)

    return app, proj_id, token_a, token_b


def test_api_generate_fix_with_provenance_and_semantic(api_test_setup, temp_repo: Path):
    app, proj_id, token_a, _ = api_test_setup
    with TestClient(app) as client:
        resp = client.post(
            f"/api/project-reviews/{proj_id}/findings/fp_api_1/generate-fix",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "custom_finding": {
                    "file": "calc.py",
                    "line": 2,
                    "rule_id": "RULE-CALC",
                    "fingerprint": "fp_api_1",
                }
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "patch" in data
        assert "provenance" in data
        assert "semantic_verification" in data
        assert data["semantic_verification"]["valid"] is True


def test_api_get_provenance_owner_success(api_test_setup):
    app, proj_id, token_a, _ = api_test_setup
    with TestClient(app) as client:
        gen = client.post(
            f"/api/project-reviews/{proj_id}/findings/fp_prov/generate-fix",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"custom_finding": {"file": "calc.py", "line": 2, "rule_id": "R1", "fingerprint": "fp_prov"}},
        )
        patch_id = gen.json()["patch"]["patch_id"]

        resp = client.get(
            f"/api/project-reviews/{proj_id}/patches/{patch_id}/provenance",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        assert resp.json()["provenance"]["patch_id"] == patch_id


def test_api_get_provenance_cross_tenant_404(api_test_setup):
    app, proj_id, token_a, token_b = api_test_setup
    with TestClient(app) as client:
        gen = client.post(
            f"/api/project-reviews/{proj_id}/findings/fp_cross/generate-fix",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"custom_finding": {"file": "calc.py", "line": 2, "rule_id": "R1", "fingerprint": "fp_cross"}},
        )
        patch_id = gen.json()["patch"]["patch_id"]

        # Cross-tenant request -> 404
        resp = client.get(
            f"/api/project-reviews/{proj_id}/patches/{patch_id}/provenance",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.status_code == 404


def test_api_get_verification_confidence_report(api_test_setup):
    app, proj_id, token_a, _ = api_test_setup
    with TestClient(app) as client:
        gen = client.post(
            f"/api/project-reviews/{proj_id}/findings/fp_conf/generate-fix",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"custom_finding": {"file": "calc.py", "line": 2, "rule_id": "R1", "fingerprint": "fp_conf"}},
        )
        patch_id = gen.json()["patch"]["patch_id"]

        resp = client.get(
            f"/api/project-reviews/{proj_id}/patches/{patch_id}/verification",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "dimensions" in data
        assert len(data["dimensions"]) == 6


def test_api_get_history_audit_trail(api_test_setup):
    app, proj_id, token_a, _ = api_test_setup
    with TestClient(app) as client:
        gen = client.post(
            f"/api/project-reviews/{proj_id}/findings/fp_hist/generate-fix",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"custom_finding": {"file": "calc.py", "line": 2, "rule_id": "R1", "fingerprint": "fp_hist"}},
        )
        patch_id = gen.json()["patch"]["patch_id"]

        resp = client.get(
            f"/api/project-reviews/{proj_id}/patches/{patch_id}/history",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        assert "audit_trail" in resp.json()
        assert len(resp.json()["audit_trail"]) >= 1


def test_api_verify_semantic_endpoint(api_test_setup):
    app, proj_id, token_a, _ = api_test_setup
    with TestClient(app) as client:
        gen = client.post(
            f"/api/project-reviews/{proj_id}/findings/fp_sem/generate-fix",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"custom_finding": {"file": "calc.py", "line": 2, "rule_id": "R1", "fingerprint": "fp_sem"}},
        )
        patch_id = gen.json()["patch"]["patch_id"]

        resp = client.post(
            f"/api/project-reviews/{proj_id}/patches/{patch_id}/verify-semantic",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        assert resp.json()["valid"] is True


def test_api_verify_behavioral_endpoint(api_test_setup):
    app, proj_id, token_a, _ = api_test_setup
    with TestClient(app) as client:
        gen = client.post(
            f"/api/project-reviews/{proj_id}/findings/fp_beh/generate-fix",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"custom_finding": {"file": "calc.py", "line": 2, "rule_id": "R1", "fingerprint": "fp_beh"}},
        )
        patch_id = gen.json()["patch"]["patch_id"]

        resp = client.post(
            f"/api/project-reviews/{proj_id}/patches/{patch_id}/verify-behavioral",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        assert "status" in resp.json()


def test_api_stale_check_endpoint(api_test_setup):
    app, proj_id, token_a, _ = api_test_setup
    with TestClient(app) as client:
        client.post(
            f"/api/project-reviews/{proj_id}/findings/fp_stale/generate-fix",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"custom_finding": {"file": "calc.py", "line": 2, "rule_id": "R1", "fingerprint": "fp_stale"}},
        )

        resp = client.get(
            f"/api/project-reviews/{proj_id}/patches/stale-check",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        assert "checks" in resp.json()


def test_api_rollback_conflict_returns_409(api_test_setup, temp_repo: Path):
    app, proj_id, token_a, _ = api_test_setup
    with TestClient(app) as client:
        gen = client.post(
            f"/api/project-reviews/{proj_id}/findings/fp_409/generate-fix",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"custom_finding": {"file": "calc.py", "line": 2, "rule_id": "R1", "fingerprint": "fp_409"}},
        )
        patch_id = gen.json()["patch"]["patch_id"]

        # Apply patch
        app_resp = client.post(
            f"/api/project-reviews/{proj_id}/patches/{patch_id}/apply",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert app_resp.status_code == 200

        # Modify file on disk to trigger rollback conflict
        (temp_repo / "calc.py").write_text("def conflicting_edit(): pass\n", encoding="utf-8")

        # Rollback -> 409 Conflict!
        rb_resp = client.post(
            f"/api/project-reviews/{proj_id}/patches/{patch_id}/rollback",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert rb_resp.status_code == 409
        assert "ROLLBACK_CONFLICT" in rb_resp.json()["detail"]


def test_api_cross_tenant_apply_and_rollback_denied(api_test_setup):
    app, proj_id, token_a, token_b = api_test_setup
    with TestClient(app) as client:
        gen = client.post(
            f"/api/project-reviews/{proj_id}/findings/fp_denied/generate-fix",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"custom_finding": {"file": "calc.py", "line": 2, "rule_id": "R1", "fingerprint": "fp_denied"}},
        )
        patch_id = gen.json()["patch"]["patch_id"]

        # Tenant B apply -> 404
        apply_denied = client.post(
            f"/api/project-reviews/{proj_id}/patches/{patch_id}/apply",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert apply_denied.status_code == 404

        # Tenant B rollback -> 404
        rb_denied = client.post(
            f"/api/project-reviews/{proj_id}/patches/{patch_id}/rollback",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert rb_denied.status_code == 404

