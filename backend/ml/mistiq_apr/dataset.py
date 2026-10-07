from __future__ import annotations

import hashlib
import json
from collections import Counter
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import ProjectFinding, ProjectReview, ReviewedProject
from .constants import FAILURE_CATEGORIES, PROJECT_REVIEW_DATASET_VERSION


@dataclass(frozen=True)
class Observation:
    """One chronological training example: state at review N → target in review N+1.

    The audit fields below exist so the leakage validator can verify, rather
    than assume, that features were only built from evidence at or before the
    observation timestamp and that the next-review target review never fed the
    feature construction.
    """

    project_id: int
    review_id: int
    review_number: int
    timestamp: str
    features: dict[str, float]
    target: str
    previous_category: str | None
    feature_max_timestamp: str | None = None
    target_review_id: int | None = None
    feature_review_ids: tuple[int, ...] = ()
    @property
    def key(self): return (self.project_id, self.review_id, self.target)
    # Review the target label came from (review N+1). None when unknown.
    target_review_id: int | None = None
    # Timestamp of the review the target label came from.
    target_timestamp: str | None = None
    # Reviews whose findings contributed to the feature vector (review N and earlier).
    feature_review_ids: tuple[int, ...] = field(default_factory=tuple)
    # Latest timestamp among reviews that contributed to the feature vector.
    feature_max_timestamp: str | None = None

    @property
    def key(self) -> tuple[int, int, str]:
        """Stable identity used for duplicate detection and preprocessing audits."""
        return (self.project_id, self.review_id, self.target)


def load_review_records(session: Session, project_id: int | None = None) -> list[ProjectReview]:
    query = select(ProjectReview).options(selectinload(ProjectReview.findings)).order_by(ProjectReview.project_id, ProjectReview.review_number)
    if project_id is not None:
        query = query.where(ProjectReview.project_id == project_id)
    return list(session.scalars(query).all())


def build_observations(session: Session, project_id: int | None = None) -> list[Observation]:
    reviews = load_review_records(session, project_id)
    grouped: dict[int, list[ProjectReview]] = {}
    for review in reviews:
        grouped.setdefault(review.project_id, []).append(review)
    observations: list[Observation] = []
    for project_reviews in grouped.values():
        for index, current in enumerate(project_reviews[:-1]):
            following = project_reviews[index + 1]
            current_categories = sorted({finding.category for finding in current.findings})
            if not current_categories:
                continue
            history = project_reviews[: index + 1]
            previous_categories = [finding.category for review in project_reviews[:index] for finding in review.findings]
            next_categories = sorted({finding.category for finding in following.findings})
            feature_review_ids = tuple(review.id for review in history)
            feature_max_timestamp = max(review.timestamp.isoformat() for review in history)
            for target in next_categories:
                observations.append(Observation(
                    current.project_id, current.id, current.review_number, current.timestamp.isoformat(),
                    make_features(history, current, previous_categories), target, current_categories[-1],
                    target_review_id=following.id,
                    target_timestamp=following.timestamp.isoformat(),
                    feature_review_ids=feature_review_ids,
                    feature_max_timestamp=feature_max_timestamp,
                ))
    return observations


def make_features(history: list[ProjectReview], current: ProjectReview, previous_categories: list[str] | None = None) -> dict[str, float]:
    findings = [finding for review in history for finding in review.findings]
    categories = [finding.category for finding in findings]
    recent = categories[-5:]
    features: dict[str, float] = {}
    metrics = current.metrics or {}
    for severity in ("critical", "high", "medium", "low"):
        features[f"static_{severity}_findings"] = float(metrics.get(severity, 0))
    features["static_total_findings"] = float(len(current.findings))
    snapshot = current.snapshot or {}
    features["static_complexity_index"] = float(snapshot.get("file_count", 0))
    for key in ("security", "testing", "architecture", "dependency", "configuration"):
        feature_key = "config" if key == "configuration" else key
        features[f"static_{feature_key}_risk"] = float(sum(f.category == key and f.severity in {"critical", "high"} for f in current.findings))
    features["static_requirement_coverage"] = float(snapshot.get("requirement_coverage", 0))
    latest = categories[-1] if categories else None
    for category in FAILURE_CATEGORIES:
        features[f"latest_failure_{category}"] = float(category == latest)
        features[f"seq_freq_{category}"] = float(categories.count(category))
        positions = [i for i, value in enumerate(categories) if value == category]
        features[f"seq_recency_{category}"] = float(len(categories) - positions[-1]) if positions else float(len(categories) + 1)
        streak = 0
        for review in reversed(history):
            if any(f.category == category for f in review.findings): streak += 1
            else: break
        features[f"seq_repetition_{category}"] = float(streak)
        transitions = sum(1 for a, b in zip(categories, categories[1:]) if a == category or b == category)
        features[f"seq_transition_{category}"] = float(transitions)
        features[f"seq_component_{category}"] = float(sum(f.category == category and (f.component or f.file) is not None for f in findings))
    features["seq_failure_diversity_recent"] = float(len(set(recent)))
    features["seq_change_intensity"] = float(len((snapshot.get("recent_churn") or "").splitlines()))
    features["seq_testing_weakness"] = float(sum(f.category == "testing" for f in current.findings))
    severity_values = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    current_severity = sum(severity_values.get(f.severity, 0) for f in current.findings)
    prior_severity = sum(severity_values.get(f.severity, 0) for f in history[-2].findings) if len(history) > 1 else current_severity
    features["seq_severity_trajectory"] = float(current_severity - prior_severity)
    return features


def dataset_status(session: Session) -> dict[str, Any]:
    reviews = load_review_records(session)
    observations = build_observations(session)
    projects = {review.project_id for review in reviews}
    targets = sorted({observation.target for observation in observations})
    timestamps = sorted(observation.timestamp for observation in observations) or sorted(
        review.timestamp.isoformat() for review in reviews
    )
    ready = (
        len(observations) >= 10
        and len(targets) >= 2
        and len({(o.project_id, o.review_id) for o in observations}) >= 3
    )
    return {
        "dataset_version": PROJECT_REVIEW_DATASET_VERSION,
        "projects": len(projects),
        "reviews": len(reviews),
        "transitions": sum(max(0, len([r for r in reviews if r.project_id == p]) - 1) for p in projects),
        "training_observations": len(observations),
        "failure_categories": len(targets),
        "failure_category_list": targets,
        "date_range": {"first": timestamps[0], "last": timestamps[-1]} if timestamps else None,
        "status": "READY" if ready else "INSUFFICIENT DATA FOR VALID MODEL EVALUATION",
        "message": "Observations are chronological and targets come only from the next persisted review.",
    }


def compute_dataset_hash(observations: list[Observation]) -> str:
    """Deterministic hash of the chronological observation set (dataset versioning)."""
    payload = [
        {
            "project_id": row.project_id,
            "review_id": row.review_id,
            "review_number": row.review_number,
            "timestamp": row.timestamp,
            "target": row.target,
            "features": {name: round(row.features.get(name, 0.0), 12) for name in sorted(row.features)},
        }
        for row in sorted(observations, key=lambda r: (r.timestamp, r.project_id, r.review_number, r.target))
    ]
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def build_prediction_features(session: Session, project_id: int) -> tuple[dict[str, float], dict[str, Any]] | None:
    """Build the feature vector for the project's most recent review (online prediction).

    Returns None when the project has no persisted reviews. Only evidence at or
    before the latest review is used; no future review exists to leak from.
    """
    reviews = load_review_records(session, project_id)
    if not reviews:
        return None
    latest = reviews[-1]
    categories = [finding.category for review in reviews for finding in review.findings]
    features = make_features(reviews, latest)
    evidence = {
        "review_count": len(reviews),
        "latest_review_number": latest.review_number,
        "latest_review_timestamp": latest.timestamp.isoformat(),
        "findings_in_latest_review": len(latest.findings),
        "observed_categories": sorted(set(categories)),
        "recent_categories": categories[-5:],
        "transition_count": max(0, len(reviews) - 1),
        "note": "Historical evidence describes past reviews only; it does not guarantee future failures.",
    }
    return features, evidence

# Compatibility adapters for the pre-existing research package surface.
def load_real_reviews(session: Session, project_id: int | None = None):
    return load_review_records(session, project_id)

class SimulationConfig: pass
def load_or_build_simulated_reviews(*_args, **_kwargs):
    return []
def run_simulation(*_args, **_kwargs):
    return []
