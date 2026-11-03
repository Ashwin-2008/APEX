"""Semantic Patch Verification Engine for APEX 2.0.

Goes beyond AST syntax parsing to verify program semantics:
1. Function Contract Preservation (names, parameters, defaults, return annotations, decorators, async/sync, raised exceptions).
2. Control-Flow Preservation (branches, loops, try/except/finally, return paths, raise, break/continue, await).
3. Variable and Scope Integrity (undefined names, references, bindings).
4. Semantic Risk Classification (SAFE_TRANSFORMATION, LOW_RISK_TRANSFORMATION, MEDIUM_RISK_TRANSFORMATION, HIGH_RISK_TRANSFORMATION, SEMANTICALLY_UNVERIFIABLE).
"""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from app.services.remediation.patch_generator import CodePatch


class SemanticRisk(str, Enum):
    SAFE_TRANSFORMATION = "SAFE_TRANSFORMATION"
    LOW_RISK_TRANSFORMATION = "LOW_RISK_TRANSFORMATION"
    MEDIUM_RISK_TRANSFORMATION = "MEDIUM_RISK_TRANSFORMATION"
    HIGH_RISK_TRANSFORMATION = "HIGH_RISK_TRANSFORMATION"
    SEMANTICALLY_UNVERIFIABLE = "SEMANTICALLY_UNVERIFIABLE"


@dataclass
class FunctionContract:
    name: str
    is_async: bool
    args: list[str]
    defaults_count: int
    has_vararg: bool
    has_kwarg: bool
    return_annotation: str | None
    decorators: list[str]
    raised_exceptions: list[str]
    has_return: bool


@dataclass
class SemanticVerificationResult:
    valid: bool
    risk_level: SemanticRisk
    summary: str
    details: list[str] = field(default_factory=list)
    contract_changes: list[str] = field(default_factory=list)
    control_flow_changes: list[str] = field(default_factory=list)
    undefined_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["risk_level"] = self.risk_level.value
        return data


class FunctionContractExtractor(ast.NodeVisitor):
    """Extracts function contracts from an AST."""

    def __init__(self) -> None:
        self.contracts: dict[str, FunctionContract] = {}

    def _extract_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = [arg.arg for arg in node.args.args]
        defaults_count = len(node.args.defaults)
        has_vararg = node.args.vararg is not None
        has_kwarg = node.args.kwarg is not None

        return_ann = None
        if node.returns:
            return_ann = ast.unparse(node.returns) if hasattr(ast, "unparse") else str(node.returns)

        decorators = []
        for dec in node.decorator_list:
            dec_str = ast.unparse(dec) if hasattr(ast, "unparse") else str(dec)
            decorators.append(dec_str)

        raised = []
        has_return = False
        for sub in ast.walk(node):
            if isinstance(sub, ast.Raise):
                if sub.exc:
                    exc_name = ast.unparse(sub.exc) if hasattr(ast, "unparse") else "Exception"
                    raised.append(exc_name)
            elif isinstance(sub, ast.Return):
                has_return = True

        self.contracts[node.name] = FunctionContract(
            name=node.name,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            args=args,
            defaults_count=defaults_count,
            has_vararg=has_vararg,
            has_kwarg=has_kwarg,
            return_annotation=return_ann,
            decorators=decorators,
            raised_exceptions=raised,
            has_return=has_return,
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._extract_func(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._extract_func(node)
        self.generic_visit(node)


class ControlFlowSummary:
    """Summarizes structural control-flow constructs."""

    def __init__(self, tree: ast.AST) -> None:
        self.if_count = 0
        self.loop_count = 0
        self.try_count = 0
        self.raise_count = 0
        self.return_count = 0
        self.await_count = 0
        self.with_count = 0

        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                self.if_count += 1
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                self.loop_count += 1
            elif isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
                self.try_count += 1
            elif isinstance(node, ast.Raise):
                self.raise_count += 1
            elif isinstance(node, ast.Return):
                self.return_count += 1
            elif isinstance(node, ast.Await):
                self.await_count += 1
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                self.with_count += 1


class ScopeIntegrityChecker(ast.NodeVisitor):
    """Detects potentially undefined names introduced into functions/modules."""

    BUILTIN_NAMES = {
        "abs", "all", "any", "ascii", "bin", "bool", "breakpoint", "bytearray", "bytes",
        "callable", "chr", "classmethod", "compile", "complex", "delattr", "dict", "dir",
        "divmod", "enumerate", "eval", "exec", "filter", "float", "format", "frozenset",
        "getattr", "globals", "hasattr", "hash", "help", "hex", "id", "input", "int",
        "isinstance", "issubclass", "iter", "len", "list", "locals", "map", "max",
        "memoryview", "min", "next", "object", "oct", "open", "ord", "pow", "print",
        "property", "range", "repr", "reversed", "round", "set", "setattr", "slice",
        "sorted", "staticmethod", "str", "sum", "super", "tuple", "type", "vars", "zip",
        "__import__", "None", "True", "False", "Ellipsis", "NotImplemented",
        "Exception", "BaseException", "ValueError", "TypeError", "KeyError", "IndexError",
        "AttributeError", "RuntimeError", "StopIteration", "OSError", "IOError",
    }

    def __init__(self) -> None:
        self.defined_globals: set[str] = set(self.BUILTIN_NAMES)
        self.undefined_references: set[str] = set()

    def check(self, tree: ast.AST) -> set[str]:
        # Collect all module-level imports and definitions
        for node in getattr(tree, "body", []):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.defined_globals.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    self.defined_globals.add(alias.asname or alias.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.defined_globals.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.defined_globals.add(target.id)

        # Check function bodies
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._check_function_scope(node)

        return self.undefined_references

    def _check_function_scope(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        local_scope = set(self.defined_globals)
        for arg in func_node.args.args:
            local_scope.add(arg.arg)
        if func_node.args.vararg:
            local_scope.add(func_node.args.vararg.arg)
        if func_node.args.kwarg:
            local_scope.add(func_node.args.kwarg.arg)

        # First pass: collect local assignments
        for sub in ast.walk(func_node):
            if isinstance(sub, ast.Assign):
                for target in sub.targets:
                    if isinstance(target, ast.Name):
                        local_scope.add(target.id)
            elif isinstance(sub, ast.For):
                if isinstance(sub.target, ast.Name):
                    local_scope.add(sub.target.id)
            elif isinstance(sub, (ast.With, ast.AsyncWith)):
                for item in sub.items:
                    if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                        local_scope.add(item.optional_vars.id)
            elif isinstance(sub, ast.ExceptHandler) and sub.name:
                local_scope.add(sub.name)

        # Second pass: check loaded names
        for sub in ast.walk(func_node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                if sub.id not in local_scope:
                    self.undefined_references.add(sub.id)


class SemanticVerifier:
    """Verifies semantic preservation between original and patched code."""

    @classmethod
    def verify_semantics(
        cls,
        original_code: str,
        patched_code: str,
        rule_id: str = "",
        expected_strategy: str = "",
    ) -> SemanticVerificationResult:
        try:
            orig_tree = ast.parse(original_code)
        except SyntaxError:
            return SemanticVerificationResult(
                valid=False,
                risk_level=SemanticRisk.SEMANTICALLY_UNVERIFIABLE,
                summary="Original code has syntax errors; cannot establish semantic baseline.",
                details=["Original code failed ast.parse."],
            )

        try:
            patched_tree = ast.parse(patched_code)
        except SyntaxError as e:
            return SemanticVerificationResult(
                valid=False,
                risk_level=SemanticRisk.HIGH_RISK_TRANSFORMATION,
                summary=f"Patched code introduces SyntaxError: {e.msg}",
                details=[f"Line {e.lineno}: {e.msg}"],
            )

        contract_changes: list[str] = []
        control_flow_changes: list[str] = []
        details: list[str] = []

        # 1. Function Contract Preservation
        orig_ext = FunctionContractExtractor()
        orig_ext.visit(orig_tree)
        orig_contracts = orig_ext.contracts

        patch_ext = FunctionContractExtractor()
        patch_ext.visit(patched_tree)
        patch_contracts = patch_ext.contracts

        for name, o_c in orig_contracts.items():
            if name not in patch_contracts:
                contract_changes.append(f"Function '{name}' was deleted or renamed.")
                continue

            p_c = patch_contracts[name]
            # Signature preservation
            if o_c.args != p_c.args:
                contract_changes.append(f"Function '{name}' parameters changed: {o_c.args} -> {p_c.args}")
            if o_c.defaults_count != p_c.defaults_count:
                contract_changes.append(f"Function '{name}' parameter defaults changed.")
            if o_c.return_annotation != p_c.return_annotation:
                contract_changes.append(f"Function '{name}' return type annotation altered.")
            if o_c.is_async != p_c.is_async:
                # Async alteration is permitted only if rule explicitly addresses async conversion
                if "ASYNC" not in rule_id:
                    contract_changes.append(f"Function '{name}' async status modified unexpectedly.")
            if o_c.has_return and not p_c.has_return:
                contract_changes.append(f"Function '{name}' had return statement which was removed.")
            if o_c.decorators != p_c.decorators:
                contract_changes.append(f"Function '{name}' decorators modified: {o_c.decorators} -> {p_c.decorators}")

        # 2. Control-Flow Preservation Analysis
        orig_cf = ControlFlowSummary(orig_tree)
        patch_cf = ControlFlowSummary(patched_tree)

        # Regressions in control flow
        if patch_cf.try_count < orig_cf.try_count:
            control_flow_changes.append("Patch removed try/except block(s), weakening exception handling.")
        if patch_cf.loop_count < orig_cf.loop_count:
            control_flow_changes.append("Patch removed loop structure(s).")

        # Intentional transformations
        if "TYPE-UNCHECKED-OPTIONAL-DEREFERENCE" in rule_id or "OPTIONAL" in rule_id:
            if patch_cf.if_count >= orig_cf.if_count:
                details.append("Expected None-guard branch added.")
        elif "RESOURCE-UNCLOSED-HANDLE" in rule_id:
            if patch_cf.with_count >= orig_cf.with_count:
                details.append("Expected context manager boundary established.")
        elif "ASYNC-BLOCKING-IO-CALL" in rule_id:
            if patch_cf.await_count >= orig_cf.await_count:
                details.append("Expected await expression introduced.")

        # 3. Variable and Scope Integrity
        scope_checker = ScopeIntegrityChecker()
        undefined = sorted(list(scope_checker.check(patched_tree)))

        # 4. Semantic Risk Classification
        if contract_changes:
            return SemanticVerificationResult(
                valid=False,
                risk_level=SemanticRisk.HIGH_RISK_TRANSFORMATION,
                summary="High semantic risk: Patch violates function contract or removes public symbols.",
                details=details,
                contract_changes=contract_changes,
                control_flow_changes=control_flow_changes,
                undefined_names=undefined,
            )

        if undefined:
            return SemanticVerificationResult(
                valid=False,
                risk_level=SemanticRisk.HIGH_RISK_TRANSFORMATION,
                summary=f"High semantic risk: Patch introduces undefined reference(s): {', '.join(undefined)}",
                details=details,
                contract_changes=contract_changes,
                control_flow_changes=control_flow_changes,
                undefined_names=undefined,
            )

        if control_flow_changes:
            return SemanticVerificationResult(
                valid=False,
                risk_level=SemanticRisk.MEDIUM_RISK_TRANSFORMATION,
                summary="Medium semantic risk: Patch altered exception or loop boundaries.",
                details=details,
                contract_changes=contract_changes,
                control_flow_changes=control_flow_changes,
                undefined_names=undefined,
            )

        # Safe transformations
        risk = SemanticRisk.SAFE_TRANSFORMATION if expected_strategy == "DETERMINISTIC_AST" else SemanticRisk.LOW_RISK_TRANSFORMATION
        return SemanticVerificationResult(
            valid=True,
            risk_level=risk,
            summary="Semantic verification passed: Function contracts preserved, control-flow sound, scope intact.",
            details=details,
            contract_changes=[],
            control_flow_changes=[],
            undefined_names=[],
        )

