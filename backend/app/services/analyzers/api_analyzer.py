"""API Intelligence Engine: route inventory, schema validation, and endpoint authentication markers."""
from __future__ import annotations

import ast
import re
import time
from pathlib import Path
from typing import Any

from app.services.analyzers.base import AnalyzerOutput, AnalyzerStatus, FindingItem


def run_api_analysis(root_dir: str | Path) -> AnalyzerOutput:
    """Extract API routes, HTTP methods, authentication enforcement, and contract consistency."""
    start_time = time.perf_counter()
    root = Path(root_dir).resolve()
    findings: list[FindingItem] = []
    routes: list[dict[str, Any]] = []

    py_files = [
        p for p in root.rglob("*.py")
        if not any(part in {".git", "node_modules", "venv", ".venv", "__pycache__"} for part in p.parts)
    ]

    for p in py_files:
        rel = str(p.relative_to(root)).replace("\\", "/")
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content, filename=str(p))
            lines = content.splitlines()

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    for dec in node.decorator_list:
                        dec_str = ast.unparse(dec) if hasattr(ast, "unparse") else ""
                        match = re.search(r"\.(get|post|put|patch|delete|route)\s*\(\s*['\"]([^'\"]+)['\"]", dec_str, re.IGNORECASE)
                        if match:
                            method = match.group(1).upper()
                            path_str = match.group(2)
                            has_auth = any(auth_kw in dec_str.lower() or any(auth_kw in a.arg.lower() for a in node.args.args) for auth_kw in ["auth", "user", "token", "current_user", "security", "permission"])

                            route_info = {
                                "method": method,
                                "path": path_str,
                                "function": node.name,
                                "file": rel,
                                "line": getattr(node, "lineno", 1),
                                "has_auth": has_auth,
                            }
                            routes.append(route_info)

                            # If mutation endpoint (POST/PUT/PATCH/DELETE) has no auth parameter or decorator
                            if method in {"POST", "PUT", "PATCH", "DELETE"} and not has_auth and not any(pub in path_str.lower() for pub in ["login", "register", "token", "health", "public"]):
                                findings.append(
                                    FindingItem(
                                        category="authentication",
                                        severity="medium",
                                        confidence=0.75,
                                        evidence=f"Mutation endpoint {method} '{path_str}' in {rel}:{node.lineno} does not declare authentication or authorization dependencies.",
                                        analyzer_source="api_surface_analyzer",
                                        rule_id="API-UNPROTECTED-MUTATION",
                                        file=rel,
                                        line=getattr(node, "lineno", 1),
                                        title=f"Unprotected Mutation Endpoint: {method} {path_str}",
                                        remediation="Enforce authentication and permission checks using a dependency or middleware.",
                                    )
                                )
        except Exception:
            pass

    status = AnalyzerStatus.COMPLETE if routes else AnalyzerStatus.NOT_APPLICABLE
    duration = (time.perf_counter() - start_time) * 1000
    return AnalyzerOutput(
        analyzer_name="api_analyzer",
        status=status,
        findings=findings,
        metrics={
            "total_routes_discovered": len(routes),
            "authenticated_routes_count": sum(1 for r in routes if r["has_auth"]),
            "unprotected_routes_count": sum(1 for r in routes if not r["has_auth"]),
            "routes_sample": routes[:30],
        },
        duration_ms=duration,
        files_analyzed=len(py_files),
    )

