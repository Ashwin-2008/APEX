"""Comprehensive Analysis Engine: orchestrates modular analyzers and calculates honest coverage."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.analyzers.api_analyzer import run_api_analysis
from app.services.analyzers.architecture_analyzer import run_architecture_analysis
from app.services.analyzers.code_intel_analyzer import run_code_intelligence_analysis
from app.services.analyzers.base import AnalyzerOutput, AnalyzerStatus, FindingItem
from app.services.analyzers.config_analyzer import run_config_analysis
from app.services.analyzers.database_analyzer import run_database_analysis
from app.services.analyzers.dependency_analyzer import run_dependency_analysis
from app.services.analyzers.discovery import discover_repository
from app.services.analyzers.dynamic_analyzer import run_dynamic_analysis
from app.services.analyzers.security_analyzer import run_security_analysis
from app.services.analyzers.testing_analyzer import run_testing_analysis


def run_comprehensive_analysis(
    repository_path: str | Path,
    enabled_analyzers: list[str] | None = None,
    run_dynamic: bool = False,
) -> dict[str, Any]:
    """Execute all active deterministic analyzers, compiling honest coverage and finding evidence."""
    start_time = time.perf_counter()
    root = Path(repository_path).resolve()
    if not root.is_dir():
        raise ValueError(f"Repository directory does not exist: {repository_path}")

    # 1. Structural discovery
    discovery = discover_repository(root)

    # 2. Selected analyzer set
    selected = set(enabled_analyzers or [
        "security", "dependency", "testing", "architecture", "database", "configuration", "api", "code_intelligence"
    ])

    analyzer_results: dict[str, AnalyzerOutput] = {}
    all_findings: list[FindingItem] = []

    # Run Security Analyzer
    if "security" in selected:
        sec_out = run_security_analysis(root)
        analyzer_results["security"] = sec_out
        all_findings.extend(sec_out.findings)

    # Run Dependency Analyzer
    if "dependency" in selected:
        dep_out = run_dependency_analysis(root)
        analyzer_results["dependency"] = dep_out
        all_findings.extend(dep_out.findings)

    # Run Testing Analyzer
    if "testing" in selected:
        test_out = run_testing_analysis(root)
        analyzer_results["testing"] = test_out
        all_findings.extend(test_out.findings)

    # Run Architecture Analyzer
    if "architecture" in selected:
        arch_out = run_architecture_analysis(root)
        analyzer_results["architecture"] = arch_out
        all_findings.extend(arch_out.findings)

    # Run Database Analyzer
    if "database" in selected:
        db_out = run_database_analysis(root)
        analyzer_results["database"] = db_out
        all_findings.extend(db_out.findings)

    # Run Configuration Analyzer
    if "configuration" in selected:
        cfg_out = run_config_analysis(root)
        analyzer_results["configuration"] = cfg_out
        all_findings.extend(cfg_out.findings)

    # Run API Analyzer
    if "api" in selected:
        api_out = run_api_analysis(root)
        analyzer_results["api"] = api_out
        all_findings.extend(api_out.findings)

    # Run Code Intelligence Analyzer (McCabe AST Complexity & Dead Code)
    if "code_intelligence" in selected or "code_intel" in selected:
        intel_out = run_code_intelligence_analysis(root)
        analyzer_results["code_intelligence"] = intel_out
        all_findings.extend(intel_out.findings)

    # Run Dynamic Analyzer (opt-in)
    if "dynamic" in selected or run_dynamic:
        dyn_out = run_dynamic_analysis(root, enabled=run_dynamic)
        analyzer_results["dynamic"] = dyn_out
        all_findings.extend(dyn_out.findings)
    else:
        analyzer_results["dynamic"] = AnalyzerOutput(
            analyzer_name="dynamic_analyzer",
            status=AnalyzerStatus.NOT_APPLICABLE,
            metrics={"policy": "opt_in_required"},
        )

    # Calculate actual scan coverage
    analyzed_count = discovery.supported_files
    total_count = max(1, discovery.total_files)
    coverage_ratio = min(1.0, round(analyzed_count / total_count, 3))
    coverage_pct = round(coverage_ratio * 100, 1)

    # Overall analysis status
    failed_any = any(res.status == AnalyzerStatus.FAILED for res in analyzer_results.values())
    if failed_any:
        overall_status = AnalyzerStatus.PARTIAL.value
    elif coverage_pct >= 80:
        overall_status = AnalyzerStatus.COMPLETE.value
    else:
        overall_status = AnalyzerStatus.PARTIAL.value

    # Findings breakdown by severity
    severity_counts = {
        "critical": sum(1 for f in all_findings if f.severity == "critical"),
        "high": sum(1 for f in all_findings if f.severity == "high"),
        "medium": sum(1 for f in all_findings if f.severity == "medium"),
        "low": sum(1 for f in all_findings if f.severity == "low"),
        "info": sum(1 for f in all_findings if f.severity == "info"),
    }

    total_duration_ms = (time.perf_counter() - start_time) * 1000

    coverage_manifest = {
        "overall_status": overall_status,
        "coverage_percentage": coverage_pct,
        "total_files": discovery.total_files,
        "supported_files": discovery.supported_files,
        "analyzed_files": analyzed_count,
        "skipped_files": discovery.skipped_files,
        "excluded_files": discovery.excluded_files,
        "duration_ms": round(total_duration_ms, 2),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analyzers": {
            k: {
                "status": v.status.value,
                "findings_count": len(v.findings),
                "duration_ms": round(v.duration_ms, 2),
                "error_message": v.error_message,
            }
            for k, v in analyzer_results.items()
        },
    }

    return {
        "discovery": discovery.to_dict(),
        "coverage": coverage_manifest,
        "analyzers": {k: v.to_dict() for k, v in analyzer_results.items()},
        "findings": [f.to_dict() for f in all_findings],
        "severity_counts": severity_counts,
        "summary": {
            "total_findings": len(all_findings),
            "critical_or_high": severity_counts["critical"] + severity_counts["high"],
            "coverage_percentage": coverage_pct,
            "overall_status": overall_status,
            "duration_ms": round(total_duration_ms, 2),
        },
    }

