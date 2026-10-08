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


def persist_analysis(session: Session, analysis: dict, affected_files: list[str] | None = None, affected_analyzers: list[str] | None = None, related_commit: str | None = None) -> dict:
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
    previous_findings = list(previous.findings) if previous else []
    historical = {finding.fingerprint: finding for finding in session.scalars(select(ProjectFinding).join(ProjectReview).where(ProjectReview.project_id == project.id)).all()}
    current_fingerprints = set()
    seen_fingerprints_in_this_review = set()  # Track duplicates within this review
    
    for event in events:
        fingerprint = fingerprint_event(event)
        # Skip duplicates within the same review
        if fingerprint in seen_fingerprints_in_this_review:
            continue
        seen_fingerprints_in_this_review.add(fingerprint)
        current_fingerprints.add(fingerprint)
        
        old = historical.get(fingerprint)
        lifecycle = "REOPENED" if old and old.status == "RESOLVED" else "ACTIVE" if old else "NEW"
        session.add(ProjectFinding(review_id=review.id, category=event["category"], severity=event["severity"], confidence=event["confidence"], component=event.get("component"), file=event.get("file"), line=event.get("line"), evidence=event["evidence"], analyzer_source=event["analyzer_source"], remediation=event["remediation"], status=lifecycle, fingerprint=fingerprint, related_commit=related_commit))
    
    resolution_events = []
    if affected_files is not None:
        normalized = {str(Path(file)).replace("\\", "/").lower() for file in affected_files}
        # Check ALL historical findings for this project that are not in current analysis
        all_previous_findings = session.scalars(select(ProjectFinding).join(ProjectReview).where(
            ProjectReview.project_id == project.id,
            ProjectFinding.status != "RESOLVED"  # Only consider unresolved findings
        )).all()
        
        for old in all_previous_findings:
            old_file = (old.file or "").replace("\\", "/").lower()
            # Only resolve if: fingerprint not in current analysis, not already resolved
            if old.fingerprint not in current_fingerprints:
                analyzer_map = {"testing": {"test_inventory"}, "dependency": {"dependency_analyzer"}, "security": {"secret_detector"}, "requirements": {"requirements_analyzer"}, "coverage": {"requirements_analyzer"}, "source": {"surface_analyzer", "secret_detector"}, "api": {"surface_analyzer"}, "authentication": {"surface_analyzer"}}
                affected_sources = set().union(*(analyzer_map.get(name, set()) for name in (affected_analyzers or [])))
                analyzer_affected = bool(affected_sources and old.analyzer_source in affected_sources)
                if not old_file and not analyzer_affected:
                    continue
                    
                # Check if the affected files match the finding's file
                is_affected = analyzer_affected
                for file in normalized:
                    file_lower = file.lower()
                    # Exact match
                    if old_file == file_lower:
                        is_affected = True
                        break
                    # Finding file ends with changed file (file.py matches src/module/file.py)
                    if old_file.endswith(file_lower):
                        is_affected = True
                        break
                    # Changed file ends with finding file (src/module/ matches src/module/file.py)
                    if file_lower.endswith(old_file):
                        is_affected = True
                        break
                    # Check if the file paths share a common directory
                    if Path(old_file).parent == Path(file_lower):
                        is_affected = True
                        break
                    # Check if the changed file is a parent directory of the finding file
                    if str(Path(old_file).parent).startswith(file_lower):
                        is_affected = True
                        break
                    # Check if the finding file is in the changed directory
                    if old_file.startswith(file_lower):
                        is_affected = True
                        break
                        
                if is_affected:
                    old.status = "RESOLVED"
                    old.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    old.resolution_evidence = "Affected scope was re-analyzed and the finding was not detected."
                    old.related_commit = related_commit or old.related_commit
                    resolution_events.append({"finding_id": old.id, "fingerprint": old.fingerprint, "category": old.category, "severity": old.severity, "component": old.component, "file": old.file, "resolved_at": old.resolved_at.isoformat(), "resolution_evidence": old.resolution_evidence, "related_commit": old.related_commit})
    for rank, prediction in enumerate(analysis.get("next_failure_predictions", []), 1):
        session.add(ProjectPrediction(review_id=review.id, category=prediction["category"], probability=prediction["probability"], confidence=prediction["confidence"], rank=rank, supporting_evidence={"historical_support": prediction.get("historical_support", 0), "evidence": prediction.get("evidence")}))
    _persist_requirements(session, project.id, review.id, analysis.get("requirements", []), analysis.get("project", {}).get("path", ""), events)
    project.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.commit()
    result = serialize_review(session, review.id)
    result["resolved_events"] = resolution_events
    result["requirements"] = analysis.get("requirements", [])
    result["failure_dna"] = analysis.get("failure_dna", {})
    result["next_failure_predictions"] = analysis.get("next_failure_predictions", [])
    return result


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


def failure_history(session: Session, project_id: int) -> dict:
    """Aggregate every persisted finding across a project's reviews.

    Each review stores its own row per fingerprint, so grouping by fingerprint
    gives the observed lifecycle of a failure: how many reviews detected it,
    when it was first and last seen, and its latest lifecycle status. Nothing is
    recomputed or inferred here; the response only restates persisted rows.
    """
    project = session.get(ReviewedProject, project_id)
    if project is None:
        raise ValueError("Project not found")
    reviews = session.scalars(
        select(ProjectReview).options(selectinload(ProjectReview.findings))
        .where(ProjectReview.project_id == project_id).order_by(ProjectReview.review_number)
    ).all()
    grouped: dict[str, list[tuple[int, datetime, ProjectFinding]]] = {}
    for review in reviews:
        for finding in review.findings:
            grouped.setdefault(finding.fingerprint, []).append((review.review_number, review.timestamp, finding))

    findings = []
    for fingerprint, rows in grouped.items():
        rows.sort(key=lambda item: item[0])
        review_numbers = sorted({review_number for review_number, _, _ in rows})
        timestamps = [timestamp for _, timestamp, _ in rows]
        latest = rows[-1][2]
        findings.append({
            "fingerprint": fingerprint,
            "category": latest.category,
            "severity": latest.severity,
            "confidence": latest.confidence,
            "component": latest.component,
            "file": latest.file,
            "line": latest.line,
            "evidence": latest.evidence,
            "analyzer_source": latest.analyzer_source,
            "remediation": latest.remediation,
            "status": latest.status,
            "occurrences": len(review_numbers),
            "review_numbers": review_numbers,
            "first_seen": min(timestamps).isoformat(),
            "last_seen": max(timestamps).isoformat(),
            "resolved_at": latest.resolved_at.isoformat() if latest.resolved_at else None,
            "resolution_evidence": latest.resolution_evidence,
            "related_commit": latest.related_commit,
        })
    findings.sort(key=lambda item: (item["first_seen"], item["fingerprint"]))

    resolved = sum(1 for item in findings if item["status"] == "RESOLVED")
    timestamps = [review.timestamp for review in reviews]
    summary = {
        "review_count": len(reviews),
        "distinct_failure_count": len(findings),
        "open_failure_count": len(findings) - resolved,
        "resolved_failure_count": resolved,
        "categories": sorted({item["category"] for item in findings}),
        "first_review_at": min(timestamps).isoformat() if timestamps else None,
        "last_review_at": max(timestamps).isoformat() if timestamps else None,
    }
    return {
        "project": {"id": project.id, "name": project.name, "repository_path": project.repository_path},
        "summary": summary,
        "findings": findings,
        "message": None if findings else "No persisted failure history yet.",
    }
