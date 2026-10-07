"""Chronological (never shuffled) walk-forward split generation.

Walk-forward protocol:

    Cutoff 1: Train → earliest observations        Test → next timepoint group
    Cutoff 2: Train → observations up to cutoff 2  Test → next timepoint group
    Cutoff k: Train → all observations strictly before the cutoff timepoint
              Test  → every observation at the next timepoint

Observations are ordered by (timestamp, project_id, review_number, target) and
split at timepoint-group boundaries only. Training always contains strictly
earlier observations than the test group it is evaluated on. Random shuffling
never occurs.
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


def _next_boundary(boundaries: list[int], current: int, total: int) -> int:
    for boundary in boundaries:
        if boundary > current:
            return boundary
    return total
