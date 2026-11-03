"""Testing Intelligence Engine: test framework discovery, test-to-source ratio, and untested path detection."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from app.services.analyzers.base import AnalyzerOutput, AnalyzerStatus, FindingItem

TEST_FRAMEWORKS = [
    ("pytest", ["pytest", "import pytest"], [".py"]),
    ("unittest", ["import unittest", "from unittest"], [".py"]),
    ("vitest", ["from 'vitest'", "import { describe, it", "vitest"], [".ts", ".tsx", ".js"]),
    ("jest", ["from '@jest/globals'", "jest.mock", "describe("], [".ts", ".tsx", ".js"]),
    ("playwright", ["@playwright/test", "from playwright"], [".py", ".ts", ".js"]),
]


def run_testing_analysis(root_dir: str | Path) -> AnalyzerOutput:
    """Evaluate repository test inventory, frameworks, and untested module paths."""
    start_time = time.perf_counter()
    root = Path(root_dir).resolve()
    findings: list[FindingItem] = []

    test_files: list[Path] = []
    source_files: list[Path] = []
    detected_frameworks: set[str] = set()

    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"} for part in p.parts):
            continue
        name_lower = p.name.lower()
        suffix = p.suffix.lower()

        if suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go"}:
            is_test = (
                name_lower.startswith("test_")
                or "_test." in name_lower
                or ".test." in name_lower
                or ".spec." in name_lower
                or "tests" in p.parts
                or "test" in p.parts
            )
            if is_test:
                test_files.append(p)
                # Framework detection
                try:
                    head = p.read_text(encoding="utf-8", errors="ignore")[:2000]
                    for fw, patterns, exts in TEST_FRAMEWORKS:
                        if suffix in exts and any(pat in head for pat in patterns):
                            detected_frameworks.add(fw)
                except OSError:
                    pass
            else:
                source_files.append(p)

    total_source = len(source_files)
    total_test = len(test_files)
    test_to_source_ratio = round(total_test / max(1, total_source), 3)

    if total_test == 0:
        findings.append(
            FindingItem(
                category="testing",
                severity="high",
                confidence=0.96,
                evidence=f"No automated test files detected across {total_source} source files in repository.",
                analyzer_source="test_inventory",
                rule_id="TST-ZERO-TESTS",
                title="Zero Test Coverage: No Test Files Found",
                remediation="Add unit and integration tests covering the primary execution and business logic paths.",
            )
        )
    elif test_to_source_ratio < 0.15:
        findings.append(
            FindingItem(
                category="testing",
                severity="medium",
                confidence=0.85,
                evidence=f"Low test-to-source file ratio: {total_test} test files for {total_source} source files ({test_to_source_ratio * 100:.1f}%).",
                analyzer_source="test_inventory",
                rule_id="TST-LOW-COVERAGE-RATIO",
                title="Low Test-to-Source Coverage Ratio",
                remediation="Expand automated test suites to cover core modules, API endpoints, and edge cases.",
            )
        )

    # Check for untested core modules (e.g. services, routes, api without corresponding test)
    untested_core: list[str] = []
    test_stems = {p.stem.replace("test_", "").replace("_test", "").replace(".test", "").lower() for p in test_files}
    for s_file in source_files:
        rel = str(s_file.relative_to(root)).replace("\\", "/")
        if any(kw in rel.lower() for kw in ["service", "controller", "route", "api", "model"]):
            if s_file.stem.lower() not in test_stems:
                untested_core.append(rel)

    if untested_core:
        findings.append(
            FindingItem(
                category="testing",
                severity="low",
                confidence=0.80,
                evidence=f"Untested critical application components: {', '.join(untested_core[:5])} have no matching test file.",
                analyzer_source="test_path_analyzer",
                rule_id="TST-UNTESTED-COMPONENTS",
                title="Critical Components Missing Dedicated Unit Tests",
                remediation="Implement unit tests covering each service and endpoint handler.",
                metadata={"untested_components": untested_core[:20]},
            )
        )

    duration = (time.perf_counter() - start_time) * 1000
    return AnalyzerOutput(
        analyzer_name="testing_analyzer",
        status=AnalyzerStatus.COMPLETE,
        findings=findings,
        metrics={
            "total_test_files": total_test,
            "total_source_files": total_source,
            "test_to_source_ratio": test_to_source_ratio,
            "detected_frameworks": sorted(detected_frameworks),
            "untested_core_modules_count": len(untested_core),
        },
        duration_ms=duration,
        files_analyzed=total_test + total_source,
    )

