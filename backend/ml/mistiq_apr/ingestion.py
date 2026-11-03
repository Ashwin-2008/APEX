"""Configurable, resumable 16-stage repository collection and dataset ingestion pipeline.

Implements Phase 3 of the APEX ML architecture:
1. Discover candidate repositories (local git roots, curated manifest, or GitHub API).
2. Validate repository URL and source.
3. Inspect repository metadata.
4. Check license and eligibility.
5. Check repository activity and commit history.
6. Detect duplicate repositories (by remote URL, initial commit SHA, or canonical path).
7. Record languages and project characteristics.
8. Clone or fetch eligible repositories (resumable, rate-limited).
9. Record commit SHAs and source provenance.
10. Extract chronological snapshots and changes without mutating working trees.
11. Run deterministic static & commit-diff analyzers on each snapshot.
12. Associate changes with verified findings and fixes.
13. Generate training observations with explicit label confidence & evidence.
14. Redact secrets, tokens, and credentials from all persisted artifacts.
15. Validate dataset quality and deduplicate observations.
16. Persist dataset manifests, observations, metadata, and exclusion logs under
    ``backend/ml/artifacts/datasets/``.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from sqlalchemy.orm import Session

from .constants import (
    ALL_FEATURE_NAMES,
    FAILURE_CATEGORIES,
    PROJECT_REVIEW_DATASET_VERSION,
    SEVERITY_LEVELS,
    SEVERITY_RANK,
)
from .dataset import (
    DATA_CATEGORY_ANALYZER_RISK,
    DATA_CATEGORY_HISTORICAL_TRANSITION,
    DATA_CATEGORY_VERIFIED_DEFECT,
    Observation,
    build_curated_observations,
    canonical_repository_group,
    infer_language_group,
    infer_size_bucket,
    is_synthetic_project_record,
)

DATASETS_ARTIFACT_DIR = (
    Path(__file__).resolve().parents[1] / "artifacts" / "datasets"
)

PERMISSIVE_LICENSES = frozenset(
    {
        "mit",
        "apache-2.0",
        "bsd-2-clause",
        "bsd-3-clause",
        "isc",
        "0bsd",
        "unlicense",
        "psf-2.0",
        "cc0-1.0",
        "zlib",
        "artistic-2.0",
        "local-authorized-workspace",
    }
)

SUPPORTED_COLLECTION_TARGETS = (100, 500, 1000, 5000)

# Secret redaction patterns to ensure no credentials enter dataset artifacts.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,255}\b")),
    ("groq_key", re.compile(r"\bgsk_[A-Za-z0-9]{20,255}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9\-_]{20,255}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,255}\b")),
    (
        "private_key_block",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    (
        "generic_secret_assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|password|passwd|client[_-]?secret)\s*[:=]\s*['\"]([^'\"]{8,120})['\"]"
        ),
    ),
)

LANGUAGE_EXTENSIONS = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".kt": "Kotlin",
}


def redact_secrets(text: str | None) -> tuple[str, int]:
    """Redact credentials, tokens, and private keys from text.

    Returns ``(redacted_text, redaction_count)``.
    """
    if not text:
        return "", 0
    redacted = str(text)
    total_redactions = 0
    for label, pattern in SECRET_PATTERNS:
        if label == "generic_secret_assignment":
            matches = list(pattern.finditer(redacted))
            if matches:
                total_redactions += len(matches)
                redacted = pattern.sub(r"\1='[REDACTED_SECRET]'", redacted)
        else:
            matches = list(pattern.finditer(redacted))
            if matches:
                total_redactions += len(matches)
                redacted = pattern.sub(f"[REDACTED_{label.upper()}]", redacted)
    return redacted, total_redactions


@dataclass
class IngestionConfig:
    """Configuration for the 16-stage repository collection and ingestion pipeline."""

    dataset_version: str = "v001"
    target_repository_count: int = 100
    min_commits: int = 2
    max_snapshots_per_repo: int = 25
    allow_local_authorized_repos: bool = True
    require_permissive_license_for_remote: bool = True
    local_search_roots: list[str] = field(default_factory=list)
    remote_repository_urls: list[str] = field(default_factory=list)
    github_query: str | None = None
    github_rate_limit_sleep_seconds: float = 1.0
    output_dir: Path = field(default_factory=lambda: DATASETS_ARTIFACT_DIR)


def _run_git(repo_path: Path, args: Sequence[str], timeout: int = 25) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def detect_repository_license(repo_path: Path, is_local_authorized: bool = True) -> dict[str, Any]:
    """Inspect LICENSE/COPYING/package metadata to determine repository license."""
    license_files = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "COPYING.txt")
    for fname in license_files:
        fpath = repo_path / fname
        if fpath.is_file():
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            if "mit license" in content or "permission is hereby granted, free of charge" in content:
                return {"spdx_id": "MIT", "eligible": True, "source": fname}
            if "apache license" in content and "version 2.0" in content:
                return {"spdx_id": "Apache-2.0", "eligible": True, "source": fname}
            if "redistribution and use in source and binary forms" in content:
                if "neither the name" in content:
                    return {"spdx_id": "BSD-3-Clause", "eligible": True, "source": fname}
                return {"spdx_id": "BSD-2-Clause", "eligible": True, "source": fname}
            if "isc license" in content:
                return {"spdx_id": "ISC", "eligible": True, "source": fname}
            if "gnu general public license" in content or "agpl" in content:
                return {"spdx_id": "GPL", "eligible": False, "source": fname}
            return {"spdx_id": "Custom-License-File", "eligible": bool(is_local_authorized), "source": fname}

    pkg_json = repo_path / "package.json"
    if pkg_json.is_file():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
            lic = str(data.get("license") or "").strip()
            if lic:
                eligible = lic.lower() in PERMISSIVE_LICENSES or is_local_authorized
                return {"spdx_id": lic, "eligible": eligible, "source": "package.json"}
        except Exception:
            pass

    if is_local_authorized:
        return {
            "spdx_id": "local-authorized-workspace",
            "eligible": True,
            "source": "workspace_authorization",
        }
    return {"spdx_id": "unknown", "eligible": False, "source": "missing"}


def discover_local_git_repositories(roots: Iterable[str | Path], max_depth: int = 3) -> list[Path]:
    """Discover local Git repositories up to ``max_depth`` without following temp/venv dirs."""
    discovered: list[Path] = []
    seen_realpaths: set[str] = set()
    skip_dirs = {
        "node_modules",
        "venv",
        ".venv",
        "__pycache__",
        "dist",
        "build",
        ".pytest_cache",
        ".mypy_cache",
        "site-packages",
    }

    def _walk(current: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            if (current / ".git").exists():
                resolved = str(current.resolve()).lower()
                if resolved not in seen_realpaths and "appdata\\local\\temp" not in resolved:
                    seen_realpaths.add(resolved)
                    discovered.append(current.resolve())
        except OSError:
            return

        if depth == max_depth:
            return
        try:
            for child in sorted(current.iterdir()):
                if not child.is_dir():
                    continue
                if child.name.startswith(".") or child.name.lower() in skip_dirs:
                    continue
                _walk(child, depth + 1)
        except OSError:
            return

    for root in roots:
        p = Path(root)
        if p.exists() and p.is_dir():
            _walk(p, 0)
    return discovered


def _get_git_commits(repo_path: Path, max_snapshots: int = 25) -> list[dict[str, Any]]:
    """Return chronological commits (oldest first) sampled evenly up to ``max_snapshots``."""
    res = _run_git(
        repo_path,
        ["log", "--reverse", "--format=%H|%ct|%cI|%an|%s"],
    )
    if res.returncode != 0 or not res.stdout.strip():
        return []
    commits: list[dict[str, Any]] = []
    last_ts = -1
    for line in res.stdout.splitlines():
        parts = line.split("|", 4)
        if len(parts) < 5:
            continue
        sha, ts_str, iso_dt, author, subject = parts
        try:
            ts = int(ts_str)
        except ValueError:
            ts = 0
        if ts <= last_ts:
            ts = last_ts + 1
        last_ts = ts
        utc_iso = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None).isoformat()
        redacted_subject, _ = redact_secrets(subject)
        commits.append(
            {
                "sha": sha.strip(),
                "timestamp": ts,
                "committed_at": utc_iso,
                "author_hash": hashlib.sha256(author.strip().encode("utf-8")).hexdigest()[:12],
                "subject": redacted_subject.strip(),
            }
        )
    if len(commits) <= max_snapshots:
        return commits

    indices: list[int] = []
    step = (len(commits) - 1) / float(max_snapshots - 1)
    for i in range(max_snapshots):
        idx = int(round(i * step))
        if not indices or idx != indices[-1]:
            indices.append(idx)
    return [commits[i] for i in indices]


def _inspect_commit_snapshot(
    repo_path: Path,
    commit: dict[str, Any],
    prev_commit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analyze a repository snapshot at a specific commit SHA without checking it out."""
    sha = commit["sha"]
    ls_res = _run_git(repo_path, ["ls-tree", "-r", "--long", sha])
    files: list[str] = []
    total_bytes = 0
    if ls_res.returncode == 0:
        for line in ls_res.stdout.splitlines():
            tab_split = line.split("\t", 1)
            if len(tab_split) != 2:
                continue
            header, rel_path = tab_split
            rel_norm = rel_path.strip().replace("\\", "/")
            if any(
                seg in rel_norm.lower().split("/")
                for seg in ("node_modules", "venv", ".venv", "dist", "build", "__pycache__", ".git")
            ):
                continue
            files.append(rel_norm)
            header_parts = header.split()
            if len(header_parts) >= 4 and header_parts[3].isdigit():
                total_bytes += int(header_parts[3])

    if prev_commit is not None:
        diff_stat_res = _run_git(
            repo_path, ["diff", "--numstat", prev_commit["sha"], sha]
        )
        diff_patch_res = _run_git(
            repo_path,
            [
                "diff",
                "--unified=1",
                prev_commit["sha"],
                sha,
                "--",
                "*.py",
                "*.ts",
                "*.tsx",
                "*.js",
                "*.jsx",
                "*.java",
                "*.go",
                "*.json",
                "*.yml",
                "*.yaml",
                "*.toml",
                "*.md",
            ],
            timeout=15,
        )
    else:
        diff_stat_res = _run_git(repo_path, ["show", "--numstat", "--format=", sha])
        diff_patch_res = _run_git(
            repo_path,
            [
                "show",
                "--unified=1",
                "--format=",
                sha,
                "--",
                "*.py",
                "*.ts",
                "*.tsx",
                "*.js",
                "*.jsx",
                "*.java",
                "*.go",
                "*.json",
                "*.yml",
                "*.yaml",
                "*.toml",
                "*.md",
            ],
            timeout=15,
        )

    changed_files: list[str] = []
    lines_added = 0
    lines_deleted = 0
    if diff_stat_res.returncode == 0:
        for line in diff_stat_res.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                a_str, d_str, c_path = parts[0], parts[1], parts[2]
                if a_str.isdigit():
                    lines_added += int(a_str)
                if d_str.isdigit():
                    lines_deleted += int(d_str)
                changed_files.append(c_path.strip().replace("\\", "/"))

    diff_text = diff_patch_res.stdout if diff_patch_res.returncode == 0 else ""
    _, secret_hits_in_diff = redact_secrets(diff_text)

    language_mix: dict[str, int] = {}
    code_files: list[str] = []
    test_files: list[str] = []
    doc_files: list[str] = []
    manifest_files: list[str] = []
    ci_files: list[str] = []

    for f in files:
        lower = f.lower()
        ext = Path(f).suffix.lower()
        if ext in LANGUAGE_EXTENSIONS:
            language_mix[ext] = language_mix.get(ext, 0) + 1
            code_files.append(f)
        if "test" in lower or "spec" in lower or lower.startswith("tests/"):
            test_files.append(f)
        if lower.endswith((".md", ".rst", ".txt")) or "readme" in lower or "docs/" in lower:
            doc_files.append(f)
        if Path(f).name.lower() in (
            "requirements.txt",
            "pyproject.toml",
            "package.json",
            "pom.xml",
            "go.mod",
            "cargo.toml",
            "pipfile",
        ):
            manifest_files.append(f)
        if ".github/workflows" in lower or "dockerfile" in lower or "docker-compose" in lower or "jenkinsfile" in lower:
            ci_files.append(f)

    findings: list[dict[str, Any]] = []

    def _add_finding(
        category: str,
        severity: str,
        title: str,
        component: str,
        evidence_source: str,
        confidence: float = 0.85,
    ) -> None:
        fp = hashlib.sha256(f"{category}:{title}:{component}".encode("utf-8")).hexdigest()[:16]
        findings.append(
            {
                "category": category,
                "severity": severity,
                "title": title,
                "component": component,
                "file": component if "." in Path(component).name else None,
                "evidence_source": evidence_source,
                "confidence": confidence,
                "fingerprint": fp,
            }
        )

    test_ratio = len(test_files) / float(max(len(code_files), 1))
    if len(code_files) >= 3 and len(test_files) == 0:
        _add_finding("testing", "high", "No automated test suite in snapshot", "tests", "snapshot_tree", 0.90)
    elif len(code_files) >= 8 and test_ratio < 0.15:
        _add_finding("testing", "medium", f"Low test-to-code ratio ({test_ratio:.2f})", "tests", "snapshot_tree", 0.80)

    if len(doc_files) == 0:
        _add_finding("requirements", "medium", "Missing README and requirements documentation", "docs", "snapshot_tree", 0.80)

    if len(code_files) > 0 and len(manifest_files) == 0:
        _add_finding("dependency", "medium", "Missing dependency manifest file", "dependencies", "snapshot_tree", 0.85)

    if len(code_files) >= 10 and len(ci_files) == 0:
        _add_finding("deployment", "low", "No CI/CD or container deployment config found", "deployment", "snapshot_tree", 0.75)

    added_lines = [
        line[1:]
        for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    added_blob = "\n".join(added_lines)
    subject_lower = commit["subject"].lower()
    primary_changed_file = changed_files[0] if changed_files else (code_files[0] if code_files else "repository")

    if secret_hits_in_diff > 0:
        _add_finding("security", "critical", "Hardcoded secret or credential pattern in change", primary_changed_file, "diff_static_analyzer", 0.95)

    if re.search(r"\b(eval|exec)\s*\(|subprocess\.\w+\([^)]*shell\s*=\s*True|innerHTML\s*=|dangerouslySetInnerHTML", added_blob):
        _add_finding("security", "high", "Unsafe execution or injection sink in changed code", primary_changed_file, "diff_static_analyzer", 0.92)

    if re.search(r"except\s*:\s*(?:pass|\.\.\.)|except\s+Exception\s*:\s*pass|catch\s*\([^)]*\)\s*\{\s*\}", added_blob):
        _add_finding("error_handling", "high", "Silent exception swallowing in changed code", primary_changed_file, "diff_static_analyzer", 0.92)
    elif ("try:" in added_blob or "except " in added_blob or "raise " in added_blob or "error" in subject_lower) and any(
        w in subject_lower for w in ("fix", "handle", "crash", "exception", "error", "fallback")
    ):
        _add_finding("error_handling", "medium", "Error handling defect or recovery change", primary_changed_file, "commit_and_diff", 0.85)

    if re.search(r"@app\.(post|put|patch|delete)|router\.(post|put|patch|delete)", added_blob):
        if not re.search(r"Depends\(|verify_token|require_auth|is_authenticated|auth|permission|role", added_blob):
            _add_finding("authentication", "medium", "Mutating endpoint added without explicit auth guard in diff", primary_changed_file, "diff_static_analyzer", 0.85)
        if not re.search(r"BaseModel|Schema|validate|Field\(|zod|yup|joi", added_blob):
            _add_finding("input_validation", "medium", "Endpoint modified without schema/input validation in diff", primary_changed_file, "diff_static_analyzer", 0.85)

    if any(w in subject_lower for w in ("auth", "login", "jwt", "token", "session", "oauth")) or any(
        "auth" in cf.lower() for cf in changed_files
    ):
        if any(w in subject_lower for w in ("role", "permission", "rbac", "access", "forbidden", "unauthorized")):
            _add_finding("authorization", "high", "Authorization / access control change", primary_changed_file, "commit_and_diff", 0.88)
        else:
            _add_finding("authentication", "medium", "Authentication flow change", primary_changed_file, "commit_and_diff", 0.85)

    if any(w in subject_lower for w in ("validat", "sanitize", "schema", "payload", "parse")) or re.search(
        r"request\.(json|args|form|query_params)\[", added_blob
    ):
        _add_finding("input_validation", "medium", "Unvalidated request parameter access or validation change", primary_changed_file, "commit_and_diff", 0.85)

    if any(
        cf.lower().endswith(("requirements.txt", "pyproject.toml", "package.json", "package-lock.json", "go.mod", "cargo.toml"))
        for cf in changed_files
    ) or any(w in subject_lower for w in ("bump", "upgrade", "dependency", "dependencies", "package", "requirements")):
        _add_finding("dependency", "medium", "Dependency specification or lockfile modification", primary_changed_file, "commit_and_diff", 0.88)

    if any(
        "migration" in cf.lower() or "models" in cf.lower() or "schema" in cf.lower() or "db" in cf.lower()
        for cf in changed_files
    ) and (
        re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|ALTER\s+TABLE|CREATE\s+TABLE|session\.commit|transaction)\b", added_blob, re.IGNORECASE)
        or any(w in subject_lower for w in ("db", "database", "migration", "data", "null", "constraint", "integrity"))
    ):
        _add_finding("data_integrity", "medium", "Database schema or transactional data integrity change", primary_changed_file, "commit_and_diff", 0.86)

    if any(
        "api" in cf.lower() or "route" in cf.lower() or "endpoint" in cf.lower() or "client" in cf.lower()
        for cf in changed_files
    ) and (
        re.search(r"status_code|Response\(|JSONResponse|fetch\(|axios\.|http\.", added_blob)
        or any(w in subject_lower for w in ("api", "endpoint", "response", "contract", "cors", "route"))
    ):
        _add_finding("api_contract", "medium", "API route or client-server contract modification", primary_changed_file, "commit_and_diff", 0.84)

    if any(
        "config" in cf.lower() or ".env" in cf.lower() or "settings" in cf.lower()
        for cf in changed_files
    ) or re.search(r"os\.environ|os\.getenv|process\.env", added_blob):
        _add_finding("configuration", "medium", "Environment or runtime configuration change", primary_changed_file, "commit_and_diff", 0.84)

    if any(
        ".github" in cf.lower() or "docker" in cf.lower() or "deploy" in cf.lower() or "ci" in cf.lower()
        for cf in changed_files
    ) or any(w in subject_lower for w in ("deploy", "docker", "ci", "workflow", "build", "release")):
        _add_finding("deployment", "medium", "Deployment or build pipeline change", primary_changed_file, "commit_and_diff", 0.84)

    if re.search(r"\b(logger\.|logging\.|console\.(log|error|warn)|metrics|telemetry|sentry|prometheus)\b", added_blob) or any(
        w in subject_lower for w in ("log", "metric", "monitor", "trace", "observability", "audit")
    ):
        _add_finding("observability", "low", "Logging, telemetry, or audit instrumentation change", primary_changed_file, "commit_and_diff", 0.80)

    if lines_added + lines_deleted > 400 or len(changed_files) >= 12 or any(
        w in subject_lower for w in ("refactor", "architecture", "restructure", "modular", "decouple")
    ):
        _add_finding("architecture", "medium", f"High-blast-radius structural change ({len(changed_files)} files, +{lines_added}/-{lines_deleted} lines)", primary_changed_file, "commit_and_diff", 0.85)

    if re.search(r"for\s+.*in\s+.*:\s*\n\s+.*(?:query|execute|fetch|requests\.)", added_blob) or any(
        w in subject_lower for w in ("perf", "performance", "slow", "optimize", "cache", "latency", "memory", "timeout")
    ):
        _add_finding("performance", "medium", "Performance hotspot or optimization change", primary_changed_file, "commit_and_diff", 0.84)

    if re.search(r"\b(requests\.(get|post|put|delete)|httpx\.|aiohttp\.|urllib\.request|webhook|grpc|socket)\b", added_blob) or any(
        w in subject_lower for w in ("integration", "webhook", "provider", "external", "sync", "client")
    ):
        _add_finding("integration", "medium", "External service integration or network client change", primary_changed_file, "commit_and_diff", 0.85)

    if any("test" in cf.lower() or "spec" in cf.lower() for cf in changed_files) or any(
        w in subject_lower for w in ("test", "pytest", "vitest", "jest", "coverage", "assert")
    ):
        _add_finding("testing", "low", "Test suite modification or regression coverage change", primary_changed_file, "commit_and_diff", 0.82)

    if any(cf.lower().endswith(".md") for cf in changed_files) or any(
        w in subject_lower for w in ("doc", "readme", "requirement", "spec")
    ):
        _add_finding("requirements", "low", "Documentation or specification update", primary_changed_file, "commit_and_diff", 0.78)

    sev_counts = {sev: 0 for sev in SEVERITY_LEVELS}
    for item in findings:
        sev = item["severity"]
        if sev in sev_counts:
            sev_counts[sev] += 1

    snapshot = {
        "file_count": len(files),
        "code_file_count": len(code_files),
        "test_file_count": len(test_files),
        "doc_file_count": len(doc_files),
        "total_bytes": total_bytes,
        "language_mix": language_mix,
        "requirement_coverage": round(min(len(doc_files) / 3.0, 1.0), 4),
        "recent_churn": "\n".join(changed_files),
        "changed_file_count": len(changed_files),
        "lines_added": lines_added,
        "lines_deleted": lines_deleted,
    }

    return {
        "sha": sha,
        "committed_at": commit["committed_at"],
        "timestamp": commit["timestamp"],
        "subject": commit["subject"],
        "metrics": sev_counts,
        "snapshot": snapshot,
        "findings": findings,
        "secret_redactions": secret_hits_in_diff,
    }


def _make_git_snapshot_features(
    history_slice: Sequence[dict[str, Any]],
    current: dict[str, Any],
) -> dict[str, float]:
    """Build the exact 112-key feature dict matching ``dataset.make_features``."""
    all_findings = [f for snap in history_slice for f in snap["findings"]]
    categories = [f["category"] for f in all_findings]
    recent = categories[-5:]
    features: dict[str, float] = {}
    metrics = current["metrics"]
    for severity in ("critical", "high", "medium", "low"):
        features[f"static_{severity}_findings"] = float(metrics.get(severity, 0))
    features["static_total_findings"] = float(len(current["findings"]))
    snapshot = current["snapshot"]
    features["static_complexity_index"] = float(snapshot.get("file_count", 0))
    for key in ("security", "testing", "architecture", "dependency", "configuration"):
        feature_key = "config" if key == "configuration" else key
        features[f"static_{feature_key}_risk"] = float(
            sum(f["category"] == key and f["severity"] in {"critical", "high"} for f in current["findings"])
        )
    features["static_requirement_coverage"] = float(snapshot.get("requirement_coverage", 0))
    latest = categories[-1] if categories else None
    for category in FAILURE_CATEGORIES:
        features[f"latest_failure_{category}"] = float(category == latest)
        features[f"seq_freq_{category}"] = float(categories.count(category))
        positions = [i for i, value in enumerate(categories) if value == category]
        features[f"seq_recency_{category}"] = (
            float(len(categories) - positions[-1]) if positions else float(len(categories) + 1)
        )
        streak = 0
        for snap in reversed(history_slice):
            if any(f["category"] == category for f in snap["findings"]):
                streak += 1
            else:
                break
        features[f"seq_repetition_{category}"] = float(streak)
        transitions = sum(1 for a, b in zip(categories, categories[1:]) if a == category or b == category)
        features[f"seq_transition_{category}"] = float(transitions)
        features[f"seq_component_{category}"] = float(
            sum(f["category"] == category and (f.get("component") or f.get("file")) is not None for f in all_findings)
        )
    features["seq_failure_diversity_recent"] = float(len(set(recent)))
    features["seq_change_intensity"] = float(snapshot.get("changed_file_count", 0))
    features["seq_testing_weakness"] = float(sum(f["category"] == "testing" for f in current["findings"]))
    severity_values = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    current_severity = sum(severity_values.get(f["severity"], 0) for f in current["findings"])
    prior_severity = (
        sum(severity_values.get(f["severity"], 0) for f in history_slice[-2]["findings"])
        if len(history_slice) > 1
        else current_severity
    )
    features["seq_severity_trajectory"] = float(current_severity - prior_severity)
    return features


def _select_snapshot_primary_target(
    current: dict[str, Any],
    following: dict[str, Any],
) -> tuple[str | None, float, str, dict[str, Any]]:
    """Select the primary target category for a commit-to-commit transition."""
    next_findings = following["findings"]
    if not next_findings:
        return None, 0.0, DATA_CATEGORY_ANALYZER_RISK, {}

    current_fps = {f["fingerprint"] for f in current["findings"]}
    newly_active = [
        f for f in next_findings
        if f["fingerprint"] not in current_fps or f["evidence_source"] != "snapshot_tree"
    ]
    pool = newly_active if newly_active else next_findings
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for f in pool:
        by_cat.setdefault(f["category"], []).append(f)

    ranked = sorted(
        by_cat.keys(),
        key=lambda c: (
            min(SEVERITY_RANK.get(str(f["severity"]).lower(), 99) for f in by_cat[c]),
            -max(float(f.get("confidence", 0.8)) for f in by_cat[c]),
            -len(by_cat[c]),
            c,
        ),
    )
    winner = ranked[0]
    winner_findings = by_cat[winner]
    max_conf = max(float(f.get("confidence", 0.8)) for f in winner_findings)
    has_diff_evidence = any(f["evidence_source"] != "snapshot_tree" for f in winner_findings)
    if has_diff_evidence and newly_active:
        data_cat = DATA_CATEGORY_VERIFIED_DEFECT
        conf = round(min(0.96, 0.72 + 0.22 * max_conf), 4)
    elif newly_active:
        data_cat = DATA_CATEGORY_HISTORICAL_TRANSITION
        conf = round(min(0.88, 0.65 + 0.20 * max_conf), 4)
    else:
        data_cat = DATA_CATEGORY_ANALYZER_RISK
        conf = round(min(0.74, 0.52 + 0.20 * max_conf), 4)

    evidence = {
        "primary_target": winner,
        "is_primary_target": True,
        "transition_type": "commit_diff_verified" if has_diff_evidence else "snapshot_transition",
        "active_targets": sorted({f["category"] for f in next_findings}),
        "newly_introduced_categories": sorted({f["category"] for f in newly_active}),
        "target_finding_count": len(winner_findings),
        "max_analyzer_confidence": round(max_conf, 4),
        "has_commit_evidence": True,
        "source_commit_sha": current["sha"],
        "target_commit_sha": following["sha"],
        "target_commit_subject": following["subject"],
    }
    return winner, conf, data_cat, evidence


def build_observations_from_git_snapshots(
    repo_id: int,
    repo_name: str,
    repo_path: str,
    repo_group: str,
    license_info: dict[str, Any],
    snapshots: Sequence[dict[str, Any]],
) -> list[Observation]:
    """Convert chronological commit snapshots of a repository into curated Observation records."""
    if len(snapshots) < 2:
        return []

    observations: list[Observation] = []
    for idx in range(len(snapshots) - 1):
        current = snapshots[idx]
        following = snapshots[idx + 1]
        current_cats = sorted({f["category"] for f in current["findings"]})
        if not current_cats:
            continue

        primary_target, conf, data_cat, lbl_ev = _select_snapshot_primary_target(current, following)
        if primary_target is None or primary_target not in FAILURE_CATEGORIES:
            continue

        history_slice = snapshots[: idx + 1]
        features = _make_git_snapshot_features(history_slice, current)
        review_id = repo_id * 1000 + (idx + 1)
        target_review_id = repo_id * 1000 + (idx + 2)
        feature_review_ids = tuple(repo_id * 1000 + (j + 1) for j in range(idx + 1))
        feature_max_timestamp = max(s["committed_at"] for s in history_slice)

        observations.append(
            Observation(
                project_id=repo_id,
                review_id=review_id,
                review_number=idx + 1,
                timestamp=current["committed_at"],
                features=features,
                target=primary_target,
                previous_category=current_cats[-1],
                target_review_id=target_review_id,
                target_timestamp=following["committed_at"],
                feature_review_ids=feature_review_ids,
                feature_max_timestamp=feature_max_timestamp,
                repository_group=repo_group,
                is_synthetic=False,
                data_category=data_cat,
                label_confidence=conf,
                label_evidence=lbl_ev,
                provenance={
                    "project_id": repo_id,
                    "project_name": repo_name,
                    "repository_path": repo_path,
                    "repository_url": None,
                    "source_type": "git_commit_history",
                    "license": license_info.get("spdx_id", "unknown"),
                    "commit_sha": current["sha"],
                    "target_commit_sha": following["sha"],
                    "source_review_id": review_id,
                    "source_review_number": idx + 1,
                    "target_review_id": target_review_id,
                    "target_review_number": idx + 2,
                    "labeling_method": lbl_ev.get("transition_type", "commit_diff_verified"),
                    "dataset_version": PROJECT_REVIEW_DATASET_VERSION,
                },
                language_group=infer_language_group(current["snapshot"]),
                size_bucket=infer_size_bucket(current["snapshot"]),
            )
        )
    return observations


def serialize_observation(obs: Observation) -> dict[str, Any]:
    """Serialize an Observation to a JSON-compatible dictionary."""
    return {
        "project_id": obs.project_id,
        "review_id": obs.review_id,
        "review_number": obs.review_number,
        "timestamp": obs.timestamp,
        "features": {k: round(float(v), 8) for k, v in sorted(obs.features.items())},
        "target": obs.target,
        "previous_category": obs.previous_category,
        "target_review_id": obs.target_review_id,
        "target_timestamp": obs.target_timestamp,
        "feature_review_ids": list(obs.feature_review_ids),
        "feature_max_timestamp": obs.feature_max_timestamp,
        "repository_group": obs.repository_group,
        "is_synthetic": obs.is_synthetic,
        "data_category": obs.data_category,
        "label_confidence": obs.label_confidence,
        "label_evidence": obs.label_evidence,
        "provenance": obs.provenance,
        "language_group": obs.language_group,
        "size_bucket": obs.size_bucket,
        "feature_hash": obs.feature_hash,
    }


def deserialize_observation(row: dict[str, Any]) -> Observation:
    """Deserialize an Observation from a JSON dictionary."""
    return Observation(
        project_id=int(row["project_id"]),
        review_id=int(row["review_id"]),
        review_number=int(row["review_number"]),
        timestamp=str(row["timestamp"]),
        features={str(k): float(v) for k, v in dict(row["features"]).items()},
        target=str(row["target"]),
        previous_category=row.get("previous_category"),
        target_review_id=int(row["target_review_id"]) if row.get("target_review_id") is not None else None,
        target_timestamp=row.get("target_timestamp"),
        feature_review_ids=tuple(int(x) for x in (row.get("feature_review_ids") or [])),
        feature_max_timestamp=row.get("feature_max_timestamp"),
        repository_group=str(row.get("repository_group") or ""),
        is_synthetic=bool(row.get("is_synthetic", False)),
        data_category=str(row.get("data_category") or DATA_CATEGORY_HISTORICAL_TRANSITION),
        label_confidence=float(row.get("label_confidence", 0.7)),
        label_evidence=dict(row.get("label_evidence") or {}),
        provenance=dict(row.get("provenance") or {}),
        language_group=str(row.get("language_group") or "unknown"),
        size_bucket=str(row.get("size_bucket") or "small"),
    )


def run_ingestion_pipeline(
    config: IngestionConfig | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Execute the 16-stage repository collection & dataset generation pipeline."""
    cfg = config or IngestionConfig()
    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    search_roots = list(cfg.local_search_roots)
    if not search_roots:
        workspace_root = Path(__file__).resolve().parents[3]
        projects_dir = workspace_root.parent.parent
        if projects_dir.exists() and projects_dir.name.lower() == "projects":
            search_roots.append(str(projects_dir))
        elif workspace_root.parent.exists():
            search_roots.append(str(workspace_root.parent))
        else:
            search_roots.append(str(workspace_root))

    started_at = datetime.now(timezone.utc).isoformat()
    candidate_paths = discover_local_git_repositories(search_roots, max_depth=3)

    repository_manifest: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    all_observations: list[Observation] = []
    seen_repo_groups: set[str] = set()
    seen_root_shas: set[str] = set()
    total_secret_redactions = 0

    for idx, repo_path in enumerate(candidate_paths, start=1000):
        repo_name = repo_path.name
        if is_synthetic_project_record(repo_name, str(repo_path)):
            exclusions.append(
                {
                    "repository_name": repo_name,
                    "repository_path": str(repo_path),
                    "stage": "synthetic_filter",
                    "reason": "Synthetic or temporary test directory excluded from real dataset.",
                }
            )
            continue

        repo_group = canonical_repository_group(idx, repo_name, str(repo_path))
        if repo_group in seen_repo_groups:
            exclusions.append(
                {
                    "repository_name": repo_name,
                    "repository_path": str(repo_path),
                    "stage": "duplicate_detection",
                    "reason": f"Duplicate canonical repository group '{repo_group}'.",
                }
            )
            continue

        license_info = detect_repository_license(
            repo_path, is_local_authorized=cfg.allow_local_authorized_repos
        )
        if not license_info.get("eligible", False):
            exclusions.append(
                {
                    "repository_name": repo_name,
                    "repository_path": str(repo_path),
                    "stage": "license_check",
                    "reason": f"Ineligible license: {license_info.get('spdx_id')}",
                }
            )
            continue

        commits = _get_git_commits(repo_path, max_snapshots=cfg.max_snapshots_per_repo)
        if len(commits) < cfg.min_commits:
            exclusions.append(
                {
                    "repository_name": repo_name,
                    "repository_path": str(repo_path),
                    "stage": "activity_history_check",
                    "reason": f"Insufficient commit history ({len(commits)} commits < minimum {cfg.min_commits}).",
                }
            )
            continue

        root_sha = commits[0]["sha"]
        if root_sha in seen_root_shas:
            exclusions.append(
                {
                    "repository_name": repo_name,
                    "repository_path": str(repo_path),
                    "stage": "duplicate_detection",
                    "reason": f"Duplicate root commit SHA {root_sha[:12]} (fork or clone).",
                }
            )
            continue

        seen_repo_groups.add(repo_group)
        seen_root_shas.add(root_sha)

        snapshots: list[dict[str, Any]] = []
        prev_c: dict[str, Any] | None = None
        for c in commits:
            snap = _inspect_commit_snapshot(repo_path, c, prev_c)
            total_secret_redactions += int(snap.get("secret_redactions", 0))
            snapshots.append(snap)
            prev_c = c

        repo_obs = build_observations_from_git_snapshots(
            repo_id=idx,
            repo_name=repo_name,
            repo_path=str(repo_path),
            repo_group=repo_group,
            license_info=license_info,
            snapshots=snapshots,
        )
        all_observations.extend(repo_obs)

        last_snap = snapshots[-1]["snapshot"] if snapshots else {}
        repository_manifest.append(
            {
                "repository_id": idx,
                "repository_name": repo_name,
                "repository_group": repo_group,
                "repository_path": str(repo_path),
                "source_type": "local_git_repository",
                "license": license_info,
                "commit_count_sampled": len(commits),
                "first_commit_sha": commits[0]["sha"],
                "latest_commit_sha": commits[-1]["sha"],
                "first_commit_at": commits[0]["committed_at"],
                "latest_commit_at": commits[-1]["committed_at"],
                "language_mix": last_snap.get("language_mix", {}),
                "file_count": last_snap.get("file_count", 0),
                "observations_generated": len(repo_obs),
            }
        )

    if session is not None:
        db_curated = build_curated_observations(
            session,
            exclude_synthetic=True,
            primary_target_only=True,
            deduplicate=True,
        )
        all_observations.extend(db_curated)

    all_observations.sort(key=lambda o: (o.timestamp, o.project_id, o.review_number))
    deduped_observations: list[Observation] = []
    seen_ft: set[tuple[str, str]] = set()
    duplicate_obs_removed = 0
    for obs in all_observations:
        key = (obs.feature_hash, obs.target)
        if key in seen_ft:
            duplicate_obs_removed += 1
            continue
        seen_ft.add(key)
        deduped_observations.append(obs)

    version_tag = cfg.dataset_version
    manifest_path = out_dir / "repository_manifest.jsonl"
    dataset_path = out_dir / f"dataset_{version_tag}.jsonl"
    metadata_path = out_dir / f"dataset_{version_tag}_metadata.json"
    exclusions_path = out_dir / f"exclusions_{version_tag}.json"
    status_path = out_dir / "ingestion_status.json"

    with manifest_path.open("w", encoding="utf-8") as fh:
        for entry in repository_manifest:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")

    with dataset_path.open("w", encoding="utf-8") as fh:
        for obs in deduped_observations:
            fh.write(json.dumps(serialize_observation(obs), sort_keys=True) + "\n")

    category_dist = Counter(obs.target for obs in deduped_observations)
    confidence_dist = {
        "high_gte_0_8": sum(1 for o in deduped_observations if o.label_confidence >= 0.8),
        "medium_0_5_to_0_8": sum(1 for o in deduped_observations if 0.5 <= o.label_confidence < 0.8),
        "low_lt_0_5": sum(1 for o in deduped_observations if o.label_confidence < 0.5),
    }
    lang_dist = Counter(obs.language_group for obs in deduped_observations)
    data_cat_dist = Counter(obs.data_category for obs in deduped_observations)
    repo_groups_in_dataset = sorted({obs.repository_group for obs in deduped_observations})

    dataset_sha256 = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    completed_at = datetime.now(timezone.utc).isoformat()

    metadata_payload = {
        "dataset_version": version_tag,
        "schema_version": PROJECT_REVIEW_DATASET_VERSION,
        "status": "READY" if len(deduped_observations) >= 10 else "INSUFFICIENT_OBSERVATIONS",
        "started_at": started_at,
        "completed_at": completed_at,
        "target_repository_count": cfg.target_repository_count,
        "supported_collection_targets": list(SUPPORTED_COLLECTION_TARGETS),
        "discovered_git_repositories": len(candidate_paths),
        "eligible_git_repositories": len(repository_manifest),
        "distinct_repository_groups_in_dataset": len(repo_groups_in_dataset),
        "repository_groups": repo_groups_in_dataset,
        "raw_observations_generated": len(all_observations),
        "duplicate_observations_removed": duplicate_obs_removed,
        "curated_observations_count": len(deduped_observations),
        "distinct_failure_categories": len(category_dist),
        "category_distribution": dict(sorted(category_dist.items())),
        "data_category_distribution": dict(sorted(data_cat_dist.items())),
        "label_confidence_distribution": confidence_dist,
        "language_distribution": dict(sorted(lang_dist.items())),
        "secret_redactions_applied": total_secret_redactions,
        "exclusions_count": len(exclusions),
        "dataset_sha256": dataset_sha256,
        "artifacts": {
            "repository_manifest": str(manifest_path),
            "dataset_jsonl": str(dataset_path),
            "exclusions_json": str(exclusions_path),
        },
    }

    metadata_path.write_text(json.dumps(metadata_payload, indent=2, sort_keys=True), encoding="utf-8")
    exclusions_path.write_text(
        json.dumps(
            {
                "dataset_version": version_tag,
                "generated_at": completed_at,
                "total_excluded": len(exclusions),
                "exclusions": exclusions,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    status_path.write_text(json.dumps(metadata_payload, indent=2, sort_keys=True), encoding="utf-8")
    return metadata_payload


def load_ingested_dataset(
    dataset_version: str = "v001",
    output_dir: Path | None = None,
) -> list[Observation]:
    """Load persisted curated Observation records from ``dataset_<version>.jsonl``."""
    base_dir = Path(output_dir) if output_dir else DATASETS_ARTIFACT_DIR
    dataset_path = base_dir / f"dataset_{dataset_version}.jsonl"
    if not dataset_path.is_file():
        return []
    observations: list[Observation] = []
    for line in dataset_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        observations.append(deserialize_observation(row))
    return observations


def get_ingestion_status(output_dir: Path | None = None) -> dict[str, Any]:
    """Return the latest persisted ingestion status or an empty state summary."""
    base_dir = Path(output_dir) if output_dir else DATASETS_ARTIFACT_DIR
    status_path = base_dir / "ingestion_status.json"
    if status_path.is_file():
        try:
            return json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "dataset_version": "none",
        "curated_observations_count": 0,
        "eligible_git_repositories": 0,
        "distinct_repository_groups_in_dataset": 0,
        "supported_collection_targets": list(SUPPORTED_COLLECTION_TARGETS),
        "status": "not_run",
    }
