"""Interprocedural Security Taint Analysis Engine for APEX 2.0.

Traces untrusted user inputs (FastAPI, Flask, user-controlled parameters) across function
and module boundaries to dangerous execution sinks (command execution, SQL injection,
path traversal, SSRF, and unescaped rendering).
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.analyzers.base import FindingItem
from app.services.analyzers.repository_graph import RepositorySymbolIndex, SymbolDefinition
from app.services.analyzers.type_engine import is_safe_injection_type, stringify_annotation

MAX_CALL_DEPTH = 6

# Dangerous Sink Definitions
COMMAND_SINKS = {
    "os.system",
    "os.popen",
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_output",
    "subprocess.check_call",
    "eval",
    "exec",
}

SQL_SINKS = {
    "cursor.execute",
    "cursor.executemany",
    "connection.execute",
    "session.execute",
    "db.execute",
    "raw_sql",
}

FILE_SINKS = {
    "open",
    "pathlib.Path",
    "os.remove",
    "os.unlink",
    "os.rmdir",
    "shutil.rmtree",
    "shutil.copy",
    "shutil.move",
}

SSRF_SINKS = {
    "requests.get",
    "requests.post",
    "requests.request",
    "urllib.request.urlopen",
    "httpx.get",
    "httpx.post",
}

XSS_SINKS = {
    "render_template_string",
    "flask.render_template_string",
}

SANITIZER_MARKERS = {
    "os.path.basename",
    "Path.name",
    ".name",
    "shlex.quote",
    "int(",
    "float(",
    "html.escape",
}


@dataclass
class TaintStep:
    step: int
    file: str
    line: int
    symbol: str
    expression: str
    role: str  # source, call, parameter, propagation, sink


class InterproceduralTaintAnalyzer:
    """Performs bounded repository-wide interprocedural taint flow analysis."""

    def __init__(self, symbol_index: RepositorySymbolIndex) -> None:
        self.index = symbol_index
        self.findings: list[FindingItem] = []

    def analyze(self) -> list[FindingItem]:
        """Discover entry points and trace data flow across functions to dangerous sinks."""
        findings: list[FindingItem] = []
        visited_traces: set[tuple[str, str, int]] = set()

        for qname, sym in self.index.symbols.items():
            if not sym.is_route_handler:
                continue

            # In route handlers, parameters (except self/request/session) are external sources
            sources = [
                p for p in sym.parameters
                if p not in {"self", "cls", "request", "db", "session", "_"}
            ]

            file_path = self.index.root_dir / sym.file_path
            if not file_path.is_file():
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content, filename=str(file_path))
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == sym.name:
                    # Type-informed safety check: exclude parameters annotated with safe non-string types (int, float, bool, UUID)
                    safe_params = set()
                    for arg in node.args.args:
                        if arg.annotation:
                            ann_str = stringify_annotation(arg.annotation)
                            if is_safe_injection_type(ann_str):
                                safe_params.add(arg.arg)
                    has_request_obj = any(p in {"request", "req"} for p in sym.parameters)
                    active_sources = [p for p in sources if p not in safe_params]
                    if not active_sources and not has_request_obj:
                        continue

                    self._trace_function(
                        func_node=node,
                        sym=sym,
                        initial_taints=set(active_sources),
                        depth=0,
                        call_stack=[sym.qname],
                        trace_steps=[
                            TaintStep(
                                step=1,
                                file=sym.file_path,
                                line=sym.start_line,
                                symbol=sym.name,
                                expression=f"Endpoint parameter(s): {', '.join(active_sources) or 'request'}",
                                role="source",
                            )
                        ],
                        collected_findings=findings,
                        visited_traces=visited_traces,
                    )
        return findings

    def _trace_function(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        sym: SymbolDefinition,
        initial_taints: set[str],
        depth: int,
        call_stack: list[str],
        trace_steps: list[TaintStep],
        collected_findings: list[FindingItem],
        visited_traces: set[tuple[str, str, int]],
    ) -> None:
        if depth > MAX_CALL_DEPTH:
            return

        tainted_vars: set[str] = set(initial_taints)
        sanitized_vars: set[str] = set()

        # 1. Detect assignments (sources, sanitizers, and variable propagation)
        for node in func_node.body:
            if isinstance(node, ast.Assign):
                rhs_expr = ""
                try:
                    rhs_expr = ast.unparse(node.value)
                except Exception:
                    pass

                untrusted_markers = [
                    "request.query_params",
                    "request.path_params",
                    "request.args",
                    "request.form",
                    "request.values",
                    "request.json",
                    "request.get_json",
                    "request.data",
                    "request.headers",
                    "request.cookies",
                ]
                is_source = any(m in rhs_expr for m in untrusted_markers)
                is_sanitizer = any(san in rhs_expr for san in SANITIZER_MARKERS)
                is_tainted_propagation = any(t in rhs_expr for t in tainted_vars)

                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if is_sanitizer:
                            sanitized_vars.add(target.id)
                            tainted_vars.discard(target.id)
                        elif is_source or is_tainted_propagation:
                            tainted_vars.add(target.id)
                            trace_steps.append(
                                TaintStep(
                                    step=len(trace_steps) + 1,
                                    file=sym.file_path,
                                    line=node.lineno,
                                    symbol=sym.name,
                                    expression=f"{target.id} = {rhs_expr}",
                                    role="propagation" if is_tainted_propagation else "source",
                                )
                            )

        # 2. Inspect calls inside the function
        for node in ast.walk(func_node):
            if not isinstance(node, ast.Call):
                continue

            callee_expr = ""
            try:
                callee_expr = ast.unparse(node.func)
            except Exception:
                continue

            call_args = []
            for arg in node.args:
                try:
                    call_args.append(ast.unparse(arg))
                except Exception:
                    call_args.append("")

            call_kwargs = {}
            for kw in node.keywords:
                if kw.arg:
                    try:
                        call_kwargs[kw.arg] = ast.unparse(kw.value)
                    except Exception:
                        pass

            # Detect which arguments contain tainted variables that are NOT sanitized
            tainted_arg_indices: list[int] = []
            for idx, arg_str in enumerate(call_args):
                has_taint = any(t_var in arg_str for t_var in tainted_vars)
                has_sanitized = any(s_var in arg_str for s_var in sanitized_vars)
                if has_taint and not has_sanitized:
                    tainted_arg_indices.append(idx)

            tainted_kw_names = [
                k for k, v in call_kwargs.items()
                if any(t_var in v for t_var in tainted_vars) and not any(s_var in v for s_var in sanitized_vars)
            ]

            has_taint = len(tainted_arg_indices) > 0 or len(tainted_kw_names) > 0
            if not has_taint:
                continue

            call_line = getattr(node, "lineno", sym.start_line)

            # Check if this call is an immediate dangerous sink
            sink_match = self._check_dangerous_sink(callee_expr, call_args, call_kwargs, tainted_vars, sanitized_vars)
            if sink_match:
                cat, rule_id, title, sev, rem = sink_match
                trace_key = (rule_id, sym.file_path, call_line)
                if trace_key not in visited_traces:
                    visited_traces.add(trace_key)

                    final_steps = list(trace_steps) + [
                        TaintStep(
                            step=len(trace_steps) + 1,
                            file=sym.file_path,
                            line=call_line,
                            symbol=sym.name,
                            expression=f"{callee_expr}({', '.join(call_args)})",
                            role="sink",
                        )
                    ]

                    flow_dicts = [
                        {
                            "step": s.step,
                            "file": s.file,
                            "line": s.line,
                            "symbol": s.symbol,
                            "expression": s.expression,
                            "role": s.role,
                        }
                        for s in final_steps
                    ]

                    if len(call_stack) > 1:
                        hops_desc = " -> ".join(call_stack)
                        evidence = (
                            f"Interprocedural taint flow from {final_steps[0].file}:{final_steps[0].line} "
                            f"through call path [{hops_desc}] to dangerous sink '{callee_expr}' "
                            f"at {sym.file_path}:{call_line}."
                        )
                        confidence = 0.95
                    else:
                        evidence = (
                            f"Untrusted input flow from {final_steps[0].file}:{final_steps[0].line} "
                            f"to dangerous sink '{callee_expr}' at line {call_line}."
                        )
                        confidence = 0.92

                    collected_findings.append(
                        FindingItem(
                            category=cat,
                            severity=sev,
                            confidence=confidence,
                            evidence=evidence,
                            analyzer_source="interprocedural_taint_engine",
                            rule_id=rule_id,
                            component=sym.file_path,
                            file=sym.file_path,
                            line=call_line,
                            title=title,
                            remediation=rem,
                            data_flow=flow_dicts,
                            metadata={
                                "interprocedural": len(call_stack) > 1,
                                "call_path": call_stack,
                                "source_location": f"{final_steps[0].file}:{final_steps[0].line}",
                                "sink_location": f"{sym.file_path}:{call_line}",
                                "sink_expression": callee_expr,
                            },
                        )
                    )
                continue

            # If not an immediate sink, resolve target symbol in the repository
            resolved_callee = self._resolve_target_symbol(sym, callee_expr)
            if resolved_callee and resolved_callee in self.index.symbols:
                callee_sym = self.index.symbols[resolved_callee]
                if callee_sym.qname in call_stack:
                    continue

                callee_taints: set[str] = set()
                for idx in tainted_arg_indices:
                    if idx < len(callee_sym.parameters):
                        callee_taints.add(callee_sym.parameters[idx])

                for kw_name in tainted_kw_names:
                    if kw_name in callee_sym.parameters:
                        callee_taints.add(kw_name)

                if callee_taints:
                    callee_file_path = self.index.root_dir / callee_sym.file_path
                    if callee_file_path.is_file():
                        try:
                            callee_content = callee_file_path.read_text(encoding="utf-8", errors="ignore")
                            callee_tree = ast.parse(callee_content, filename=str(callee_file_path))
                            for c_node in ast.walk(callee_tree):
                                if isinstance(c_node, (ast.FunctionDef, ast.AsyncFunctionDef)) and c_node.name == callee_sym.name:
                                    step_call = TaintStep(
                                        step=len(trace_steps) + 1,
                                        file=sym.file_path,
                                        line=call_line,
                                        symbol=sym.name,
                                        expression=f"Call {callee_expr}({', '.join(call_args)})",
                                        role="call",
                                    )
                                    step_callee_entry = TaintStep(
                                        step=len(trace_steps) + 2,
                                        file=callee_sym.file_path,
                                        line=callee_sym.start_line,
                                        symbol=callee_sym.name,
                                        expression=f"Enter {callee_sym.name} with tainted param(s): {', '.join(callee_taints)}",
                                        role="parameter",
                                    )
                                    self._trace_function(
                                        func_node=c_node,
                                        sym=callee_sym,
                                        initial_taints=callee_taints,
                                        depth=depth + 1,
                                        call_stack=call_stack + [callee_sym.qname],
                                        trace_steps=list(trace_steps) + [step_call, step_callee_entry],
                                        collected_findings=collected_findings,
                                        visited_traces=visited_traces,
                                    )
                                    break
                        except Exception:
                            pass

    def _resolve_target_symbol(self, caller_sym: SymbolDefinition, callee_expr: str) -> str | None:
        """Resolve a callee expression to a qualified internal symbol name."""
        caller_mod = None
        for m in self.index.modules.values():
            if m.file_path == caller_sym.file_path:
                caller_mod = m
                break

        if not caller_mod:
            return None

        # 1. Local symbol in the same module
        local_cand = f"{caller_mod.canonical_name}.{callee_expr}"
        if local_cand in self.index.symbols:
            return local_cand

        # 2. Imported symbol (from mod import func)
        if callee_expr in caller_mod.imported_symbols:
            tgt_mod, sym_name = caller_mod.imported_symbols[callee_expr]
            cand = f"{tgt_mod}.{sym_name}"
            if cand in self.index.symbols:
                return cand
            for s in self.index.symbols:
                if s.endswith(f".{sym_name}") and (tgt_mod in s or s.startswith(tgt_mod)):
                    return s

        # 3. Module member (mod.func)
        if "." in callee_expr:
            base, _, method = callee_expr.partition(".")
            if base in caller_mod.imports:
                tgt_mod = caller_mod.imports[base]
                cand = f"{tgt_mod}.{method}"
                if cand in self.index.symbols:
                    return cand

        return None

    def _check_dangerous_sink(
        self,
        callee_expr: str,
        call_args: list[str],
        call_kwargs: dict[str, str],
        tainted_vars: set[str],
        sanitized_vars: set[str],
    ) -> tuple[str, str, str, str, str] | None:
        """Evaluate if the call target matches a dangerous sink and is not sanitized."""
        # 1. Command Execution Sinks
        if any(callee_expr == s or callee_expr.endswith(f".{s}") for s in COMMAND_SINKS):
            is_shell = (
                call_kwargs.get("shell") in {"True", "1"}
                or "True" in call_kwargs.get("shell", "")
                or any("shell=True" in arg for arg in call_args)
            )
            if callee_expr in {"os.system", "os.popen", "eval", "exec"} or is_shell:
                return (
                    "security",
                    "SEC-TAINT-CMD-INJECTION",
                    "Interprocedural Command Injection Risk",
                    "critical",
                    "Avoid shell=True and pass command arguments as a validated, unquoted sequence array.",
                )
            if call_args and any("+" in arg or "%" in arg or "f\"" in arg or "f'" in arg for arg in call_args):
                return (
                    "security",
                    "SEC-TAINT-CMD-INJECTION",
                    "Dynamic Command String Construction in Subprocess",
                    "high",
                    "Avoid dynamic string formatting in commands; pass arguments as an explicit sequence array.",
                )

        # 2. SQL Execution Sinks
        if any(s in callee_expr for s in SQL_SINKS):
            first_arg = call_args[0] if call_args else ""
            has_params = len(call_args) > 1 or "params" in call_kwargs
            is_tainted_sql = any(t in first_arg for t in tainted_vars)
            is_formatting = any(m in first_arg for m in ["f\"", "f'", " + ", " % "])
            if (is_tainted_sql or is_formatting) and not has_params:
                return (
                    "security",
                    "SEC-TAINT-SQL-INJECTION",
                    "Interprocedural SQL Injection Vulnerability",
                    "critical",
                    "Use parameterized queries with bind variables instead of dynamic SQL string formatting.",
                )

        # 3. Path Traversal Sinks
        if any(callee_expr == s or callee_expr.endswith(f".{s}") for s in FILE_SINKS):
            path_arg = call_args[0] if call_args else ""
            has_taint = any(t in path_arg for t in tainted_vars)
            has_sanitizer = any(s in path_arg for s in sanitized_vars) or any(m in path_arg for m in SANITIZER_MARKERS)
            if has_taint and not has_sanitizer:
                return (
                    "security",
                    "SEC-TAINT-PATH-TRAVERSAL",
                    "Interprocedural Path Traversal Risk",
                    "high",
                    "Sanitize user-provided file paths with os.path.basename() and verify they remain within the intended base directory.",
                )

        # 4. SSRF Sinks
        if any(callee_expr == s or callee_expr.endswith(f".{s}") for s in SSRF_SINKS):
            url_arg = call_args[0] if call_args else ""
            if any(t in url_arg for t in tainted_vars):
                return (
                    "security",
                    "SEC-TAINT-SSRF",
                    "Server-Side Request Forgery (SSRF) Candidate",
                    "high",
                    "Validate and restrict target URLs against a strict domain whitelist before making outbound HTTP requests.",
                )

        # 5. XSS Sinks
        if any(callee_expr == s or callee_expr.endswith(f".{s}") for s in XSS_SINKS):
            return (
                "security",
                "SEC-TAINT-XSS",
                "Unsafe Template String Rendering (XSS / SSTI)",
                "high",
                "Use static template files with automatic contextual HTML escaping instead of render_template_string.",
            )

        return None
