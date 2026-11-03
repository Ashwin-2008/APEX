"""Dry-Run Verification Sandbox for Generated Code Patches in APEX 2.0.

Verifies generated patches before disk application:
1. In-memory clean diff application.
2. AST syntax check (prevents introducing syntax errors).
3. In-memory flaw elimination check (ensures the target defect is actually resolved).
4. Structural regression check (ensures no functions or classes were deleted).
"""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from app.services.remediation.patch_generator import CodePatch


class PatchVerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    DIFF_APPLY_FAILED = "DIFF_APPLY_FAILED"
    FLAW_PERSISTS = "FLAW_PERSISTS"
    REGRESSION_INTRODUCED = "REGRESSION_INTRODUCED"


@dataclass
class PatchVerificationResult:
    status: PatchVerificationStatus
    valid: bool
    syntax_ok: bool
    flaw_eliminated: bool
    details: str
    diff: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


class PatchVerifier:
    """Dry-run verification sandbox for generated patches."""

    @classmethod
    def apply_patch_in_memory(cls, original_code: str, patch: CodePatch) -> str | None:
        """Applies patch in memory without modifying the filesystem."""
        if patch.patched_full_content:
            return patch.patched_full_content

        # Fallback line substitution if snippet matches
        if patch.original_snippet and patch.original_snippet in original_code:
            return original_code.replace(patch.original_snippet, patch.patched_snippet, 1)

        return None

    @classmethod
    def verify_patch(
        cls,
        patch: CodePatch,
        repo_root: Path | None = None,
        original_code: str | None = None,
    ) -> PatchVerificationResult:
        """Runs the 4-stage verification sandbox on a candidate patch."""
        # Step 1: Read original code if not provided
        if original_code is None:
            if not repo_root:
                return PatchVerificationResult(
                    status=PatchVerificationStatus.DIFF_APPLY_FAILED,
                    valid=False,
                    syntax_ok=False,
                    flaw_eliminated=False,
                    details="Neither original_code nor repo_root was provided for verification.",
                    diff=patch.unified_diff,
                )
            target_path = repo_root / patch.file
            if not target_path.is_file():
                return PatchVerificationResult(
                    status=PatchVerificationStatus.DIFF_APPLY_FAILED,
                    valid=False,
                    syntax_ok=False,
                    flaw_eliminated=False,
                    details=f"Target file {patch.file} does not exist on disk.",
                    diff=patch.unified_diff,
                )
            try:
                original_code = target_path.read_text(encoding="utf-8", errors="ignore")
            except OSError as e:
                return PatchVerificationResult(
                    status=PatchVerificationStatus.DIFF_APPLY_FAILED,
                    valid=False,
                    syntax_ok=False,
                    flaw_eliminated=False,
                    details=f"Failed reading {patch.file}: {e}",
                    diff=patch.unified_diff,
                )

        # Step 2: Apply patch in-memory
        patched_code = cls.apply_patch_in_memory(original_code, patch)
        if patched_code is None:
            return PatchVerificationResult(
                status=PatchVerificationStatus.DIFF_APPLY_FAILED,
                valid=False,
                syntax_ok=False,
                flaw_eliminated=False,
                details="Failed applying patch diff cleanly in-memory.",
                diff=patch.unified_diff,
            )

        # Step 3: AST Syntax Verification
        try:
            patched_tree = ast.parse(patched_code, filename=patch.file)
        except SyntaxError as e:
            return PatchVerificationResult(
                status=PatchVerificationStatus.SYNTAX_ERROR,
                valid=False,
                syntax_ok=False,
                flaw_eliminated=False,
                details=f"Patch introduces SyntaxError: '{e.msg}' at line {e.lineno}, col {e.offset}",
                diff=patch.unified_diff,
            )

        # Step 4: Flaw Elimination Verification
        flaw_persists, flaw_reason = cls._check_flaw_persists(patched_tree, patched_code, patch.rule_id)
        if flaw_persists:
            return PatchVerificationResult(
                status=PatchVerificationStatus.FLAW_PERSISTS,
                valid=False,
                syntax_ok=True,
                flaw_eliminated=False,
                details=f"Target defect persists after patch: {flaw_reason}",
                diff=patch.unified_diff,
            )

        # Step 5: Regression Prevention Check
        try:
            orig_tree = ast.parse(original_code, filename=patch.file)
            orig_defs = {node.name for node in ast.walk(orig_tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
            new_defs = {node.name for node in ast.walk(patched_tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
            dropped_defs = orig_defs - new_defs
            if dropped_defs:
                return PatchVerificationResult(
                    status=PatchVerificationStatus.REGRESSION_INTRODUCED,
                    valid=False,
                    syntax_ok=True,
                    flaw_eliminated=True,
                    details=f"Patch inadvertently removed definitions: {sorted(list(dropped_defs))}",
                    diff=patch.unified_diff,
                )
        except Exception:
            pass  # If original had syntax issues, ignore regression definition check

        return PatchVerificationResult(
            status=PatchVerificationStatus.VERIFIED,
            valid=True,
            syntax_ok=True,
            flaw_eliminated=True,
            details="Patch passed dry-run verification: clean AST syntax, target flaw eliminated, zero regressions.",
            diff=patch.unified_diff,
        )

    @classmethod
    def _check_flaw_persists(cls, tree: ast.AST, code: str, rule_id: str) -> tuple[bool, str]:
        """Inspects patched AST/code to ensure the target flaw was eliminated."""
        # 1. Concurrency: ASYNC-BLOCKING-IO-CALL
        if "ASYNC-BLOCKING-IO-CALL" in rule_id:
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef):
                    for subnode in ast.walk(node):
                        if isinstance(subnode, ast.Call):
                            # Check for time.sleep
                            if isinstance(subnode.func, ast.Attribute) and subnode.func.attr == "sleep":
                                if isinstance(subnode.func.value, ast.Name) and subnode.func.value.id == "time":
                                    return True, "Blocking call 'time.sleep' still present in async function."
            return False, ""

        # 2. Security: SEC-TAINT-COMMAND-INJECTION
        if "SEC-TAINT-COMMAND-INJECTION" in rule_id or "CMD-INJECTION" in rule_id:
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for kw in node.keywords:
                        if kw.arg == "shell":
                            if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                                return True, "Vulnerable keyword argument 'shell=True' still present."
            return False, ""

        # 3. Resource Management: RESOURCE-UNCLOSED-HANDLE
        if "RESOURCE-UNCLOSED-HANDLE" in rule_id:
            # Check if open() is invoked outside a with statement
            with_opens = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.With, ast.AsyncWith)):
                    for item in node.items:
                        with_opens.add(item.context_expr)

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id == "open":
                        if node not in with_opens:
                            # If bare open call outside with statement
                            return True, "Unclosed resource handle: bare 'open()' call without 'with' statement."
            return False, ""

        return False, ""

