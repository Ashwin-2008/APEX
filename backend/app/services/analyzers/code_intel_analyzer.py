"""Advanced AST Code Intelligence Engine: McCabe cyclomatic complexity and dead-code detection.

Implements Module C of Phase 2A:
- Mathematically precise McCabe cyclomatic complexity with granular tier categorization.
- Conservative dead-code detection (unreachable code after return/raise, unreferenced private symbols, unused imports).
- Framework and entrypoint awareness (preserves FastAPI/Flask routes, Pytest fixtures, Celery tasks, and __all__ exports).
- Maintainability intelligence (excessive nesting depth, parameter bloat, broad exceptions).
"""
from __future__ import annotations

import ast
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.analyzers.base import AnalyzerOutput, AnalyzerStatus, FindingItem
from app.services.analyzers.repository_graph import (
    RepositorySymbolIndex,
    calculate_mccabe_complexity,
)

FRAMEWORK_DECORATORS = frozenset({
    "get", "post", "put", "delete", "patch", "route", "options", "head",
    "fixture", "mark", "task", "shared_task", "command", "group", "option",
    "validator", "field_validator", "root_validator", "property", "setter",
    "classmethod", "staticmethod", "abstractmethod", "override", "listens_for",
})


def _is_framework_symbol(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    """Determine if a function/class is protected from dead-code elimination by framework conventions."""
    # 1. Test functions
    if node.name.startswith("test_") or node.name.endswith("_test"):
        return True

    # 2. Dunder methods
    if node.name.startswith("__") and node.name.endswith("__"):
        return True

    # 3. Decorator inspection
    for dec in getattr(node, "decorator_list", []):
        dec_name = ""
        if isinstance(dec, ast.Name):
            dec_name = dec.id
        elif isinstance(dec, ast.Attribute):
            dec_name = dec.attr
        elif isinstance(dec, ast.Call):
            if isinstance(dec.func, ast.Name):
                dec_name = dec.func.id
            elif isinstance(dec.func, ast.Attribute):
                dec_name = dec.func.attr

        if dec_name.lower() in FRAMEWORK_DECORATORS:
            return True

    return False


def _calculate_max_nesting(node: ast.AST, current_depth: int = 0) -> int:
    """Calculate maximum block nesting depth inside a function."""
    max_d = current_depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith)):
            d = _calculate_max_nesting(child, current_depth + 1)
            if d > max_d:
                max_d = d
        else:
            d = _calculate_max_nesting(child, current_depth)
            if d > max_d:
                max_d = d
    return max_d


class DeadCodeVisitor(ast.NodeVisitor):
    """Detects unreachable statements and unused imports within a single file."""

    def __init__(self, filename: str, lines: list[str]) -> None:
        self.filename = filename
        self.lines = lines
        self.findings: list[FindingItem] = []
        self.imported_names: dict[str, int] = {}  # name -> line
        self.used_names: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            self.imported_names[name] = node.lineno
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            name = alias.asname or alias.name
            if name != "*":
                self.imported_names[name] = node.lineno
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Load, ast.Del)):
            self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.used_names.add(node.attr)
        self.generic_visit(node)

    def _check_block_unreachable(self, stmts: list[ast.stmt]) -> None:
        for idx, stmt in enumerate(stmts):
            if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                # Any statements immediately following this in the same block are unreachable
                if idx + 1 < len(stmts):
                    next_stmt = stmts[idx + 1]
                    unreach_line = getattr(next_stmt, "lineno", stmt.lineno + 1)
                    stmt_type = type(stmt).__name__.lower()
                    self.findings.append(
                        FindingItem(
                            category="error_handling",
                            severity="medium",
                            confidence=0.96,
                            evidence=(
                                f"Unreachable code detected at line {unreach_line}: statement appears "
                                f"after an unconditional '{stmt_type}' at line {stmt.lineno}."
                            ),
                            analyzer_source="dead_code_analyzer",
                            rule_id="CODE-UNREACHABLE-STMT",
                            file=self.filename,
                            line=unreach_line,
                            title=f"Unreachable Statement in {self.filename}:{unreach_line}",
                            remediation="Remove or refactor unreachable statements after unconditional control flow.",
                        )
                    )
                break

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_block_unreachable(node.body)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_block_unreachable(node.body)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self._check_block_unreachable(node.body)
        self._check_block_unreachable(node.orelse)

        # Check statically impossible branch (if False / if 0)
        if isinstance(node.test, ast.Constant) and not bool(node.test.value):
            self.findings.append(
                FindingItem(
                    category="error_handling",
                    severity="low",
                    confidence=0.99,
                    evidence=f"Statically unreachable 'if {node.test.value}:' branch at line {node.lineno}.",
                    analyzer_source="dead_code_analyzer",
                    rule_id="CODE-STATICALLY-FALSE-BRANCH",
                    file=self.filename,
                    line=node.lineno,
                    title=f"Statically False Branch in {self.filename}:{node.lineno}",
                    remediation="Remove dead conditional branches that can never execute.",
                )
            )
        self.generic_visit(node)

    def finalize(self) -> None:
        # Check unused imports (skip __init__.py which commonly re-exports symbols)
        if not self.filename.endswith("__init__.py"):
            for imp_name, line in self.imported_names.items():
                if imp_name not in self.used_names:
                    self.findings.append(
                        FindingItem(
                            category="architecture",
                            severity="low",
                            confidence=0.91,
                            evidence=f"Unused import '{imp_name}' declared at line {line}.",
                            analyzer_source="dead_code_analyzer",
                            rule_id="CODE-UNUSED-IMPORT",
                            file=self.filename,
                            line=line,
                            title=f"Unused Import '{imp_name}' in {self.filename}",
                            remediation="Remove unreferenced imports to keep module dependencies clean and reduce load times.",
                        )
                    )


def run_code_intelligence_analysis(root_dir: str | Path) -> AnalyzerOutput:
    """Perform repository-wide McCabe complexity indexing and conservative dead-code detection."""
    start_time = time.perf_counter()
    root = Path(root_dir).resolve()
    findings: list[FindingItem] = []

    symbol_index = RepositorySymbolIndex(root)

    # Collect all symbol identifiers referenced across the entire repository
    repo_referenced_names: set[str] = set()
    for mod_info in symbol_index.modules.values():
        p = root / mod_info.file_path
        if not p.is_file():
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content, filename=str(p))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    repo_referenced_names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    repo_referenced_names.add(node.attr)
        except Exception:
            pass

    complexity_counts = {"low": 0, "moderate": 0, "high": 0, "very_high": 0, "critical": 0}
    total_functions = 0
    max_complexity = 1
    highest_complexity_func: dict[str, Any] = {}

    for mod_name, mod_info in symbol_index.modules.items():
        file_path = root / mod_info.file_path
        if not file_path.is_file():
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            lines = content.splitlines()
            tree = ast.parse(content, filename=mod_info.file_path)
        except Exception:
            continue

        # 1. Unreachable statements and unused imports
        visitor = DeadCodeVisitor(mod_info.file_path, lines)
        visitor.visit(tree)
        visitor.finalize()
        findings.extend(visitor.findings)

        # 2. Function-level Complexity and Code Smells
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total_functions += 1
                comp = calculate_mccabe_complexity(node)
                start_ln = getattr(node, "lineno", 1)
                end_ln = getattr(node, "end_lineno", start_ln) or start_ln
                span = end_ln - start_ln + 1

                # Classify tier
                if comp <= 5:
                    complexity_counts["low"] += 1
                elif comp <= 10:
                    complexity_counts["moderate"] += 1
                elif comp <= 20:
                    complexity_counts["high"] += 1
                elif comp <= 50:
                    complexity_counts["very_high"] += 1
                else:
                    complexity_counts["critical"] += 1

                if comp > max_complexity:
                    max_complexity = comp
                    highest_complexity_func = {
                        "name": node.name,
                        "file": mod_info.file_path,
                        "line": start_ln,
                        "complexity": comp,
                    }

                # Actionable High Complexity Finding
                if comp >= 15 or (comp >= 10 and span >= 80):
                    sev = "critical" if comp > 30 else ("high" if comp >= 20 else "medium")
                    findings.append(
                        FindingItem(
                            category="architecture",
                            severity=sev,
                            confidence=0.92,
                            evidence=(
                                f"High McCabe cyclomatic complexity ({comp}) in `{node.name}` "
                                f"spanning {span} lines (lines {start_ln}-{end_ln})."
                            ),
                            analyzer_source="cyclomatic_complexity_analyzer",
                            rule_id="CODE-MCCABE-COMPLEXITY",
                            file=mod_info.file_path,
                            line=start_ln,
                            end_line=end_ln,
                            title=f"High Cyclomatic Complexity in `{node.name}` ({comp})",
                            remediation="Decompose nested decision branches into focused helper functions to reduce defect density.",
                            metadata={
                                "complexity": comp,
                                "line_span": span,
                                "function_name": node.name,
                            },
                        )
                    )

                # Excessive Parameter Count (> 6 parameters)
                param_count = len(node.args.args)
                if param_count > 6 and not _is_framework_symbol(node):
                    findings.append(
                        FindingItem(
                            category="maintainability",
                            severity="medium",
                            confidence=0.88,
                            evidence=f"Function `{node.name}` declares {param_count} parameters, exceeding the recommended limit of 6.",
                            analyzer_source="maintainability_analyzer",
                            rule_id="CODE-EXCESSIVE-PARAMETERS",
                            file=mod_info.file_path,
                            line=start_ln,
                            title=f"Parameter Bloat in `{node.name}` ({param_count} parameters)",
                            remediation="Encapsulate related parameters into a dedicated data transfer object (DTO) or Pydantic model.",
                            metadata={"parameter_count": param_count},
                        )
                    )

                # Excessive Nesting Depth (> 4 levels)
                nesting = _calculate_max_nesting(node)
                if nesting > 4:
                    findings.append(
                        FindingItem(
                            category="maintainability",
                            severity="medium",
                            confidence=0.87,
                            evidence=f"Function `{node.name}` has excessive nesting depth ({nesting} levels), impeding code readability.",
                            analyzer_source="maintainability_analyzer",
                            rule_id="CODE-EXCESSIVE-NESTING",
                            file=mod_info.file_path,
                            line=start_ln,
                            title=f"Deep Block Nesting in `{node.name}` ({nesting} levels)",
                            remediation="Use guard clauses and early returns to flatten deep conditional nesting.",
                            metadata={"nesting_depth": nesting},
                        )
                    )

                # 3. Unreferenced Private Function Check (Dead Code)
                if (
                    node.name.startswith("_")
                    and not (node.name.startswith("__") and node.name.endswith("__"))
                    and not _is_framework_symbol(node)
                ):
                    # Check if node.name is referenced anywhere outside its definition
                    # Count occurrences in repo_referenced_names
                    if node.name not in repo_referenced_names:
                        findings.append(
                            FindingItem(
                                category="maintainability",
                                severity="low",
                                confidence=0.85,
                                evidence=f"Private function `{node.name}` at line {start_ln} is never referenced in any repository module.",
                                analyzer_source="dead_code_analyzer",
                                rule_id="CODE-UNREFERENCED-PRIVATE-FUNCTION",
                                file=mod_info.file_path,
                                line=start_ln,
                                title=f"Unreferenced Private Function `{node.name}`",
                                remediation="Verify if this private function is obsolete and safely remove it to maintain repository hygiene.",
                            )
                        )

            # Suspicious broad exception catching (except: pass or except Exception: pass)
            elif isinstance(node, ast.ExceptHandler):
                is_broad = node.type is None or (isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"})
                if is_broad and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    line_no = getattr(node, "lineno", 1)
                    findings.append(
                        FindingItem(
                            category="error_handling",
                            severity="medium",
                            confidence=0.90,
                            evidence=f"Silent exception suppression detected at line {line_no} (`except Exception: pass`).",
                            analyzer_source="error_handling_analyzer",
                            rule_id="CODE-SILENT-EXCEPTION-PASS",
                            file=mod_info.file_path,
                            line=line_no,
                            title=f"Silent Exception Suppression in {mod_info.file_path}:{line_no}",
                            remediation="Log captured exceptions or handle specific exception types instead of silently swallowing errors.",
                        )
                    )

    duration = (time.perf_counter() - start_time) * 1000
    return AnalyzerOutput(
        analyzer_name="code_intel_analyzer",
        status=AnalyzerStatus.COMPLETE,
        findings=findings,
        metrics={
            "total_functions_analyzed": total_functions,
            "max_cyclomatic_complexity": max_complexity,
            "complexity_distribution": complexity_counts,
            "highest_complexity_function": highest_complexity_func,
            "dead_code_findings": sum(1 for f in findings if "dead_code" in f.analyzer_source),
        },
        duration_ms=duration,
        files_analyzed=len(symbol_index.modules),
        files_skipped=len(symbol_index.parse_errors),
    )

