"""Regression Intelligence and Commit Attribution Engine for APEX 2.0.

Tracks finding evolution across repository revisions, identifies regressions,
and correlates newly introduced or reopened defects with Git commits.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class RegressionClassification(str, Enum):
    NEW_REGRESSION = "NEW_REGRESSION"
    REOPENED_REGRESSION = "REOPENED_REGRESSION"
    EXISTING_ISSUE = "EXISTING_ISSUE"
    RESOLVED = "RESOLVED"
    SUPPRESSED = "SUPPRESSED"
    UNCONFIRMED_CHANGE = "UNCONFIRMED_CHANGE"


@dataclass
class RegressionItem:
    finding_fingerprint: str
    category: str
    severity: str
    file: str | None
    line: int | None
    classification: RegressionClassification
    introduced_commit: str | None = None
    resolved_commit: str | None = None
    review_span: int = 1
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["classification"] = self.classification.value
        return data


class RegressionTracker:
    """Compares current findings against prior historical reviews to identify regressions."""

    @staticmethod
    def evaluate_regressions(
        current_findings: list[dict[str, Any]],
        historical_findings: list[dict[str, Any]],
        current_commit: str | None = None,
    ) -> list[RegressionItem]:
        # Map historical findings by fingerprint: fp -> finding dict
        hist_map: dict[str, dict[str, Any]] = {}
        for h in historical_findings:
            fp = h.get("fingerprint")
            if fp:
                hist_map[fp] = h

        current_fps = set()
        items: list[RegressionItem] = []

        # 1. Process current findings
        for cur in current_findings:
            fp = cur.get("fingerprint") or hashlib.sha256(
                f"{cur.get('analyzer_source')}:{cur.get('rule_id')}:{cur.get('file')}:{cur.get('line')}".encode()
            ).hexdigest()
            current_fps.add(fp)

            if cur.get("suppressed"):
                items.append(
                    RegressionItem(
                        finding_fingerprint=fp,
                        category=cur.get("category", "general"),
                        severity=cur.get("severity", "medium"),
                        file=cur.get("file"),
                        line=cur.get("line"),
                        classification=RegressionClassification.SUPPRESSED,
                        explanation="Finding is currently suppressed by engineer review.",
                    )
                )
                continue

            if fp not in hist_map:
                # Newly introduced finding
                items.append(
                    RegressionItem(
                        finding_fingerprint=fp,
                        category=cur.get("category", "general"),
                        severity=cur.get("severity", "medium"),
                        file=cur.get("file"),
                        line=cur.get("line"),
                        classification=RegressionClassification.NEW_REGRESSION,
                        introduced_commit=current_commit or "uncommitted_workspace",
                        explanation=f"New defect introduced in commit '{current_commit or 'working tree'}'.",
                    )
                )
            else:
                prev = hist_map[fp]
                prev_status = str(prev.get("status", "")).upper()
                if prev_status == "RESOLVED":
                    items.append(
                        RegressionItem(
                            finding_fingerprint=fp,
                            category=cur.get("category", "general"),
                            severity=cur.get("severity", "medium"),
                            file=cur.get("file"),
                            line=cur.get("line"),
                            classification=RegressionClassification.REOPENED_REGRESSION,
                            introduced_commit=current_commit,
                            explanation="Previously resolved issue has reappeared in current revision.",
                        )
                    )
                else:
                    items.append(
                        RegressionItem(
                            finding_fingerprint=fp,
                            category=cur.get("category", "general"),
                            severity=cur.get("severity", "medium"),
                            file=cur.get("file"),
                            line=cur.get("line"),
                            classification=RegressionClassification.EXISTING_ISSUE,
                            introduced_commit=prev.get("related_commit"),
                            explanation="Persistent defect unchanged from prior review.",
                        )
                    )

        # 2. Process resolved findings (present historically, but absent now)
        for fp, prev in hist_map.items():
            if fp not in current_fps and str(prev.get("status", "")).upper() != "RESOLVED":
                items.append(
                    RegressionItem(
                        finding_fingerprint=fp,
                        category=prev.get("category", "general"),
                        severity=prev.get("severity", "medium"),
                        file=prev.get("file"),
                        line=prev.get("line"),
                        classification=RegressionClassification.RESOLVED,
                        resolved_commit=current_commit,
                        explanation=f"Issue successfully resolved in revision '{current_commit or 'current'}'.",
                    )
                )

        return items

