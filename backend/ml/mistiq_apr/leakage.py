"""Automated data-leakage validation for the MISTIQ-APR research pipeline.

The evaluation refuses to run when any critical (error-level) check fails.
Checks verified:

1. Temporal leakage    — no feature timestamp may be later than the observation
                         timestamp it describes.
2. Target leakage      — the next-review target review must never contribute to
                         the feature construction of the current observation.
3. Duplicate observations — (project_id, review_id, target) must be unique.
4. Future preprocessing leakage — scalers/encoders must be fitted on training
                         rows only (verified numerically against a train-only
                         refit, plus fit-scope bookkeeping).
5. Cross-project leakage — the same project may appear in training and testing
                         only when its training observations are strictly
                         earlier than its test observations (documented as an
                         explicit warning when it occurs).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from .dataset import Observation
from .temporal import WalkForwardSplit

CHECK_TEMPORAL = "temporal_leakage"
CHECK_TARGET = "target_leakage"
CHECK_DUPLICATES = "duplicate_observations"
CHECK_PREPROCESSING = "future_preprocessing_leakage"
CHECK_CROSS_PROJECT = "cross_project_leakage"


def _parse(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp)


def _check(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def validate_leakage(
    observations: list[Observation],
    splits: list[WalkForwardSplit] | None = None,
    preprocessing_reports: list[dict] | None = None,
) -> dict:
    """Run every leakage check and return a structured pass/fail report.

    ``passed`` is False when any check reports an error; evaluation must not run
    in that case. ``warnings`` document accepted-by-policy conditions such as
    strictly-earlier same-project observations in both train and test.
    """
    checks: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Temporal leakage: features must not postdate their observation.
    temporal_errors: list[str] = []
    for row in observations:
        if row.feature_max_timestamp is None:
            temporal_errors.append(
                f"project {row.project_id} review {row.review_id}: feature timestamps were not recorded"
            )
            continue
        try:
            if _parse(row.feature_max_timestamp) > _parse(row.timestamp):
                temporal_errors.append(
                    f"project {row.project_id} review {row.review_id}: feature timestamp "
                    f"{row.feature_max_timestamp} is later than observation timestamp {row.timestamp}"
                )
        except ValueError:
            temporal_errors.append(
                f"project {row.project_id} review {row.review_id}: unparseable timestamp"
            )
    if temporal_errors:
        checks.append(_check(CHECK_TEMPORAL, "failed", "; ".join(temporal_errors[:5])))
        errors.extend(temporal_errors)
    else:
        checks.append(_check(
            CHECK_TEMPORAL, "passed",
            f"All {len(observations)} observations carry feature timestamps at or before their observation time.",
        ))

    # 2. Target leakage: target review must not feed the feature construction.
    target_errors: list[str] = []
    for row in observations:
        if row.target_review_id is None:
            continue
        if row.target_review_id in row.feature_review_ids:
            target_errors.append(
                f"project {row.project_id} review {row.review_id}: target review "
                f"{row.target_review_id} contributed features for target '{row.target}'"
            )
    if target_errors:
        checks.append(_check(CHECK_TARGET, "failed", "; ".join(target_errors[:5])))
        errors.extend(target_errors)
    else:
        checks.append(_check(
            CHECK_TARGET, "passed",
            "No next-review target review appears in any feature construction.",
        ))

    # 3. Duplicate observations: project_id + review_id + target must be unique.
    counts = Counter(row.key for row in observations)
    duplicates = {key: count for key, count in counts.items() if count > 1}
    if duplicates:
        detail = "; ".join(
            f"project {key[0]} review {key[1]} target '{key[2]}' x{count}"
            for key, count in list(duplicates.items())[:5]
        )
        checks.append(_check(CHECK_DUPLICATES, "failed", detail))
        errors.append(f"duplicate observations detected: {detail}")
    else:
        checks.append(_check(
            CHECK_DUPLICATES, "passed",
            f"All {len(observations)} observations are unique on (project_id, review_id, target).",
        ))

    # 4. Future preprocessing leakage: scalers/encoders fitted on training rows only.
    if preprocessing_reports is None:
        checks.append(_check(
            CHECK_PREPROCESSING, "skipped",
            "No preprocessing objects exist at this stage; train-only fitting is "
            "verified numerically whenever the evaluation fits a model.",
        ))
    else:
        preprocessing_errors: list[str] = []
        for report in preprocessing_reports:
            if report.get("scaler_fit_on_train_only") is False:
                preprocessing_errors.append(
                    f"{report.get('model', 'model')}: scaler statistics differ from a "
                    "train-only refit - preprocessing saw non-training rows"
                )
            fit_keys = set(map(tuple, report.get("fit_observation_keys", [])))
            train_keys = set(map(tuple, report.get("train_observation_keys", [])))
            if fit_keys - train_keys:
                preprocessing_errors.append(
                    f"{report.get('model', 'model')}: fitted on "
                    f"{len(fit_keys - train_keys)} non-training observations"
                )
        if preprocessing_errors:
            checks.append(_check(CHECK_PREPROCESSING, "failed", "; ".join(preprocessing_errors[:5])))
            errors.extend(preprocessing_errors)
        else:
            checks.append(_check(
                CHECK_PREPROCESSING, "passed",
                f"All {len(preprocessing_reports)} fitted preprocessing objects were verified "
                "against a train-only refit.",
            ))

    # 5. Cross-project leakage policy: same project in train and test is only
    # acceptable when its training observations are strictly earlier.
    if not splits:
        checks.append(_check(
            CHECK_CROSS_PROJECT, "skipped",
            "Split-level check runs together with walk-forward split generation.",
        ))
    else:
        cross_errors: list[str] = []
        overlapping: set[int] = set()
        for split in splits:
            train_times: dict[int, list[str]] = {}
            test_times: dict[int, list[str]] = {}
            for row in split.train:
                train_times.setdefault(row.project_id, []).append(row.timestamp)
            for row in split.test:
                test_times.setdefault(row.project_id, []).append(row.timestamp)
            for project_id, test_stamps in test_times.items():
                if project_id not in train_times:
                    continue
                overlapping.add(project_id)
                latest_train = max(train_times[project_id])
                earliest_test = min(test_stamps)
                try:
                    strictly_earlier = _parse(latest_train) < _parse(earliest_test)
                except ValueError:
                    strictly_earlier = False
                if not strictly_earlier:
                    cross_errors.append(
                        f"project {project_id}: training observation at {latest_train} is not "
                        f"strictly earlier than test observation at {earliest_test} (cutoff {split.index})"
                    )
        if cross_errors:
            checks.append(_check(CHECK_CROSS_PROJECT, "failed", "; ".join(cross_errors[:5])))
            errors.extend(cross_errors)
        elif overlapping:
            detail = (
                f"Projects {sorted(overlapping)} appear in both training and test sets. This is "
                "accepted for temporal project prediction because their training observations are "
                "strictly earlier than their test observations."
            )
            checks.append(_check(CHECK_CROSS_PROJECT, "passed", detail))
            warnings.append(detail)
        else:
            checks.append(_check(
                CHECK_CROSS_PROJECT, "passed",
                "No project appears in both training and test sets.",
            ))

    return {
        "passed": not errors,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }


