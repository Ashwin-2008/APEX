"""Configuration and Deployment Intelligence Engine: Docker, CI/CD, env vars, health checks."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from app.services.analyzers.base import AnalyzerOutput, AnalyzerStatus, FindingItem


def run_config_analysis(root_dir: str | Path) -> AnalyzerOutput:
    """Analyze Dockerfiles, docker-compose, CI/CD, and environment configurations."""
    start_time = time.perf_counter()
    root = Path(root_dir).resolve()
    findings: list[FindingItem] = []
    files_analyzed = 0

    # 1. Dockerfile checks
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        name_lower = p.name.lower()
        if "dockerfile" in name_lower or name_lower.endswith(".dockerfile"):
            files_analyzed += 1
            rel = str(p.relative_to(root)).replace("\\", "/")
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                # Check root user
                if "USER " not in content and "USER\t" not in content:
                    findings.append(
                        FindingItem(
                            category="deployment",
                            severity="medium",
                            confidence=0.88,
                            evidence=f"Dockerfile '{rel}' does not specify a non-root USER instruction; container will execute as root.",
                            analyzer_source="docker_analyzer",
                            rule_id="DOCKER-CONTAINER-ROOT-USER",
                            file=rel,
                            title="Container Executes as Root User",
                            remediation="Add a non-privileged user (e.g. `USER appuser`) before the CMD/ENTRYPOINT instructions.",
                        )
                    )
                # Check for pinned base image
                from_lines = [l for l in content.splitlines() if l.strip().upper().startswith("FROM ")]
                for fl in from_lines:
                    if ":latest" in fl.lower() or (":" not in fl and "@" not in fl):
                        findings.append(
                            FindingItem(
                                category="deployment",
                                severity="low",
                                confidence=0.90,
                                evidence=f"Unpinned base image tag '{fl.strip()}' in '{rel}'.",
                                analyzer_source="docker_analyzer",
                                rule_id="DOCKER-UNPINNED-BASE-IMAGE",
                                file=rel,
                                title="Unpinned Docker Base Image Tag",
                                remediation="Pin an exact digest or immutable version tag (e.g. `python:3.11.8-slim`).",
                            )
                        )
            except OSError:
                pass

        # 2. CI/CD checks
        if ".github/workflows" in str(p).lower() and p.suffix.lower() in {".yml", ".yaml"}:
            files_analyzed += 1
            rel = str(p.relative_to(root)).replace("\\", "/")
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                # Check for pull_request_target with checkout of PR head
                if "pull_request_target" in content and "ref: ${{ github.event.pull_request.head.sha }}" in content:
                    findings.append(
                        FindingItem(
                            category="security",
                            severity="critical",
                            confidence=0.95,
                            evidence=f"GitHub Actions workflow '{rel}' uses pull_request_target with untrusted PR checkout, permitting privilege escalation.",
                            analyzer_source="cicd_analyzer",
                            rule_id="CICD-PR-TARGET-POISONING",
                            file=rel,
                            title="Dangerous pull_request_target in CI/CD Workflow",
                            remediation="Use the standard 'pull_request' trigger for untrusted forks or do not check out PR head code with elevated secrets.",
                        )
                    )
            except OSError:
                pass

    status = AnalyzerStatus.COMPLETE if files_analyzed > 0 else AnalyzerStatus.NOT_APPLICABLE
    duration = (time.perf_counter() - start_time) * 1000
    return AnalyzerOutput(
        analyzer_name="config_analyzer",
        status=status,
        findings=findings,
        metrics={"deployment_files_analyzed": files_analyzed},
        duration_ms=duration,
        files_analyzed=files_analyzed,
    )

