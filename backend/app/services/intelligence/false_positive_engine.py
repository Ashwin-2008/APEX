"""False-Positive Intelligence and Auditable Review Feedback Engine for APEX 2.0.

Collects user review decisions under strict multi-tenant isolation, identifies
systemic rule false-positive patterns, and provides actionable rule improvement
suggestions without silently tampering with analyzer detection logic.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class ReviewClassification(str, Enum):
    CONFIRMED_TRUE_POSITIVE = "CONFIRMED_TRUE_POSITIVE"
    CONFIRMED_FALSE_POSITIVE = "CONFIRMED_FALSE_POSITIVE"
    ACCEPTED_RISK = "ACCEPTED_RISK"
    WONT_FIX = "WONT_FIX"
    NEEDS_INVESTIGATION = "NEEDS_INVESTIGATION"
    DUPLICATE_FINDING = "DUPLICATE_FINDING"


@dataclass
class ReviewFeedbackItem:
    feedback_id: str
    finding_id: str
    project_id: int
    user_id: int
    rule_id: str
    analyzer_source: str
    file: str | None
    evidence_snippet: str
    classification: ReviewClassification
    justification: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    commit_sha: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["classification"] = self.classification.value
        return data


@dataclass
class RuleFeedbackSummary:
    rule_id: str
    total_reviews: int
    false_positives: int
    true_positives: int
    accepted_risks: int
    fp_rate: float
    common_justifications: list[str] = field(default_factory=list)
    suggested_refinement: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FalsePositiveIntelligenceManager:
    """Manages tenant-isolated feedback and computes deterministic rule improvement statistics."""

    def __init__(self) -> None:
        # project_id -> list[ReviewFeedbackItem]
        self._tenant_feedback: dict[int, list[ReviewFeedbackItem]] = defaultdict(list)

    def record_feedback(
        self,
        project_id: int,
        user_id: int,
        finding_id: str,
        rule_id: str,
        analyzer_source: str,
        file: str | None,
        evidence: str,
        classification: str | ReviewClassification,
        justification: str,
        commit_sha: str | None = None,
    ) -> ReviewFeedbackItem:
        """Record an auditable review decision bound to the authenticated user and authorized project."""
        clean_justification = justification.strip()
        if len(clean_justification) < 5:
            raise ValueError("A meaningful justification (at least 5 characters) is required for auditability.")

        try:
            c_enum = ReviewClassification(classification)
        except ValueError:
            c_enum = ReviewClassification.CONFIRMED_FALSE_POSITIVE

        f_id = f"fb_{hashlib.sha256(f'{project_id}:{finding_id}:{datetime.now(timezone.utc).timestamp()}'.encode()).hexdigest()[:12]}"
        item = ReviewFeedbackItem(
            feedback_id=f_id,
            finding_id=finding_id,
            project_id=project_id,
            user_id=user_id,
            rule_id=rule_id,
            analyzer_source=analyzer_source,
            file=file,
            evidence_snippet=evidence[:200],
            classification=c_enum,
            justification=clean_justification,
            commit_sha=commit_sha,
        )

        self._tenant_feedback[project_id].append(item)
        return item

    def get_project_feedback(self, project_id: int) -> list[dict[str, Any]]:
        """Retrieve feedback history strictly isolated to the specified project."""
        return [item.to_dict() for item in self._tenant_feedback.get(project_id, [])]

    def analyze_rule_patterns(self, project_id: int) -> list[RuleFeedbackSummary]:
        """Aggregate feedback per rule to highlight systemic false positive candidates without silent logic changes."""
        items = self._tenant_feedback.get(project_id, [])
        by_rule: dict[str, list[ReviewFeedbackItem]] = defaultdict(list)
        for it in items:
            by_rule[it.rule_id].append(it)

        summaries: list[RuleFeedbackSummary] = []
        for rule_id, rule_items in by_rule.items():
            fps = sum(1 for i in rule_items if i.classification == ReviewClassification.CONFIRMED_FALSE_POSITIVE)
            tps = sum(1 for i in rule_items if i.classification == ReviewClassification.CONFIRMED_TRUE_POSITIVE)
            ars = sum(1 for i in rule_items if i.classification == ReviewClassification.ACCEPTED_RISK)
            total = len(rule_items)
            fp_rate = round(fps / max(1, total), 3)

            justifications = [i.justification for i in rule_items if i.classification == ReviewClassification.CONFIRMED_FALSE_POSITIVE]
            
            refinement = None
            if fps >= 2 and fp_rate >= 0.50:
                refinement = (
                    f"Rule '{rule_id}' has a high false-positive rate ({fp_rate * 100:.1f}% across {total} reviews). "
                    f"Common reviewer theme: '{justifications[0]}'. "
                    f"Recommendation: introduce a dedicated sanitizer check or framework AST filter via regression test."
                )

            summaries.append(
                RuleFeedbackSummary(
                    rule_id=rule_id,
                    total_reviews=total,
                    false_positives=fps,
                    true_positives=tps,
                    accepted_risks=ars,
                    fp_rate=fp_rate,
                    common_justifications=justifications[:3],
                    suggested_refinement=refinement,
                )
            )

        return summaries


# Global singleton manager for project feedback
feedback_manager = FalsePositiveIntelligenceManager()

