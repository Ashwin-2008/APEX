"""Chronological (never shuffled) walk-forward and repository-grouped split generation.

Walk-forward protocol:

    Cutoff 1: Train -> earliest observations        Test -> next timepoint group
    Cutoff 2: Train -> observations up to cutoff 2  Test -> next timepoint group
    Cutoff k: Train -> all observations strictly before the cutoff timepoint
              Test  -> every observation at the next timepoint

Repository-grouped generalization protocol:

    Observations are grouped by canonical repository identity (repository_group)
    and ordered chronologically by each repository group's earliest observation.
    For each held-out repository group, training uses only observations from
    strictly other repository groups whose timestamps do not postdate the held-out
    observation, testing generalization to unseen repositories.
"""
from __future__ import annotations

from dataclasses import dataclass

from .constants import (
    MIN_DISTINCT_TIMEPOINTS_FOR_EVALUATION,
    MIN_OBSERVATIONS_FOR_EVALUATION,
    STATUS_INSUFFICIENT_WALK_FORWARD,
    WALK_FORWARD_MIN_TRAIN_OBSERVATIONS,
)
from .dataset import Observation

WALK_FORWARD_COMPLETED = "COMPLETED"
REPO_GROUPED_COMPLETED = "COMPLETED"
STATUS_INSUFFICIENT_REPO_GROUPED = "INSUFFICIENT DATA FOR REPOSITORY-GROUPED EVALUATION"


def time_key(row: Observation) -> tuple[str, int, int, str]:
    """Global chronological ordering key. Deterministic; never randomized."""
    return (row.timestamp, row.project_id, row.review_number, row.target)


@dataclass(frozen=True)
class WalkForwardSplit:
    """One walk-forward cutoff: expanding training window, next-timepoint test."""

    index: int
    train: tuple[Observation, ...]
    test: tuple[Observation, ...]
    train_start: str
    train_end: str
    test_start: str
    test_end: str

    def to_record(self) -> dict:
        return {
            "cutoff": self.index,
            "train_size": len(self.train),
            "test_size": len(self.test),
            "train_time_range": {"start": self.train_start, "end": self.train_end},
            "test_time_range": {"start": self.test_start, "end": self.test_end},
        }


def _group_boundaries(ordered: list[Observation]) -> list[int]:
    """Start indices of each distinct (timestamp, project, review) timepoint group."""
    boundaries: list[int] = []
    previous_key = None
    for index, row in enumerate(ordered):
        key = (row.timestamp, row.project_id, row.review_number)
        if key != previous_key:
            boundaries.append(index)
            previous_key = key
    return boundaries


def generate_walk_forward_splits(
    observations: list[Observation],
    min_train: int = WALK_FORWARD_MIN_TRAIN_OBSERVATIONS,
) -> tuple[list[WalkForwardSplit], str, str]:
    """Build walk-forward cutoffs over strictly chronological observations.

    Returns (splits, status, message). When data is insufficient the splits list
    is empty and status is INSUFFICIENT DATA FOR WALK-FORWARD EVALUATION with a
    message explaining exactly why.
    """
    ordered = sorted(observations, key=time_key)
    if len(ordered) < MIN_OBSERVATIONS_FOR_EVALUATION:
        return [], STATUS_INSUFFICIENT_WALK_FORWARD, (
            f"Only {len(ordered)} chronological observations are available; "
            f"at least {MIN_OBSERVATIONS_FOR_EVALUATION} are required."
        )
    boundaries = _group_boundaries(ordered)
    if len(boundaries) < MIN_DISTINCT_TIMEPOINTS_FOR_EVALUATION:
        return [], STATUS_INSUFFICIENT_WALK_FORWARD, (
            f"Only {len(boundaries)} distinct chronological timepoints are available; "
            f"at least {MIN_DISTINCT_TIMEPOINTS_FOR_EVALUATION} are required."
        )
    if len({row.target for row in ordered}) < 2:
        return [], STATUS_INSUFFICIENT_WALK_FORWARD, (
            "The dataset contains a single failure-category outcome; "
            "at least two are required."
        )
    splits: list[WalkForwardSplit] = []
    for boundary in boundaries[1:]:
        train = tuple(ordered[:boundary])
        test = tuple(ordered[boundary : _next_boundary(boundaries, boundary, len(ordered))])
        if len(train) < min_train or not test:
            continue
        if len({row.target for row in train}) < 2:
            continue
        splits.append(
            WalkForwardSplit(
                index=len(splits) + 1,
                train=train,
                test=test,
                train_start=train[0].timestamp,
                train_end=train[-1].timestamp,
                test_start=test[0].timestamp,
                test_end=test[-1].timestamp,
            )
        )
    if not splits:
        return [], STATUS_INSUFFICIENT_WALK_FORWARD, (
            "No valid cutoff exists where the expanding training window reaches "
            f"{min_train} observations with at least two outcome classes."
        )
    return splits, WALK_FORWARD_COMPLETED, (
        f"{len(splits)} walk-forward cutoffs over {len(ordered)} chronological "
        "observations; training windows expand forward and are never shuffled."
    )


def generate_repository_grouped_splits(
    observations: list[Observation],
    min_train: int = WALK_FORWARD_MIN_TRAIN_OBSERVATIONS,
) -> tuple[list[WalkForwardSplit], str, str]:
    """Build repository-grouped splits to evaluate generalization to unseen repositories.

    Each fold holds out one canonical repository group (or project_id if group
    is unset) and trains exclusively on observations from other repository groups.
    """
    ordered = sorted(observations, key=time_key)
    if len(ordered) < MIN_OBSERVATIONS_FOR_EVALUATION:
        return [], STATUS_INSUFFICIENT_REPO_GROUPED, (
            f"Only {len(ordered)} observations are available; at least "
            f"{MIN_OBSERVATIONS_FOR_EVALUATION} are required for repository-grouped evaluation."
        )

    def _group_id(row: Observation) -> str:
        return row.repository_group or f"project:{row.project_id}"

    groups: dict[str, list[Observation]] = {}
    for row in ordered:
        groups.setdefault(_group_id(row), []).append(row)

    if len(groups) < 2:
        return [], STATUS_INSUFFICIENT_REPO_GROUPED, (
            f"Only {len(groups)} distinct repository group(s) available; at least 2 are required."
        )

    ordered_group_keys = sorted(groups.keys(), key=lambda g: (groups[g][0].timestamp, g))
    splits: list[WalkForwardSplit] = []
    for held_out_group in ordered_group_keys:
        test_rows = tuple(groups[held_out_group])
        train_rows = tuple(r for r in ordered if _group_id(r) != held_out_group)
        if len(train_rows) < min_train or not test_rows:
            continue
        if len({r.target for r in train_rows}) < 2:
            continue
        splits.append(
            WalkForwardSplit(
                index=len(splits) + 1,
                train=train_rows,
                test=test_rows,
                train_start=train_rows[0].timestamp,
                train_end=train_rows[-1].timestamp,
                test_start=test_rows[0].timestamp,
                test_end=test_rows[-1].timestamp,
            )
        )

    if not splits:
        return [], STATUS_INSUFFICIENT_REPO_GROUPED, (
            "No repository group has a complementary training set with at least "
            f"{min_train} observations and two outcome classes."
        )
    return splits, REPO_GROUPED_COMPLETED, (
        f"{len(splits)} unseen-repository holdout folds across {len(groups)} repository groups."
    )


def generate_chronological_holdout_split(
    observations: list[Observation],
    train_fraction: float = 0.70,
    val_fraction: float = 0.15,
) -> dict[str, tuple[Observation, ...]]:
    """Split observations chronologically at timepoint boundaries into train, val, and untouched test."""
    ordered = sorted(observations, key=time_key)
    if not ordered:
        return {"train": (), "validation": (), "test": ()}
    boundaries = _group_boundaries(ordered)
    if len(boundaries) < 3:
        n = len(ordered)
        t_end = max(1, int(n * train_fraction))
        v_end = max(t_end, int(n * (train_fraction + val_fraction)))
        return {
            "train": tuple(ordered[:t_end]),
            "validation": tuple(ordered[t_end:v_end]),
            "test": tuple(ordered[v_end:]),
        }

    n_groups = len(boundaries)
    train_g = max(1, int(round(n_groups * train_fraction)))
    val_g = max(train_g + 1, min(n_groups - 1, int(round(n_groups * (train_fraction + val_fraction)))))
    train_idx = boundaries[min(train_g, len(boundaries) - 1)]
    val_idx = boundaries[min(val_g, len(boundaries) - 1)]
    return {
        "train": tuple(ordered[:train_idx]),
        "validation": tuple(ordered[train_idx:val_idx]),
        "test": tuple(ordered[val_idx:]),
    }


def _next_boundary(boundaries: list[int], current: int, total: int) -> int:
    for boundary in boundaries:
        if boundary > current:
            return boundary
    return total
