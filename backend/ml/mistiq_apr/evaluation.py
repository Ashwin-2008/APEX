from __future__ import annotations

from typing import Any
import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, log_loss, precision_score, recall_score

from .constants import (
    ALL_FEATURE_NAMES,
    STATUS_INSUFFICIENT_EVALUATION,
    STATUS_INSUFFICIENT_WALK_FORWARD,
    STATUS_VALID_EVALUATION,
)
from .dataset import Observation
from .leakage import validate_leakage
from .models import MODEL_SPECS, MISTIQ_APR, feature_matrix, fit_predict
from .temporal import WALK_FORWARD_COMPLETED, generate_walk_forward_splits

WALK_FORWARD_METHOD = (
    "Walk-forward temporal evaluation: observations are ordered by timestamp and "
    "scored at expanding chronological cutoffs. Training always contains strictly "
    "earlier observations than the test group it predicts; no shuffling occurs."
)
REFUSED_STATUS = "EVALUATION REFUSED: DATA LEAKAGE DETECTED"


def _matrix(rows: list[Observation], names: list[str] | None = None):
    names = names or list(ALL_FEATURE_NAMES)
    return feature_matrix(rows, names), [row.target for row in rows]


def metrics(y_true, probabilities, classes) -> dict[str, Any]:
    predictions = [classes[int(np.argmax(row))] for row in probabilities]
    labels = list(classes)
    return {"sample_count": len(y_true), "accuracy": float(accuracy_score(y_true, predictions)), "macro_precision": float(precision_score(y_true, predictions, labels=labels, average="macro", zero_division=0)), "macro_recall": float(recall_score(y_true, predictions, labels=labels, average="macro", zero_division=0)), "macro_f1": float(f1_score(y_true, predictions, labels=labels, average="macro", zero_division=0)), "top_2_accuracy": float(np.mean([actual in [classes[i] for i in np.argsort(row)[-2:]] for actual, row in zip(y_true, probabilities)])), "top_3_accuracy": float(np.mean([actual in [classes[i] for i in np.argsort(row)[-3:]] for actual, row in zip(y_true, probabilities)])), "log_loss": float(log_loss(y_true, probabilities, labels=labels)) if len(set(y_true)) > 1 else None, "confusion_matrix": confusion_matrix(y_true, predictions, labels=labels).tolist(), "labels": labels}


def evaluate_model(name: str, train: list[Observation], test: list[Observation], kind: str = "logistic", feature_names: list[str] | None = None) -> dict[str, Any]:
    """Evaluate a single model on one chronological train/test pair (legacy helper)."""
    if not train or not test or len({row.target for row in train}) < 2:
        return {"model": name, "status": "INSUFFICIENT DATA", "metrics": None}
    global_classes = sorted({row.target for row in train + test})
    spec = {"model": name, "kind": kind, "features": feature_names}
    probabilities, _ = fit_predict(spec, train, test, global_classes)
    return {"model": name, "status": "EVALUATED", "metrics": metrics([row.target for row in test], probabilities, global_classes), "classes": global_classes}


def _refusal(leakage: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": REFUSED_STATUS,
        "refused": True,
        "results": [],
        "walk_forward_splits": 0,
        "leakage": leakage,
        "walk_forward": {
            "status": "REFUSED",
            "message": "Evaluation refused because critical data leakage was detected.",
            "n_cutoffs": 0,
            "cutoffs": [],
        },
        "methodology": WALK_FORWARD_METHOD,
    }


def evaluate_temporal(observations: list[Observation]) -> dict[str, Any]:
    """Walk-forward temporal evaluation with automated leakage refusal.

    Observations are sorted chronologically and never shuffled. For every valid
    cutoff the record stores training size, test size, training/test time
    ranges, predictions, actual labels, and metrics for each model; results are
    pooled across all valid cutoffs for the aggregate comparison.
    """
    splits, walk_status, walk_message = generate_walk_forward_splits(observations)
    leakage = validate_leakage(observations, splits)
    if not leakage["passed"]:
        return _refusal(leakage)
    if walk_status != WALK_FORWARD_COMPLETED:
        return {
            "status": STATUS_INSUFFICIENT_EVALUATION,
            "results": [],
            "walk_forward_splits": 0,
            "leakage": leakage,
            "walk_forward": {"status": walk_status, "message": walk_message, "n_cutoffs": 0, "cutoffs": []},
            "methodology": WALK_FORWARD_METHOD,
        }

    global_classes = sorted({row.target for row in observations})
    pooled_actual: dict[str, list[str]] = {spec["model"]: [] for spec in MODEL_SPECS}
    pooled_probabilities: dict[str, list[list[float]]] = {spec["model"]: [] for spec in MODEL_SPECS}
    cutoff_records: list[dict[str, Any]] = []
    preprocessing_reports: list[dict[str, Any]] = []

    for split in splits:
        record = split.to_record()
        record["models"] = {}
        for spec in MODEL_SPECS:
            probabilities, report = fit_predict(spec, list(split.train), list(split.test), global_classes)
            if report is not None:
                preprocessing_reports.append(report)
            actual = [row.target for row in split.test]
            predictions = [global_classes[int(np.argmax(row))] for row in probabilities]
            model_metrics = metrics(actual, probabilities, global_classes)
            record["models"][spec["model"]] = {
                "predictions": predictions,
                "actual": actual,
                "probabilities": np.round(np.asarray(probabilities, dtype=float), 8).tolist(),
                "metrics": model_metrics,
            }
            pooled_actual[spec["model"]].extend(actual)
            pooled_probabilities[spec["model"]].extend(np.round(np.asarray(probabilities, dtype=float), 8).tolist())
        primary = record["models"][MISTIQ_APR]
        record["predictions"] = primary["predictions"]
        record["actual"] = primary["actual"]
        record["metrics"] = primary["metrics"]
        cutoff_records.append(record)

    leakage = validate_leakage(observations, splits, preprocessing_reports)
    if not leakage["passed"]:
        return _refusal(leakage)

    results = [
        {
            "model": spec["model"],
            "status": "EVALUATED",
            "metrics": metrics(pooled_actual[spec["model"]], np.asarray(pooled_probabilities[spec["model"]], dtype=float), global_classes),
            "n_cutoffs": len(splits),
        }
        for spec in MODEL_SPECS
    ]
    return {
        "status": STATUS_VALID_EVALUATION,
        "refused": False,
        "results": results,
        "walk_forward_splits": len(splits),
        "leakage": leakage,
        "walk_forward": {
            "status": WALK_FORWARD_COMPLETED,
            "message": walk_message,
            "n_cutoffs": len(splits),
            "cutoffs": cutoff_records,
            "total_test_predictions": sum(len(split.test) for split in splits),
            "global_classes": global_classes,
        },
        "train_observations": len(observations),
        "methodology": WALK_FORWARD_METHOD,
    }

PipelineStatus = str
PipelineReport = dict


def run_mistiq_apr_pipeline(observations=None, *_args, **_kwargs):
    """Compatibility adapter: run the temporal evaluation on given observations."""
    rows = observations if isinstance(observations, list) else []
    return evaluate_temporal(rows)


def build_evaluation_report(result):
    return result


def save_evaluation_to_disk(result, path):
    import json
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return target
