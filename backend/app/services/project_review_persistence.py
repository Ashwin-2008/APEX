from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import ProjectFinding, ProjectPrediction, ProjectReview, ReviewedProject, ProjectRequirement, RequirementCoverage


def fingerprint_event(event: dict) -> str:
    material = "|".join(str(event.get(key, "")).strip().lower() for key in ("category", "component", "file", "line", "analyzer_source", "evidence"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _metrics(events: list[dict]) -> dict[str, int]:
    return {severity: sum(event.get("severity") == severity for event in events) for severity in ("critical", "high", "medium", "low")}


def persist_analysis(session: Session, analysis: dict) -> dict:
    path = analysis["project"]["path"]
    project = session.scalar(select(ReviewedProject).where(ReviewedProject.repository_path == path))
    if project is None:
        project = ReviewedProject(name=Path(path).name or path, repository_path=path)
        session.add(project)
        session.flush()
    previous = session.scalar(select(ProjectReview).where(ProjectReview.project_id == project.id).order_by(ProjectReview.review_number.desc()))
    number = (previous.review_number if previous else 0) + 1
    events = analysis.get("events", [])
    review = ProjectReview(project_id=project.id, review_number=number, timestamp=datetime.now(timezone.utc).replace(tzinfo=None), snapshot=analysis.get("project", {}), metrics=_metrics(events), status="completed")
    session.add(review)
    session.flush()
    for event in events:
        session.add(ProjectFinding(review_id=review.id, category=event["category"], severity=event["severity"], confidence=event["confidence"], component=event.get("component"), file=event.get("file"), line=event.get("line"), evidence=event["evidence"], analyzer_source=event["analyzer_source"], remediation=event["remediation"], status=event.get("status", "open"), fingerprint=fingerprint_event(event)))
    for rank, prediction in enumerate(analysis.get("next_failure_predictions", []), 1):
        session.add(ProjectPrediction(review_id=review.id, category=prediction["category"], probability=prediction["probability"], confidence=prediction["confidence"], rank=rank, supporting_evidence={"historical_support": prediction.get("historical_support", 0), "evidence": prediction.get("evidence")}))
    _persist_requirements(session, project.id, review.id, analysis.get("requirements", []), analysis.get("project", {}).get("path", ""), events)
    project.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.commit()
    return serialize_review(session, review.id)


def _persist_requirements(session: Session, project_id: int, review_id: int, items: list[dict], project_path: str, events: list[dict]) -> None:
    existing = {r.requirement_key: r for r in session.scalars(select(ProjectRequirement).where(ProjectRequirement.project_id == project_id)).all()}
    for item in items:
        requirement = existing.get(item["requirement_key"])
        if requirement is None:
            requirement = ProjectRequirement(project_id=project_id, requirement_key=item["requirement_key"], title=item["title"], description=item.get("description"), source=item.get("source", "repository"), priority=item.get("priority"), status="active")
            session.add(requirement); session.flush(); existing[requirement.requirement_key] = requirement
        words = {word.lower() for word in item["title"].split() if len(word) > 4}
        files = []
        try:
            files = [str(p.relative_to(project_path)) for p in Path(project_path).rglob("*") if p.is_file() and any(word in p.name.lower() for word in words)]
        except OSError:
            pass
        tests = [file for file in files if "test" in file.lower() or "spec" in file.lower()]
        status = "COVERED" if files and tests else "PARTIALLY_COVERED" if files else "UNKNOWN"
        evidence = "Implementation files: " + ", ".join(files[:5]) if files else "No deterministic implementation evidence found; coverage is unknown."
        if tests: evidence += "; test files: " + ", ".join(tests[:5])
        session.add(RequirementCoverage(requirement_id=requirement.id, review_id=review_id, implementation_evidence={"files": files[:20]}, test_evidence={"files": tests[:20]}, related_findings=[e["category"] for e in events if any(word in e.get("evidence", "").lower() for word in words)], status=status, confidence=.8 if files else 0, evidence=evidence))


def serialize_review(session: Session, review_id: int) -> dict:
    review = session.scalar(select(ProjectReview).options(selectinload(ProjectReview.findings), selectinload(ProjectReview.predictions)).where(ProjectReview.id == review_id))
    if review is None:
        raise ValueError("Review not found")
    return {"id": review.id, "project_id": review.project_id, "review_number": review.review_number, "timestamp": review.timestamp.isoformat(), "metrics": review.metrics, "snapshot": review.snapshot, "status": review.status, "findings": [{"id": f.id, "category": f.category, "severity": f.severity, "confidence": f.confidence, "component": f.component, "file": f.file, "line": f.line, "evidence": f.evidence, "analyzer_source": f.analyzer_source, "remediation": f.remediation, "status": f.status, "fingerprint": f.fingerprint} for f in review.findings], "predictions": [{"category": p.category, "probability": p.probability, "confidence": p.confidence, "rank": p.rank, "supporting_evidence": p.supporting_evidence} for p in sorted(review.predictions, key=lambda x: x.rank)]}


def project_history(session: Session, project_id: int) -> dict:
    project = session.get(ReviewedProject, project_id)
    if project is None:
        raise ValueError("Project not found")
    reviews = session.scalars(select(ProjectReview).where(ProjectReview.project_id == project_id).order_by(ProjectReview.review_number)).all()
    return {"project": {"id": project.id, "name": project.name, "repository_path": project.repository_path}, "reviews": [{"id": r.id, "review_number": r.review_number, "timestamp": r.timestamp.isoformat(), "metrics": r.metrics, "finding_count": sum(r.metrics.values()), "top_prediction": None} for r in reviews]}


def compare_reviews(session: Session, project_id: int) -> dict:
    reviews = session.scalars(select(ProjectReview).options(selectinload(ProjectReview.findings)).where(ProjectReview.project_id == project_id).order_by(ProjectReview.review_number.desc()).limit(2)).all()
    if len(reviews) < 2:
        return {"previous": None, "current": serialize_review(session, reviews[0].id) if reviews else None, "resolved_findings": [], "persistent_findings": [], "newly_introduced_findings": [], "changed_components": [], "metric_changes": {}, "category_changes": {}, "risk_changes": {}, "summary": "A comparison requires at least two completed reviews."}
    current, previous = reviews[0], reviews[1]
    old = {f.fingerprint: f for f in previous.findings}; new = {f.fingerprint: f for f in current.findings}
    resolved = [f for key, f in old.items() if key not in new]; introduced = [f for key, f in new.items() if key not in old]; persistent = [f for key, f in new.items() if key in old]
    changed_components = sorted({f.component or f.file for f in resolved + introduced + persistent if f.component or f.file})
    metric_changes = {key: {"previous": previous.metrics.get(key, 0), "current": current.metrics.get(key, 0), "delta": current.metrics.get(key, 0) - previous.metrics.get(key, 0)} for key in set(previous.metrics) | set(current.metrics)}
    categories = lambda fs: sorted({f.category for f in fs})
    return {"previous": serialize_review(session, previous.id), "current": serialize_review(session, current.id), "resolved_findings": [serialize_finding(f) for f in resolved], "persistent_findings": [serialize_finding(f) for f in persistent], "newly_introduced_findings": [serialize_finding(f) for f in introduced], "changed_components": changed_components, "metric_changes": metric_changes, "category_changes": {"resolved": sorted(set(categories(resolved))), "introduced": sorted(set(categories(introduced))), "persistent": sorted(set(categories(persistent)))}, "risk_changes": {"resolved_high_or_critical": sum(f.severity in {"high", "critical"} for f in resolved), "introduced_high_or_critical": sum(f.severity in {"high", "critical"} for f in introduced)}, "summary": "These are observed differences between reviews; they do not establish causality."}


def serialize_finding(f: ProjectFinding) -> dict:
    return {"id": f.id, "category": f.category, "severity": f.severity, "confidence": f.confidence, "component": f.component, "file": f.file, "line": f.line, "evidence": f.evidence, "analyzer_source": f.analyzer_source, "remediation": f.remediation, "fingerprint": f.fingerprint}
