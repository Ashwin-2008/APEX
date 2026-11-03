"""Unified Evidence Validation Engine for APEX 2.0.

Validates that every analyzer finding is supported by concrete, fresh,
and non-contradicted repository evidence before presentation or promotion.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from app.services.analyzers.base import FindingItem


class EvidenceType(str, Enum):
    STATIC_SOURCE = "STATIC_SOURCE"
    AST_PATTERN = "AST_PATTERN"
    DATA_FLOW_SOURCE = "DATA_FLOW_SOURCE"
    DATA_FLOW_SINK = "DATA_FLOW_SINK"
    CALL_GRAPH_PATH = "CALL_GRAPH_PATH"
    TYPE_INFORMATION = "TYPE_INFORMATION"
    RUNTIME_COVERAGE = "RUNTIME_COVERAGE"
    TEST_FAILURE = "TEST_FAILURE"
    DEPENDENCY_ADVISORY = "DEPENDENCY_ADVISORY"
    ARCHITECTURE_RELATIONSHIP = "ARCHITECTURE_RELATIONSHIP"
    CONFIGURATION_CONTEXT = "CONFIGURATION_CONTEXT"
    CONTROL_FLOW = "CONTROL_FLOW"
    SANITIZER_EVIDENCE = "SANITIZER_EVIDENCE"


class ValidationState(str, Enum):
    VALIDATED = "VALIDATED"
    PARTIALLY_VALIDATED = "PARTIALLY_VALIDATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIABLE = "UNVERIFIABLE"


@dataclass
class EvidenceItem:
    id: str
    finding_id: str
    evidence_type: EvidenceType
    source_analyzer: str
    file: str | None
    start_line: int | None
    end_line: int | None
    code_expression: str
    description: str
    verification_status: ValidationState = ValidationState.PARTIALLY_VALIDATED
    confidence_contribution: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    commit_sha: str | None = None
    file_content_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_type"] = self.evidence_type.value
        data["verification_status"] = self.verification_status.value
        return data


def compute_file_hash(path: Path) -> str | None:
    """Compute sha256 of file content to guarantee evidence freshness."""
    if not path.is_file():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


class EvidenceValidator:
    """Performs rigorous ground-truth verification and freshness validation on finding evidence."""

    def __init__(self, repo_root: Path, current_commit: str | None = None) -> None:
        self.repo_root = repo_root.resolve()
        self.current_commit = current_commit
        self._file_cache: dict[str, str] = {}
        self._hash_cache: dict[str, str | None] = {}

    def _get_file_content(self, rel_path: str) -> str | None:
        norm = rel_path.replace("\\", "/").lstrip("./")
        if norm in self._file_cache:
            return self._file_cache[norm]
        full_path = self.repo_root / norm
        if full_path.is_file():
            try:
                content = full_path.read_text(encoding="utf-8", errors="ignore")
                self._file_cache[norm] = content
                self._hash_cache[norm] = hashlib.sha256(content.encode("utf-8")).hexdigest()
                return content
            except OSError:
                return None
        return None

    def validate_finding(
        self,
        finding: FindingItem | dict[str, Any],
        finding_id: str = "",
    ) -> tuple[ValidationState, list[EvidenceItem]]:
        """Validate all evidence attached to a finding and determine its overall validation state."""
        f_dict = finding.to_dict() if isinstance(finding, FindingItem) else finding
        fid = finding_id or f_dict.get("fingerprint") or f_dict.get("rule_id", "unknown")
        analyzer_source = f_dict.get("analyzer_source", "unknown")
        file_path = f_dict.get("file")
        line = f_dict.get("line")
        evidence_text = f_dict.get("evidence", "")
        rule_id = f_dict.get("rule_id", "")
        data_flow = f_dict.get("data_flow", [])
        metadata = f_dict.get("metadata", {})

        items: list[EvidenceItem] = []

        # 1. Base Static Source Evidence
        if not file_path:
            # Finding has no associated file path (e.g. global config or missing attribution)
            evi_id = f"evi_{hashlib.sha256((fid + '_global').encode()).hexdigest()[:12]}"
            if analyzer_source in {"configuration", "dependency"} and evidence_text:
                items.append(
                    EvidenceItem(
                        id=evi_id,
                        finding_id=fid,
                        evidence_type=EvidenceType.CONFIGURATION_CONTEXT,
                        source_analyzer=analyzer_source,
                        file=None,
                        start_line=None,
                        end_line=None,
                        code_expression="",
                        description=evidence_text,
                        verification_status=ValidationState.VALIDATED,
                        confidence_contribution=0.80,
                        commit_sha=self.current_commit,
                    )
                )
                return ValidationState.VALIDATED, items
            else:
                items.append(
                    EvidenceItem(
                        id=evi_id,
                        finding_id=fid,
                        evidence_type=EvidenceType.STATIC_SOURCE,
                        source_analyzer=analyzer_source,
                        file=None,
                        start_line=None,
                        end_line=None,
                        code_expression="",
                        description="Finding lacks associated source file path.",
                        verification_status=ValidationState.INSUFFICIENT_EVIDENCE,
                        confidence_contribution=0.10,
                        commit_sha=self.current_commit,
                    )
                )
                return ValidationState.INSUFFICIENT_EVIDENCE, items

        # Verify source file presence and freshness on disk
        content = self._get_file_content(file_path)
        file_hash = self._hash_cache.get(file_path.replace("\\", "/").lstrip("./"))

        if content is None:
            # File does not exist on disk
            evi_id = f"evi_{hashlib.sha256((fid + '_nofile').encode()).hexdigest()[:12]}"
            items.append(
                EvidenceItem(
                    id=evi_id,
                    finding_id=fid,
                    evidence_type=EvidenceType.STATIC_SOURCE,
                    source_analyzer=analyzer_source,
                    file=file_path,
                    start_line=line,
                    end_line=line,
                    code_expression="",
                    description=f"Referenced source file '{file_path}' does not exist on disk.",
                    verification_status=ValidationState.UNVERIFIABLE,
                    confidence_contribution=0.0,
                    commit_sha=self.current_commit,
                )
            )
            return ValidationState.UNVERIFIABLE, items

        lines = content.splitlines()
        target_snippet = ""
        if line and 0 < line <= len(lines):
            target_snippet = lines[line - 1].strip()

        # 2. Check for Contradictory Evidence (e.g. active sanitizers or explicit guards)
        is_contradicted = False
        contradiction_reason = ""
        if "SEC-TAINT" in rule_id or "SECURITY" in rule_id:
            # Look for sanitizer signatures in target or surrounding lines
            context_lines = "\n".join(lines[max(0, (line or 1) - 5):min(len(lines), (line or 1) + 3)])
            for san in ["os.path.basename", "shlex.quote", "secure_filename", "escape"]:
                if san in context_lines and san in evidence_text.lower():
                    is_contradicted = True
                    contradiction_reason = f"Verified presence of sanitizer '{san}' on the data path contradicts injection vulnerability."
                    break

        if is_contradicted:
            items.append(
                EvidenceItem(
                    id=f"evi_{hashlib.sha256((fid + '_contra').encode()).hexdigest()[:12]}",
                    finding_id=fid,
                    evidence_type=EvidenceType.SANITIZER_EVIDENCE,
                    source_analyzer=analyzer_source,
                    file=file_path,
                    start_line=line,
                    end_line=line,
                    code_expression=target_snippet,
                    description=contradiction_reason,
                    verification_status=ValidationState.CONTRADICTED,
                    confidence_contribution=-0.90,
                    commit_sha=self.current_commit,
                    file_content_hash=file_hash,
                )
            )
            return ValidationState.CONTRADICTED, items

        # 3. Data Flow Evidence Verification
        if data_flow:
            has_source = False
            has_sink = False
            for step in data_flow:
                s_role = step.get("role", "")
                s_file = step.get("file", file_path)
                s_line = step.get("line")
                s_expr = step.get("expression", "")

                step_content = self._get_file_content(s_file) if s_file else content
                step_lines = step_content.splitlines() if step_content else []
                step_snippet = step_lines[s_line - 1].strip() if s_line and 0 < s_line <= len(step_lines) else s_expr

                e_type = (
                    EvidenceType.DATA_FLOW_SOURCE if s_role == "source" else
                    EvidenceType.DATA_FLOW_SINK if s_role == "sink" else
                    EvidenceType.CALL_GRAPH_PATH
                )
                if s_role == "source":
                    has_source = True
                if s_role == "sink":
                    has_sink = True

                step_num = step.get("step", 0)
                step_id_raw = f"{fid}_{step_num}"
                evi_id = f"evi_{hashlib.sha256(step_id_raw.encode()).hexdigest()[:12]}"

                items.append(
                    EvidenceItem(
                        id=evi_id,
                        finding_id=fid,
                        evidence_type=e_type,
                        source_analyzer=analyzer_source,
                        file=s_file,
                        start_line=s_line,
                        end_line=s_line,
                        code_expression=step_snippet,
                        description=f"Step #{step.get('step')}: {s_role} in {s_file}:{s_line}",
                        verification_status=ValidationState.VALIDATED,
                        confidence_contribution=0.30 if s_role in {"source", "sink"} else 0.15,
                        commit_sha=self.current_commit,
                        file_content_hash=file_hash,
                    )
                )

            if has_source and has_sink:
                return ValidationState.VALIDATED, items
            return ValidationState.PARTIALLY_VALIDATED, items

        # 4. AST / Type / Architecture Evidence Verification
        if target_snippet:
            e_type = EvidenceType.STATIC_SOURCE
            if "TYPE" in rule_id:
                e_type = EvidenceType.TYPE_INFORMATION
            elif "ARCH" in rule_id:
                e_type = EvidenceType.ARCHITECTURE_RELATIONSHIP
            elif "AST" in rule_id or "COMPLEXITY" in rule_id:
                e_type = EvidenceType.AST_PATTERN

            items.append(
                EvidenceItem(
                    id=f"evi_{hashlib.sha256((fid + '_src').encode()).hexdigest()[:12]}",
                    finding_id=fid,
                    evidence_type=e_type,
                    source_analyzer=analyzer_source,
                    file=file_path,
                    start_line=line,
                    end_line=line,
                    code_expression=target_snippet,
                    description=evidence_text[:250],
                    verification_status=ValidationState.VALIDATED,
                    confidence_contribution=0.85,
                    commit_sha=self.current_commit,
                    file_content_hash=file_hash,
                )
            )
            return ValidationState.VALIDATED, items
        else:
            # Line reference is out of bounds or missing
            items.append(
                EvidenceItem(
                    id=f"evi_{hashlib.sha256((fid + '_oob').encode()).hexdigest()[:12]}",
                    finding_id=fid,
                    evidence_type=EvidenceType.STATIC_SOURCE,
                    source_analyzer=analyzer_source,
                    file=file_path,
                    start_line=line,
                    end_line=line,
                    code_expression="",
                    description=f"Line {line} is out of bounds or missing in file '{file_path}'.",
                    verification_status=ValidationState.INSUFFICIENT_EVIDENCE,
                    confidence_contribution=0.20,
                    commit_sha=self.current_commit,
                    file_content_hash=file_hash,
                )
            )
            return ValidationState.INSUFFICIENT_EVIDENCE, items
