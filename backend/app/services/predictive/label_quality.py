"""Label quality, provenance classification, and synthetic filtering (Phase 4)."""
from __future__ import annotations

import re
from typing import Any
from .constants import ProvenanceClassification

SYNTHETIC_PATH_PATTERNS = re.compile(
    r"(?i)(appdata[\\/]+local[\\/]+temp|[/\\]tmp[/\\]|pytest-of-|"
    r"mistiq_(?:e2e|complete|direct|live|diag)|showcase|synthetic|test_fixture)"
)


class LabelQualityAssessor:
    """Classifies dataset provenance and verifies label trustworthiness."""

    @staticmethod
    def is_synthetic(
        name: str | None,
        repository_path: str | None,
        repository_url: str | None = None,
    ) -> bool:
        """Determines if a project record originates from a test or synthetic environment."""
        combined = f"{name or ''} {repository_path or ''} {repository_url or ''}"
        return bool(SYNTHETIC_PATH_PATTERNS.search(combined))

    @classmethod
    def classify_provenance(
        cls,
        *,
        name: str | None,
        repository_path: str | None,
        repository_url: str | None = None,
        has_commit_evidence: bool = False,
        has_lifecycle_evidence: bool = False,
        has_curated_labels: bool = False,
        is_fixture: bool = False,
        sample_count: int = 0,
    ) -> tuple[ProvenanceClassification, float, dict[str, Any]]:
        """Classifies provenance tier and returns (classification, confidence, audit_reasons)."""
        reasons: dict[str, Any] = {
            "synthetic_match": False,
            "has_commit_evidence": has_commit_evidence,
            "has_lifecycle_evidence": has_lifecycle_evidence,
            "has_curated_labels": has_curated_labels,
            "sample_count": sample_count,
        }

        if is_fixture:
            reasons["is_explicit_fixture"] = True
            return ProvenanceClassification.TEST_FIXTURE, 0.20, reasons

        if cls.is_synthetic(name, repository_path, repository_url):
            reasons["synthetic_match"] = True
            return ProvenanceClassification.SYNTHETIC, 0.30, reasons

        if sample_count == 0:
            reasons["empty_dataset"] = True
            return ProvenanceClassification.INSUFFICIENT_LABELS, 0.0, reasons

        if has_commit_evidence and has_lifecycle_evidence:
            reasons["verified_by"] = "git_commit_and_lifecycle_records"
            return ProvenanceClassification.VERIFIED_REAL, 0.95, reasons

        if has_curated_labels or has_commit_evidence:
            reasons["verified_by"] = "curated_ground_truth"
            return ProvenanceClassification.CURATED_REAL, 0.85, reasons

        if has_lifecycle_evidence:
            reasons["verified_by"] = "static_analyzer_findings_only"
            return ProvenanceClassification.UNVERIFIED, 0.60, reasons

        return ProvenanceClassification.INSUFFICIENT_LABELS, 0.40, reasons

    @classmethod
    def evaluate_dataset_provenance(cls, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Audits a collection of dataset records and counts provenance distribution."""
        counts = {tier.value: 0 for tier in ProvenanceClassification}
        total = len(records)
        untrusted_count = 0

        for r in records:
            prov = r.get("provenance_classification", ProvenanceClassification.UNVERIFIED.value)
            if prov in counts:
                counts[prov] += 1
            else:
                counts[ProvenanceClassification.UNVERIFIED.value] += 1

            if prov in (
                ProvenanceClassification.SYNTHETIC.value,
                ProvenanceClassification.TEST_FIXTURE.value,
                ProvenanceClassification.UNVERIFIED.value,
                ProvenanceClassification.INSUFFICIENT_LABELS.value,
            ):
                untrusted_count += 1

        is_scientifically_justified = (
            total >= 20 and (counts[ProvenanceClassification.VERIFIED_REAL.value] + counts[ProvenanceClassification.CURATED_REAL.value]) / total >= 0.70
        )

        return {
            "total_records": total,
            "distribution": counts,
            "untrusted_count": untrusted_count,
            "trusted_count": total - untrusted_count,
            "scientifically_justified": is_scientifically_justified,
            "verdict": "APPROVED_FOR_TRAINING" if is_scientifically_justified else "EXPERIMENTAL_ONLY",
        }

