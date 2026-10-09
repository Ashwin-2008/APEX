from __future__ import annotations

from collections import Counter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import ProjectFinding, ProjectPrediction, ProjectReview, ProjectRequirement, RequirementCoverage


def _reviews(session: Session, project_id: int):
    return session.scalars(
        select(ProjectReview)
        .options(selectinload(ProjectReview.findings), selectinload(ProjectReview.predictions))
        .where(ProjectReview.project_id == project_id)
        .order_by(ProjectReview.review_number)
    ).all()


def trajectory(session: Session, project_id: int) -> dict:
    reviews = _reviews(session, project_id)
    if not reviews:
        return {"reviews": [], "transitions": [], "loops": [], "message": "Insufficient historical evidence."}
    sequence = [sorted({f.category for f in r.findings}) for r in reviews]
    transitions = Counter((a, b) for old, new in zip(sequence, sequence[1:]) for a in old for b in new if a != b)
    edges = [{"from": a, "to": b, "count": count} for (a, b), count in transitions.items()]
    loops = []
    if len(sequence) >= 3:
        flat = [cat for group in sequence for cat in group]
        for i in range(len(flat) - 2):
            if flat[i] == flat[i + 2] and flat[i] != flat[i + 1]:
                loops.append({"pattern": f"{flat[i]} → {flat[i + 1]} → {flat[i]}", "occurrence_count": 1})
    return {
        "reviews": [
            {"review_number": r.review_number, "timestamp": r.timestamp.isoformat(), "categories": cats, "finding_count": len(r.findings)}
            for r, cats in zip(reviews, sequence)
        ],
        "transitions": edges,
        "loops": loops,
        "message": None if len(reviews) >= 2 else "Insufficient historical evidence for reliable transition analysis.",
    }


def _serialize_finding(f: ProjectFinding) -> dict:
    return {
        "id": f.id,
        "category": f.category,
        "severity": f.severity,
        "confidence": f.confidence,
        "component": f.component,
        "file": f.file,
        "line": f.line,
        "evidence": f.evidence,
        "analyzer_source": f.analyzer_source,
        "remediation": f.remediation,
        "fingerprint": f.fingerprint,
        "status": f.status,
    }


def evolution(session: Session, project_id: int) -> dict:
    reviews = _reviews(session, project_id)
    if not reviews:
        return {
            "reviews_summary": [],
            "review_comparisons": [],
            "lifecycle_counts": {
                "unique_findings": 0,
                "total_occurrences": 0,
                "active_count": 0,
                "resolved_count": 0,
                "reopened_count": 0,
                "persistent_count": 0,
            },
            "risk_domains": [],
            "resolution_analysis": {
                "resolved_count": 0,
                "persistent_count": 0,
                "resolution_ratio": 0.0,
                "avg_occurrences_before_resolution": 0.0,
                "coverage_note": "No project reviews have been completed yet.",
            },
            "improvements": [],
            "regressions": [],
            "persistent_risks": [],
            "stability": {"review_count": 0, "persistent_category_count": 0},
            "dna_evolution": [],
            "prediction_evolution": [],
            "insufficient_history": True,
            "insufficient_history_message": "At least two completed project reviews are required to compute an engineering trajectory.",
            "message": "No historical reviews found.",
        }

    # Track all historical appearances by fingerprint
    # fingerprint -> list of (review_number, timestamp, finding)
    all_appearances: dict[str, list[tuple[int, ProjectFinding]]] = {}
    for r in reviews:
        for f in r.findings:
            all_appearances.setdefault(f.fingerprint, []).append((r.review_number, f))

    # Review summaries for chronological timeline
    reviews_summary = []
    seen_so_far: set[str] = set()

    for idx, r in enumerate(reviews):
        curr_fps = {f.fingerprint for f in r.findings}
        prev_fps = {f.fingerprint for f in reviews[idx - 1].findings} if idx > 0 else set()

        crit = sum(f.severity == "critical" for f in r.findings)
        high = sum(f.severity == "high" for f in r.findings)
        med = sum(f.severity == "medium" for f in r.findings)
        low = sum(f.severity == "low" for f in r.findings)

        newly_intro = len(curr_fps - seen_so_far)
        persistent_count = len(curr_fps & prev_fps) if idx > 0 else 0
        resolved_count = len(prev_fps - curr_fps) if idx > 0 else 0
        # Reopened: in curr_fps, was in seen_so_far, but was NOT in prev_fps
        reopened_count = len((curr_fps & seen_so_far) - prev_fps) if idx > 0 else 0

        seen_so_far.update(curr_fps)

        reviews_summary.append({
            "review_number": r.review_number,
            "review_id": r.id,
            "timestamp": r.timestamp.isoformat(),
            "finding_count": len(r.findings),
            "critical_count": crit,
            "high_count": high,
            "medium_count": med,
            "low_count": low,
            "newly_introduced": newly_intro,
            "resolved_count": resolved_count,
            "persistent_count": persistent_count,
            "reopened_count": reopened_count,
        })

    # Pairwise review comparisons
    comparisons = []
    improvements, regressions, persistent = [], [], []
    cumulative_seen: set[str] = set()

    for previous, current in zip(reviews, reviews[1:]):
        cumulative_seen.update(f.fingerprint for f in previous.findings)
        old = {f.fingerprint: f for f in previous.findings}
        new = {f.fingerprint: f for f in current.findings}

        resolved_fps = old.keys() - new.keys()
        new_or_reopened_fps = new.keys() - old.keys()
        persistent_fps = old.keys() & new.keys()

        introduced_list = [new[k] for k in new_or_reopened_fps if k not in cumulative_seen]
        reopened_list = [new[k] for k in new_or_reopened_fps if k in cumulative_seen]
        resolved_list = [old[k] for k in resolved_fps]
        persistent_list = [new[k] for k in persistent_fps]

        # For backwards compatibility:
        improvements.extend({
            "review_from": previous.review_number,
            "review_to": current.review_number,
            "category": f.category,
            "type": "resolved",
            "evidence": f.evidence,
        } for f in resolved_list)

        regressions.extend({
            "review_from": previous.review_number,
            "review_to": current.review_number,
            "category": f.category,
            "type": "introduced",
            "evidence": f.evidence,
        } for f in introduced_list)

        persistent.extend({
            "review_from": previous.review_number,
            "review_to": current.review_number,
            "category": f.category,
            "type": "persistent",
        } for f in persistent_list)

        # Category changes
        all_cats = {f.category for f in list(old.values()) + list(new.values())}
        category_changes = {}
        for cat in sorted(all_cats):
            prev_c = sum(f.category == cat for f in old.values())
            curr_c = sum(f.category == cat for f in new.values())
            category_changes[cat] = {"previous": prev_c, "current": curr_c, "delta": curr_c - prev_c}

        # Severity changes
        sev_changes = {}
        for sev in ("critical", "high", "medium", "low"):
            prev_s = sum(f.severity == sev for f in old.values())
            curr_s = sum(f.severity == sev for f in new.values())
            sev_changes[sev] = {"previous": prev_s, "current": curr_s, "delta": curr_s - prev_s}

        comparisons.append({
            "from_review": previous.review_number,
            "to_review": current.review_number,
            "from_timestamp": previous.timestamp.isoformat(),
            "to_timestamp": current.timestamp.isoformat(),
            "newly_introduced": [_serialize_finding(f) for f in introduced_list],
            "resolved": [_serialize_finding(f) for f in resolved_list],
            "persistent": [_serialize_finding(f) for f in persistent_list],
            "reopened": [_serialize_finding(f) for f in reopened_list],
            "category_changes": category_changes,
            "severity_changes": sev_changes,
            "summary": f"Review #{current.review_number} compared against #{previous.review_number}: {len(resolved_list)} resolved, {len(introduced_list)} introduced, {len(persistent_list)} persistent, {len(reopened_list)} reopened.",
        })

    # DNA evolution
    dna = []
    dimensions = {
        "authentication_risk": "authentication",
        "authorization_risk": "authorization",
        "testing_weakness": "testing",
        "dependency_risk": "dependency",
        "configuration_risk": "configuration",
        "integration_fragility": "integration",
        "architecture_risk": "architecture",
        "security_risk": "security",
    }
    for key, category in dimensions.items():
        values = [
            {
                "review_number": r.review_number,
                "value": round(
                    sum(f.severity in {"critical", "high"} for f in r.findings if f.category == category)
                    / max(1, len(r.findings)),
                    3,
                ),
            }
            for r in reviews
        ]
        trend = (
            "Improving"
            if len(values) > 1 and values[-1]["value"] < values[0]["value"]
            else "Worsening"
            if len(values) > 1 and values[-1]["value"] > values[0]["value"]
            else "Stable"
        )
        dna.append({"dimension": key, "category": category, "values": values, "trend": trend})

    # Risk domain breakdown
    all_observed_categories = sorted({f.category for r in reviews for f in r.findings})
    latest_review = reviews[-1]
    latest_findings = latest_review.findings
    first_review = reviews[0]

    risk_domains = []
    for cat in all_observed_categories:
        unique_fps_in_cat = {fp for fp, apps in all_appearances.items() if apps[0][1].category == cat}
        current_active_cat = sum(f.category == cat for f in latest_findings)
        first_active_cat = sum(f.category == cat for f in first_review.findings)
        resolved_in_cat = len(unique_fps_in_cat) - current_active_cat
        revs_present = sorted({rn for fp in unique_fps_in_cat for rn, _ in all_appearances[fp]})

        trend = (
            "Improving"
            if len(reviews) > 1 and current_active_cat < first_active_cat
            else "Worsening"
            if len(reviews) > 1 and current_active_cat > first_active_cat
            else "Stable"
        )

        risk_domains.append({
            "category": cat,
            "total_detected": len(unique_fps_in_cat),
            "current_active": current_active_cat,
            "resolved_count": max(0, resolved_in_cat),
            "trend": trend,
            "reviews_present": revs_present,
        })

    # Lifecycle counts across all reviews
    total_distinct_fps = len(all_appearances)
    total_occurrences = sum(len(apps) for apps in all_appearances.values())
    active_now = len(latest_findings)
    total_resolved = sum(1 for fp, apps in all_appearances.items() if apps[-1][1].status == "RESOLVED" or fp not in {f.fingerprint for f in latest_findings})
    total_reopened = sum(1 for fp, apps in all_appearances.items() if any(f.status == "REOPENED" for _, f in apps))
    persistent_across_reviews = sum(1 for fp, apps in all_appearances.items() if len(apps) > 1)

    resolution_analysis = {
        "resolved_count": total_resolved,
        "persistent_count": persistent_across_reviews,
        "resolution_ratio": round(total_resolved / max(1, total_distinct_fps), 3),
        "avg_occurrences_before_resolution": round(
            sum(len(apps) for fp, apps in all_appearances.items() if fp not in {f.fingerprint for f in latest_findings})
            / max(1, total_resolved),
            2,
        ) if total_resolved else 0.0,
        "coverage_note": "Deterministic comparison between consecutive reviews based on scope re-analysis.",
    }

    insufficient_history = len(reviews) < 2
    insufficient_history_message = (
        "At least two completed project reviews are required to compute a deterministic trajectory."
        if insufficient_history
        else None
    )

    return {
        "reviews_summary": reviews_summary,
        "review_comparisons": comparisons,
        "lifecycle_counts": {
            "unique_findings": total_distinct_fps,
            "total_occurrences": total_occurrences,
            "active_count": active_now,
            "resolved_count": total_resolved,
            "reopened_count": total_reopened,
            "persistent_count": persistent_across_reviews,
        },
        "risk_domains": risk_domains,
        "resolution_analysis": resolution_analysis,
        "improvements": improvements,
        "regressions": regressions,
        "persistent_risks": persistent,
        "stability": {
            "review_count": len(reviews),
            "persistent_category_count": len({x["category"] for x in persistent}),
        },
        "dna_evolution": dna,
        "prediction_evolution": [
            {
                "review_number": r.review_number,
                "predictions": [
                    {"category": p.category, "confidence": p.confidence, "probability": p.probability}
                    for p in sorted(r.predictions, key=lambda x: x.rank)[:3]
                ],
            }
            for r in reviews
        ],
        "insufficient_history": insufficient_history,
        "insufficient_history_message": insufficient_history_message,
        "message": "Observed deterministic trajectory based on historical project reviews.",
    }


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

