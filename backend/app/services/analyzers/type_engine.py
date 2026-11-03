"""Type Intelligence Engine: PEP 484 type inference, None-safety risk analysis,
and type-informed false-positive mitigation for APEX 2.0.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.analyzers.base import FindingItem


NUMERIC_TYPES = {"int", "float", "complex"}
BOOL_TYPES = {"bool"}
SAFE_INJECTION_TYPES = NUMERIC_TYPES | BOOL_TYPES | {"uuid.UUID", "UUID"}


@dataclass
class TypeSignature:
    param_types: dict[str, str] = field(default_factory=dict)
    param_optionals: dict[str, bool] = field(default_factory=dict)
    return_type: str | None = None
    return_optional: bool = False


def stringify_annotation(node: ast.AST | None) -> str:
    """Convert an AST type annotation into a canonical string representation."""
    if node is None:
        return "Any"
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Attribute):
        return f"{stringify_annotation(node.value)}.{node.attr}"
    if isinstance(node, ast.Subscript):
        val = stringify_annotation(node.value)
        slice_val = stringify_annotation(node.slice)
        return f"{val}[{slice_val}]"
    if isinstance(node, ast.Tuple):
        elts = [stringify_annotation(e) for e in node.elts]
        return ", ".join(elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        # Python 3.10+ union: int | None
        left = stringify_annotation(node.left)
        right = stringify_annotation(node.right)
        return f"{left} | {right}"
    return "Any"


def is_optional_type(annotation_str: str) -> bool:
    """Determine if a type annotation includes None/Optional."""
    if not annotation_str or annotation_str == "Any":
        return False
    normalized = annotation_str.replace(" ", "")
    if "Optional[" in normalized:
        return True
    if "None" in normalized:
        if "|None" in normalized or "None|" in normalized:
            return True
        if "Union[" in normalized and "None" in normalized:
            return True
    return False


def is_safe_injection_type(annotation_str: str) -> bool:
    """Return True if the type annotation guarantees safety against string injection sinks."""
    if not annotation_str or annotation_str == "Any":
        return False
    normalized = annotation_str.replace(" ", "")
    # Check if purely numeric, boolean, or UUID
    for safe in SAFE_INJECTION_TYPES:
        if normalized == safe or normalized == f"Optional[{safe}]":
            return True
        if f"{safe}|None" == normalized or f"None|{safe}" == normalized:
            return True
    return False


class TypeSignatureExtractor(ast.NodeVisitor):
    """Extracts function parameter and return type signatures across a module AST."""

    def __init__(self, module_name: str = "") -> None:
        self.module_name = module_name
        self.signatures: dict[str, TypeSignature] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_function(node)
        self.generic_visit(node)

    def _record_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        sig = TypeSignature()
        # Parse return type
        if node.returns:
            ret_str = stringify_annotation(node.returns)
            sig.return_type = ret_str
            sig.return_optional = is_optional_type(ret_str)

        # Parse parameter types
        for arg in node.args.args:
            if arg.arg in {"self", "cls"}:
                continue
            if arg.annotation:
                ann_str = stringify_annotation(arg.annotation)
                sig.param_types[arg.arg] = ann_str
                sig.param_optionals[arg.arg] = is_optional_type(ann_str)
            else:
                sig.param_types[arg.arg] = "Any"
                sig.param_optionals[arg.arg] = False

        self.signatures[node.name] = sig


class NoneSafetyChecker(ast.NodeVisitor):
    """Detects unchecked attribute access or method calls on Optional[T] variables."""

    def __init__(self, file_path: str, source_code: str) -> None:
        self.file_path = file_path
        self.source_lines = source_code.splitlines()
        self.findings: list[FindingItem] = []
        # Current scope: var_name -> (type_str, line_def)
        self.optional_vars: dict[str, tuple[str, int]] = {}
        # Guarded variables in current scope
        self.guarded_vars: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._analyze_callable(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._analyze_callable(node)

    def _analyze_callable(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        saved_optionals = dict(self.optional_vars)
        saved_guards = set(self.guarded_vars)

        # Register optional parameters
        for arg in node.args.args:
            if arg.annotation:
                ann = stringify_annotation(arg.annotation)
                if is_optional_type(ann):
                    self.optional_vars[arg.arg] = (ann, arg.lineno)

        # Inspect statements inside function body
        self._inspect_block(node.body)

        self.optional_vars = saved_optionals
        self.guarded_vars = saved_guards

    def _inspect_block(self, statements: list[ast.stmt]) -> None:
        for stmt in statements:
            # 1. Assignment to Optional or None
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                ann = stringify_annotation(stmt.annotation)
                if is_optional_type(ann):
                    self.optional_vars[stmt.target.id] = (ann, stmt.lineno)
            elif isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and isinstance(stmt.value, ast.Constant) and stmt.value.value is None:
                        self.optional_vars[target.id] = ("Optional[Any]", stmt.lineno)

            # 2. Guard statements: if var is not None, if var:, assert var is not None
            if isinstance(stmt, ast.Assert):
                self._extract_guards(stmt.test)
            elif isinstance(stmt, ast.If):
                # Analyze guard condition
                new_guards = self._extract_guard_vars(stmt.test)
                
                # Check if this is an early exit pattern: if var is None: return / raise
                is_exit_guard = False
                for body_stmt in stmt.body:
                    if isinstance(body_stmt, (ast.Return, ast.Raise)):
                        is_exit_guard = True
                        break

                if is_exit_guard:
                    inverted_guards = self._extract_inverted_guards(stmt.test)
                    self.guarded_vars.update(inverted_guards)

                # Process 'then' block with new guards
                saved_guards = set(self.guarded_vars)
                self.guarded_vars.update(new_guards)
                self._inspect_block(stmt.body)
                self.guarded_vars = saved_guards

                # Process 'else' block
                if stmt.orelse:
                    self._inspect_block(stmt.orelse)
                continue

            # 3. Check for dereferences in this statement
            self._check_dereference(stmt)

            # Recursive traversal for nested compound statements
            if hasattr(stmt, "body") and isinstance(stmt.body, list) and not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.If)):
                self._inspect_block(stmt.body)

    def _extract_guard_vars(self, test: ast.expr) -> set[str]:
        """Extract variable names guarded against None in positive conditions (if var: / if var is not None:)."""
        guards: set[str] = set()
        if isinstance(test, ast.Name):
            guards.add(test.id)
        elif isinstance(test, ast.Compare):
            # var is not None
            if isinstance(test.left, ast.Name):
                for op, comp in zip(test.ops, test.comparators):
                    if isinstance(op, ast.IsNot) and isinstance(comp, ast.Constant) and comp.value is None:
                        guards.add(test.left.id)
                    elif isinstance(op, ast.NotEq) and isinstance(comp, ast.Constant) and comp.value is None:
                        guards.add(test.left.id)
        elif isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
            for val in test.values:
                guards.update(self._extract_guard_vars(val))
        return guards

    def _extract_inverted_guards(self, test: ast.expr) -> set[str]:
        """Extract variable names guarded when early return happens on None (if var is None: return)."""
        guards: set[str] = set()
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and isinstance(test.operand, ast.Name):
            guards.add(test.operand.id)
        elif isinstance(test, ast.Compare):
            if isinstance(test.left, ast.Name):
                for op, comp in zip(test.ops, test.comparators):
                    if isinstance(op, ast.Is) and isinstance(comp, ast.Constant) and comp.value is None:
                        guards.add(test.left.id)
                    elif isinstance(op, ast.Eq) and isinstance(comp, ast.Constant) and comp.value is None:
                        guards.add(test.left.id)
        return guards

    def _extract_guards(self, test: ast.expr) -> None:
        """Update self.guarded_vars from assert statements."""
        self.guarded_vars.update(self._extract_guard_vars(test))

    def _check_dereference(self, node: ast.AST) -> None:
        """Traverse expressions inside statement to find unguarded dereferences on optional variables."""
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                var_name = child.value.id
                if var_name in self.optional_vars and var_name not in self.guarded_vars:
                    ann_type, def_line = self.optional_vars[var_name]
                    line_no = getattr(child, "lineno", def_line)
                    code_snippet = self.source_lines[line_no - 1].strip() if 0 < line_no <= len(self.source_lines) else ""
                    self.findings.append(
                        FindingItem(
                            category="bug_risk",
                            severity="high",
                            confidence=0.88,
                            evidence=(
                                f"Variable '{var_name}' annotated as '{ann_type}' is dereferenced "
                                f"('.{child.attr}') without a None-check at line {line_no}:\n`{code_snippet}`"
                            ),
                            analyzer_source="type_intelligence",
                            rule_id="TYPE-UNCHECKED-OPTIONAL-DEREFERENCE",
                            title="Unchecked Optional Dereference Risk (NoneType Attribute Access)",
                            remediation=(
                                f"Add an explicit guard `if {var_name} is not None:` or `assert {var_name} is not None` "
                                f"before accessing '.{child.attr}'."
                            ),
                            file=self.file_path,
                            line=line_no,
                        )
                    )


def run_type_intelligence_analysis(root_dir: str | Path) -> tuple[list[FindingItem], dict[str, Any], dict[str, TypeSignature]]:
    """Scan all Python modules for type signatures and None-safety risks."""
    root = Path(root_dir).resolve()
    findings: list[FindingItem] = []
    signatures: dict[str, TypeSignature] = {}

    total_functions = 0
    annotated_functions = 0
    total_params = 0
    annotated_params = 0

    for py_file in root.rglob("*.py"):
        if any(p in py_file.parts for p in {".git", "venv", ".venv", "__pycache__", "dist", "build"}):
            continue
        try:
            source = py_file.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source, filename=str(py_file))
        except (SyntaxError, OSError):
            continue

        rel_path = str(py_file.relative_to(root)).replace("\\", "/")
        mod_key = rel_path.replace(".py", "").replace("/", ".")

        # 1. Extract type signatures
        extractor = TypeSignatureExtractor(module_name=mod_key)
        extractor.visit(tree)
        for fn_name, sig in extractor.signatures.items():
            full_key = f"{mod_key}.{fn_name}"
            signatures[full_key] = sig
            total_functions += 1
            if sig.return_type != "Any":
                annotated_functions += 1
            for p_type in sig.param_types.values():
                total_params += 1
                if p_type != "Any":
                    annotated_params += 1

        # 2. Check None-Safety risks
        checker = NoneSafetyChecker(file_path=rel_path, source_code=source)
        checker.visit(tree)
        findings.extend(checker.findings)

    coverage_metrics = {
        "total_functions": total_functions,
        "annotated_functions": annotated_functions,
        "function_annotation_rate": round(annotated_functions / max(1, total_functions), 3),
        "total_params": total_params,
        "annotated_params": annotated_params,
        "param_annotation_rate": round(annotated_params / max(1, total_params), 3),
        "none_safety_violations_count": len(findings),
    }

    return findings, coverage_metrics, signatures
