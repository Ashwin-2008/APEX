"""Root Cause Analysis Engine for APEX 2.0.

Identifies the fundamental engineering defect underlying multiple symptomatic
findings across security, architecture, type-safety, and testing domains.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from app.services.analyzers.base import FindingItem


class RootCauseCategory(str, Enum):
    UNSAFE_INPUT_HANDLING = "UNSAFE_INPUT_HANDLING"
    AUTHENTICATION_WEAKNESS = "AUTHENTICATION_WEAKNESS"
    AUTHORIZATION_FAILURE = "AUTHORIZATION_FAILURE"
    RESOURCE_LIFECYCLE_ERROR = "RESOURCE_LIFECYCLE_ERROR"
    CONCURRENCY_DESIGN_ERROR = "CONCURRENCY_DESIGN_ERROR"
    ARCHITECTURAL_COUPLING = "ARCHITECTURAL_COUPLING"
    DEPENDENCY_RISK = "DEPENDENCY_RISK"
    CONFIGURATION_MISMANAGEMENT = "CONFIGURATION_MISMANAGEMENT"
    ERROR_HANDLING_DEFECT = "ERROR_HANDLING_DEFECT"
    TESTING_GAP = "TESTING_GAP"
    TYPE_SAFETY_DEFECT = "TYPE_SAFETY_DEFECT"


@dataclass
class RootCauseItem:
    id: str
    category: RootCauseCategory
    title: str
    primary_finding_id: str
    related_finding_ids: list[str] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    affected_functions: list[str] = field(default_factory=list)
    supporting_evidence: list[str] = field(default_factory=list)
    confidence: float = 0.85
    impact: str = "High risk to system stability or security."
    recommended_remediation: str = ""
    verification_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["category"] = self.category.value
        return data


class RootCauseAnalyzer:
    """Analyzes clustered finding relationships to synthesize root cause hypotheses."""

    @staticmethod
    def analyze(findings: list[FindingItem | dict[str, Any]]) -> list[RootCauseItem]:
        normalized: list[dict[str, Any]] = [
            f.to_dict() if isinstance(f, FindingItem) else dict(f) for f in findings
        ]

        # Group findings by affected component/file and thematic category
        by_file_and_theme: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for f in normalized:
            file_key = (f.get("file") or "global").replace("\\", "/").lower()
            cat = (f.get("category") or "general").lower()

            # Determine theme
            theme = "other"
            rule = (f.get("rule_id") or "").upper()
            if "SEC" in rule or "SQL" in rule or "INJECTION" in rule or "TAINT" in rule:
                theme = "input_security"
            elif "AUTH" in rule:
                theme = "authentication"
            elif "RESOURCE" in rule or "LEAK" in rule:
                theme = "resource"
            elif "ASYNC" in rule or "CONCURRENCY" in rule or "LOCK" in rule:
                theme = "concurrency"
            elif "ARCH" in rule or "CYCLE" in rule:
                theme = "architecture"
            elif "TYPE" in rule or "OPTIONAL" in rule:
                theme = "type_safety"
            elif "TEST" in rule or "COVERAGE" in rule:
                theme = "testing"

            group_key = f"{file_key}::{theme}"
            by_file_and_theme[group_key].append(f)

        root_causes: list[RootCauseItem] = []

        for group_key, items in by_file_and_theme.items():
            if not items:
                continue

            file_part, theme_part = group_key.split("::", 1)
            primary = max(items, key=lambda x: (x.get("severity") == "critical", x.get("severity") == "high", x.get("confidence", 0)))
            p_id = primary.get("fingerprint") or primary.get("rule_id", "p0")
            related_ids = [it.get("fingerprint") or it.get("rule_id", "") for it in items if (it.get("fingerprint") or it.get("rule_id")) != p_id]
            all_files = sorted(list({it.get("file") for it in items if it.get("file")}))

            if theme_part == "input_security":
                rc = RootCauseItem(
                    id=f"rc_input_{hashlib.sha256(group_key.encode()).hexdigest()[:8]}",
                    category=RootCauseCategory.UNSAFE_INPUT_HANDLING,
                    title=f"Unsafe Input Handling in {file_part or 'API Controller'}",
                    primary_finding_id=p_id,
                    related_finding_ids=related_ids,
                    affected_files=all_files,
                    affected_functions=[],
                    supporting_evidence=[it.get("evidence", "")[:200] for it in items],
                    confidence=0.90,
                    impact="Allows untrusted external parameters to reach sensitive execution sinks, risking injection or data tampering.",
                    recommended_remediation="Implement strict Pydantic/type validation schemas at route entry points and use parameterized execution.",
                    verification_steps=["Run security taint analysis", "Execute integration test with adversarial payload"],
                )
                root_causes.append(rc)

            elif theme_part == "concurrency":
                rc = RootCauseItem(
                    id=f"rc_conc_{hashlib.sha256(group_key.encode()).hexdigest()[:8]}",
                    category=RootCauseCategory.CONCURRENCY_DESIGN_ERROR,
                    title=f"Asynchronous Execution and Concurrency Risk in {file_part}",
                    primary_finding_id=p_id,
                    related_finding_ids=related_ids,
                    affected_files=all_files,
                    affected_functions=[],
                    supporting_evidence=[it.get("evidence", "")[:200] for it in items],
                    confidence=0.88,
                    impact="Blocks the asynchronous event loop or causes race conditions on shared memory under concurrent load.",
                    recommended_remediation="Replace blocking synchronous operations with non-blocking async equivalents and protect shared state with asyncio.Lock.",
                    verification_steps=["Run concurrency stress tests", "Profile event loop latency"],
                )
                root_causes.append(rc)

            elif theme_part == "resource":
                rc = RootCauseItem(
                    id=f"rc_res_{hashlib.sha256(group_key.encode()).hexdigest()[:8]}",
                    category=RootCauseCategory.RESOURCE_LIFECYCLE_ERROR,
                    title=f"Improper Resource Lifecycle Management in {file_part}",
                    primary_finding_id=p_id,
                    related_finding_ids=related_ids,
                    affected_files=all_files,
                    affected_functions=[],
                    supporting_evidence=[it.get("evidence", "")[:200] for it in items],
                    confidence=0.87,
                    impact="Exhausts operating system file descriptors or connection pools during high throughput.",
                    recommended_remediation="Enclose resource allocations in context managers ('with' blocks) or finally clauses.",
                    verification_steps=["Run resource leak detector", "Verify handle closure under test"],
                )
                root_causes.append(rc)

            elif theme_part == "type_safety":
                rc = RootCauseItem(
                    id=f"rc_type_{hashlib.sha256(group_key.encode()).hexdigest()[:8]}",
                    category=RootCauseCategory.TYPE_SAFETY_DEFECT,
                    title=f"Missing Nullability Safety and Type Verification in {file_part}",
                    primary_finding_id=p_id,
                    related_finding_ids=related_ids,
                    affected_files=all_files,
                    affected_functions=[],
                    supporting_evidence=[it.get("evidence", "")[:200] for it in items],
                    confidence=0.85,
                    impact="Can trigger uncaught AttributeError / TypeError crashes when null or unexpected types are encountered at runtime.",
                    recommended_remediation="Add explicit None-guards ('if var is not None:') before dereferencing optional values.",
                    verification_steps=["Run type intelligence analysis", "Execute unit tests with None input"],
                )
                root_causes.append(rc)

            elif theme_part == "architecture":
                rc = RootCauseItem(
                    id=f"rc_arch_{hashlib.sha256(group_key.encode()).hexdigest()[:8]}",
                    category=RootCauseCategory.ARCHITECTURAL_COUPLING,
                    title=f"Tight Architectural Coupling and Circular Dependency in {file_part}",
                    primary_finding_id=p_id,
                    related_finding_ids=related_ids,
                    affected_files=all_files,
                    affected_functions=[],
                    supporting_evidence=[it.get("evidence", "")[:200] for it in items],
                    confidence=0.92,
                    impact="Prevents modular compilation, creates hidden runtime import race conditions, and impedes maintainability.",
                    recommended_remediation="Refactor shared abstractions into a common lower layer or inject dependencies via interfaces.",
                    verification_steps=["Run architecture dependency graph analysis", "Verify acyclic directed graph"],
                )
                root_causes.append(rc)

        return root_causes

