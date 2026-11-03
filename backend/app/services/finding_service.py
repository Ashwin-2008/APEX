"""Finding Intelligence and Lifecycle Management Service."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ProjectFinding, ProjectReview, ReviewedProject


def compute_deterministic_fingerprint(
    analyzer_source: str,
    rule_id: str,
    category: str,
    file_path: str | None,
    evidence_text: str,
) -> str:
    """Generate a stable fingerprint independent of line numbers or whitespace shifts."""
    clean_file = (file_path or "global").replace("\\", "/").lower()
    # Normalize evidence by stripping line numbers and excess whitespace
    normalized_evidence = re.sub(r"line\s+\d+", "line_X", evidence_text.lower())
    normalized_evidence = re.sub(r"\s+", " ", normalized_evidence).strip()
    raw = f"{analyzer_source.lower()}:{rule_id.lower()}:{category.lower()}:{clean_file}:{normalized_evidence[:150]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def suppress_finding(
    session: Session,
    finding_id: int,
    user_id: int,
    reason: str,
    suppression_type: str = "false_positive",
) -> ProjectFinding:
    """Mark a finding as false positive or suppressed with a required justification."""
    clean_reason = reason.strip()
    if len(clean_reason) < 5:
        raise ValueError("A clear justification (at least 5 characters) is required to suppress a finding.")

    finding = session.get(ProjectFinding, finding_id)
    if not finding:
        raise ValueError("Finding not found.")

    finding.suppressed = True
    finding.suppression_reason = clean_reason
    finding.suppression_type = suppression_type
    finding.suppressed_at = datetime.now(timezone.utc)
    finding.suppressed_by = user_id
    finding.status = "SUPPRESSED"
    session.commit()
    session.refresh(finding)
    return finding


def unsuppress_finding(session: Session, finding_id: int) -> ProjectFinding:
    """Reopen a previously suppressed finding."""
    finding = session.get(ProjectFinding, finding_id)
    if not finding:
        raise ValueError("Finding not found.")

    finding.suppressed = False
    finding.suppression_reason = None
    finding.suppression_type = None
    finding.suppressed_at = None
    finding.suppressed_by = None
    finding.status = "ACTIVE"
    session.commit()
    session.refresh(finding)
    return finding


def serialize_finding(f: ProjectFinding) -> dict[str, Any]:
    return {
        "id": f.id,
        "review_id": f.review_id,
        "title": f.title or f"{f.category.capitalize()} in {f.file or f.component or 'project'}",
        "category": f.category,
        "severity": f.severity,
        "confidence": round(f.confidence, 3),
        "component": f.component,
        "file": f.file,
        "line": f.line,
        "evidence": f.evidence,
        "analyzer_source": f.analyzer_source,
        "remediation": f.remediation,
        "status": f.status,
        "fingerprint": f.fingerprint,
        "detected_at": f.detected_at.isoformat() if f.detected_at else None,
        "updated_at": f.updated_at.isoformat() if f.updated_at else None,
        "resolved_at": f.resolved_at.isoformat() if f.resolved_at else None,
        "resolution_evidence": f.resolution_evidence,
        "related_commit": f.related_commit,
        "suppressed": f.suppressed,
        "suppression_reason": f.suppression_reason,
        "suppression_type": f.suppression_type,
        "suppressed_at": f.suppressed_at.isoformat() if f.suppressed_at else None,
    }

