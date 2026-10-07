from __future__ import annotations

from collections import Counter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import ProjectFinding, ProjectPrediction, ProjectReview, ProjectRequirement, RequirementCoverage


def _reviews(session: Session, project_id: int):
    return session.scalars(select(ProjectReview).options(selectinload(ProjectReview.findings), selectinload(ProjectReview.predictions)).where(ProjectReview.project_id == project_id).order_by(ProjectReview.review_number)).all()


def trajectory(session: Session, project_id: int) -> dict:
    reviews = _reviews(session, project_id)
    if not reviews: return {"reviews": [], "transitions": [], "loops": [], "message": "Insufficient historical evidence."}
    sequence = [sorted({f.category for f in r.findings}) for r in reviews]
    transitions = Counter((a, b) for old, new in zip(sequence, sequence[1:]) for a in old for b in new if a != b)
    edges = [{"from": a, "to": b, "count": count} for (a, b), count in transitions.items()]
    loops = []
    if len(sequence) >= 3:
        flat = [cat for group in sequence for cat in group]
        for i in range(len(flat) - 2):
            if flat[i] == flat[i + 2] and flat[i] != flat[i + 1]: loops.append({"pattern": f"{flat[i]} → {flat[i + 1]} → {flat[i]}", "occurrence_count": 1})
    return {"reviews": [{"review_number": r.review_number, "timestamp": r.timestamp.isoformat(), "categories": cats, "finding_count": len(r.findings)} for r, cats in zip(reviews, sequence)], "transitions": edges, "loops": loops, "message": None if len(reviews) >= 2 else "Insufficient historical evidence for reliable transition analysis."}


def evolution(session: Session, project_id: int) -> dict:
    reviews = _reviews(session, project_id)
    improvements, regressions, persistent = [], [], []
    for previous, current in zip(reviews, reviews[1:]):
        old = {f.fingerprint: f for f in previous.findings}; new = {f.fingerprint: f for f in current.findings}
        improvements.extend({"review_from": previous.review_number, "review_to": current.review_number, "category": old[k].category, "type": "resolved", "evidence": old[k].evidence} for k in old.keys() - new.keys())
        regressions.extend({"review_from": previous.review_number, "review_to": current.review_number, "category": new[k].category, "type": "introduced", "evidence": new[k].evidence} for k in new.keys() - old.keys())
        persistent.extend({"review_from": previous.review_number, "review_to": current.review_number, "category": new[k].category, "type": "persistent"} for k in old.keys() & new.keys())
    dna = []
    dimensions = {"authentication_risk": "authentication", "authorization_risk": "authorization", "testing_weakness": "testing", "dependency_risk": "dependency", "configuration_risk": "configuration", "integration_fragility": "integration", "architecture_risk": "architecture", "security_risk": "security"}
    for key, category in dimensions.items():
        values = [{"review_number": r.review_number, "value": round(sum(f.severity in {"critical", "high"} for f in r.findings if f.category == category) / max(1, len(r.findings)), 3)} for r in reviews]
        dna.append({"dimension": key, "category": category, "values": values, "trend": "Improving" if len(values) > 1 and values[-1]["value"] < values[0]["value"] else "Worsening" if len(values) > 1 and values[-1]["value"] > values[0]["value"] else "Stable"})
    return {"improvements": improvements, "regressions": regressions, "persistent_risks": persistent, "stability": {"review_count": len(reviews), "persistent_category_count": len({x["category"] for x in persistent})}, "dna_evolution": dna, "prediction_evolution": [{"review_number": r.review_number, "predictions": [{"category": p.category, "confidence": p.confidence, "probability": p.probability} for p in sorted(r.predictions, key=lambda x: x.rank)[:3]]} for r in reviews], "message": "Observed association based on historical project reviews."}


def requirements(session: Session, project_id: int) -> dict:
    rows = session.scalars(select(ProjectRequirement).options(selectinload(ProjectRequirement.coverage)).where(ProjectRequirement.project_id == project_id)).all()
    if not rows: return {"requirements": [], "message": "No structured requirements were detected."}
    result = []
    for row in rows:
        latest = sorted(row.coverage, key=lambda c: c.review_id)[-1] if row.coverage else None
        result.append({"id": row.id, "requirement_key": row.requirement_key, "title": row.title, "description": row.description, "source": row.source, "priority": row.priority, "coverage": {"status": latest.status, "confidence": latest.confidence, "evidence": latest.evidence, "implementation": latest.implementation_evidence, "tests": latest.test_evidence, "related_findings": latest.related_findings} if latest else {"status": "UNKNOWN", "confidence": 0, "evidence": "No coverage observation exists."}})
    return {"requirements": result, "message": None}


def research_observations(session: Session, project_id: int) -> dict:
    reviews = _reviews(session, project_id); observations = []
    for previous, current in zip([None] + reviews, reviews):
        categories = [f.category for f in current.findings]; previous_category = previous.findings[-1].category if previous and previous.findings else None
        for category in categories: observations.append({"project_id": project_id, "review_id": current.id, "timestamp": current.timestamp.isoformat(), "current_failure_category": category, "previous_failure_category": previous_category, "failure_frequency": categories.count(category), "failure_recency": len(reviews) - current.review_number, "failure_transition_frequency": 0, "component_failure_frequency": 0, "change_intensity": current.snapshot.get("recent_churn", ""), "test_weakness": current.metrics.get("high", 0), "severity": next((f.severity for f in current.findings if f.category == category), None), "next_failure_category": None})
    return {"observations": observations, "message": "Research dataset preparation only; no model training or accuracy claim."}
