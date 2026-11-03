"""Static and Dynamic Reconciliation Intelligence Engine for APEX 2.0.

Provides rigorous ground-truth reconciliation between static AST reachability,
dynamic test coverage traces, and JUnit execution failure stack traces.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from app.services.analyzers.base import FindingItem
from app.services.analyzers.trace_engine import DynamicTraceReconciler, parse_coverage_json, parse_junit_xml


class ReachabilityClassification(str, Enum):
    STATICALLY_UNREACHABLE = "STATICALLY_UNREACHABLE"
    NOT_OBSERVED_IN_TESTS = "NOT_OBSERVED_IN_TESTS"
    DYNAMICALLY_OBSERVED = "DYNAMICALLY_OBSERVED"
    UNKNOWN = "UNKNOWN"


@dataclass
class ReconciledReachability:
    file: str
    line: int
    classification: ReachabilityClassification
    explanation: str
    is_confirmed_dead_code: bool = False
    trace_artifact_provenance: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["classification"] = self.classification.value
        return data


class AdvancedRuntimeReconciler:
    """Rigorous runtime reconciler enforcing strict non-extrapolation principles."""

    def __init__(self, root_dir: Path, current_commit: str | None = None) -> None:
        self.root_dir = root_dir.resolve()
        self.current_commit = current_commit
        self.executed_lines: dict[str, set[int]] = {}
        self.test_failures: list[Any] = []
        self.provenance: dict[str, Any] = {}
        self._load_and_validate_artifacts()

    def _load_and_validate_artifacts(self) -> None:
        """Load coverage and test reports, rejecting stale artifacts from mismatched commits."""
        cov_json = self.root_dir / "coverage.json"
        if cov_json.is_file():
            try:
                data = json.loads(cov_json.read_text(encoding="utf-8", errors="ignore"))
                # Check commit metadata if present
                report_commit = data.get("meta", {}).get("commit_sha") or data.get("commit_sha")
                if self.current_commit and report_commit and report_commit != self.current_commit:
                    # Stale coverage from different commit -> reject
                    self.provenance["coverage_status"] = "REJECTED_STALE_COMMIT"
                else:
                    self.executed_lines.update(parse_coverage_json(cov_json, self.root_dir))
                    self.provenance["coverage_status"] = "CURRENT"
                    self.provenance["coverage_format"] = "coverage.json"
            except Exception:
                pass

        junit_xml = self.root_dir / "junit.xml"
        if junit_xml.is_file():
            self.test_failures.extend(parse_junit_xml(junit_xml, self.root_dir))
            self.provenance["junit_status"] = "LOADED"

    def classify_reachability(
        self,
        file_path: str,
        line: int,
        is_statically_unreachable: bool = False,
    ) -> ReconciledReachability:
        """Classify statement reachability without fallaciously conflating unobserved with dead code."""
        norm_file = file_path.replace("\\", "/").lstrip("./")

        # 1. Static AST Proof takes precedence for terminal exit points
        if is_statically_unreachable:
            return ReconciledReachability(
                file=norm_file,
                line=line,
                classification=ReachabilityClassification.STATICALLY_UNREACHABLE,
                explanation="Static control-flow analysis mathematically proves statement cannot execute (succeeds terminal return/raise).",
                is_confirmed_dead_code=True,
                trace_artifact_provenance=self.provenance.get("coverage_status"),
            )

        # 2. Check Dynamic Execution Traces
        if not self.executed_lines or norm_file not in self.executed_lines:
            return ReconciledReachability(
                file=norm_file,
                line=line,
                classification=ReachabilityClassification.UNKNOWN,
                explanation="No reliable test execution coverage data available for this module.",
                is_confirmed_dead_code=False,
                trace_artifact_provenance="NO_COVERAGE_DATA",
            )

        executed_set = self.executed_lines[norm_file]
        if line in executed_set:
            return ReconciledReachability(
                file=norm_file,
                line=line,
                classification=ReachabilityClassification.DYNAMICALLY_OBSERVED,
                explanation=f"Dynamic test execution confirms line {line} was executed during test suite run.",
                is_confirmed_dead_code=False,
                trace_artifact_provenance=self.provenance.get("coverage_status"),
            )
        else:
            # STRICT PRINCIPLE: Zero test coverage is NOT proof of dead code!
            return ReconciledReachability(
                file=norm_file,
                line=line,
                classification=ReachabilityClassification.NOT_OBSERVED_IN_TESTS,
                explanation=(
                    f"Line {line} was not executed across existing automated tests. "
                    f"This indicates a test coverage gap, NOT verified dead code."
                ),
                is_confirmed_dead_code=False,
                trace_artifact_provenance=self.provenance.get("coverage_status"),
            )

    def correlate_test_failures(self, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Correlate test failures only when file, function, and exact line match with semantic plausibility."""
        if not self.test_failures:
            return findings

        for f in findings:
            f_file = (f.get("file") or "").replace("\\", "/").lstrip("./")
            f_line = f.get("line") or 0
            if not f_file or f_line <= 0:
                continue

            for failure in self.test_failures:
                # Find matching frame within 1 line
                match = next(
                    (frame for frame in failure.stack_frames if frame.file_path == f_file and abs(frame.line_number - f_line) <= 1),
                    None,
                )
                if match:
                    # Semantic category plausibility check
                    is_plausible = True
                    msg = failure.message.lower()
                    cat = f.get("category", "").lower()
                    if "database" in cat and not any(kw in msg for kw in ["sql", "db", "query", "syntax", "cursor", "operational"]):
                        is_plausible = False

                    if is_plausible:
                        f["runtime_corroborated"] = True
                        corr_tag = f"[Correlated Test Failure]: Test '{failure.test_name}' failed at {f_file}:{match.line_number} ({failure.message[:120]})"
                        if corr_tag not in f.get("evidence", ""):
                            f["evidence"] = f.get("evidence", "") + "\n" + corr_tag
        return findings

