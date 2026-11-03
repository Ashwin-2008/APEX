from __future__ import annotations

from typing import Any
import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_recall_fscore_support,
    precision_score,
    recall_score,
)

from .constants import (
    ALL_FEATURE_NAMES,
    STATUS_INSUFFICIENT_EVALUATION,
    STATUS_INSUFFICIENT_WALK_FORWARD,
    STATUS_VALID_EVALUATION,
)
from .dataset import Observation
from .leakage import validate_leakage
from .models import MODEL_SPECS, MISTIQ_APR, feature_matrix, fit_predict
from .temporal import (
    REPO_GROUPED_COMPLETED,
    WALK_FORWARD_COMPLETED,
    generate_chronological_holdout_split,
    generate_repository_grouped_splits,
    generate_walk_forward_splits,
)

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
    prec_arr, rec_arr, f1_arr, sup_arr = precision_recall_fscore_support(
        y_true, predictions, labels=labels, average=None, zero_division=0
    )
    per_category = {
        str(lbl): {
            "precision": float(prec_arr[idx]),
            "recall": float(rec_arr[idx]),
            "f1": float(f1_arr[idx]),
            "support": int(sup_arr[idx]),
        }
        for idx, lbl in enumerate(labels)
    }
    return {
        "sample_count": len(y_true),
        "accuracy": float(accuracy_score(y_true, predictions)),
        "macro_precision": float(precision_score(y_true, predictions, labels=labels, average="macro", zero_division=0)),
        "macro_recall": float(recall_score(y_true, predictions, labels=labels, average="macro", zero_division=0)),
        "macro_f1": float(f1_score(y_true, predictions, labels=labels, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, predictions, labels=labels, average="weighted", zero_division=0)),
        "top_2_accuracy": float(
            np.mean([actual in [classes[i] for i in np.argsort(row)[-2:]] for actual, row in zip(y_true, probabilities)])
        ),
        "top_3_accuracy": float(
            np.mean([actual in [classes[i] for i in np.argsort(row)[-3:]] for actual, row in zip(y_true, probabilities)])
        ),
        "log_loss": float(log_loss(y_true, probabilities, labels=labels)) if len(set(y_true)) > 1 else None,
        "confusion_matrix": confusion_matrix(y_true, predictions, labels=labels).tolist(),
        "per_category": per_category,
        "labels": labels,
    }


def evaluate_model(
    name: str,
    train: list[Observation],
    test: list[Observation],
    kind: str = "logistic",
    feature_names: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate a single model on one chronological train/test pair (legacy helper)."""
    if not train or not test or len({row.target for row in train}) < 2:
        return {"model": name, "status": "INSUFFICIENT DATA", "metrics": None}
    global_classes = sorted({row.target for row in train + test})
    spec = {"model": name, "kind": kind, "features": feature_names}
    probabilities, _ = fit_predict(spec, train, test, global_classes)
    return {
        "model": name,
        "status": "EVALUATED",
        "metrics": metrics([row.target for row in test], probabilities, global_classes),
        "classes": global_classes,
    }


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


def evaluate_temporal(
    observations: list[Observation],
    extra_specs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
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

    specs = list(MODEL_SPECS)
    if extra_specs:
        existing_names = {s["model"] for s in specs}
        for es in extra_specs:
            if es["model"] not in existing_names:
                specs.append(es)
                existing_names.add(es["model"])

    global_classes = sorted({row.target for row in observations})
    pooled_actual: dict[str, list[str]] = {spec["model"]: [] for spec in specs}
    pooled_probabilities: dict[str, list[list[float]]] = {spec["model"]: [] for spec in specs}
    pooled_test_obs: dict[str, list[Observation]] = {spec["model"]: [] for spec in specs}
    cutoff_records: list[dict[str, Any]] = []
    preprocessing_reports: list[dict[str, Any]] = []

    for split in splits:
        record = split.to_record()
        record["models"] = {}
        for spec in specs:
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
            pooled_test_obs[spec["model"]].extend(split.test)
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
            "metrics": metrics(
                pooled_actual[spec["model"]],
                np.asarray(pooled_probabilities[spec["model"]], dtype=float),
                global_classes,
            ),
            "n_cutoffs": len(splits),
        }
        for spec in specs
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


def _compute_subgroup_metrics(
    test_obs: list[Observation],
    probabilities: np.ndarray,
    global_classes: list[str],
) -> dict[str, Any]:
    """Compute subgroup performance across language, repository size, and label confidence."""
    subgroups: dict[str, dict[str, Any]] = {
        "by_language": {},
        "by_size_bucket": {},
        "by_label_confidence": {},
    }
    if not test_obs or len(test_obs) != len(probabilities):
        return subgroups

    def _eval_slice(indices: list[int]) -> dict[str, Any] | None:
        if not indices:
            return None
        y_sub = [test_obs[i].target for i in indices]
        p_sub = probabilities[indices]
        m = metrics(y_sub, p_sub, global_classes)
        return {
            "sample_count": m["sample_count"],
            "accuracy": m["accuracy"],
            "macro_f1": m["macro_f1"],
            "weighted_f1": m["weighted_f1"],
            "top_2_accuracy": m["top_2_accuracy"],
        }

    langs = sorted({o.language_group for o in test_obs})
    for lang in langs:
        idxs = [i for i, o in enumerate(test_obs) if o.language_group == lang]
        res = _eval_slice(idxs)
        if res:
            subgroups["by_language"][lang] = res

    sizes = sorted({o.size_bucket for o in test_obs})
    for sz in sizes:
        idxs = [i for i, o in enumerate(test_obs) if o.size_bucket == sz]
        res = _eval_slice(idxs)
        if res:
            subgroups["by_size_bucket"][sz] = res

    high_idxs = [i for i, o in enumerate(test_obs) if o.label_confidence >= 0.8]
    med_idxs = [i for i, o in enumerate(test_obs) if o.label_confidence < 0.8]
    if high_idxs:
        subgroups["by_label_confidence"]["high_gte_0_8"] = _eval_slice(high_idxs)
    if med_idxs:
        subgroups["by_label_confidence"]["medium_lt_0_8"] = _eval_slice(med_idxs)

    return subgroups


def evaluate_candidate_comprehensive(
    observations: list[Observation],
    candidate_spec: dict[str, Any],
) -> dict[str, Any]:
    """Run comprehensive Phase 6 evaluation for a candidate model specification:
    1. Walk-forward temporal evaluation against all baselines.
    2. Chronological holdout split (70% train / 15% val / 15% test).
    3. Unseen-repository grouped evaluation (leave-one-repository-group-out).
    4. Subgroup evaluation (language, size bucket, label confidence).
    """
    cand_name = candidate_spec["model"]
    temporal_res = evaluate_temporal(observations, extra_specs=[candidate_spec])

    # Extract pooled test observations and candidate probabilities from walk-forward
    splits, walk_status, _ = generate_walk_forward_splits(observations)
    global_classes = sorted({row.target for row in observations})
    wf_test_obs: list[Observation] = []
    wf_cand_probs: list[list[float]] = []

    if walk_status == WALK_FORWARD_COMPLETED and not temporal_res.get("refused"):
        for split in splits:
            probs, _ = fit_predict(candidate_spec, list(split.train), list(split.test), global_classes)
            wf_test_obs.extend(split.test)
            wf_cand_probs.extend(probs.tolist())

    subgroups = (
        _compute_subgroup_metrics(wf_test_obs, np.asarray(wf_cand_probs, dtype=float), global_classes)
        if wf_test_obs
        else {}
    )

    # Chronological holdout evaluation
    holdout = generate_chronological_holdout_split(observations)
    train_val = list(holdout.get("train", ())) + list(holdout.get("validation", ()))
    test_rows = list(holdout.get("test", ()))
    holdout_eval: dict[str, Any] = {
        "status": "COMPLETED" if len({r.target for r in train_val}) >= 2 and test_rows else "INSUFFICIENT_DATA"
    }
    if holdout_eval["status"] == "COMPLETED":
        h_probs, _ = fit_predict(candidate_spec, train_val, test_rows, global_classes)
        holdout_eval["metrics"] = metrics([r.target for r in test_rows], h_probs, global_classes)
        holdout_eval["train_size"] = len(train_val)
        holdout_eval["test_size"] = len(test_rows)

    # Unseen-repository grouped evaluation
    repo_splits, repo_status, repo_msg = generate_repository_grouped_splits(observations)
    repo_eval: dict[str, Any] = {"status": repo_status, "message": repo_msg, "n_folds": len(repo_splits)}
    if repo_status == REPO_GROUPED_COMPLETED and repo_splits:
        repo_leakage = validate_leakage(observations, repo_splits, require_disjoint_repo_groups=True)
        repo_eval["leakage_passed"] = repo_leakage["passed"]
        pooled_repo_y: list[str] = []
        pooled_repo_p: list[list[float]] = []
        pooled_base_p: dict[str, list[list[float]]] = {s["model"]: [] for s in MODEL_SPECS}
        for r_split in repo_splits:
            probs, _ = fit_predict(candidate_spec, list(r_split.train), list(r_split.test), global_classes)
            pooled_repo_y.extend(r.target for r in r_split.test)
            pooled_repo_p.extend(probs.tolist())
            for b_spec in MODEL_SPECS:
                b_probs, _ = fit_predict(b_spec, list(r_split.train), list(r_split.test), global_classes)
                pooled_base_p[b_spec["model"]].extend(b_probs.tolist())

        repo_eval["candidate_metrics"] = metrics(
            pooled_repo_y, np.asarray(pooled_repo_p, dtype=float), global_classes
        )
        repo_eval["baseline_comparison"] = {
            b_name: metrics(pooled_repo_y, np.asarray(b_p, dtype=float), global_classes)
            for b_name, b_p in pooled_base_p.items()
        }

    # Find candidate summary from walk-forward results
    cand_wf_metrics = None
    for item in temporal_res.get("results", []):
        if item["model"] == cand_name:
            cand_wf_metrics = item["metrics"]
            break

    return {
        "candidate_model": cand_name,
        "candidate_kind": candidate_spec["kind"],
        "status": temporal_res["status"],
        "walk_forward_metrics": cand_wf_metrics,
        "walk_forward_comparison": temporal_res.get("results", []),
        "walk_forward_splits": temporal_res.get("walk_forward_splits", 0),
        "chronological_holdout": holdout_eval,
        "unseen_repository_evaluation": repo_eval,
        "subgroup_metrics": subgroups,
        "leakage": temporal_res.get("leakage"),
        "temporal_result": temporal_res,
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
