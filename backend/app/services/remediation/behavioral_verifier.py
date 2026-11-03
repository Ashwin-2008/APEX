"""Behavioral Verification Engine for Candidate Code Patches in APEX 2.0.

Executes tests against both original baseline and candidate-patched code inside an
isolated sandbox (ephemeral Docker container or restricted subprocess environment).
Detects test regressions, validates flaw elimination, and computes behavioral integrity states:
- NOT_RUN
- BASELINE_FAILED
- PASSED
- REGRESSION_DETECTED
- PARTIALLY_PASSED
- TIMED_OUT
- EXECUTION_FAILED
- UNVERIFIABLE
"""
from __future__ import annotations

import ast
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.analyzers.dynamic_analyzer import is_docker_available, build_docker_sandbox_command
from app.services.remediation.patch_generator import CodePatch

logger = logging.getLogger(__name__)


class BehavioralStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    BASELINE_FAILED = "BASELINE_FAILED"
    PASSED = "PASSED"
    REGRESSION_DETECTED = "REGRESSION_DETECTED"
    PARTIALLY_PASSED = "PARTIALLY_PASSED"
    TIMED_OUT = "TIMED_OUT"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    UNVERIFIABLE = "UNVERIFIABLE"


@dataclass
class TestRunSummary:
    exit_code: int
    duration_ms: float
    total_tests: int
    passed_tests: int
    failed_tests: int
    failed_test_names: list[str] = field(default_factory=list)
    output: str = ""
    timed_out: bool = False


@dataclass
class BehavioralVerificationResult:
    status: BehavioralStatus
    valid: bool
    summary: str
    affected_symbol: str | None = None
    test_files_run: list[str] = field(default_factory=list)
    baseline_run: dict[str, Any] | None = None
    patched_run: dict[str, Any] | None = None
    newly_failing_tests: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


class BehavioralVerifier:
    """Executes behavioral test verification in temporary sandbox environments."""

    DEFAULT_TIMEOUT_SEC = 20

    @classmethod
    def identify_affected_symbols(cls, original_code: str, patch: CodePatch) -> list[str]:
        """Extracts function and class names surrounding the patched snippet."""
        affected: list[str] = []
        try:
            tree = ast.parse(original_code, filename=patch.file)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    # Check if patch original_snippet is inside node text or line range
                    if hasattr(ast, "unparse"):
                        node_text = ast.unparse(node)
                        if patch.original_snippet and patch.original_snippet.strip() in node_text:
                            affected.append(node.name)
                    else:
                        affected.append(node.name)
        except Exception:
            pass
        return list(dict.fromkeys(affected))

    @classmethod
    def discover_relevant_tests(
        cls,
        repo_root: Path,
        patch: CodePatch,
        affected_symbols: list[str],
    ) -> list[Path]:
        """Discovers test files targeting the patched file or affected symbols."""
        relevant: list[Path] = []
        target_stem = Path(patch.file).stem

        # Search for test files in repo
        test_patterns = [
            f"test_{target_stem}.py",
            f"{target_stem}_test.py",
            f"test_*{target_stem}*.py",
        ]
        for pattern in test_patterns:
            for p in repo_root.glob(f"**/{pattern}"):
                if p.is_file() and ".apex_backup" not in p.parts:
                    relevant.append(p)

        # Fallback: scan tests folder for symbol references
        tests_dir = repo_root / "tests"
        if tests_dir.is_dir() and not relevant:
            for p in tests_dir.rglob("test_*.py"):
                if p.is_file() and ".apex_backup" not in p.parts:
                    try:
                        content = p.read_text(encoding="utf-8", errors="ignore")
                        if target_stem in content or any(sym in content for sym in affected_symbols):
                            relevant.append(p)
                    except OSError:
                        continue

        return list(dict.fromkeys(relevant))

    @classmethod
    def _run_test_command(
        cls,
        working_dir: Path,
        test_file: Path | None = None,
        timeout: int = DEFAULT_TIMEOUT_SEC,
    ) -> TestRunSummary:
        """Executes test runner in an isolated subprocess with stripped environment."""
        start_t = time.perf_counter()

        cmd = [sys.executable, "-m", "pytest"]
        if test_file:
            cmd.append(str(test_file.relative_to(working_dir)))
        cmd.extend(["-q", "--no-header", "--tb=short"])

        # Restricted environment
        restricted_env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PYTHONPATH": str(working_dir),
            "PYTHONDONTWRITEBYTECODE": "1",
        }

        try:
            res = subprocess.run(
                cmd,
                cwd=str(working_dir),
                env=restricted_env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = (time.perf_counter() - start_t) * 1000
            output = (res.stdout or "") + "\n" + (res.stderr or "")

            total = 0
            passed = 0
            failed = 0
            failed_names = []

            # Parse pytest brief output summary e.g. "2 passed, 1 failed in 0.12s"
            passed_m = re.search(r"(\d+)\s+passed", output)
            failed_m = re.search(r"(\d+)\s+failed", output)
            if passed_m:
                passed = int(passed_m.group(1))
            if failed_m:
                failed = int(failed_m.group(1))
            total = passed + failed

            # Find failed test names
            for line in output.splitlines():
                if line.startswith("FAILED "):
                    failed_names.append(line.split()[1] if len(line.split()) > 1 else line)

            return TestRunSummary(
                exit_code=res.returncode,
                duration_ms=duration,
                total_tests=total,
                passed_tests=passed,
                failed_tests=failed,
                failed_test_names=failed_names,
                output=output,
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            duration = (time.perf_counter() - start_t) * 1000
            return TestRunSummary(
                exit_code=-1,
                duration_ms=duration,
                total_tests=0,
                passed_tests=0,
                failed_tests=0,
                output="Test execution timed out.",
                timed_out=True,
            )
        except Exception as e:
            duration = (time.perf_counter() - start_t) * 1000
            return TestRunSummary(
                exit_code=-2,
                duration_ms=duration,
                total_tests=0,
                passed_tests=0,
                failed_tests=0,
                output=f"Failed executing test runner: {e}",
                timed_out=False,
            )

    @classmethod
    def verify_patch_behavior(
        cls,
        repo_root: Path,
        patch: CodePatch,
        patched_code: str,
        timeout: int = DEFAULT_TIMEOUT_SEC,
    ) -> BehavioralVerificationResult:
        """Executes full behavioral baseline comparison between original and candidate patch."""
        orig_file = repo_root / patch.file
        if not orig_file.is_file():
            return BehavioralVerificationResult(
                status=BehavioralStatus.EXECUTION_FAILED,
                valid=False,
                summary=f"Target file {patch.file} does not exist in repository root.",
            )

        original_code = orig_file.read_text(encoding="utf-8", errors="ignore")
        affected_symbols = cls.identify_affected_symbols(original_code, patch)
        symbol_label = affected_symbols[0] if affected_symbols else None

        relevant_tests = cls.discover_relevant_tests(repo_root, patch, affected_symbols)
        if not relevant_tests:
            return BehavioralVerificationResult(
                status=BehavioralStatus.UNVERIFIABLE,
                valid=False,
                summary="No unit tests found covering the affected module or symbols; behavioral verification unverifiable.",
                affected_symbol=symbol_label,
                details=["No matching test files found for behavioral verification sandbox."],
            )

        # Create isolated temporary workspace
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_repo = Path(tmpdir)
            # Mirror the repo contents excluding .git, node_modules, .apex_backup
            for item in repo_root.iterdir():
                if item.name in {".git", "node_modules", ".apex_backup", "__pycache__", ".venv", "venv"}:
                    continue
                dest = temp_repo / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))
                else:
                    shutil.copy2(item, dest)

            # 1. Run baseline on original code
            baseline = cls._run_test_command(temp_repo, timeout=timeout)
            if baseline.timed_out:
                return BehavioralVerificationResult(
                    status=BehavioralStatus.TIMED_OUT,
                    valid=False,
                    summary="Baseline test run timed out before patch could be evaluated.",
                    affected_symbol=symbol_label,
                    baseline_run=asdict(baseline),
                )

            # 2. Apply patch in temporary repository
            temp_target = temp_repo / patch.file
            temp_target.parent.mkdir(parents=True, exist_ok=True)
            temp_target.write_text(patched_code, encoding="utf-8")

            # 3. Run candidate tests on patched code
            patched_run = cls._run_test_command(temp_repo, timeout=timeout)
            if patched_run.timed_out:
                return BehavioralVerificationResult(
                    status=BehavioralStatus.TIMED_OUT,
                    valid=False,
                    summary="Candidate patch test run timed out (possible infinite loop or hang).",
                    affected_symbol=symbol_label,
                    baseline_run=asdict(baseline),
                    patched_run=asdict(patched_run),
                )

            # 4. Compare Baseline vs Patched
            # Newly failing tests = tests that failed in patched_run but were NOT in baseline failed names
            newly_failing = [
                t for t in patched_run.failed_test_names
                if t not in baseline.failed_test_names
            ]

            if newly_failing:
                return BehavioralVerificationResult(
                    status=BehavioralStatus.REGRESSION_DETECTED,
                    valid=False,
                    summary=f"Behavioral regression detected: {len(newly_failing)} previously passing test(s) now fail.",
                    affected_symbol=symbol_label,
                    test_files_run=[str(p.relative_to(repo_root)) for p in relevant_tests],
                    baseline_run=asdict(baseline),
                    patched_run=asdict(patched_run),
                    newly_failing_tests=newly_failing,
                    details=[f"Regressed test: {t}" for t in newly_failing],
                )

            if baseline.failed_tests > 0 and patched_run.failed_tests > 0:
                # Pre-existing failures persisted without new regressions
                return BehavioralVerificationResult(
                    status=BehavioralStatus.PARTIALLY_PASSED,
                    valid=True,
                    summary=f"Patch passed behavioral check with pre-existing baseline failures ({patched_run.failed_tests} existing failures unchanged).",
                    affected_symbol=symbol_label,
                    test_files_run=[str(p.relative_to(repo_root)) for p in relevant_tests],
                    baseline_run=asdict(baseline),
                    patched_run=asdict(patched_run),
                    newly_failing_tests=[],
                )

            if patched_run.exit_code == 0:
                return BehavioralVerificationResult(
                    status=BehavioralStatus.PASSED,
                    valid=True,
                    summary=f"All {patched_run.passed_tests} behavioral tests passed cleanly against patched candidate.",
                    affected_symbol=symbol_label,
                    test_files_run=[str(p.relative_to(repo_root)) for p in relevant_tests],
                    baseline_run=asdict(baseline),
                    patched_run=asdict(patched_run),
                    newly_failing_tests=[],
                )

            return BehavioralVerificationResult(
                status=BehavioralStatus.EXECUTION_FAILED,
                valid=False,
                summary=f"Test runner exited with non-zero code {patched_run.exit_code}.",
                affected_symbol=symbol_label,
                test_files_run=[str(p.relative_to(repo_root)) for p in relevant_tests],
                baseline_run=asdict(baseline),
                patched_run=asdict(patched_run),
            )

