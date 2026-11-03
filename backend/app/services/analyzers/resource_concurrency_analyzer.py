"""Resource Safety and Concurrency Risk Analyzer for APEX 2.0.

Detects:
1. Unclosed file handles, database sessions, and sockets (Resource Leaks).
2. Blocking synchronous I/O operations inside `async def` coroutines (Event Loop Starvation).
3. Unsynchronized mutation of shared module-level mutable state in concurrent/async scopes.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from app.services.analyzers.base import AnalyzerOutput, AnalyzerStatus, FindingItem


BLOCKING_ASYNC_CALLS = {
    "time.sleep": ("asyncio.sleep", "Use 'await asyncio.sleep()' to avoid blocking the event loop."),
    "requests.get": ("httpx.AsyncClient.get", "Use an asynchronous HTTP client like 'httpx.AsyncClient' or 'aiohttp'."),
    "requests.post": ("httpx.AsyncClient.post", "Use an asynchronous HTTP client like 'httpx.AsyncClient' or 'aiohttp'."),
    "subprocess.run": ("asyncio.create_subprocess_exec", "Use 'asyncio.create_subprocess_exec' or run in executor."),
    "subprocess.call": ("asyncio.create_subprocess_exec", "Use 'asyncio.create_subprocess_exec' or run in executor."),
}

RESOURCE_CREATORS = {
    "open": "file handle",
    "socket.socket": "network socket",
    "SessionLocal": "database session",
    "sqlite3.connect": "database connection",
    "psycopg2.connect": "database connection",
}


class ConcurrencyAndResourceVisitor(ast.NodeVisitor):
    """AST visitor detecting resource leaks, event loop blockers, and unsynchronized shared mutations."""

    def __init__(self, file_path: str, source_code: str) -> None:
        self.file_path = file_path
        self.source_lines = source_code.splitlines()
        self.findings: list[FindingItem] = []

        # Module-level mutable variables: name -> line_no
        self.module_mutables: dict[str, int] = {}
        self.current_function: str | None = None
        self.is_async_context: bool = False
        self.inside_lock_context: bool = False

    def visit_Module(self, node: ast.Module) -> None:
        # 1. Identify module-level mutable collections (dict, list, set)
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        if isinstance(stmt.value, (ast.Dict, ast.List, ast.Set)):
                            self.module_mutables[target.id] = stmt.lineno
                        elif isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name):
                            if stmt.value.func.id in {"dict", "list", "set", "defaultdict"}:
                                self.module_mutables[target.id] = stmt.lineno
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        prev_fn = self.current_function
        prev_async = self.is_async_context
        self.current_function = node.name
        self.is_async_context = True

        self._check_function_resources(node)
        self.generic_visit(node)

        self.current_function = prev_fn
        self.is_async_context = prev_async

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        prev_fn = self.current_function
        prev_async = self.is_async_context
        self.current_function = node.name
        self.is_async_context = False

        self._check_function_resources(node)
        self.generic_visit(node)

        self.current_function = prev_fn
        self.is_async_context = prev_async

    def visit_With(self, node: ast.With) -> None:
        prev_lock = self.inside_lock_context
        if self._is_lock_context(node.items):
            self.inside_lock_context = True
        self.generic_visit(node)
        self.inside_lock_context = prev_lock

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        prev_lock = self.inside_lock_context
        if self._is_lock_context(node.items):
            self.inside_lock_context = True
        self.generic_visit(node)
        self.inside_lock_context = prev_lock

    def visit_Call(self, node: ast.Call) -> None:
        call_name = self._get_call_name(node.func)
        line_no = getattr(node, "lineno", 1)

        # 1. Check for blocking calls inside async functions
        if self.is_async_context and call_name in BLOCKING_ASYNC_CALLS:
            replacement, rem_msg = BLOCKING_ASYNC_CALLS[call_name]
            snippet = self._get_snippet(line_no)
            self.findings.append(
                FindingItem(
                    category="performance",
                    severity="high",
                    confidence=0.92,
                    evidence=(
                        f"Blocking synchronous call '{call_name}()' executed inside async coroutine "
                        f"'{self.current_function}' at line {line_no}. This starves the event loop:\n`{snippet}`"
                    ),
                    analyzer_source="concurrency_analyzer",
                    rule_id="ASYNC-BLOCKING-IO-CALL",
                    title="Blocking Synchronous Call in Async Coroutine (Event Loop Starvation)",
                    remediation=rem_msg,
                    file=self.file_path,
                    line=line_no,
                )
            )

        # 2. Check for shared mutable modifications without locks in async functions
        if self.is_async_context and not self.inside_lock_context:
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                target_var = node.func.value.id
                method = node.func.attr
                if target_var in self.module_mutables and method in {"append", "extend", "pop", "update", "clear", "add", "remove"}:
                    snippet = self._get_snippet(line_no)
                    self.findings.append(
                        FindingItem(
                            category="bug_risk",
                            severity="high",
                            confidence=0.86,
                            evidence=(
                                f"Shared module-level mutable '{target_var}' modified via '.{method}()' "
                                f"inside async function '{self.current_function}' without a lock at line {line_no}:\n`{snippet}`"
                            ),
                            analyzer_source="concurrency_analyzer",
                            rule_id="CONCURRENCY-UNSYNCHRONIZED-SHARED-STATE",
                            title="Unsynchronized Shared Mutable State in Async Scope",
                            remediation=f"Protect mutations to '{target_var}' with 'async with asyncio.Lock():' or a thread lock.",
                            file=self.file_path,
                            line=line_no,
                        )
                    )

        self.generic_visit(node)

    def _check_function_resources(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Inspect statement block to find resource creations that lack a matching close() or context manager."""
        # Find resources bound in normal assignment: f = open(...)
        created_resources: dict[str, tuple[str, int]] = {}  # var_name -> (type, line)
        closed_resources: set[str] = set()

        for stmt in ast.walk(func_node):
            if isinstance(stmt, ast.Assign):
                if isinstance(stmt.value, ast.Call):
                    c_name = self._get_call_name(stmt.value.func)
                    if c_name in RESOURCE_CREATORS:
                        for target in stmt.targets:
                            if isinstance(target, ast.Name):
                                created_resources[target.id] = (RESOURCE_CREATORS[c_name], stmt.lineno)
            elif isinstance(stmt, ast.Call):
                # Check for .close() call: f.close()
                if isinstance(stmt.func, ast.Attribute) and stmt.func.attr == "close":
                    if isinstance(stmt.func.value, ast.Name):
                        closed_resources.add(stmt.func.value.id)

        # Subtract resources that were explicitly closed
        for var_name, (res_type, line_no) in created_resources.items():
            if var_name not in closed_resources:
                snippet = self._get_snippet(line_no)
                self.findings.append(
                    FindingItem(
                        category="resource",
                        severity="medium",
                        confidence=0.85,
                        evidence=(
                            f"Resource ({res_type}) allocated to variable '{var_name}' at line {line_no} "
                            f"is not enclosed in a context manager ('with') and has no explicit '.close()' call:\n`{snippet}`"
                        ),
                        analyzer_source="resource_analyzer",
                        rule_id="RESOURCE-UNCLOSED-HANDLE",
                        title=f"Potential Resource Leak: Unclosed {res_type.capitalize()}",
                        remediation=f"Use a context manager (`with ... as {var_name}:`) or ensure `{var_name}.close()` is called in a finally block.",
                        file=self.file_path,
                        line=line_no,
                    )
                )

    def _is_lock_context(self, items: list[ast.withitem]) -> bool:
        for item in items:
            name = self._get_call_name(item.context_expr)
            if any(k in name.lower() for k in ["lock", "mutex", "semaphore"]):
                return True
        return False

    def _get_call_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._get_call_name(node.value)}.{node.attr}"
        return ""

    def _get_snippet(self, line_no: int) -> str:
        if 0 < line_no <= len(self.source_lines):
            return self.source_lines[line_no - 1].strip()
        return ""


def run_resource_concurrency_analysis(root_dir: str | Path) -> tuple[list[FindingItem], dict[str, Any]]:
    """Scan all Python modules for unclosed resources, event loop blockers, and concurrency risks."""
    root = Path(root_dir).resolve()
    findings: list[FindingItem] = []

    total_async_functions = 0
    blocking_calls_found = 0
    unclosed_resources_found = 0

    for py_file in root.rglob("*.py"):
        if any(p in py_file.parts for p in {".git", "venv", ".venv", "__pycache__", "dist", "build"}):
            continue
        try:
            source = py_file.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source, filename=str(py_file))
        except (SyntaxError, OSError):
            continue

        rel_path = str(py_file.relative_to(root)).replace("\\", "/")
        visitor = ConcurrencyAndResourceVisitor(file_path=rel_path, source_code=source)
        visitor.visit(tree)

        findings.extend(visitor.findings)

        # Tally metrics
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                total_async_functions += 1

    for f in findings:
        if f.rule_id == "ASYNC-BLOCKING-IO-CALL":
            blocking_calls_found += 1
        elif f.rule_id == "RESOURCE-UNCLOSED-HANDLE":
            unclosed_resources_found += 1

    metrics = {
        "total_async_functions": total_async_functions,
        "blocking_async_calls_count": blocking_calls_found,
        "unclosed_resources_count": unclosed_resources_found,
        "concurrency_findings_total": len(findings),
    }

    return findings, metrics
