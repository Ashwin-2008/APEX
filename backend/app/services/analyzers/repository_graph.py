"""Shared Repository Graph, Symbol Index, and Architecture Intelligence Infrastructure.

Provides canonical module resolution, repository-wide symbol indexing, cross-file import
resolution, interprocedural call graph construction, and Tarjan's cycle detection.
"""
from __future__ import annotations

import ast
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SKIP_DIRS = frozenset({
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    "coverage",
    ".idea",
    ".vscode",
})


@dataclass
class CallSite:
    caller_qname: str
    callee_expr: str
    resolved_target_qname: str | None
    args: list[str] = field(default_factory=list)
    kwargs: dict[str, str] = field(default_factory=dict)
    file_path: str = ""
    line: int = 1


@dataclass
class SymbolDefinition:
    name: str
    qname: str
    kind: str  # function, async_function, method, class
    file_path: str
    start_line: int
    end_line: int
    parameters: list[str] = field(default_factory=list)
    is_route_handler: bool = False
    is_private: bool = False
    decorators: list[str] = field(default_factory=list)
    complexity: int = 1
    calls: list[CallSite] = field(default_factory=list)
    return_statements: list[str] = field(default_factory=list)


@dataclass
class ModuleInfo:
    canonical_name: str
    file_path: str
    package: str
    symbols: dict[str, SymbolDefinition] = field(default_factory=dict)
    imports: dict[str, str] = field(default_factory=dict)  # local_alias -> canonical_or_raw_target
    imported_symbols: dict[str, tuple[str, str]] = field(default_factory=dict)  # local_alias -> (module, symbol)
    loc: int = 0
    parse_error: str | None = None


class CanonicalModuleResolver:
    """Resolves file paths to canonical Python module names and relative/absolute imports."""

    def __init__(self, root_dir: Path, py_files: list[Path]) -> None:
        self.root_dir = root_dir.resolve()
        self.file_to_module: dict[str, str] = {}
        self.module_to_file: dict[str, str] = {}
        self._build_module_map(py_files)

    def _build_module_map(self, py_files: list[Path]) -> None:
        for p in py_files:
            try:
                rel = p.resolve().relative_to(self.root_dir)
            except ValueError:
                continue

            rel_str = str(rel).replace("\\", "/")
            # Build dot notation path removing .py or /__init__.py
            parts = list(rel.parts)
            if parts[-1].endswith(".py"):
                parts[-1] = parts[-1][:-3]
            if parts[-1] == "__init__":
                parts.pop()

            canonical = ".".join(parts) if parts else "__root__"
            self.file_to_module[rel_str] = canonical
            self.module_to_file[canonical] = rel_str

            # Also support short forms if nested in common root prefixes (backend, src, app)
            if len(parts) > 1 and parts[0] in {"backend", "src"}:
                short_canonical = ".".join(parts[1:])
                if short_canonical not in self.module_to_file:
                    self.module_to_file[short_canonical] = rel_str

    def resolve_import(self, current_module: str, target: str, level: int = 0) -> str:
        """Resolve absolute or relative import to its canonical module name."""
        if level > 0:
            # Relative import
            curr_parts = current_module.split(".") if current_module != "__root__" else []
            # Level 1 means from . (current package), level 2 means from ..
            base_parts = curr_parts[:-level] if level <= len(curr_parts) else []
            resolved_parts = base_parts + ([target] if target else [])
            candidate = ".".join(resolved_parts)
            if candidate in self.module_to_file:
                return candidate
            return candidate

        # Absolute import
        if target in self.module_to_file:
            return target

        # Check submodules
        for mod in self.module_to_file:
            if mod.endswith(f".{target}") or mod == target:
                return mod

        return target


def calculate_mccabe_complexity(node: ast.AST) -> int:
    """Calculate exact McCabe cyclomatic complexity for an AST function/method/class node."""
    complexity = 1
    for child in ast.walk(node):
        if isinstance(
            child,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.ExceptHandler,
                ast.With,
                ast.AsyncWith,
                ast.IfExp,
            ),
        ):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += max(1, len(child.values) - 1)
        elif hasattr(ast, "Match") and isinstance(child, ast.Match):  # Python 3.10+
            # Each case pattern is a branch
            complexity += max(0, len(getattr(child, "cases", [])) - 1)
    return complexity


class RepositorySymbolIndex:
    """Repository-wide AST symbol index, call graph, and dependency mapping."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.modules: dict[str, ModuleInfo] = {}
        self.symbols: dict[str, SymbolDefinition] = {}
        self.call_graph: dict[str, set[str]] = defaultdict(set)
        self.call_sites: list[CallSite] = []
        self.import_graph: dict[str, set[str]] = defaultdict(set)
        self.parse_errors: list[dict[str, Any]] = []

        self._discover_and_parse()

    def _discover_and_parse(self) -> None:
        py_files: list[Path] = []
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for f in files:
                if f.endswith(".py"):
                    py_files.append(Path(root) / f)

        self.resolver = CanonicalModuleResolver(self.root_dir, py_files)

        for p in py_files:
            rel_str = str(p.relative_to(self.root_dir)).replace("\\", "/")
            canonical_mod = self.resolver.file_to_module.get(rel_str, rel_str)
            package_name = canonical_mod.rpartition(".")[0]

            mod_info = ModuleInfo(
                canonical_name=canonical_mod,
                file_path=rel_str,
                package=package_name,
            )

            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                mod_info.loc = len(content.splitlines())
                tree = ast.parse(content, filename=rel_str)
            except SyntaxError as exc:
                mod_info.parse_error = str(exc)
                self.parse_errors.append({
                    "file": rel_str,
                    "line": exc.lineno or 1,
                    "error": str(exc),
                })
                self.modules[canonical_mod] = mod_info
                continue
            except Exception as exc:
                mod_info.parse_error = str(exc)
                self.parse_errors.append({
                    "file": rel_str,
                    "line": 1,
                    "error": str(exc),
                })
                self.modules[canonical_mod] = mod_info
                continue

            self._index_module_ast(mod_info, tree, content)
            self.modules[canonical_mod] = mod_info

        # Second pass: resolve cross-file calls
        self._resolve_call_graph()

    def _index_module_ast(self, mod: ModuleInfo, tree: ast.AST, content: str) -> None:
        lines = content.splitlines()

        # 1. Imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name
                    target = self.resolver.resolve_import(mod.canonical_name, alias.name)
                    mod.imports[local] = target
                    self.import_graph[mod.canonical_name].add(target)
            elif isinstance(node, ast.ImportFrom):
                target_mod = self.resolver.resolve_import(mod.canonical_name, node.module or "", node.level)
                for alias in node.names:
                    local = alias.asname or alias.name
                    mod.imported_symbols[local] = (target_mod, alias.name)
                    self.import_graph[mod.canonical_name].add(target_mod)

        # 2. Top-level & Class Functions/Methods
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._extract_function(mod, node, prefix=mod.canonical_name)
            elif isinstance(node, ast.ClassDef):
                class_qname = f"{mod.canonical_name}.{node.name}"
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self._extract_function(mod, item, prefix=class_qname, is_method=True)

    def _extract_function(
        self,
        mod: ModuleInfo,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        prefix: str,
        is_method: bool = False,
    ) -> None:
        qname = f"{prefix}.{node.name}"
        params = [arg.arg for arg in node.args.args]
        start_ln = getattr(node, "lineno", 1)
        end_ln = getattr(node, "end_lineno", start_ln) or start_ln

        # Detect route handlers
        is_route = False
        decorators: list[str] = []
        for dec in node.decorator_list:
            dec_src = ast.unparse(dec) if hasattr(ast, "unparse") else ""
            decorators.append(dec_src)
            if any(m in dec_src.lower() for m in [".get", ".post", ".put", ".delete", ".patch", ".route"]):
                is_route = True

        comp = calculate_mccabe_complexity(node)
        is_private = node.name.startswith("_") and not (node.name.startswith("__") and node.name.endswith("__"))

        sym = SymbolDefinition(
            name=node.name,
            qname=qname,
            kind="method" if is_method else ("async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"),
            file_path=mod.file_path,
            start_line=start_ln,
            end_line=end_ln,
            parameters=params,
            is_route_handler=is_route,
            is_private=is_private,
            decorators=decorators,
            complexity=comp,
        )

        # Collect return statements
        for sub in ast.walk(node):
            if isinstance(sub, ast.Return) and sub.value is not None:
                try:
                    sym.return_statements.append(ast.unparse(sub.value))
                except Exception:
                    pass

        # Collect call expressions inside the function
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                try:
                    func_expr = ast.unparse(sub.func)
                except Exception:
                    func_expr = ""

                call_args = []
                for a in sub.args:
                    try:
                        call_args.append(ast.unparse(a))
                    except Exception:
                        pass

                call_kwargs = {}
                for kw in sub.keywords:
                    if kw.arg:
                        try:
                            call_kwargs[kw.arg] = ast.unparse(kw.value)
                        except Exception:
                            pass

                cs = CallSite(
                    caller_qname=qname,
                    callee_expr=func_expr,
                    resolved_target_qname=None,
                    args=call_args,
                    kwargs=call_kwargs,
                    file_path=mod.file_path,
                    line=getattr(sub, "lineno", start_ln),
                )
                sym.calls.append(cs)
                self.call_sites.append(cs)

        mod.symbols[node.name] = sym
        self.symbols[qname] = sym

    def _resolve_call_graph(self) -> None:
        """Resolve call expressions to internal qualified symbol names where possible."""
        for cs in self.call_sites:
            caller_sym = self.symbols.get(cs.caller_qname)
            if not caller_sym:
                continue

            mod_name = cs.caller_qname.split(".")[0]
            # Match caller module
            caller_mod = None
            for m in self.modules.values():
                if m.file_path == cs.file_path:
                    caller_mod = m
                    break

            if not caller_mod:
                continue

            expr = cs.callee_expr
            resolved = None

            # 1. Local function in the same module
            local_target = f"{caller_mod.canonical_name}.{expr}"
            if local_target in self.symbols:
                resolved = local_target

            # 2. Imported symbol (from ... import func)
            elif expr in caller_mod.imported_symbols:
                target_mod, symbol_name = caller_mod.imported_symbols[expr]
                candidate = f"{target_mod}.{symbol_name}"
                if candidate in self.symbols:
                    resolved = candidate
                else:
                    # Check if target_mod itself is registered with another prefix
                    for s in self.symbols:
                        if s.endswith(f".{symbol_name}") and target_mod in s:
                            resolved = s
                            break

            # 3. Method on module (module.func)
            elif "." in expr:
                base, _, method = expr.partition(".")
                if base in caller_mod.imports:
                    target_mod = caller_mod.imports[base]
                    candidate = f"{target_mod}.{method}"
                    if candidate in self.symbols:
                        resolved = candidate

            if resolved:
                cs.resolved_target_qname = resolved
                self.call_graph[cs.caller_qname].add(resolved)


class TarjanCycleDetector:
    """Detects strongly connected components and extracts canonical, deduplicated cycles."""

    @staticmethod
    def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
        """Identify all elementary cycles in a directed graph using Tarjan's SCC algorithm."""
        index = 0
        indices: dict[str, int] = {}
        lowlinks: dict[str, int] = {}
        on_stack: set[str] = set()
        stack: list[str] = []
        sccs: list[list[str]] = []

        all_nodes = list(graph.keys())
        for u in list(graph.keys()):
            for v in graph[u]:
                if v not in graph:
                    all_nodes.append(v)

        def strongconnect(node: str):
            nonlocal index
            indices[node] = index
            lowlinks[node] = index
            index += 1
            stack.append(node)
            on_stack.add(node)

            for neighbor in graph.get(node, set()):
                if neighbor not in indices:
                    strongconnect(neighbor)
                    lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
                elif neighbor in on_stack:
                    lowlinks[node] = min(lowlinks[node], indices[neighbor])

            if lowlinks[node] == indices[node]:
                scc = []
                while True:
                    w = stack.pop()
                    on_stack.remove(w)
                    scc.append(w)
                    if w == node:
                        break
                if len(scc) > 1 or (len(scc) == 1 and node in graph.get(node, set())):
                    sccs.append(scc)

        for n in all_nodes:
            if n not in indices:
                strongconnect(n)

        # Extract elementary cycles from SCCs
        cycles: list[list[str]] = []
        seen_canonical: set[tuple[str, ...]] = set()

        for scc in sccs:
            scc_set = set(scc)
            subgraph = {u: graph.get(u, set()) & scc_set for u in scc}

            def dfs(path: list[str]):
                curr = path[-1]
                for nxt in sorted(subgraph.get(curr, set())):
                    if nxt == path[0]:
                        # Cycle completed
                        canon = TarjanCycleDetector._canonical_rotation(path)
                        if canon not in seen_canonical:
                            seen_canonical.add(canon)
                            cycles.append(list(canon) + [canon[0]])
                    elif nxt not in path and len(path) < 10:  # Bound cycle length
                        dfs(path + [nxt])

            for node in sorted(scc):
                dfs([node])

        return cycles

    @staticmethod
    def _canonical_rotation(cycle: list[str]) -> tuple[str, ...]:
        """Normalize cycle so that the lexicographically smallest element appears first."""
        if not cycle:
            return ()
        min_idx = cycle.index(min(cycle))
        rotated = cycle[min_idx:] + cycle[:min_idx]
        return tuple(rotated)

