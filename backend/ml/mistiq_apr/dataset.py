from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import ProjectFinding, ProjectReview, ReviewedProject
from .constants import (
    FAILURE_CATEGORIES,
    MIN_DISTINCT_CATEGORIES_FOR_EVALUATION,
    MIN_DISTINCT_TIMEPOINTS_FOR_EVALUATION,
    MIN_OBSERVATIONS_FOR_EVALUATION,
    PROJECT_REVIEW_DATASET_VERSION,
    SEVERITY_RANK,
    WALK_FORWARD_MIN_TRAIN_OBSERVATIONS,
)

DATA_CATEGORY_VERIFIED_DEFECT = "verified_defect_example"
DATA_CATEGORY_ANALYZER_RISK = "analyzer_detected_risk"
DATA_CATEGORY_HISTORICAL_TRANSITION = "historical_failure_transition"
DATA_CATEGORY_UNLABELED_SNAPSHOT = "unlabeled_repository_snapshot"
DATA_CATEGORY_SYNTHETIC_TEST = "synthetic_test_example"

SYNTHETIC_PATH_PATTERNS = re.compile(
    r"(?i)(appdata[\\/]+local[\\/]+temp|[/\\]tmp[/\\]|pytest-of-|"
    r"mistiq_(?:e2e|complete|direct|live|diag)|showcase|synthetic)"
)


@dataclass(frozen=True)
class Observation:
    """One chronological training example: state at review N -> target in review N+1.

    The audit and provenance fields allow leakage validators and experiment
    runners to verify that features were built strictly from evidence at or
    before the observation timestamp, that the target review never leaked into
    feature construction, and that each observation can be traced to its source
    repository, review transition, and labeling method.
    """

    project_id: int
    review_id: int
    review_number: int
    timestamp: str
    features: dict[str, float]
    target: str
    previous_category: str | None
    # Review the target label came from (review N+1). None when unknown.
    target_review_id: int | None = None
    # Timestamp of the review the target label came from.
    target_timestamp: str | None = None
    # Reviews whose findings contributed to the feature vector (review N and earlier).
    feature_review_ids: tuple[int, ...] = field(default_factory=tuple)
    # Latest timestamp among reviews that contributed to the feature vector.
    feature_max_timestamp: str | None = None
    # Provenance & data quality fields (Task A / Phase 3 & 4).
    repository_group: str = ""
    is_synthetic: bool = False
    data_category: str = DATA_CATEGORY_HISTORICAL_TRANSITION
    label_confidence: float = 0.7
    label_evidence: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    language_group: str = "unknown"
    size_bucket: str = "small"

    @property
    def key(self) -> tuple[int, int, str]:
        """Stable identity used for duplicate detection and preprocessing audits."""
        return (self.project_id, self.review_id, self.target)

    @property
    def transition_key(self) -> tuple[int, int]:
        """Identity of the chronological transition (project_id, source_review_id)."""
        return (self.project_id, self.review_id)

    @property
    def feature_hash(self) -> str:
        """Deterministic SHA-256 of the feature vector."""
        rounded = {name: round(float(self.features.get(name, 0.0)), 12) for name in sorted(self.features)}
        return hashlib.sha256(json.dumps(rounded, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def is_synthetic_project_record(
    name: str | None,
    repository_path: str | None,
    repository_url: str | None = None,
) -> bool:
    """Return True when a project record comes from a synthetic/temp E2E test fixture."""
    combined = f"{name or ''} {repository_path or ''} {repository_url or ''}"
    return bool(SYNTHETIC_PATH_PATTERNS.search(combined))


def canonical_repository_group(
    project_id: int,
    name: str | None,
    repository_path: str | None,
    repository_url: str | None = None,
) -> str:
    """Normalize repository identity so duplicate/nested paths share a group ID."""
    if is_synthetic_project_record(name, repository_path, repository_url):
        lower_name = (name or "").lower()
        match = re.match(r"^(mistiq_[a-z0-9_]+?)_[a-z0-9]{6,10}$", lower_name)
        prefix = match.group(1) if match else "synthetic_e2e_fixture"
        return f"synthetic:{prefix}"
    if repository_url:
        cleaned = repository_url.strip().lower().removesuffix(".git").rstrip("/")
        return f"url:{cleaned}"
    if repository_path:
        norm = str(repository_path).strip().replace("\\", "/").rstrip("/")
        parts = [p for p in norm.split("/") if p]
        # Collapse duplicate consecutive folder names such as .../MISTIQ/MISTIQ or .../SakshaDatathon/Saksha_Datathon
        if len(parts) >= 2:
            last_norm = re.sub(r"[^a-z0-9]", "", parts[-1].lower())
            prev_norm = re.sub(r"[^a-z0-9]", "", parts[-2].lower())
            if last_norm and last_norm == prev_norm:
                parts = parts[:-1]
        return "repo:" + "/".join(parts).lower()
    return f"project:{project_id}"


def infer_language_group(snapshot: dict[str, Any] | None) -> str:
    """Classify dominant programming language from a review snapshot."""
    mix = (snapshot or {}).get("language_mix") or {}
    if not isinstance(mix, dict) or not mix:
        return "unknown"
    code_map = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".java": "java",
        ".go": "go",
        ".rb": "ruby",
        ".php": "php",
        ".rs": "rust",
    }
    counts: Counter[str] = Counter()
    for ext, count in mix.items():
        lang = code_map.get(str(ext).lower())
        if lang and isinstance(count, (int, float)):
            counts[lang] += int(count)
    if not counts:
        return "other"
    return counts.most_common(1)[0][0]


def infer_size_bucket(snapshot: dict[str, Any] | None) -> str:
    """Classify repository size by file count."""
    file_count = int((snapshot or {}).get("file_count", 0) or 0)
    if file_count <= 5:
        return "tiny"
    if file_count <= 50:
        return "small"
    if file_count <= 500:
        return "medium"
    return "large"


def select_primary_target(current: ProjectReview, following: ProjectReview) -> tuple[str | None, dict[str, Any]]:
    """Select the single primary next-failure category for a review transition.

    Target selection hierarchy (documented for Task A):
    1. Categories of findings in review N+1 whose fingerprint was NOT active in
       review N (newly introduced or reopened failures), ranked by highest
       severity (critical > high > medium > low), highest analyzer confidence,
       finding count in review N+1, and deterministic alphabetical tie-breaker.
    2. If all findings in review N+1 were already active in review N (persistent
       failures), rank active categories in review N+1 by highest severity,
       highest confidence, count, and alphabetical tie-breaker.
    """
    if not following.findings:
        return None, {"reason": "no_findings_in_next_review"}

    current_fps = {f.fingerprint for f in current.findings}
    next_findings = list(following.findings)
    newly_active = [f for f in next_findings if f.fingerprint not in current_fps]
    candidate_pool = newly_active if newly_active else next_findings
    transition_type = "newly_introduced_or_reopened" if newly_active else "persistent_active"

    by_category: dict[str, list[ProjectFinding]] = {}
    for finding in candidate_pool:
        by_category.setdefault(finding.category, []).append(finding)

    def _score(cat: str) -> tuple[int, float, int, str]:
        items = by_category[cat]
        best_sev_rank = min(SEVERITY_RANK.get(str(f.severity).lower(), 99) for f in items)
        max_conf = max(float(f.confidence or 0.0) for f in items)
        # Negate count and confidence for ascending sort or invert best_sev_rank for descending sort
        return (-best_sev_rank, round(max_conf, 6), len(items), -FAILURE_CATEGORIES.index(cat) if cat in FAILURE_CATEGORIES else -99)

    ranked = sorted(by_category.keys(), key=lambda c: (_score(c)[0], _score(c)[1], _score(c)[2], c), reverse=True)
    # Fix tie-breaker so alphabetical is deterministic
    ranked = sorted(
        by_category.keys(),
        key=lambda c: (
            min(SEVERITY_RANK.get(str(f.severity).lower(), 99) for f in by_category[c]),
            -max(float(f.confidence or 0.0) for f in by_category[c]),
            -len(by_category[c]),
            c,
        ),
    )
    winner = ranked[0]
    active_targets = sorted({f.category for f in next_findings})
    newly_introduced_categories = sorted({f.category for f in newly_active})
    return winner, {
        "primary_target": winner,
        "transition_type": transition_type,
        "active_targets": active_targets,
        "newly_introduced_categories": newly_introduced_categories,
        "next_review_finding_count": len(next_findings),
    }


def compute_label_metadata(
    project: ReviewedProject | None,
    current: ProjectReview,
    following: ProjectReview,
    target: str,
) -> tuple[float, str, dict[str, Any], dict[str, Any], bool, str]:
    """Compute label confidence, data category, label evidence, provenance, is_synthetic, and repo_group."""
    name = project.name if project else None
    repo_path = project.repository_path if project else (current.snapshot or {}).get("path")
    repo_url = project.repository_url if project else None
    source_type = project.source_type if project else "local"
    commit_sha = project.current_commit_sha if project else None

    synthetic = is_synthetic_project_record(name, repo_path, repo_url)
    repo_group = canonical_repository_group(current.project_id, name, repo_path, repo_url)

    primary_target, primary_meta = select_primary_target(current, following)
    current_fps = {f.fingerprint for f in current.findings}
    target_findings = [f for f in following.findings if f.category == target]
    new_target_findings = [f for f in target_findings if f.fingerprint not in current_fps]
    has_commit_evidence = any(bool(f.related_commit) for f in target_findings) or bool(commit_sha)
    has_reopened = any(str(f.status).upper() == "REOPENED" for f in target_findings)
    bugfix_count = int((following.snapshot or {}).get("bugfix_commit_count", 0) or 0)
    max_analyzer_conf = max((float(f.confidence or 0.7) for f in target_findings), default=0.7)

    if synthetic:
        data_category = DATA_CATEGORY_SYNTHETIC_TEST
        label_confidence = round(min(0.35, 0.25 * max_analyzer_conf), 4)
        labeling_method = "synthetic_e2e_fixture_transition"
    elif new_target_findings and (has_commit_evidence or has_reopened or bugfix_count > 0):
        data_category = DATA_CATEGORY_VERIFIED_DEFECT
        label_confidence = round(min(0.98, 0.75 + 0.20 * max_analyzer_conf), 4)
        labeling_method = "verified_transition_with_commit_or_lifecycle_evidence"
    elif new_target_findings:
        data_category = DATA_CATEGORY_HISTORICAL_TRANSITION
        label_confidence = round(min(0.90, 0.65 + 0.20 * max_analyzer_conf), 4)
        labeling_method = "chronological_newly_introduced_finding"
    else:
        data_category = DATA_CATEGORY_ANALYZER_RISK
        label_confidence = round(min(0.75, 0.50 + 0.20 * max_analyzer_conf), 4)
        labeling_method = "persistent_analyzer_finding_transition"

    label_evidence = {
        **primary_meta,
        "is_primary_target": target == primary_target,
        "target_finding_count": len(target_findings),
        "new_or_reopened_count": len(new_target_findings),
        "analyzer_sources": sorted({f.analyzer_source for f in target_findings if f.analyzer_source}),
        "max_analyzer_confidence": round(max_analyzer_conf, 4),
        "has_commit_evidence": has_commit_evidence,
    }
    provenance = {
        "project_id": current.project_id,
        "project_name": name,
        "repository_path": repo_path,
        "repository_url": repo_url,
        "source_type": source_type,
        "commit_sha": commit_sha,
        "source_review_id": current.id,
        "source_review_number": current.review_number,
        "target_review_id": following.id,
        "target_review_number": following.review_number,
        "labeling_method": labeling_method,
        "dataset_version": PROJECT_REVIEW_DATASET_VERSION,
    }
    return label_confidence, data_category, label_evidence, provenance, synthetic, repo_group


def load_review_records(session: Session, project_id: int | None = None) -> list[ProjectReview]:
    query = (
        select(ProjectReview)
        .options(selectinload(ProjectReview.findings), selectinload(ProjectReview.project))
        .order_by(ProjectReview.project_id, ProjectReview.review_number)
    )
    if project_id is not None:
        query = query.where(ProjectReview.project_id == project_id)
    return list(session.scalars(query).all())


def build_observations(session: Session, project_id: int | None = None) -> list[Observation]:
    """Build all chronological observations from persisted reviews.

    Preserves exact compatibility with the v1.0 dataset contract while attaching
    provenance, repository grouping, synthetic detection, and label confidence.
    """
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
            features = make_features(history, current, previous_categories)
            project_obj = getattr(current, "project", None)
            lang_group = infer_language_group(current.snapshot)
            sz_bucket = infer_size_bucket(current.snapshot)
            for target in next_categories:
                conf, data_cat, lbl_ev, prov, is_syn, repo_grp = compute_label_metadata(
                    project_obj, current, following, target
                )
                observations.append(
                    Observation(
                        current.project_id,
                        current.id,
                        current.review_number,
                        current.timestamp.isoformat(),
                        features,
                        target,
                        current_categories[-1],
                        target_review_id=following.id,
                        target_timestamp=following.timestamp.isoformat(),
                        feature_review_ids=feature_review_ids,
                        feature_max_timestamp=feature_max_timestamp,
                        repository_group=repo_grp,
                        is_synthetic=is_syn,
                        data_category=data_cat,
                        label_confidence=conf,
                        label_evidence=lbl_ev,
                        provenance=prov,
                        language_group=lang_group,
                        size_bucket=sz_bucket,
                    )
                )
    return observations


def build_curated_observations(
    session: Session,
    project_id: int | None = None,
    *,
    exclude_synthetic: bool = True,
    primary_target_only: bool = True,
    deduplicate: bool = True,
    min_label_confidence: float = 0.0,
) -> list[Observation]:
    """Build provenance-validated, non-exploded observations for scientific training.

    Unlike raw ``build_observations`` (which explodes a multi-finding review into
    multiple identical feature vectors with different single-class labels and
    includes temporary E2E test directories), ``build_curated_observations``:
    - Excludes synthetic/temporary test directories when ``exclude_synthetic=True``.
    - Assigns one primary target per transition when ``primary_target_only=True``.
    - Deduplicates identical ``(repository_group, feature_hash, target)`` rows
      when ``deduplicate=True``.
    - Enforces ``min_label_confidence``.
    """
    raw = build_observations(session, project_id)
    filtered: list[Observation] = []
    seen_dedup: set[tuple[str, str, str]] = set()

    for obs in raw:
        if exclude_synthetic and obs.is_synthetic:
            continue
        if primary_target_only and not obs.label_evidence.get("is_primary_target", True):
            continue
        if obs.label_confidence < min_label_confidence:
            continue
        if deduplicate:
            dedup_key = (obs.repository_group, obs.feature_hash, obs.target)
            if dedup_key in seen_dedup:
                continue
            seen_dedup.add(dedup_key)
        filtered.append(obs)
    return filtered


def make_features(
    history: list[ProjectReview],
    current: ProjectReview,
    previous_categories: list[str] | None = None,
) -> dict[str, float]:
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
        features[f"static_{feature_key}_risk"] = float(
            sum(f.category == key and f.severity in {"critical", "high"} for f in current.findings)
        )
    features["static_requirement_coverage"] = float(snapshot.get("requirement_coverage", 0))
    latest = categories[-1] if categories else None
    for category in FAILURE_CATEGORIES:
        features[f"latest_failure_{category}"] = float(category == latest)
        features[f"seq_freq_{category}"] = float(categories.count(category))
        positions = [i for i, value in enumerate(categories) if value == category]
        features[f"seq_recency_{category}"] = (
            float(len(categories) - positions[-1]) if positions else float(len(categories) + 1)
        )
        streak = 0
        for review in reversed(history):
            if any(f.category == category for f in review.findings):
                streak += 1
            else:
                break
        features[f"seq_repetition_{category}"] = float(streak)
        transitions = sum(1 for a, b in zip(categories, categories[1:]) if a == category or b == category)
        features[f"seq_transition_{category}"] = float(transitions)
        features[f"seq_component_{category}"] = float(
            sum(f.category == category and (f.component or f.file) is not None for f in findings)
        )
    features["seq_failure_diversity_recent"] = float(len(set(recent)))
    features["seq_change_intensity"] = float(len((snapshot.get("recent_churn") or "").splitlines()))
    features["seq_testing_weakness"] = float(sum(f.category == "testing" for f in current.findings))
    severity_values = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    current_severity = sum(severity_values.get(f.severity, 0) for f in current.findings)
    prior_severity = (
        sum(severity_values.get(f.severity, 0) for f in history[-2].findings)
        if len(history) > 1
        else current_severity
    )
    features["seq_severity_trajectory"] = float(current_severity - prior_severity)
    return features


def audit_dataset(session: Session) -> dict[str, Any]:
    """Comprehensive provenance, duplication, and label-quality audit of persisted data."""
    projects = list(session.scalars(select(ReviewedProject).order_by(ReviewedProject.id)).all())
    reviews = load_review_records(session)
    raw_observations = build_observations(session)
    curated_real = build_curated_observations(
        session, exclude_synthetic=True, primary_target_only=True, deduplicate=True
    )
    curated_all_primary = build_curated_observations(
        session, exclude_synthetic=False, primary_target_only=True, deduplicate=False
    )

    reviews_by_project: dict[int, list[ProjectReview]] = {}
    for rev in reviews:
        reviews_by_project.setdefault(rev.project_id, []).append(rev)

    real_projects = [
        p for p in projects if not is_synthetic_project_record(p.name, p.repository_path, p.repository_url)
    ]
    synthetic_projects = [
        p for p in projects if is_synthetic_project_record(p.name, p.repository_path, p.repository_url)
    ]
    real_project_ids = {p.id for p in real_projects}
    repo_groups = {
        canonical_repository_group(p.id, p.name, p.repository_path, p.repository_url) for p in projects
    }
    real_repo_groups = {
        canonical_repository_group(p.id, p.name, p.repository_path, p.repository_url) for p in real_projects
    }

    unlabeled_snapshots = sum(1 for p in projects if len(reviews_by_project.get(p.id, [])) < 2)
    transitions_without_labels = 0
    total_transitions = 0
    for proj_revs in reviews_by_project.values():
        for idx, curr in enumerate(proj_revs[:-1]):
            total_transitions += 1
            nxt = proj_revs[idx + 1]
            if not curr.findings or not nxt.findings:
                transitions_without_labels += 1

    missing_label_pct = (
        round((transitions_without_labels / total_transitions) * 100.0, 2) if total_transitions > 0 else 0.0
    )

    feature_hashes = Counter(obs.feature_hash for obs in raw_observations)
    feature_target_hashes = Counter((obs.feature_hash, obs.target) for obs in raw_observations)
    exact_duplicates = sum(count - 1 for count in feature_target_hashes.values() if count > 1)
    duplicate_pct = (
        round((exact_duplicates / len(raw_observations)) * 100.0, 2) if raw_observations else 0.0
    )

    data_categories = Counter(obs.data_category for obs in raw_observations)
    data_categories[DATA_CATEGORY_UNLABELED_SNAPSHOT] = unlabeled_snapshots

    confidence_bins = {
        "high_gte_0_8": sum(1 for o in raw_observations if o.label_confidence >= 0.8),
        "medium_0_5_to_0_8": sum(1 for o in raw_observations if 0.5 <= o.label_confidence < 0.8),
        "low_lt_0_5": sum(1 for o in raw_observations if o.label_confidence < 0.5),
    }

    return {
        "total_projects": len(projects),
        "unique_repository_groups": len(repo_groups),
        "unique_real_repository_groups": len(real_repo_groups),
        "real_projects": len(real_projects),
        "synthetic_temp_projects": len(synthetic_projects),
        "total_reviews": len(reviews),
        "real_reviews": sum(len(reviews_by_project.get(pid, [])) for pid in real_project_ids),
        "synthetic_reviews": sum(
            len(reviews_by_project.get(p.id, [])) for p in synthetic_projects
        ),
        "total_transitions": total_transitions,
        "real_transitions": sum(
            max(0, len(reviews_by_project.get(pid, [])) - 1) for pid in real_project_ids
        ),
        "synthetic_transitions": sum(
            max(0, len(reviews_by_project.get(p.id, [])) - 1) for p in synthetic_projects
        ),
        "raw_observations": len(raw_observations),
        "curated_real_observations": len(curated_real),
        "curated_primary_observations": len(curated_all_primary),
        "unique_feature_vectors": len(feature_hashes),
        "unique_feature_target_pairs": len(feature_target_hashes),
        "duplicate_observations": exact_duplicates,
        "duplicate_observation_percentage": duplicate_pct,
        "transitions_without_labels": transitions_without_labels,
        "missing_label_percentage": missing_label_pct,
        "data_categories": dict(data_categories),
        "label_confidence_distribution": confidence_bins,
        "category_distribution_raw": dict(Counter(o.target for o in raw_observations)),
        "category_distribution_curated_real": dict(Counter(o.target for o in curated_real)),
        "language_distribution": dict(Counter(o.language_group for o in raw_observations)),
        "size_bucket_distribution": dict(Counter(o.size_bucket for o in raw_observations)),
        "repositories_with_sufficient_history": {
            "gte_2_reviews_total": sum(1 for revs in reviews_by_project.values() if len(revs) >= 2),
            "gte_2_reviews_real": sum(
                1 for pid in real_project_ids if len(reviews_by_project.get(pid, [])) >= 2
            ),
            "gte_3_reviews_total": sum(1 for revs in reviews_by_project.values() if len(revs) >= 3),
            "gte_3_reviews_real": sum(
                1 for pid in real_project_ids if len(reviews_by_project.get(pid, [])) >= 3
            ),
            "gte_5_reviews_total": sum(1 for revs in reviews_by_project.values() if len(revs) >= 5),
            "gte_5_reviews_real": sum(
                1 for pid in real_project_ids if len(reviews_by_project.get(pid, [])) >= 5
            ),
        },
        "data_origin": (
            "mixed"
            if real_projects and synthetic_projects
            else "synthetic"
            if synthetic_projects
            else "real"
            if real_projects
            else "empty"
        ),
        "traceable_provenance": all(bool(o.provenance.get("source_review_id")) for o in raw_observations),
    }


def dataset_status(session: Session) -> dict[str, Any]:
    reviews = load_review_records(session)
    observations = build_observations(session)
    projects = {review.project_id for review in reviews}
    targets = sorted({observation.target for observation in observations})
    timestamps = sorted(observation.timestamp for observation in observations) or sorted(
        review.timestamp.isoformat() for review in reviews
    )
    ready = (
        len(observations) >= MIN_OBSERVATIONS_FOR_EVALUATION
        and len(targets) >= MIN_DISTINCT_CATEGORIES_FOR_EVALUATION
        and len({(o.project_id, o.review_id) for o in observations}) >= MIN_DISTINCT_TIMEPOINTS_FOR_EVALUATION
    )
    quality = audit_dataset(session)
    return {
        "dataset_version": PROJECT_REVIEW_DATASET_VERSION,
        "projects": len(projects),
        "reviews": len(reviews),
        "transitions": sum(max(0, len([r for r in reviews if r.project_id == p]) - 1) for p in projects),
        "training_observations": len(observations),
        "distinct_timepoints": len({(o.project_id, o.review_id) for o in observations}),
        "failure_categories": len(targets),
        "failure_category_list": targets,
        "date_range": {"first": timestamps[0], "last": timestamps[-1]} if timestamps else None,
        "status": "READY" if ready else "INSUFFICIENT DATA FOR VALID MODEL EVALUATION",
        "message": "Observations are chronological and targets come only from the next persisted review.",
        "evaluation_requirements": {
            "min_observations": MIN_OBSERVATIONS_FOR_EVALUATION,
            "min_distinct_categories": MIN_DISTINCT_CATEGORIES_FOR_EVALUATION,
            "min_distinct_timepoints": MIN_DISTINCT_TIMEPOINTS_FOR_EVALUATION,
            "min_walk_forward_train_observations": WALK_FORWARD_MIN_TRAIN_OBSERVATIONS,
        },
        "quality_audit": quality,
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
    category_counts = Counter(categories)
    latest_categories = sorted({f.category for f in latest.findings})
    recurring_categories = sorted([cat for cat, cnt in category_counts.items() if cnt > 1])
    component_locations = sorted(
        {
            f"{f.file}:{f.line}" if f.file and f.line else (f.file or f.component)
            for f in latest.findings
            if f.file or f.component
        }
    )
    evidence = {
        "review_count": len(reviews),
        "latest_review_number": latest.review_number,
        "latest_review_timestamp": latest.timestamp.isoformat(),
        "findings_in_latest_review": len(latest.findings),
        "latest_review_categories": latest_categories,
        "observed_categories": sorted(set(categories)),
        "recent_categories": categories[-5:],
        "category_frequencies": dict(category_counts),
        "recurring_categories": recurring_categories,
        "localized_components": component_locations[:10],
        "transition_count": max(0, len(reviews) - 1),
        "note": "Historical evidence describes past reviews only; it does not guarantee future failures.",
    }
    return features, evidence


# Compatibility adapters for the pre-existing research package surface.
def load_real_reviews(session: Session, project_id: int | None = None):
    return load_review_records(session, project_id)


class SimulationConfig:
    pass


def load_or_build_simulated_reviews(*_args, **_kwargs):
    return []


def run_simulation(*_args, **_kwargs):
    return []
