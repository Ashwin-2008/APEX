"""MISTIQ-APR ablation study over walk-forward temporal cutoffs.

Each variant removes exactly one sequential feature group (or switches to the
static-only representation) and is re-evaluated with the same chronological
splits as the full model. Only measured results are written to the report; when
the dataset is too small the report states the unavailability message instead
of numbers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

from .artifacts import artifacts_root
from .constants import (
    ABLATION_UNAVAILABLE_MESSAGE,
    ALL_FEATURE_NAMES,
    STATIC_FEATURE_NAMES,
    SEQ_COMPONENT_FEATURE_NAMES,
    SEQ_FREQUENCY_FEATURE_NAMES,
    SEQ_RECENCY_FEATURE_NAMES,
    SEQ_REPETITION_FEATURE_NAMES,
    SEQ_TRANSITION_FEATURE_NAMES,
)
from .dataset import Observation
from .evaluation import metrics
from .models import MISTIQ_APR, fit_predict
from .temporal import WALK_FORWARD_COMPLETED, WalkForwardSplit, generate_walk_forward_splits

ABLATION_REPORT_FILENAME = "MISTIQ_APR_ABLATION_REPORT.md"

_FULL = tuple(ALL_FEATURE_NAMES)


def _without(*names: str) -> list[str]:
    removed = set(names)
    return [name for name in ALL_FEATURE_NAMES if name not in removed]


# Evaluation order: reference model first, then each single-group removal.
ABLATION_VARIANTS: list[dict[str, Any]] = [
    {"variant": "Static only", "removed": "all sequential features", "features": list(STATIC_FEATURE_NAMES)},
    {"variant": "Full MISTIQ-APR", "removed": None, "features": list(_FULL)},
    {"variant": "MISTIQ-APR without frequency", "removed": "failure frequency", "features": _without(*SEQ_FREQUENCY_FEATURE_NAMES)},
    {"variant": "MISTIQ-APR without recency", "removed": "failure recency", "features": _without(*SEQ_RECENCY_FEATURE_NAMES)},
    {"variant": "MISTIQ-APR without repetition", "removed": "failure repetition", "features": _without(*SEQ_REPETITION_FEATURE_NAMES)},
    {"variant": "MISTIQ-APR without transitions", "removed": "failure transitions", "features": _without(*SEQ_TRANSITION_FEATURE_NAMES)},
    {"variant": "MISTIQ-APR without component history", "removed": "component history", "features": _without(*SEQ_COMPONENT_FEATURE_NAMES)},
    {"variant": "MISTIQ-APR without failure diversity", "removed": "recent failure diversity", "features": _without("seq_failure_diversity_recent")},
    {"variant": "MISTIQ-APR without change intensity", "removed": "change intensity", "features": _without("seq_change_intensity")},
    {"variant": "MISTIQ-APR without testing weakness", "removed": "testing weakness", "features": _without("seq_testing_weakness")},
    {"variant": "MISTIQ-APR without severity trajectory", "removed": "severity trajectory", "features": _without("seq_severity_trajectory")},
]


def _evaluate_variant(
    variant: dict[str, Any],
    splits: list[WalkForwardSplit],
    global_classes: list[str],
) -> dict[str, Any]:
    pooled_actual: list[str] = []
    pooled_probabilities: list[list[float]] = []
    for split in splits:
        spec = {"model": variant["variant"], "kind": "logistic", "features": variant["features"]}
        probabilities, _ = fit_predict(spec, list(split.train), list(split.test), global_classes)
        pooled_actual.extend(row.target for row in split.test)
        pooled_probabilities.extend(np.round(np.asarray(probabilities, dtype=float), 8).tolist())
    result_metrics = metrics(pooled_actual, np.asarray(pooled_probabilities, dtype=float), global_classes)
    return {
        "variant": variant["variant"],
        "removed": variant["removed"],
        "feature_count": len(variant["features"]),
        "status": "EVALUATED",
        "metrics": {
            "sample_count": result_metrics["sample_count"],
            "accuracy": result_metrics["accuracy"],
            "macro_f1": result_metrics["macro_f1"],
            "top_3_accuracy": result_metrics["top_3_accuracy"],
        },
        "delta_macro_f1": None,
    }


def run_ablation(
    observations: list[Observation],
    splits: list[WalkForwardSplit] | None = None,
) -> dict[str, Any]:
    """Run the ablation study on the same walk-forward splits as the evaluation."""
    if splits is None:
        splits, walk_status, walk_message = generate_walk_forward_splits(observations)
    else:
        walk_status, walk_message = WALK_FORWARD_COMPLETED, f"{len(splits)} walk-forward cutoffs"
    if walk_status != WALK_FORWARD_COMPLETED or not splits:
        result = {
            "status": ABLATION_UNAVAILABLE_MESSAGE,
            "results": [],
            "n_cutoffs": 0,
            "message": walk_message,
            "report_path": str(_write_ablation_report(None, [])),
        }
        return result

    global_classes = sorted({row.target for row in observations})
    rows = [_evaluate_variant(variant, splits, global_classes) for variant in ABLATION_VARIANTS]
    full_f1 = next((row["metrics"]["macro_f1"] for row in rows if row["variant"] == "Full MISTIQ-APR"), None)
    for row in rows:
        if full_f1 is not None:
            row["delta_macro_f1"] = row["metrics"]["macro_f1"] - full_f1
    return {
        "status": "ABLATION EVALUATION AVAILABLE",
        "results": rows,
        "n_cutoffs": len(splits),
        "message": f"Measured on {len(splits)} walk-forward cutoffs; pooled across cutoffs.",
        "report_path": str(_write_ablation_report(walk_message, rows)),
    }


def _write_ablation_report(walk_message: str | None, rows: list[dict[str, Any]]):
    from pathlib import Path

    destination = artifacts_root() / ABLATION_REPORT_FILENAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# MISTIQ-APR Ablation Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "Protocol: walk-forward temporal evaluation (features removed one group at a time,",
        "retrained on the same expanding chronological cutoffs as the full model).",
        "Only measured results appear below; no numbers are placeholders.",
        "",
    ]
    if not rows:
        lines += [ABLATION_UNAVAILABLE_MESSAGE, ""]
    else:
        lines += [
            f"Walk-forward: {walk_message}",
            "",
            "| Variant | Removed feature group | Features | Accuracy | Macro F1 | Top-3 | Δ Macro F1 vs full |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for row in rows:
            row_metrics = row["metrics"]
            delta = row["delta_macro_f1"]
            delta_text = "—" if delta is None else f"{delta:+.4f}"
            lines.append(
                f"| {row['variant']} | {row['removed'] or '—'} | {row['feature_count']} "
                f"| {row_metrics['accuracy']:.4f} | {row_metrics['macro_f1']:.4f} "
                f"| {row_metrics['top_3_accuracy']:.4f} | {delta_text} |"
            )
        lines += [
            "",
            "Interpretation: Δ Macro F1 compares each ablated variant against the full",
            "MISTIQ-APR model on identical cutoffs. Positive values mean the ablated model",
            "scored higher without that feature group on this dataset.",
            "",
        ]
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination

