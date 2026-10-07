"""Deterministic, evidence-first project review engine.

The engine deliberately produces facts from the repository before any optional
LLM explanation is added. It is dependency-light so reviews work in a local,
air-gapped deployment as well as in production.
"""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FAILURE_CATEGORIES = [
    "requirements", "architecture", "authentication", "authorization",
    "input_validation", "data_integrity", "api_contract", "error_handling",
    "testing", "dependency", "performance", "security", "configuration",
    "deployment", "observability", "integration",
]


def _run_git(root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return ""


def _event(category: str, severity: str, confidence: float, evidence: str, source: str, **extra: Any) -> dict[str, Any]:
    return {"category": category, "severity": severity, "confidence": round(confidence, 3),
            "timestamp": datetime.now(timezone.utc).isoformat(), "evidence": evidence,
            "analyzer_source": source, "status": "open", "remediation": extra.pop("remediation", "Investigate and add a regression test."), **extra}


def analyze_project(project_path: str) -> dict[str, Any]:
    # Browsers commonly submit pasted Windows paths with surrounding quotes.
    # Normalize those harmless presentation characters before validation.
    normalized_path = str(project_path).strip().strip('"').strip("'")
    root = Path(normalized_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Repository path was not found or is not a directory: {normalized_path}")
    files = [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts and ".venv" not in p.parts]
    by_suffix = Counter(p.suffix.lower() for p in files)
    text_files = [p for p in files if p.suffix.lower() in {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".php"}]
    contents: dict[Path, str] = {}
    for p in text_files[:5000]:
        try:
            contents[p] = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            pass

    requirements: list[dict[str, str]] = []
    for path in [p for p in files if p.suffix.lower() in {".md", ".txt"} and p.stat().st_size < 2_000_000]:
        try:
            for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                match = re.match(r"^\s*(?:[-*]\s+\[[ xX]\]|#{2,4})\s+(.{12,300})$", line)
                if match and re.search(r"(?i)must|should|required|requirement|shall|user can|users can", match.group(1)):
                    requirements.append({"requirement_key": f"{path.name}:{line_number}", "title": match.group(1).strip(), "description": match.group(1).strip(), "source": path.name, "priority": "unspecified"})
        except OSError:
            pass

    events: list[dict[str, Any]] = []
    req_files = [p for p in files if p.name.lower() in {"readme.md", "requirements.md", "prd.md", "package.json", "pyproject.toml"}]
    if not req_files:
        events.append(_event("requirements", "medium", .92, "No README, PRD, requirements, or package manifest found.", "requirements_analyzer", remediation="Create a versioned requirements/acceptance specification."))
    test_files = [p for p in files if re.search(r"(^test_|_test\.|\.test\.|\.spec\.)", p.name, re.I) or "tests" in p.parts]
    if not test_files:
        events.append(_event("testing", "high", .96, "No test files were detected in the repository.", "test_inventory", remediation="Add unit and integration tests for the critical execution paths."))
    manifests = [p for p in files if p.name.lower() in {"package.json", "requirements.txt", "pyproject.toml", "poetry.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "cargo.toml", "go.mod"}]
    if not manifests:
        events.append(_event("dependency", "medium", .88, "No recognized dependency manifest was detected.", "dependency_analyzer", remediation="Pin runtime dependencies and add automated vulnerability scanning."))
    secrets = []
    secret_re = re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]")
    for path, content in contents.items():
        if ".env.example" not in path.name.lower():
            for match in secret_re.finditer(content):
                secrets.append(f"{path.relative_to(root)}:{content[:match.start()].count(chr(10)) + 1}")
    if secrets:
        events.append(_event("security", "critical", .9, f"Potential hard-coded secret pattern at {', '.join(secrets[:10])}.", "secret_detector", remediation="Move credentials to a secret manager and rotate exposed values."))
    auth_terms = sum(len(re.findall(r"(?i)auth|login|session|jwt|oauth", c)) for c in contents.values())
    route_terms = sum(len(re.findall(r"(?i)route|endpoint|router|fetch\(|axios", c)) for c in contents.values())
    if route_terms and not auth_terms:
        events.append(_event("authentication", "high", .72, "Application routes/API clients were detected but no authentication implementation markers were found.", "surface_analyzer", remediation="Document public/private surfaces and enforce authentication at the boundary."))
    git_log = _run_git(root, "log", "--pretty=%H|%aI|%s", "-n", "200")
    commits = [line.split("|", 2) for line in git_log.splitlines() if line.count("|") >= 2]
    bugfixes = [c for c in commits if re.search(r"bug|fix|hotfix|revert|patch", c[2], re.I)]
    churn = _run_git(root, "diff", "--stat", "HEAD~20", "HEAD") if len(commits) >= 20 else ""
    history = [{"timestamp": c[1], "category": "integration" if re.search(r"api|merge|integrat", c[2], re.I) else "testing" if re.search(r"test|ci|build", c[2], re.I) else "architecture" if re.search(r"refactor|arch", c[2], re.I) else "configuration" if re.search(r"config|deploy|docker", c[2], re.I) else "security" if re.search(r"auth|security|secret", c[2], re.I) else "data_integrity" if re.search(r"db|data|migration", c[2], re.I) else "integration", "evidence": c[2]} for c in reversed(commits)]
    if len(bugfixes) >= 5:
        events.append(_event("integration", "high", .78, f"Git history contains {len(bugfixes)} bug-fix/revert commits in the last {len(commits)} commits.", "git_history", remediation="Review the affected hotspots and require regression tests for each recurring fix."))

    sequence = [e["category"] for e in history] + [e["category"] for e in events]
    transitions = Counter(zip(sequence, sequence[1:]))
    outgoing = Counter(sequence)
    transition_graph = [{"from": a, "to": b, "count": n, "probability": round(n / outgoing[a], 3)} for (a, b), n in transitions.items()]
    loops = []
    for (a, b), count in transitions.items():
        if a != b and transitions.get((b, a), 0):
            occurrences = min(count, transitions[(b, a)])
            loops.append({"pattern": f"{a} → {b} → {a}", "occurrence_count": occurrences, "risk": "high" if occurrences >= 2 else "medium"})
    counts = Counter(sequence)
    total = max(1, len(sequence))
    dna = {"testing_deficiency": round(min(1, (1 if not test_files else 0) + counts["testing"] / total), 3), "dependency_risk": round(min(1, (0.5 if not manifests else 0) + counts["dependency"] / total), 3), "integration_fragility": round(min(1, counts["integration"] / total + len(bugfixes) / max(1, len(commits))), 3), "security_risk": round(min(1, (0.8 if secrets else 0) + counts["security"] / total), 3), "requirement_ambiguity": round(min(1, (0.8 if not req_files else 0) + counts["requirements"] / total), 3)}
    for key in ("architecture_coupling", "validation_weakness", "authorization_risk", "configuration_drift", "error_handling_weakness", "database_risk", "deployment_risk", "observability_weakness"):
        dna[key] = round(min(1, counts[key.removesuffix("_risk")] / total), 3)
    probs = Counter(sequence[-20:])
    predictions = [{"category": cat, "probability": round(n / max(1, sum(probs.values())), 3), "confidence": round(min(.95, .45 + n / max(1, len(sequence))), 3), "historical_support": n} for cat, n in probs.most_common(5)]
    return {"project": {"path": str(root), "file_count": len(files), "language_mix": dict(by_suffix), "commit_count": len(commits), "bugfix_commit_count": len(bugfixes), "recent_churn": churn}, "requirements": requirements, "events": events, "history": history, "transition_graph": transition_graph, "failure_loops": loops, "failure_dna": dna, "next_failure_predictions": predictions, "summary": {"event_count": len(events), "open_high_or_critical": sum(e["severity"] in {"high", "critical"} for e in events), "generated_at": datetime.now(timezone.utc).isoformat(), "methodology": "Evidence-backed deterministic analyzers plus chronological historical associations; predictions are not causal or certain."}}
