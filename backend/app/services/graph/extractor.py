"""Unified Graph Extraction Engine for APEX 2.0.

Extracts a comprehensive, evidence-grounded engineering knowledge graph covering:
- Repository & Directory structure.
- AST code symbols (classes, functions, methods, imports, inheritance, calls).
- Application API endpoints (FastAPI, Flask, Django route decorators, handlers).
- Database entities (SQLAlchemy declarative models, tables, columns, foreign keys, queries).
- Testing entities (test files, test cases, test functions, fixtures, target relationships).
- Findings & Remediation artifacts (findings, evidence, patches, transactions).
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

from app.services.analyzers.repository_graph import (
    CanonicalModuleResolver,
    SKIP_DIRS,
    calculate_mccabe_complexity,
)
from app.services.graph.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    build_canonical_id,
)
from app.services.graph.call_resolver import AdvancedCallResolver, CallResolutionType
from app.services.graph.identity_continuity import (
    compute_ast_structural_fingerprint,
    compute_symbol_signature,
)


class GraphExtractionEngine:
    """Extracts nodes and edges across code, architecture, APIs, database, and tests."""

    def __init__(self, project_id: int, repo_root: str | Path) -> None:
        self.project_id = project_id
        self.repo_root = Path(repo_root).resolve()
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[GraphEdge] = []
        self._edge_keys: set[tuple[str, str, str]] = set()

    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.canonical_id] = node

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        rel_type: EdgeType | str,
        confidence: float = 1.0,
        evidence_location: str | None = None,
        analyzer_source: str = "ast",
        provenance: dict[str, Any] | None = None,
    ) -> None:
        rtype = rel_type.value if isinstance(rel_type, EdgeType) else str(rel_type)
        key = (source_id, target_id, rtype)
        if key not in self._edge_keys:
            self._edge_keys.add(key)
            self.edges.append(
                GraphEdge(
                    source_canonical_id=source_id,
                    target_canonical_id=target_id,
                    rel_type=rtype,
                    project_id=self.project_id,
                    confidence=confidence,
                    evidence_location=evidence_location,
                    analyzer_source=analyzer_source,
                    provenance=provenance or {},
                )
            )

    def extract_full_graph(
        self,
        findings: list[dict[str, Any]] | None = None,
        transactions: list[dict[str, Any]] | None = None,
        runtime_traces: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, GraphNode], list[GraphEdge]]:
        """Executes complete repository extraction pipeline."""
        self.extract_repository_structure()
        self.extract_code_intelligence(runtime_traces=runtime_traces)
        self.extract_api_graph()
        self.extract_database_graph()
        self.extract_testing_graph()
        self.extract_cross_technology_graph()
        if findings:
            self.extract_findings_graph(findings)
        if transactions:
            self.extract_remediation_graph(transactions)
        return self.nodes, self.edges

    def extract_repository_structure(self) -> None:
        """Extracts repository, directory, and file hierarchy."""
        repo_node_id = build_canonical_id(self.project_id, "", self.repo_root.name, NodeType.REPOSITORY)
        self.add_node(
            GraphNode(
                canonical_id=repo_node_id,
                project_id=self.project_id,
                entity_type=NodeType.REPOSITORY.value,
                name=self.repo_root.name,
                qualified_name=self.repo_root.name,
                file_path="",
                metadata={"root_dir": str(self.repo_root)},
            )
        )

        for root, dirs, files in os.walk(self.repo_root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            rel_dir = os.path.relpath(root, self.repo_root).replace("\\", "/")
            if rel_dir == ".":
                rel_dir = ""

            dir_id = build_canonical_id(self.project_id, rel_dir, os.path.basename(root) or "root", NodeType.DIRECTORY)
            if rel_dir:
                self.add_node(
                    GraphNode(
                        canonical_id=dir_id,
                        project_id=self.project_id,
                        entity_type=NodeType.DIRECTORY.value,
                        name=os.path.basename(root),
                        qualified_name=rel_dir,
                        file_path=rel_dir,
                    )
                )
                parent_dir = os.path.dirname(rel_dir).replace("\\", "/")
                parent_id = build_canonical_id(self.project_id, parent_dir, os.path.basename(parent_dir) or "root", NodeType.DIRECTORY) if parent_dir else repo_node_id
                self.add_edge(parent_id, dir_id, EdgeType.CONTAINS, confidence=1.0, analyzer_source="fs")
            else:
                dir_id = repo_node_id

            for f in files:
                file_rel = os.path.join(rel_dir, f).replace("\\", "/") if rel_dir else f
                file_id = build_canonical_id(self.project_id, file_rel, f, NodeType.FILE)
                self.add_node(
                    GraphNode(
                        canonical_id=file_id,
                        project_id=self.project_id,
                        entity_type=NodeType.FILE.value,
                        name=f,
                        qualified_name=file_rel,
                        file_path=file_rel,
                        metadata={"extension": os.path.splitext(f)[1]},
                    )
                )
                self.add_edge(dir_id, file_id, EdgeType.CONTAINS, confidence=1.0, analyzer_source="fs")

    def extract_code_intelligence(self, runtime_traces: list[dict[str, Any]] | None = None) -> None:
        """Extracts modules, classes, functions, methods, imports, inheritance, and interprocedural calls."""
        py_files = []
        for root, dirs, files in os.walk(self.repo_root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for f in files:
                if f.endswith(".py"):
                    py_files.append(Path(root) / f)

        resolver = CanonicalModuleResolver(self.repo_root, py_files)
        symbol_registry: dict[str, str] = {}  # qualified_name -> canonical_id
        parsed_ast_map: dict[str, tuple[ast.AST, str, Path]] = {}
        class_hierarchy: dict[str, list[str]] = {}

        for p in py_files:
            rel_str = str(p.relative_to(self.repo_root)).replace("\\", "/")
            mod_name = resolver.file_to_module.get(rel_str, rel_str)
            file_id = build_canonical_id(self.project_id, rel_str, p.name, NodeType.FILE)

            # Module Node
            mod_id = build_canonical_id(self.project_id, rel_str, mod_name, NodeType.MODULE)
            self.add_node(
                GraphNode(
                    canonical_id=mod_id,
                    project_id=self.project_id,
                    entity_type=NodeType.MODULE.value,
                    name=mod_name.rpartition(".")[2] or mod_name,
                    qualified_name=mod_name,
                    file_path=rel_str,
                )
            )
            self.add_edge(file_id, mod_id, EdgeType.DEFINES, confidence=1.0)

            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content, filename=rel_str)
                parsed_ast_map[mod_name] = (tree, rel_str, p)
            except Exception:
                continue

            # First pass: collect symbols
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    class_qname = f"{mod_name}.{node.name}"
                    class_id = build_canonical_id(self.project_id, rel_str, class_qname, NodeType.CLASS)
                    self.add_node(
                        GraphNode(
                            canonical_id=class_id,
                            project_id=self.project_id,
                            entity_type=NodeType.CLASS.value,
                            name=node.name,
                            qualified_name=class_qname,
                            file_path=rel_str,
                            start_line=node.lineno,
                            end_line=getattr(node, "end_lineno", node.lineno),
                            metadata={
                                "docstring": ast.get_docstring(node) or "",
                                "structural_fingerprint": compute_ast_structural_fingerprint(node),
                                "signature": compute_symbol_signature(node),
                            },
                        )
                    )
                    symbol_registry[class_qname] = class_id
                    self.add_edge(mod_id, class_id, EdgeType.DEFINES, confidence=1.0, evidence_location=f"{rel_str}:{node.lineno}")

                    # Class inheritance
                    for base in node.bases:
                        base_name = getattr(base, "id", None) or getattr(base, "attr", None)
                        if base_name:
                            class_hierarchy.setdefault(class_qname, []).append(base_name)
                            base_id = build_canonical_id(self.project_id, "", base_name, NodeType.CLASS)
                            self.add_edge(class_id, base_id, EdgeType.INHERITS, confidence=0.8, evidence_location=f"{rel_str}:{node.lineno}")

                    # Methods
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            method_qname = f"{class_qname}.{item.name}"
                            method_id = build_canonical_id(self.project_id, rel_str, method_qname, NodeType.METHOD)
                            self.add_node(
                                GraphNode(
                                    canonical_id=method_id,
                                    project_id=self.project_id,
                                    entity_type=NodeType.METHOD.value,
                                    name=item.name,
                                    qualified_name=method_qname,
                                    file_path=rel_str,
                                    start_line=item.lineno,
                                    end_line=getattr(item, "end_lineno", item.lineno),
                                    metadata={
                                        "complexity": calculate_mccabe_complexity(item),
                                        "is_async": isinstance(item, ast.AsyncFunctionDef),
                                        "structural_fingerprint": compute_ast_structural_fingerprint(item),
                                        "signature": compute_symbol_signature(item),
                                    },
                                )
                            )
                            symbol_registry[method_qname] = method_id
                            self.add_edge(class_id, method_id, EdgeType.DEFINES, confidence=1.0, evidence_location=f"{rel_str}:{item.lineno}")

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_qname = f"{mod_name}.{node.name}"
                    func_id = build_canonical_id(self.project_id, rel_str, func_qname, NodeType.FUNCTION)
                    self.add_node(
                        GraphNode(
                            canonical_id=func_id,
                            project_id=self.project_id,
                            entity_type=NodeType.FUNCTION.value,
                            name=node.name,
                            qualified_name=func_qname,
                            file_path=rel_str,
                            start_line=node.lineno,
                            end_line=getattr(node, "end_lineno", node.lineno),
                            metadata={
                                "complexity": calculate_mccabe_complexity(node),
                                "is_async": isinstance(node, ast.AsyncFunctionDef),
                                "structural_fingerprint": compute_ast_structural_fingerprint(node),
                                "signature": compute_symbol_signature(node),
                            },
                        )
                    )
                    symbol_registry[func_qname] = func_id
                    self.add_edge(mod_id, func_id, EdgeType.DEFINES, confidence=1.0, evidence_location=f"{rel_str}:{node.lineno}")

        # Initialize Advanced Call Resolver
        self.call_resolver = AdvancedCallResolver(
            project_id=self.project_id,
            symbol_registry=symbol_registry,
            nodes=self.nodes,
            class_hierarchy=class_hierarchy,
            runtime_traces=runtime_traces,
        )

        # Second pass: Imports and Function Calls
        for mod_name, (tree, rel_str, path) in parsed_ast_map.items():
            mod_id = build_canonical_id(self.project_id, rel_str, mod_name, NodeType.MODULE)
            imported_aliases: dict[str, str] = {}  # alias -> target_qname

            for node in ast.walk(tree):
                # Imports
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        target_mod = resolver.resolve_import(mod_name, alias.name)
                        imported_aliases[alias.asname or alias.name] = target_mod
                        target_id = build_canonical_id(self.project_id, "", target_mod, NodeType.MODULE)
                        self.add_edge(mod_id, target_id, EdgeType.IMPORTS, confidence=1.0, evidence_location=f"{rel_str}:{node.lineno}")

                elif isinstance(node, ast.ImportFrom):
                    mod_target = resolver.resolve_import(mod_name, node.module or "", level=node.level)
                    for alias in node.names:
                        full_sym = f"{mod_target}.{alias.name}"
                        imported_aliases[alias.asname or alias.name] = full_sym
                        target_id = symbol_registry.get(full_sym) or build_canonical_id(self.project_id, "", full_sym, NodeType.SYMBOL)
                        self.add_edge(mod_id, target_id, EdgeType.IMPORTS, confidence=0.9, evidence_location=f"{rel_str}:{node.lineno}")

            # Function / Method calls
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    caller_qname = f"{mod_name}.{node.name}"
                    self._resolve_calls_in_node(node, caller_qname, rel_str, mod_name, imported_aliases, symbol_registry, current_class=None)
                elif isinstance(node, ast.ClassDef):
                    class_qname = f"{mod_name}.{node.name}"
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            caller_qname = f"{class_qname}.{item.name}"
                            self._resolve_calls_in_node(item, caller_qname, rel_str, mod_name, imported_aliases, symbol_registry, current_class=class_qname)

    def _resolve_calls_in_node(
        self,
        func_node: ast.AST,
        caller_qname: str,
        rel_str: str,
        mod_name: str,
        imported_aliases: dict[str, str],
        symbol_registry: dict[str, str],
        current_class: str | None = None,
    ) -> None:
        caller_id = symbol_registry.get(caller_qname) or build_canonical_id(self.project_id, rel_str, caller_qname, NodeType.FUNCTION)
        local_var_types: dict[str, str] = {}
        if isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in func_node.args.args:
                if arg.annotation and isinstance(arg.annotation, ast.Name):
                    local_var_types[arg.arg] = arg.annotation.id

        for child in ast.walk(func_node):
            if isinstance(child, ast.Call):
                call_expr = self._ast_expr_to_str(child.func)
                edges = self.call_resolver.resolve_call(
                    caller_qname=caller_qname,
                    caller_id=caller_id,
                    call_expr=call_expr,
                    ast_call_node=child,
                    rel_file=rel_str,
                    line_no=getattr(child, "lineno", 1),
                    current_module=mod_name,
                    current_class=current_class,
                    imported_aliases=imported_aliases,
                    local_var_types=local_var_types,
                )
                for edge in edges:
                    self.add_edge(
                        source_id=edge.source_canonical_id,
                        target_id=edge.target_canonical_id,
                        rel_type=edge.rel_type,
                        confidence=edge.confidence,
                        evidence_location=edge.evidence_location,
                        analyzer_source=edge.analyzer_source,
                        provenance=edge.provenance,
                    )

    def extract_api_graph(self) -> None:
        """Extracts FastAPI/Flask route decorators, endpoints, and handler links."""
        route_patterns = [
            re.compile(r"@(router|app|api_router)\.(get|post|put|delete|patch|options|head)\(\s*['\"]([^'\"]+)['\"]", re.IGNORECASE),
            re.compile(r"@app\.route\(\s*['\"]([^'\"]+)['\"].*?methods=\[([^\]]+)\]", re.IGNORECASE),
        ]

        for canonical_id, node in list(self.nodes.items()):
            if node.entity_type in (NodeType.FUNCTION.value, NodeType.METHOD.value):
                # Check decorators
                target_file = self.repo_root / node.file_path
                if not target_file.is_file():
                    continue

                try:
                    lines = target_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                    start = max(0, node.start_line - 15)
                    chunk = "\n".join(lines[start:node.start_line])

                    for pat in route_patterns:
                        for match in pat.finditer(chunk):
                            groups = match.groups()
                            method = groups[1].upper() if len(groups) >= 2 else "GET"
                            path = groups[2] if len(groups) >= 3 else groups[0]

                            endpoint_name = f"{method} {path}"
                            endpoint_id = build_canonical_id(self.project_id, node.file_path, endpoint_name, NodeType.API_ENDPOINT)

                            self.add_node(
                                GraphNode(
                                    canonical_id=endpoint_id,
                                    project_id=self.project_id,
                                    entity_type=NodeType.API_ENDPOINT.value,
                                    name=endpoint_name,
                                    qualified_name=endpoint_name,
                                    file_path=node.file_path,
                                    start_line=node.start_line,
                                    metadata={"http_method": method, "route_path": path},
                                )
                            )

                            # Route -> Handler function
                            self.add_edge(endpoint_id, node.canonical_id, EdgeType.HANDLES_ROUTE, confidence=1.0, evidence_location=f"{node.file_path}:{node.start_line}")
                            # File/Module -> Route
                            file_id = build_canonical_id(self.project_id, node.file_path, os.path.basename(node.file_path), NodeType.FILE)
                            self.add_edge(file_id, endpoint_id, EdgeType.EXPOSES_API, confidence=1.0)
                except Exception:
                    continue

    def extract_database_graph(self) -> None:
        """Extracts SQLAlchemy models, tables, columns, foreign keys, and query operations."""
        table_pattern = re.compile(r"__tablename__\s*=\s*['\"]([^'\"]+)['\"]")
        query_pattern = re.compile(r"\b(query|execute|select|delete|add|commit)\s*\(\s*([a-zA-Z0-9_]+)", re.IGNORECASE)

        for canonical_id, node in list(self.nodes.items()):
            if node.entity_type == NodeType.CLASS.value:
                target_file = self.repo_root / node.file_path
                if not target_file.is_file():
                    continue

                try:
                    lines = target_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                    class_chunk = "\n".join(lines[node.start_line - 1 : node.end_line])
                    match = table_pattern.search(class_chunk)
                    if match:
                        table_name = match.group(1)
                        table_id = build_canonical_id(self.project_id, node.file_path, table_name, NodeType.TABLE)
                        self.add_node(
                            GraphNode(
                                canonical_id=table_id,
                                project_id=self.project_id,
                                entity_type=NodeType.TABLE.value,
                                name=table_name,
                                qualified_name=table_name,
                                file_path=node.file_path,
                                start_line=node.start_line,
                                metadata={"model_class": node.name},
                            )
                        )
                        # Class defines table
                        self.add_edge(node.canonical_id, table_id, EdgeType.DEFINES, confidence=1.0, evidence_location=f"{node.file_path}:{node.start_line}")
                except Exception:
                    continue

            # Query detection in functions
            elif node.entity_type in (NodeType.FUNCTION.value, NodeType.METHOD.value):
                target_file = self.repo_root / node.file_path
                if not target_file.is_file():
                    continue

                try:
                    lines = target_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                    func_chunk = "\n".join(lines[node.start_line - 1 : node.end_line])
                    for m in query_pattern.finditer(func_chunk):
                        op = m.group(1).lower()
                        arg = m.group(2)
                        # Check if arg matches any table or model
                        for other_id, other_node in self.nodes.items():
                            if other_node.entity_type == NodeType.TABLE.value and (other_node.name.lower() in arg.lower() or other_node.metadata.get("model_class", "").lower() in arg.lower()):
                                rel = EdgeType.WRITES_TABLE if op in ("add", "delete", "commit") else EdgeType.READS_TABLE
                                self.add_edge(
                                    node.canonical_id,
                                    other_id,
                                    rel,
                                    confidence=0.85,
                                    evidence_location=f"{node.file_path}:{node.start_line}",
                                    provenance={"operation": op},
                                )
                except Exception:
                    continue

    def extract_testing_graph(self) -> None:
        """Extracts test files, test functions, and links to target components under test."""
        for canonical_id, node in list(self.nodes.items()):
            if node.entity_type == NodeType.FILE.value and ("test" in node.name.lower() or "tests/" in node.file_path.lower()):
                node.entity_type = NodeType.TEST_FILE.value

            elif node.entity_type == NodeType.FUNCTION.value and node.name.startswith("test_"):
                node.entity_type = NodeType.TEST_FUNCTION.value

                # Link test function to functions it calls
                for edge in list(self.edges):
                    if edge.source_canonical_id == node.canonical_id and edge.rel_type == EdgeType.CALLS.value:
                        # Target component is TESTED_BY this test function
                        self.add_edge(
                            edge.target_canonical_id,
                            node.canonical_id,
                            EdgeType.TESTED_BY,
                            confidence=0.9,
                            evidence_location=edge.evidence_location,
                            analyzer_source="test_ast",
                        )

    def extract_findings_graph(self, findings: list[dict[str, Any]]) -> None:
        """Connects findings to code symbols and repository files."""
        for finding in findings:
            fid = str(finding.get("id") or finding.get("fingerprint") or finding.get("rule_id", "issue"))
            file_path = finding.get("file_path") or finding.get("file") or ""
            line = finding.get("line") or finding.get("start_line") or 1

            finding_id = build_canonical_id(self.project_id, file_path, fid, NodeType.FINDING)
            self.add_node(
                GraphNode(
                    canonical_id=finding_id,
                    project_id=self.project_id,
                    entity_type=NodeType.FINDING.value,
                    name=finding.get("rule_id", "Finding"),
                    qualified_name=f"{finding.get('rule_id')}:{fid}",
                    file_path=file_path,
                    start_line=line,
                    metadata={
                        "severity": finding.get("severity", "medium"),
                        "category": finding.get("category", "code_smell"),
                        "message": finding.get("message", ""),
                    },
                )
            )

            # Link finding to target file or symbol
            target_symbol = None
            for nid, node in self.nodes.items():
                if node.file_path == file_path and node.entity_type in (NodeType.FUNCTION.value, NodeType.METHOD.value):
                    if node.start_line <= line <= node.end_line:
                        target_symbol = nid
                        break

            target_id = target_symbol or build_canonical_id(self.project_id, file_path, os.path.basename(file_path), NodeType.FILE)
            if target_id in self.nodes:
                self.add_edge(target_id, finding_id, EdgeType.PRODUCES_FINDING, confidence=1.0, evidence_location=f"{file_path}:{line}")

    def extract_remediation_graph(self, transactions: list[dict[str, Any]]) -> None:
        """Links remediation transactions and patches to affected files and findings."""
        for txn in transactions:
            txn_id_str = txn.get("transaction_id", "")
            txn_id = build_canonical_id(self.project_id, "", txn_id_str, NodeType.REMEDIATION_TRANSACTION)

            self.add_node(
                GraphNode(
                    canonical_id=txn_id,
                    project_id=self.project_id,
                    entity_type=NodeType.REMEDIATION_TRANSACTION.value,
                    name=txn_id_str,
                    qualified_name=txn_id_str,
                    file_path="",
                    metadata={"state": txn.get("state", "COMMITTED")},
                )
            )

            # Link to modified files
            manifest = txn.get("manifest") or {}
            for f in manifest.get("files", []):
                rel = f.get("rel_path", "")
                file_id = build_canonical_id(self.project_id, rel, os.path.basename(rel), NodeType.FILE)
                if file_id in self.nodes:
                    self.add_edge(txn_id, file_id, EdgeType.AFFECTS, confidence=1.0)

    def _ast_expr_to_str(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            base = self._ast_expr_to_str(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        return ""

    def extract_cross_technology_graph(self) -> None:
        """Extracts evidence-backed cross-technology relationships across frontend, backend, database, Docker, and CI/CD."""
        api_endpoints = {
            n.canonical_id: n for n in self.nodes.values()
            if n.entity_type == NodeType.API_ENDPOINT.value
        }
        database_models = {
            n.canonical_id: n for n in self.nodes.values()
            if n.entity_type in (NodeType.DATABASE_MODEL.value, NodeType.TABLE.value)
        }

        # 1. Frontend (React / TypeScript / JavaScript) -> Backend API Endpoints
        frontend_call_pattern = re.compile(
            r"""(?:fetch|axios\.(?:get|post|put|delete|patch)|request|client\.(?:get|post))\(\s*[`'"](/[^`'"]+)[`'"]""",
            re.IGNORECASE,
        )

        for p in self.repo_root.rglob("*"):
            if not p.is_file():
                continue
            if any(skip in p.parts for skip in SKIP_DIRS):
                continue
            if p.suffix in {".ts", ".tsx", ".js", ".jsx"}:
                try:
                    rel_f = str(p.relative_to(self.repo_root)).replace("\\", "/")
                    content = p.read_text(encoding="utf-8", errors="ignore")
                    for m in frontend_call_pattern.finditer(content):
                        route_url = m.group(1).split("?")[0].strip()
                        norm_call = re.sub(r'\$\{[^}]+\}', '{param}', route_url).rstrip("/")
                        matched_endpoint = None
                        for ep_id, ep_node in api_endpoints.items():
                            ep_route = ep_node.metadata.get("route_path", "")
                            if not ep_route:
                                continue
                            norm_ep = re.sub(r'\{[^}]+\}', '{param}', ep_route).rstrip("/")
                            if norm_call == norm_ep or norm_call.endswith(norm_ep) or norm_ep.endswith(norm_call):
                                matched_endpoint = ep_node
                                break
                            # Match parameterized root e.g. /api/v1/orders/
                            base_call = norm_call.split("{param}")[0].rstrip("/")
                            base_ep = norm_ep.split("{param}")[0].rstrip("/")
                            if base_call and base_ep and base_call == base_ep:
                                matched_endpoint = ep_node
                                break

                        if matched_endpoint:
                            client_node_id = build_canonical_id(
                                self.project_id, rel_f, f"client_call:{route_url}", NodeType.CLIENT_API_CALL
                            )
                            self.add_node(
                                GraphNode(
                                    canonical_id=client_node_id,
                                    project_id=self.project_id,
                                    entity_type=NodeType.CLIENT_API_CALL.value,
                                    name=f"ClientCall({route_url})",
                                    qualified_name=f"{rel_f}::call::{route_url}",
                                    file_path=rel_f,
                                    metadata={"target_route": route_url},
                                )
                            )
                            self.add_edge(
                                client_node_id,
                                matched_endpoint.canonical_id,
                                EdgeType.CALLS_API,
                                confidence=0.92,
                                evidence_location=rel_f,
                                analyzer_source="cross_technology_frontend_extractor",
                                provenance={"target_route": route_url, "endpoint": matched_endpoint.name},
                            )
                except Exception:
                    continue

        # 2. Route Handlers -> Services -> Database Models
        for edge in list(self.edges):
            if edge.rel_type == EdgeType.HANDLES_ROUTE.value:
                handler_id = edge.target_canonical_id
                handler_node = self.nodes.get(handler_id)
                if not handler_node:
                    continue

                for next_edge in list(self.edges):
                    if next_edge.source_canonical_id == handler_id:
                        called_target = self.nodes.get(next_edge.target_canonical_id)
                        if called_target and "service" in called_target.file_path.lower():
                            self.add_edge(
                                handler_id,
                                called_target.canonical_id,
                                EdgeType.INVOKES_SERVICE,
                                confidence=0.90,
                                analyzer_source="cross_technology_service_extractor",
                            )

                for model_id, model_node in database_models.items():
                    if handler_node.file_path:
                        try:
                            ftext = (self.repo_root / handler_node.file_path).read_text(encoding="utf-8", errors="ignore")
                            if model_node.name in ftext:
                                self.add_edge(
                                    handler_id,
                                    model_id,
                                    EdgeType.QUERIES_MODEL,
                                    confidence=0.88,
                                    evidence_location=handler_node.file_path,
                                    analyzer_source="cross_technology_orm_extractor",
                                )
                        except Exception:
                            pass

        # 3. Dockerfile -> Multi-stage builds and Application Entrypoints
        dockerfile = self.repo_root / "Dockerfile"
        if dockerfile.is_file():
            try:
                docker_content = dockerfile.read_text(encoding="utf-8", errors="ignore")
                cmd_match = re.search(r'(?:CMD|ENTRYPOINT)\s*\[?["\']?([^"\'\]\n]+)', docker_content, re.IGNORECASE)
                stage_matches = list(re.finditer(r'^\s*FROM\s+(\S+)(?:\s+AS\s+(\S+))?', docker_content, re.MULTILINE | re.IGNORECASE))
                
                stages_by_name: dict[str, str] = {}
                for idx, sm in enumerate(stage_matches):
                    base_img = sm.group(1).strip()
                    stage_name = sm.group(2).strip() if sm.group(2) else f"stage_{idx}"
                    stage_id = build_canonical_id(self.project_id, "Dockerfile", stage_name, NodeType.DOCKER_STAGE)
                    stages_by_name[stage_name] = stage_id
                    if stage_id not in self.nodes:
                        self.add_node(
                            GraphNode(
                                canonical_id=stage_id,
                                project_id=self.project_id,
                                entity_type=NodeType.DOCKER_STAGE.value,
                                name=stage_name,
                                qualified_name=f"Dockerfile::{stage_name}",
                                file_path="Dockerfile",
                                metadata={"base_image": base_img, "stage_name": stage_name, "stage_index": idx},
                            )
                        )
                    # Check if this stage inherits from a previous stage
                    if base_img in stages_by_name and stages_by_name[base_img] != stage_id:
                        self.add_edge(
                            stage_id,
                            stages_by_name[base_img],
                            EdgeType.DEPENDS_ON,
                            confidence=0.95,
                            evidence_location="Dockerfile",
                            analyzer_source="cross_technology_docker_extractor",
                        )

                # Check COPY --from=stage dependencies
                for copy_match in re.finditer(r'COPY\s+--from=(\S+)', docker_content, re.IGNORECASE):
                    src_stg = copy_match.group(1).strip()
                    if src_stg in stages_by_name and len(stages_by_name) > 1:
                        # find destination stage
                        curr_stage_id = list(stages_by_name.values())[-1]
                        if curr_stage_id != stages_by_name[src_stg]:
                            self.add_edge(
                                curr_stage_id,
                                stages_by_name[src_stg],
                                EdgeType.DEPENDS_ON,
                                confidence=0.92,
                                evidence_location="Dockerfile",
                                analyzer_source="cross_technology_docker_extractor",
                            )

                cmd_str = cmd_match.group(1).strip() if cmd_match else ""
                entry_stage_id = list(stages_by_name.values())[-1] if stages_by_name else build_canonical_id(self.project_id, "Dockerfile", "docker_runtime_stage", NodeType.DOCKER_STAGE)
                if entry_stage_id not in self.nodes:
                    self.add_node(
                        GraphNode(
                            canonical_id=entry_stage_id,
                            project_id=self.project_id,
                            entity_type=NodeType.DOCKER_STAGE.value,
                            name="docker_runtime_stage",
                            qualified_name="Dockerfile::docker_runtime_stage",
                            file_path="Dockerfile",
                            metadata={"entrypoint_cmd": cmd_str},
                        )
                    )

                entry_targets = {"backend/app/main.py", "app/main.py", "main.py", "backend/main.py"}
                if cmd_str:
                    for token in cmd_str.replace('"', '').replace("'", '').replace(',', ' ').split():
                        if token.endswith(".py") or token.endswith(".js") or token.endswith(".sh"):
                            entry_targets.add(token.replace("\\", "/"))
                            entry_targets.add(Path(token).name)

                for nid, n in self.nodes.items():
                    if n.file_path in entry_targets or Path(n.file_path).name in entry_targets:
                        self.add_edge(
                            entry_stage_id,
                            nid,
                            EdgeType.EXECUTES_ENTRYPOINT,
                            confidence=0.95,
                            evidence_location="Dockerfile",
                            analyzer_source="cross_technology_docker_extractor",
                        )
                        break
            except Exception:
                pass

        # 3.1 Docker Compose -> Service Dependencies
        for compose_name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
            compose_file = self.repo_root / compose_name
            if compose_file.is_file():
                try:
                    c_text = compose_file.read_text(encoding="utf-8", errors="ignore")
                    rel_compose = compose_name
                    # Parse service definitions and depends_on
                    # Find services block
                    import re as yaml_re
                    service_blocks = yaml_re.findall(r'^\s\s([a-zA-Z0-9_-]+):\s*$', c_text, yaml_re.MULTILINE)
                    svc_nodes: dict[str, str] = {}
                    for svc in service_blocks:
                        if svc in ("version", "services", "networks", "volumes"):
                            continue
                        svc_id = build_canonical_id(self.project_id, rel_compose, svc, NodeType.SERVICE)
                        svc_nodes[svc] = svc_id
                        self.add_node(
                            GraphNode(
                                canonical_id=svc_id,
                                project_id=self.project_id,
                                entity_type=NodeType.SERVICE.value,
                                name=svc,
                                qualified_name=f"ComposeService::{svc}",
                                file_path=rel_compose,
                                metadata={"compose_file": rel_compose, "service_name": svc},
                            )
                        )
                    # Check depends_on relationships between services
                    for svc, s_id in svc_nodes.items():
                        # Extract section for this service
                        pattern = rf'^\s\s{re.escape(svc)}:\s*\n((?:\s\s\s\s[^\n]+\n)*)'
                        m = yaml_re.search(pattern, c_text, yaml_re.MULTILINE)
                        if m:
                            svc_body = m.group(1)
                            for dep in svc_nodes.keys():
                                if dep != svc and yaml_re.search(rf'depends_on:[\s\S]*?-\s+{re.escape(dep)}', svc_body):
                                    self.add_edge(
                                        s_id,
                                        svc_nodes[dep],
                                        EdgeType.DEPENDS_ON_SERVICE,
                                        confidence=0.95,
                                        evidence_location=rel_compose,
                                        analyzer_source="cross_technology_compose_extractor",
                                    )
                except Exception:
                    pass

        # 4. CI/CD Workflows -> Test Execution
        ci_dir = self.repo_root / ".github" / "workflows"
        if ci_dir.is_dir():
            for wf_file in ci_dir.glob("*.y*ml"):
                try:
                    wf_text = wf_file.read_text(encoding="utf-8", errors="ignore")
                    rel_wf = str(wf_file.relative_to(self.repo_root)).replace("\\", "/")
                    wf_id = build_canonical_id(self.project_id, rel_wf, wf_file.stem, NodeType.CI_WORKFLOW)
                    self.add_node(
                        GraphNode(
                            canonical_id=wf_id,
                            project_id=self.project_id,
                            entity_type=NodeType.CI_WORKFLOW.value,
                            name=wf_file.stem,
                            qualified_name=f"CIWorkflow::{wf_file.stem}",
                            file_path=rel_wf,
                            metadata={"workflow_file": rel_wf},
                        )
                    )
                    if "pytest" in wf_text or "npm test" in wf_text or "vitest" in wf_text:
                        for nid, n in self.nodes.items():
                            if n.entity_type in (NodeType.TEST_FILE.value, NodeType.TEST_CASE.value, NodeType.TEST_FUNCTION.value) or "test" in n.file_path.lower():
                                self.add_edge(
                                    wf_id,
                                    nid,
                                    EdgeType.RUNS_WORKFLOW_TEST,
                                    confidence=0.92,
                                    evidence_location=rel_wf,
                                    analyzer_source="cross_technology_ci_extractor",
                                )
                except Exception:
                    continue

        # 5. Environment Variables -> Configuration Consumers
        env_pattern = re.compile(r"""(?:os\.getenv|os\.environ\.get|os\.environ\[)\s*\(?\s*['"]([A-Z0-9_]+)['"]""")
        for p in self.repo_root.rglob("*.py"):
            if any(skip in p.parts for skip in SKIP_DIRS):
                continue
            try:
                p_text = p.read_text(encoding="utf-8", errors="ignore")
                rel_p = str(p.relative_to(self.repo_root)).replace("\\", "/")
                file_id = build_canonical_id(self.project_id, rel_p, p.name, NodeType.FILE)
                for em in env_pattern.finditer(p_text):
                    var_name = em.group(1)
                    var_id = build_canonical_id(self.project_id, "", var_name, NodeType.ENV_VARIABLE)
                    if var_id not in self.nodes:
                        self.add_node(
                            GraphNode(
                                canonical_id=var_id,
                                project_id=self.project_id,
                                entity_type=NodeType.ENV_VARIABLE.value,
                                name=var_name,
                                qualified_name=f"ENV::{var_name}",
                                file_path="",
                                metadata={"env_var_name": var_name},
                            )
                        )
                    if file_id in self.nodes:
                        self.add_edge(
                            file_id,
                            var_id,
                            EdgeType.CONSUMES_ENV_VAR,
                            confidence=0.95,
                            evidence_location=rel_p,
                            analyzer_source="cross_technology_env_extractor",
                        )
            except Exception:
                continue

        # 6. Package Dependencies -> Dependency Nodes
        pkg_json = self.repo_root / "package.json"
        if pkg_json.is_file():
            try:
                import json as json_lib
                data = json_lib.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
                all_deps = dict(data.get("dependencies", {}))
                all_deps.update(data.get("devDependencies", {}))
                pkg_file_id = build_canonical_id(self.project_id, "package.json", "package.json", NodeType.FILE)
                for pkg_name, pkg_ver in all_deps.items():
                    pkg_id = build_canonical_id(self.project_id, "", f"npm::{pkg_name}", NodeType.PACKAGE)
                    if pkg_id not in self.nodes:
                        self.add_node(
                            GraphNode(
                                canonical_id=pkg_id,
                                project_id=self.project_id,
                                entity_type=NodeType.PACKAGE.value,
                                name=pkg_name,
                                qualified_name=f"npm::{pkg_name}",
                                file_path="",
                                metadata={"ecosystem": "npm", "version_constraint": str(pkg_ver)},
                            )
                        )
                    if pkg_file_id in self.nodes:
                        self.add_edge(
                            pkg_file_id,
                            pkg_id,
                            EdgeType.DEPENDS_ON,
                            confidence=0.98,
                            evidence_location="package.json",
                            analyzer_source="cross_technology_pkg_extractor",
                        )
            except Exception:
                pass

        req_txt = self.repo_root / "requirements.txt"
        if req_txt.is_file():
            try:
                r_lines = req_txt.read_text(encoding="utf-8", errors="ignore").splitlines()
                req_file_id = build_canonical_id(self.project_id, "requirements.txt", "requirements.txt", NodeType.FILE)
                for line in r_lines:
                    line_s = line.strip()
                    if not line_s or line_s.startswith("#") or line_s.startswith("-"):
                        continue
                    pkg_name = re.split(r'[<>=!~]', line_s)[0].strip()
                    if pkg_name:
                        pkg_id = build_canonical_id(self.project_id, "", f"pypi::{pkg_name}", NodeType.PACKAGE)
                        if pkg_id not in self.nodes:
                            self.add_node(
                                GraphNode(
                                    canonical_id=pkg_id,
                                    project_id=self.project_id,
                                    entity_type=NodeType.PACKAGE.value,
                                    name=pkg_name,
                                    qualified_name=f"pypi::{pkg_name}",
                                    file_path="",
                                    metadata={"ecosystem": "pypi", "specifier": line_s},
                                )
                            )
                        if req_file_id in self.nodes:
                            self.add_edge(
                                req_file_id,
                                pkg_id,
                                EdgeType.DEPENDS_ON,
                                confidence=0.98,
                                evidence_location="requirements.txt",
                                analyzer_source="cross_technology_pkg_extractor",
                            )
            except Exception:
                pass

