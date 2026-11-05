"""Temporal Dataset Builder and Chronological Splitter (Phase 4).

Generates walk-forward chronological datasets with zero temporal leakage.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import ProjectFinding, ProjectReview, ReviewedProject
from .constants import (
    FAILURE_CATEGORIES,
    MIN_OBSERVATIONS_FOR_TRAINING,
    PREDICTIVE_DATASET_VERSION,
    ProvenanceClassification,
)
from .feature_engineering import TemporalFeatureExtractor
from .label_quality import LabelQualityAssessor


@dataclass(frozen=True)
class TemporalObservation:
    """A single chronological observation: state at review N -> target at review N+1."""

    project_id: int
    source_review_id: int
    source_timestamp: str
    target_review_id: int | None
    target_timestamp: str | None
    features: dict[str, float]
    target: str
    provenance_classification: str
    label_confidence: float
    repository_group: str
    is_synthetic: bool
    label_evidence: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def target_label(self) -> str:
        return self.target

    @property
    def repository_id(self) -> str:
        return self.repository_group

    @property
    def timestamp(self) -> str:
        return self.source_timestamp

    @property
    def feature_hash(self) -> str:
        rounded = {k: round(float(v), 8) for k, v in sorted(self.features.items())}
        return hashlib.sha256(json.dumps(rounded, sort_keys=True).encode()).hexdigest()


class TemporalDatasetEngine:
    """Orchestrates temporal dataset extraction, leakage validation, and chronological splits."""

    @classmethod
    def build_observations_from_db(
        cls,
        session: Session,
        project_id: int | None = None,
        *,
        exclude_synthetic: bool = True,
    ) -> list[TemporalObservation]:
        """Builds chronological observations from persisted project reviews in the database."""
        query = (
            select(ProjectReview)
            .options(selectinload(ProjectReview.findings), selectinload(ProjectReview.project))
            .order_by(ProjectReview.project_id, ProjectReview.review_number)
        )
        if project_id is not None:
            query = query.where(ProjectReview.project_id == project_id)

        reviews = list(session.scalars(query).all())
        grouped: dict[int, list[ProjectReview]] = {}
        for r in reviews:
            grouped.setdefault(r.project_id, []).append(r)

        observations: list[TemporalObservation] = []
        for pid, p_reviews in grouped.items():
            if len(p_reviews) < 2:
                continue

            project = p_reviews[0].project
            name = project.name if project else f"proj_{pid}"
            repo_path = project.repository_path if project else ""
            repo_url = project.repository_url if project else None

            is_syn = LabelQualityAssessor.is_synthetic(name, repo_path, repo_url)
            if exclude_synthetic and is_syn:
                continue

            repo_group = f"repo:{repo_path.replace('\\', '/').lower()}" if repo_path else f"project:{pid}"

            for idx, current in enumerate(p_reviews[:-1]):
                following = p_reviews[idx + 1]
                history = p_reviews[: idx + 1]

                current_fps = {f.fingerprint for f in current.findings}
                next_findings = following.findings or []
                if not next_findings:
                    continue

                # Prioritize newly introduced or reopened categories
                newly_introduced = [f for f in next_findings if f.fingerprint not in current_fps]
                candidate_pool = newly_introduced if newly_introduced else next_findings

                # Primary target selection
                by_cat: dict[str, list[ProjectFinding]] = {}
                for f in candidate_pool:
                    if f.category:
                        by_cat.setdefault(f.category, []).append(f)

                if not by_cat:
                    continue

                primary_cat = sorted(by_cat.keys(), key=lambda c: len(by_cat[c]), reverse=True)[0]
                target_findings = by_cat[primary_cat]

                has_commit = any(bool(f.related_commit) for f in target_findings)
                has_reopened = any(str(f.status).upper() == "REOPENED" for f in target_findings)

                prov_tier, conf, _ = LabelQualityAssessor.classify_provenance(
                    name=name,
                    repository_path=repo_path,
                    repository_url=repo_url,
                    has_commit_evidence=has_commit,
                    has_lifecycle_evidence=has_reopened or len(target_findings) > 0,
                    sample_count=len(target_findings),
                )

                # Extract features strictly with cutoff at current review timestamp
                cur_ts_str = current.timestamp.isoformat() if isinstance(current.timestamp, datetime) else str(current.timestamp)
                features = TemporalFeatureExtractor.extract_features(
                    history_reviews=history,
                    current_review=current,
                    cutoff_timestamp=current.timestamp,
                )

                following_ts_str = following.timestamp.isoformat() if isinstance(following.timestamp, datetime) else str(following.timestamp)

                observations.append(
                    TemporalObservation(
                        project_id=pid,
                        source_review_id=current.id,
                        source_timestamp=cur_ts_str,
                        target_review_id=following.id,
                        target_timestamp=following_ts_str,
                        features=features,
                        target=primary_cat,
                        provenance_classification=prov_tier.value,
                        label_confidence=conf,
                        repository_group=repo_group,
                        is_synthetic=is_syn,
                        label_evidence={
                            "new_finding_count": len(newly_introduced),
                            "target_finding_count": len(target_findings),
                            "has_commit": has_commit,
                        },
                        provenance={
                            "project_name": name,
                            "dataset_version": PREDICTIVE_DATASET_VERSION,
                        },
                    )
                )

        return observations

    @classmethod
    def load_curated_dataset_file(cls, jsonl_path: Path | str) -> list[TemporalObservation]:
        """Loads curated offline observations from jsonl file (e.g. dataset_v001.jsonl)."""
        p = Path(jsonl_path)
        if not p.is_file():
            return []

        observations: list[TemporalObservation] = []
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line_s = line.strip()
                if not line_s:
                    continue
                row = json.loads(line_s)
                obs = TemporalObservation(
                    project_id=row.get("project_id", 0),
                    source_review_id=row.get("review_id", 0),
                    source_timestamp=row.get("timestamp", ""),
                    target_review_id=row.get("target_review_id"),
                    target_timestamp=row.get("target_timestamp"),
                    features=row.get("features", {}),
                    target=row.get("target", "unknown"),
                    provenance_classification=row.get("data_category", ProvenanceClassification.CURATED_REAL.value),
                    label_confidence=float(row.get("label_confidence", 0.8)),
                    repository_group=row.get("repository_group", "repo:curated"),
                    is_synthetic=bool(row.get("is_synthetic", False)),
                    label_evidence=row.get("label_evidence", {}),
                    provenance=row.get("provenance", {}),
                )
                observations.append(obs)

        return observations

    @classmethod
    def validate_leakage(cls, observations: list[TemporalObservation]) -> dict[str, Any]:
        """Validates that no future target, commits, timestamps, or entities leaked into feature vectors."""
        from .leakage_audit import TemporalLeakageAuditor
        return TemporalLeakageAuditor.audit_observations(observations)

    @classmethod
    def generate_walk_forward_splits(
        cls,
        observations: list[TemporalObservation],
        min_train_size: int = 15,
        test_size: int = 5,
    ) -> list[tuple[list[TemporalObservation], list[TemporalObservation]]]:
        """Generates strictly chronological walk-forward partitions without temporal shuffling."""
        sorted_obs = sorted(observations, key=lambda o: (o.source_timestamp or "", o.source_review_id))
        splits: list[tuple[list[TemporalObservation], list[TemporalObservation]]] = []

        n = len(sorted_obs)
        if n < min_train_size + test_size:
            split_idx = max(1, int(n * 0.75))
            return [(sorted_obs[:split_idx], sorted_obs[split_idx:])]

        current_end = min_train_size
        while current_end + test_size <= n:
            train_part = sorted_obs[:current_end]
            test_part = sorted_obs[current_end : current_end + test_size]
            splits.append((train_part, test_part))
            current_end += test_size

        return splits

    @classmethod
    def generate_repository_grouped_splits(
        cls,
        observations: list[TemporalObservation],
        n_groups_test: int = 2,
    ) -> list[tuple[list[TemporalObservation], list[TemporalObservation]]]:
        """Ensures observations from the same repository cannot appear in both train and test splits."""
        repo_to_obs: dict[str, list[TemporalObservation]] = {}
        for o in observations:
            repo_to_obs.setdefault(o.repository_group, []).append(o)

        unique_repos = sorted(repo_to_obs.keys())
        if len(unique_repos) <= 1:
            # Cannot do repository grouping with <= 1 repository
            return cls.generate_walk_forward_splits(observations)

        splits: list[tuple[list[TemporalObservation], list[TemporalObservation]]] = []
        n_repos = len(unique_repos)

        # Create folds by partitioning repositories
        step = max(1, n_groups_test)
        for i in range(0, n_repos, step):
            test_repos = set(unique_repos[i : i + step])
            train_repos = set(unique_repos) - test_repos
            if not train_repos:
                continue
            train_part = [o for o in observations if o.repository_group in train_repos]
            test_part = [o for o in observations if o.repository_group in test_repos]
            if train_part and test_part:
                splits.append((train_part, test_part))

        return splits

    @classmethod
    def generate_leave_one_repo_out_splits(
        cls,
        observations: list[TemporalObservation],
        min_repo_observations: int = 5,
    ) -> dict[str, Any]:
        """Leaves one eligible repository out for testing and trains on all remaining eligible repositories."""
        repo_to_obs: dict[str, list[TemporalObservation]] = {}
        for o in observations:
            repo_to_obs.setdefault(o.repository_group, []).append(o)

        eligible_repos: dict[str, list[TemporalObservation]] = {}
        excluded_repos: dict[str, int] = {}

        for repo, obs_list in repo_to_obs.items():
            if len(obs_list) >= min_repo_observations:
                eligible_repos[repo] = obs_list
            else:
                excluded_repos[repo] = len(obs_list)

        loro_folds: list[dict[str, Any]] = []
        for held_out_repo, test_obs in eligible_repos.items():
            train_obs = [
                o for r, obs_list in eligible_repos.items() if r != held_out_repo for o in obs_list
            ]
            loro_folds.append({
                "held_out_repository": held_out_repo,
                "test_observations": test_obs,
                "train_observations": train_obs,
                "test_sample_size": len(test_obs),
                "train_sample_size": len(train_obs),
            })

        return {
            "folds": loro_folds,
            "eligible_repositories": list(eligible_repos.keys()),
            "eligible_count": len(eligible_repos),
            "excluded_repositories": excluded_repos,
            "excluded_count": len(excluded_repos),
        }

