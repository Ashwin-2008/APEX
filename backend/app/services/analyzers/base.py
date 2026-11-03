"""Base abstractions for APEX deterministic repository analyzers."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class AnalyzerStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    RUNNING = "RUNNING"
    PENDING = "PENDING"


@dataclass
class FindingItem:
    category: str
    severity: str  # critical, high, medium, low, info
    confidence: float
    evidence: str
    analyzer_source: str
    rule_id: str
    component: str | None = None
    file: str | None = None
    line: int | None = None
    end_line: int | None = None
    title: str | None = None
    remediation: str = "Investigate and add a regression test."
    data_flow: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence,
            "analyzer_source": self.analyzer_source,
            "rule_id": self.rule_id,
            "component": self.component,
            "file": self.file,
            "line": self.line,
            "end_line": self.end_line,
            "title": self.title or f"{self.category.replace('_', ' ').capitalize()} in {self.file or self.component or 'project'}",
            "remediation": self.remediation,
            "data_flow": self.data_flow,
            "metadata": self.metadata,
            "status": "open",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@dataclass
class AnalyzerOutput:
    analyzer_name: str
    status: AnalyzerStatus
    findings: list[FindingItem] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    error_message: str | None = None
    files_analyzed: int = 0
    files_skipped: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzer_name": self.analyzer_name,
            "status": self.status.value,
            "findings_count": len(self.findings),
            "findings": [f.to_dict() for f in self.findings],
            "metrics": self.metrics,
            "duration_ms": round(self.duration_ms, 2),
            "error_message": self.error_message,
            "files_analyzed": self.files_analyzed,
            "files_skipped": self.files_skipped,
        }

