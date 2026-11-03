"""Database Intelligence Engine: schema inspection, unindexed foreign keys, unsafe transactions."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from app.services.analyzers.base import AnalyzerOutput, AnalyzerStatus, FindingItem


def run_database_analysis(root_dir: str | Path) -> AnalyzerOutput:
    """Analyze database definitions, migrations, SQL files, and ORM entity declarations."""
    start_time = time.perf_counter()
    root = Path(root_dir).resolve()
    findings: list[FindingItem] = []
    files_analyzed = 0

    target_files = [
        p for p in root.rglob("*")
        if p.is_file() and (p.suffix.lower() == ".sql" or "migration" in p.parts or "models" in p.parts or "entities" in p.parts)
        and not any(part in {".git", "node_modules", "venv", ".venv", "__pycache__"} for part in p.parts)
    ]

    for p in target_files:
        rel = str(p.relative_to(root)).replace("\\", "/")
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        files_analyzed += 1

        # Check for unindexed foreign keys in SQL schema
        if p.suffix.lower() == ".sql":
            fk_matches = re.finditer(r"(?i)FOREIGN\s+KEY\s*\(([^\)]+)\)\s+REFERENCES\s+([a-zA-Z0-9_]+)\s*\(([^\)]+)\)", content)
            for fk in fk_matches:
                col = fk.group(1).strip().strip('"`')
                if f"INDEX" not in content and f"index" not in content:
                    line_no = content[:fk.start()].count("\n") + 1
                    findings.append(
                        FindingItem(
                            category="data_integrity",
                            severity="medium",
                            confidence=0.85,
                            evidence=f"Foreign key '{col}' references {fk.group(2)} without explicit index declaration in {rel}:{line_no}.",
                            analyzer_source="schema_analyzer",
                            rule_id="DB-UNINDEXED-FK",
                            file=rel,
                            line=line_no,
                            title=f"Unindexed Foreign Key '{col}' in Schema",
                            remediation=f"Create an index on '{col}' to prevent full-table scans during JOIN operations.",
                        )
                    )

        # Check for raw string concatenation in SQL execution
        if re.search(r"(?i)SELECT\s+.*FROM.*WHERE.*=.*['\"]?\s*\+", content):
            findings.append(
                FindingItem(
                    category="data_integrity",
                    severity="high",
                    confidence=0.90,
                    evidence=f"Dynamic string concatenation in SQL statement in {rel}.",
                    analyzer_source="query_analyzer",
                    rule_id="DB-UNSAFE-QUERY-CONCAT",
                    file=rel,
                    title="Dynamic SQL Query String Concatenation",
                    remediation="Use parameterized queries with prepared statements.",
                )
            )

    status = AnalyzerStatus.COMPLETE if files_analyzed > 0 else AnalyzerStatus.NOT_APPLICABLE
    duration = (time.perf_counter() - start_time) * 1000
    return AnalyzerOutput(
        analyzer_name="database_analyzer",
        status=status,
        findings=findings,
        metrics={"schema_files_analyzed": files_analyzed},
        duration_ms=duration,
        files_analyzed=files_analyzed,
    )

