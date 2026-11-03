"""Immutable Model Registry, Candidate Experiment Runner, Promotion Gate, and Rollback.

Implements Phases 7 and 8 of the APEX ML architecture:
- Preserves ``backend/ml/artifacts/mistiq_apr/model.pkl`` (v1.0) untouched at all times.
- Stores an immutable archive backup of ``model.pkl`` v1.0 in ``archive/model_v1.0_original/``.
- Saves every trained candidate under ``candidates/<candidate_id>/`` with all 9 required
  versioned artifacts (`model.pkl`, `metadata.json`, `metrics.json`,
  `confusion_matrix.json`, `calibration.json`, `feature_schema.json`,
  `training_config.json`, `dataset_manifest.json`, `evaluation_report.md`).
- Evaluates a strict 10-point promotion gate before allowing promotion to production.
- Supports instant, zero-retraining rollback to ``v1.0`` or any prior promoted version.
"""
from __future__ import annotations

import hashlib
import json
import pickle
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import (
    METADATA_FILENAME,
    MODEL_FILENAME,
    MISTIQAPRModelArtifact,
    artifacts_root,
    default_feature_groups,
    load_valid_artifact,
    validate_artifact,
)
from .calibration import run_calibration
from .constants import (
    ALL_FEATURE_NAMES,
    EVALUATION_PROTOCOL,
    FAILURE_CATEGORIES,
    FAILURE_LABELS,
    MIN_OBSERVATIONS_FOR_EVALUATION,
    MODEL_NAME,
    PROJECT_REVIEW_DATASET_VERSION,
    STATUS_VALID_EVALUATION,
)
from .dataset import Observation, compute_dataset_hash
from .evaluation import evaluate_candidate_comprehensive
from .models import (
    CANDIDATE_MODEL_SPECS,
    LATEST_FAILURE,
    MAJORITY,
    MISTIQ_APR,
    STATIC_LOGISTIC,
    feature_matrix,
    make_estimator,
)
from .prediction import predict_next_failure


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_registry_initialized(root: Path | None = None) -> dict[str, Any]:
    """Ensure ``archive/model_v1.0_original`` and ``production/production_manifest.json`` exist."""
    base = Path(root) if root is not None else artifacts_root()
    orig_model = base / MODEL_FILENAME
    orig_meta = base / METADATA_FILENAME
    archive_dir = base / "archive" / "model_v1.0_original"
    prod_dir = base / "production"
    candidates_dir = base / "candidates"

    archive_dir.mkdir(parents=True, exist_ok=True)
    prod_dir.mkdir(parents=True, exist_ok=True)
    candidates_dir.mkdir(parents=True, exist_ok=True)

    if orig_model.is_file() and not (archive_dir / MODEL_FILENAME).is_file():
        shutil.copy2(orig_model, archive_dir / MODEL_FILENAME)
    if orig_meta.is_file() and not (archive_dir / METADATA_FILENAME).is_file():
        shutil.copy2(orig_meta, archive_dir / METADATA_FILENAME)

    manifest_path = prod_dir / "production_manifest.json"
    if not manifest_path.is_file():
        orig_sha = _sha256_file(orig_model) if orig_model.is_file() else None
        meta_obj = {}
        if orig_meta.is_file():
            try:
                meta_obj = json.loads(orig_meta.read_text(encoding="utf-8"))
            except Exception:
                meta_obj = {}
        initial_manifest = {
            "active_version": str(meta_obj.get("version") or "1.0"),
            "active_candidate_id": "model_v1.0_original",
            "active_model_relpath": MODEL_FILENAME,
            "active_model_sha256": orig_sha,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "original_v1_backup": {
                "version": "1.0",
                "candidate_id": "model_v1.0_original",
                "model_relpath": MODEL_FILENAME,
                "archive_relpath": "archive/model_v1.0_original/model.pkl",
                "sha256": orig_sha,
            },
            "promotion_history": [
                {
                    "action": "initial_registration",
                    "version": "1.0",
                    "candidate_id": "model_v1.0_original",
                    "model_relpath": MODEL_FILENAME,
                    "sha256": orig_sha,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }
        manifest_path.write_text(json.dumps(initial_manifest, indent=2, sort_keys=True), encoding="utf-8")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def train_candidate(
    observations: list[Observation],
    algorithm: str = "hybrid_sequential",
    dataset_version: str = "v001",
    candidate_id: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Train and evaluate a new candidate model without touching production artifacts."""
    base = Path(root) if root is not None else artifacts_root()
    ensure_registry_initialized(base)

    if algorithm not in CANDIDATE_MODEL_SPECS:
        raise ValueError(
            f"Unsupported algorithm '{algorithm}'. Must be one of {sorted(CANDIDATE_MODEL_SPECS)}."
        )
    spec = dict(CANDIDATE_MODEL_SPECS[algorithm])
    ts_now = datetime.now(timezone.utc)
    ts_iso = ts_now.isoformat(timespec="seconds")
    d_hash = compute_dataset_hash(observations)

    if not candidate_id:
        existing_cands = sorted((base / "candidates").glob("model_v*"))
        next_num = len(existing_cands) + 1
        candidate_id = f"model_v{next_num:03d}_{algorithm}_{d_hash[:8]}"

    cand_dir = base / "candidates" / candidate_id
    cand_dir.mkdir(parents=True, exist_ok=True)

    # Comprehensive evaluation (walk-forward, chronological holdout, unseen-repo grouped, subgroups)
    comp_eval = evaluate_candidate_comprehensive(observations, spec)
    leakage = comp_eval.get("leakage") or {}
    if not leakage.get("passed", False):
        return {
            "trained": False,
            "candidate_id": candidate_id,
            "reason": "Data leakage check failed.",
            "evaluation": comp_eval,
        }
    if comp_eval.get("status") != STATUS_VALID_EVALUATION:
        return {
            "trained": False,
            "candidate_id": candidate_id,
            "reason": f"Evaluation status is {comp_eval.get('status')}",
            "evaluation": comp_eval,
        }
    if len(observations) < MIN_OBSERVATIONS_FOR_EVALUATION:
        return {
            "trained": False,
            "candidate_id": candidate_id,
            "reason": f"Insufficient observations ({len(observations)} < {MIN_OBSERVATIONS_FOR_EVALUATION}).",
        }

    # Fit candidate model on full curated observation set
    global_classes = sorted({row.target for row in observations})
    x_all = feature_matrix(observations, list(ALL_FEATURE_NAMES))
    y_all = [row.target for row in observations]
    estimator = make_estimator(spec["kind"])
    estimator.fit(x_all, y_all)

    # Calibration report
    temporal_for_cal = comp_eval.get("temporal_result") or {}
    calibration_report = run_calibration(temporal_for_cal)

    wf_metrics = comp_eval.get("walk_forward_metrics") or {}
    repo_eval = comp_eval.get("unseen_repository_evaluation") or {}

    version_label = f"2.0-{candidate_id}"
    metadata: dict[str, Any] = {
        "model": MODEL_NAME,
        "version": version_label,
        "model_version": version_label,
        "candidate_id": candidate_id,
        "algorithm": algorithm,
        "algorithm_description": spec.get("description", ""),
        "status": "trained",
        "stage": "candidate",
        "feature_count": len(ALL_FEATURE_NAMES),
        "feature_names": list(ALL_FEATURE_NAMES),
        "feature_groups": default_feature_groups(),
        "categories": global_classes,
        "training_observations": len(observations),
        "distinct_repository_groups": len({o.repository_group for o in observations}),
        "non_synthetic_only": all(not o.is_synthetic for o in observations),
        "dataset_version": dataset_version,
        "dataset_schema_version": PROJECT_REVIEW_DATASET_VERSION,
        "dataset_hash": d_hash,
        "trained_at": ts_iso,
        "evaluation_protocol": EVALUATION_PROTOCOL,
        "calibration_summary": {
            "available": calibration_report.get("status") == "CALIBRATED",
            "status": calibration_report.get("status"),
            "brier_score": calibration_report.get("brier_score"),
            "expected_calibration_error": calibration_report.get("expected_calibration_error"),
        },
        "evaluation_metadata": {
            "protocol": EVALUATION_PROTOCOL,
            "status": comp_eval.get("status"),
            "n_cutoffs": comp_eval.get("walk_forward_splits", 0),
            "primary_model": spec["model"],
            "primary_metrics": wf_metrics,
            "unseen_repository_metrics": repo_eval.get("candidate_metrics"),
            "chronological_holdout_metrics": (comp_eval.get("chronological_holdout") or {}).get("metrics"),
            "leakage_passed": bool(leakage.get("passed")),
        },
    }

    artifact_bundle = MISTIQAPRModelArtifact(
        model=estimator,
        metadata=metadata,
        preprocessing="standard_scaler",
        feature_names=list(ALL_FEATURE_NAMES),
        feature_groups=default_feature_groups(),
        category_mapping={str(i): c for i, c in enumerate(global_classes)},
    )

    # Save all 9 required candidate artifact files
    cand_model_path = cand_dir / MODEL_FILENAME
    cand_model_path.write_bytes(pickle.dumps(artifact_bundle))
    model_sha256 = _sha256_file(cand_model_path)
    metadata["model_sha256"] = model_sha256

    (cand_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    (cand_dir / METADATA_FILENAME).write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")

    metrics_payload = {
        "candidate_id": candidate_id,
        "algorithm": algorithm,
        "trained_at": ts_iso,
        "walk_forward_metrics": wf_metrics,
        "walk_forward_comparison": comp_eval.get("walk_forward_comparison", []),
        "chronological_holdout": comp_eval.get("chronological_holdout"),
        "unseen_repository_evaluation": repo_eval,
        "subgroup_metrics": comp_eval.get("subgroup_metrics", {}),
    }
    (cand_dir / "metrics.json").write_text(json.dumps(metrics_payload, indent=2, default=str), encoding="utf-8")

    confusion_payload = {
        "candidate_id": candidate_id,
        "labels": wf_metrics.get("labels", global_classes),
        "walk_forward_confusion_matrix": wf_metrics.get("confusion_matrix", []),
        "per_category": wf_metrics.get("per_category", {}),
        "unseen_repository_confusion_matrix": (repo_eval.get("candidate_metrics") or {}).get("confusion_matrix", []),
    }
    (cand_dir / "confusion_matrix.json").write_text(json.dumps(confusion_payload, indent=2), encoding="utf-8")

    (cand_dir / "calibration.json").write_text(json.dumps(calibration_report, indent=2, default=str), encoding="utf-8")

    feature_schema_payload = {
        "schema_version": PROJECT_REVIEW_DATASET_VERSION,
        "feature_count": len(ALL_FEATURE_NAMES),
        "feature_names": list(ALL_FEATURE_NAMES),
        "feature_groups": default_feature_groups(),
    }
    (cand_dir / "feature_schema.json").write_text(json.dumps(feature_schema_payload, indent=2), encoding="utf-8")

    training_config_payload = {
        "candidate_id": candidate_id,
        "algorithm": algorithm,
        "spec": spec,
        "random_state": 42,
        "evaluation_protocol": EVALUATION_PROTOCOL,
        "trained_at": ts_iso,
    }
    (cand_dir / "training_config.json").write_text(json.dumps(training_config_payload, indent=2), encoding="utf-8")

    dataset_manifest_payload = {
        "dataset_version": dataset_version,
        "dataset_hash": d_hash,
        "observation_count": len(observations),
        "distinct_repositories": sorted({o.repository_group for o in observations}),
        "non_synthetic_only": all(not o.is_synthetic for o in observations),
        "categories": global_classes,
        "timestamp_range": {
            "first": min(o.timestamp for o in observations),
            "last": max(o.timestamp for o in observations),
        },
    }
    (cand_dir / "dataset_manifest.json").write_text(json.dumps(dataset_manifest_payload, indent=2), encoding="utf-8")

    report_md = _render_candidate_report_md(candidate_id, metadata, metrics_payload, calibration_report)
    (cand_dir / "evaluation_report.md").write_text(report_md, encoding="utf-8")

    return {
        "trained": True,
        "candidate_id": candidate_id,
        "algorithm": algorithm,
        "path": str(cand_model_path),
        "candidate_dir": str(cand_dir),
        "model_sha256": model_sha256,
        "metadata": metadata,
        "metrics": metrics_payload,
    }


def _render_candidate_report_md(
    candidate_id: str,
    metadata: dict[str, Any],
    metrics_payload: dict[str, Any],
    calibration: dict[str, Any],
) -> str:
    wf = metrics_payload.get("walk_forward_metrics") or {}
    repo = (metrics_payload.get("unseen_repository_evaluation") or {}).get("candidate_metrics") or {}
    lines = [
        f"# Candidate Model Evaluation Report: `{candidate_id}`",
        "",
        f"- **Algorithm**: `{metadata.get('algorithm')}` ({metadata.get('algorithm_description')})",
        f"- **Trained At**: `{metadata.get('trained_at')}`",
        f"- **Dataset Version**: `{metadata.get('dataset_version')}` (`{metadata.get('dataset_hash')}`)",
        f"- **Curated Observations**: `{metadata.get('training_observations')}` across `{metadata.get('distinct_repository_groups')}` real repository groups",
        f"- **Artifact SHA-256**: `{metadata.get('model_sha256')}`",
        "",
        "## 1. Walk-Forward Temporal Comparison",
        "",
        "| Model | Accuracy | Macro Precision | Macro Recall | Macro F1 | Weighted F1 | Top-2 Acc | Top-3 Acc | Log Loss |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in metrics_payload.get("walk_forward_comparison", []):
        m = row.get("metrics") or {}
        ll = f"{m['log_loss']:.4f}" if m.get("log_loss") is not None else "N/A"
        lines.append(
            f"| {row['model']} | {m.get('accuracy', 0):.4f} | {m.get('macro_precision', 0):.4f} | "
            f"{m.get('macro_recall', 0):.4f} | {m.get('macro_f1', 0):.4f} | {m.get('weighted_f1', 0):.4f} | "
            f"{m.get('top_2_accuracy', 0):.4f} | {m.get('top_3_accuracy', 0):.4f} | {ll} |"
        )

    lines.extend(
        [
            "",
            "## 2. Unseen-Repository Generalization (Leave-One-Repository-Group-Out)",
            "",
            f"- **Sample Count**: `{repo.get('sample_count', 0)}`",
            f"- **Accuracy**: `{repo.get('accuracy', 0):.4f}`",
            f"- **Macro F1**: `{repo.get('macro_f1', 0):.4f}`",
            f"- **Weighted F1**: `{repo.get('weighted_f1', 0):.4f}`",
            f"- **Top-2 Accuracy**: `{repo.get('top_2_accuracy', 0):.4f}`",
            f"- **Top-3 Accuracy**: `{repo.get('top_3_accuracy', 0):.4f}`",
            "",
            "## 3. Calibration Summary",
            "",
            f"- **Status**: `{calibration.get('status')}`",
            f"- **Brier Score**: `{calibration.get('brier_score')}`",
            f"- **Expected Calibration Error (ECE)**: `{calibration.get('expected_calibration_error')}`",
            "",
        ]
    )
    return "\n".join(lines)


def compare_with_production(
    candidate_id: str,
    root: Path | None = None,
) -> dict[str, Any]:
    """Evaluate the 10-point promotion gate comparing ``candidate_id`` against active production."""
    base = Path(root) if root is not None else artifacts_root()
    manifest = ensure_registry_initialized(base)
    cand_dir = base / "candidates" / candidate_id
    if not cand_dir.is_dir():
        raise FileNotFoundError(f"Candidate '{candidate_id}' not found under {base / 'candidates'}")

    cand_meta = json.loads((cand_dir / "metadata.json").read_text(encoding="utf-8"))
    cand_metrics_file = json.loads((cand_dir / "metrics.json").read_text(encoding="utf-8"))
    cand_dataset = json.loads((cand_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    cand_cal = json.loads((cand_dir / "calibration.json").read_text(encoding="utf-8"))

    wf_comp = {
        row["model"]: row["metrics"]
        for row in cand_metrics_file.get("walk_forward_comparison", [])
        if row.get("metrics")
    }
    cand_wf = cand_metrics_file.get("walk_forward_metrics") or {}
    maj_wf = wf_comp.get(MAJORITY) or {}
    lat_wf = wf_comp.get(LATEST_FAILURE) or {}
    stat_wf = wf_comp.get(STATIC_LOGISTIC) or {}
    prod_arch_wf = wf_comp.get(MISTIQ_APR) or {}

    repo_eval = cand_metrics_file.get("unseen_repository_evaluation") or {}
    repo_cand = repo_eval.get("candidate_metrics") or {}
    repo_base = repo_eval.get("baseline_comparison") or {}
    repo_prod_arch = repo_base.get(MISTIQ_APR) or {}
    repo_maj = repo_base.get(MAJORITY) or {}
    repo_lat = repo_base.get(LATEST_FAILURE) or {}

    # Load candidate artifact and run smoke test
    cand_artifact, load_err = load_valid_artifact(cand_dir / MODEL_FILENAME)
    smoke_passed = False
    if cand_artifact is not None and load_err is None:
        dummy_features = {name: 0.0 for name in ALL_FEATURE_NAMES}
        dummy_features["static_total_findings"] = 3.0
        pred_out = predict_next_failure(cand_artifact, dummy_features, top_k=3)
        smoke_passed = bool(pred_out.get("predicted_category")) and len(pred_out.get("predictions", [])) > 0

    verdict = validate_artifact(cand_artifact) if cand_artifact is not None else {"valid": False}

    # Evaluate the 10-point promotion checklist (Phase 8.2)
    c1_leakage = bool((cand_meta.get("evaluation_metadata") or {}).get("leakage_passed", False))
    c2_splits = (
        int(cand_meta.get("evaluation_metadata", {}).get("n_cutoffs", 0)) >= 1
        and int(repo_eval.get("n_folds", 0)) >= 2
    )
    c3_provenance = (
        bool(cand_dataset.get("non_synthetic_only", False))
        and len(cand_dataset.get("distinct_repositories", [])) >= 3
    )
    c4_beats_majority = (
        cand_wf.get("macro_f1", 0.0) > maj_wf.get("macro_f1", 0.0)
        and cand_wf.get("top_2_accuracy", 0.0) >= maj_wf.get("top_2_accuracy", 0.0)
    )
    c5_beats_latest = (
        cand_wf.get("macro_f1", 0.0) > lat_wf.get("macro_f1", 0.0)
        and cand_wf.get("top_2_accuracy", 0.0) >= lat_wf.get("top_2_accuracy", 0.0)
    )
    c6_beats_static = (
        cand_wf.get("macro_f1", 0.0) >= stat_wf.get("macro_f1", 0.0)
        and cand_wf.get("top_2_accuracy", 0.0) >= stat_wf.get("top_2_accuracy", 0.0)
    )
    # Criterion 7: Outperforms current production model architecture on curated walk-forward OR unseen-repo generalization without regressing the other
    wf_f1_gain = cand_wf.get("macro_f1", 0.0) - prod_arch_wf.get("macro_f1", 0.0)
    wf_top2_gain = cand_wf.get("top_2_accuracy", 0.0) - prod_arch_wf.get("top_2_accuracy", 0.0)
    repo_f1_gain = repo_cand.get("macro_f1", 0.0) - repo_prod_arch.get("macro_f1", 0.0)
    repo_top2_gain = repo_cand.get("top_2_accuracy", 0.0) - repo_prod_arch.get("top_2_accuracy", 0.0)
    c7_outperforms_prod = (
        (wf_f1_gain > 0 or repo_f1_gain > 0 or wf_top2_gain > 0 or repo_top2_gain > 0)
        and wf_f1_gain >= -0.01
        and repo_f1_gain >= -0.01
    )

    cand_ll = cand_wf.get("log_loss")
    prod_ll = prod_arch_wf.get("log_loss")
    c8_calibration_logloss = True
    if cand_ll is not None and prod_ll is not None:
        c8_calibration_logloss = float(cand_ll) <= float(prod_ll) * 1.25

    c9_smoke = smoke_passed
    c10_validation = bool(verdict.get("valid", False))

    criteria = {
        "1_leakage_checks_pass": c1_leakage,
        "2_chronological_and_repo_grouped_splits": c2_splits,
        "3_dataset_provenance_and_non_synthetic_quality": c3_provenance,
        "4_beats_majority_class_baseline": c4_beats_majority,
        "5_beats_latest_failure_baseline": c5_beats_latest,
        "6_beats_or_matches_static_baseline": c6_beats_static,
        "7_outperforms_production_model": c7_outperforms_prod,
        "8_calibration_and_logloss_acceptable": c8_calibration_logloss,
        "9_clean_load_and_prediction_smoke_test": c9_smoke,
        "10_artifact_schema_validation_passes": c10_validation,
    }
    eligible_for_promotion = all(criteria.values())

    return {
        "candidate_id": candidate_id,
        "active_production_version": manifest.get("active_version"),
        "active_production_candidate_id": manifest.get("active_candidate_id"),
        "eligible_for_promotion": eligible_for_promotion,
        "criteria": criteria,
        "walk_forward_deltas_vs_production_architecture": {
            "macro_f1_delta": round(wf_f1_gain, 4),
            "top_2_accuracy_delta": round(wf_top2_gain, 4),
            "accuracy_delta": round(cand_wf.get("accuracy", 0.0) - prod_arch_wf.get("accuracy", 0.0), 4),
        },
        "unseen_repository_deltas_vs_production_architecture": {
            "macro_f1_delta": round(repo_f1_gain, 4),
            "top_2_accuracy_delta": round(repo_top2_gain, 4),
            "accuracy_delta": round(repo_cand.get("accuracy", 0.0) - repo_prod_arch.get("accuracy", 0.0), 4),
        },
        "candidate_walk_forward_metrics": cand_wf,
        "production_architecture_walk_forward_metrics": prod_arch_wf,
        "candidate_unseen_repo_metrics": repo_cand,
        "production_architecture_unseen_repo_metrics": repo_prod_arch,
        "calibration": cand_cal,
    }


def promote_candidate(
    candidate_id: str,
    root: Path | None = None,
) -> dict[str, Any]:
    """Promote ``candidate_id`` to production only when all 10 promotion criteria pass.

    Never overwrites ``backend/ml/artifacts/mistiq_apr/model.pkl``; updates
    ``production/production_manifest.json`` and ``production/active_model.pkl``.
    """
    base = Path(root) if root is not None else artifacts_root()
    comparison = compare_with_production(candidate_id, root=base)
    if not comparison["eligible_for_promotion"]:
        failed = [k for k, v in comparison["criteria"].items() if not v]
        return {
            "promoted": False,
            "candidate_id": candidate_id,
            "reason": f"Candidate failed promotion gate criteria: {failed}",
            "comparison": comparison,
        }

    manifest = ensure_registry_initialized(base)
    cand_dir = base / "candidates" / candidate_id
    cand_meta = json.loads((cand_dir / "metadata.json").read_text(encoding="utf-8"))
    cand_model_file = cand_dir / MODEL_FILENAME
    cand_sha = _sha256_file(cand_model_file)

    prod_dir = base / "production"
    shutil.copy2(cand_model_file, prod_dir / "active_model.pkl")
    shutil.copy2(cand_dir / METADATA_FILENAME, prod_dir / METADATA_FILENAME)

    rel_path = f"candidates/{candidate_id}/{MODEL_FILENAME}"
    previous_entry = {
        "version": manifest.get("active_version"),
        "candidate_id": manifest.get("active_candidate_id"),
        "model_relpath": manifest.get("active_model_relpath"),
        "sha256": manifest.get("active_model_sha256"),
    }

    now_iso = datetime.now(timezone.utc).isoformat()
    manifest["previous_production"] = previous_entry
    manifest["active_version"] = str(cand_meta.get("version") or candidate_id)
    manifest["active_candidate_id"] = candidate_id
    manifest["active_model_relpath"] = rel_path
    manifest["active_model_sha256"] = cand_sha
    manifest["updated_at"] = now_iso
    manifest.setdefault("promotion_history", []).append(
        {
            "action": "promote",
            "version": manifest["active_version"],
            "candidate_id": candidate_id,
            "model_relpath": rel_path,
            "sha256": cand_sha,
            "previous_candidate_id": previous_entry["candidate_id"],
            "comparison_summary": {
                "walk_forward_deltas": comparison["walk_forward_deltas_vs_production_architecture"],
                "unseen_repository_deltas": comparison["unseen_repository_deltas_vs_production_architecture"],
            },
            "timestamp": now_iso,
        }
    )

    manifest_path = prod_dir / "production_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    cand_meta["stage"] = "production"
    cand_meta["promoted_at"] = now_iso
    (cand_dir / "metadata.json").write_text(json.dumps(cand_meta, indent=2, default=str), encoding="utf-8")
    (cand_dir / METADATA_FILENAME).write_text(json.dumps(cand_meta, indent=2, default=str), encoding="utf-8")

    return {
        "promoted": True,
        "candidate_id": candidate_id,
        "active_version": manifest["active_version"],
        "active_model_relpath": rel_path,
        "active_model_sha256": cand_sha,
        "previous_production": previous_entry,
        "comparison": comparison,
    }


def rollback_production(
    target_candidate_id: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Roll back production to the previous model or original v1.0 without retraining."""
    base = Path(root) if root is not None else artifacts_root()
    manifest = ensure_registry_initialized(base)
    prod_dir = base / "production"

    if target_candidate_id is None or target_candidate_id in ("1.0", "v1.0", "model_v1.0_original"):
        backup = manifest.get("original_v1_backup") or {
            "version": "1.0",
            "candidate_id": "model_v1.0_original",
            "model_relpath": MODEL_FILENAME,
            "sha256": _sha256_file(base / MODEL_FILENAME) if (base / MODEL_FILENAME).is_file() else None,
        }
        target_rel = backup["model_relpath"]
        target_ver = backup["version"]
        target_cid = backup["candidate_id"]
        target_sha = backup["sha256"]
    else:
        cand_file = base / "candidates" / target_candidate_id / MODEL_FILENAME
        if not cand_file.is_file():
            raise FileNotFoundError(f"Rollback target '{target_candidate_id}' not found.")
        cand_meta = json.loads((cand_file.parent / "metadata.json").read_text(encoding="utf-8"))
        target_rel = f"candidates/{target_candidate_id}/{MODEL_FILENAME}"
        target_ver = str(cand_meta.get("version") or target_candidate_id)
        target_cid = target_candidate_id
        target_sha = _sha256_file(cand_file)

    now_iso = datetime.now(timezone.utc).isoformat()
    rolled_back_from = {
        "version": manifest.get("active_version"),
        "candidate_id": manifest.get("active_candidate_id"),
        "model_relpath": manifest.get("active_model_relpath"),
    }
    manifest["active_version"] = target_ver
    manifest["active_candidate_id"] = target_cid
    manifest["active_model_relpath"] = target_rel
    manifest["active_model_sha256"] = target_sha
    manifest["updated_at"] = now_iso
    manifest.setdefault("promotion_history", []).append(
        {
            "action": "rollback",
            "version": target_ver,
            "candidate_id": target_cid,
            "model_relpath": target_rel,
            "sha256": target_sha,
            "rolled_back_from": rolled_back_from,
            "timestamp": now_iso,
        }
    )

    manifest_path = prod_dir / "production_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "rolled_back": True,
        "active_version": target_ver,
        "active_candidate_id": target_cid,
        "active_model_relpath": target_rel,
        "active_model_sha256": target_sha,
        "rolled_back_from": rolled_back_from,
    }


def list_registry_models(root: Path | None = None) -> dict[str, Any]:
    """List production, candidate, and archived models in the registry."""
    base = Path(root) if root is not None else artifacts_root()
    manifest = ensure_registry_initialized(base)

    candidates: list[dict[str, Any]] = []
    cand_root = base / "candidates"
    if cand_root.is_dir():
        for c_dir in sorted(cand_root.iterdir()):
            if not c_dir.is_dir():
                continue
            meta_file = c_dir / "metadata.json"
            if not meta_file.is_file():
                meta_file = c_dir / METADATA_FILENAME
            if meta_file.is_file():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    candidates.append(
                        {
                            "candidate_id": c_dir.name,
                            "version": meta.get("version"),
                            "algorithm": meta.get("algorithm", "logistic_regression"),
                            "stage": (
                                "production"
                                if c_dir.name == manifest.get("active_candidate_id")
                                else meta.get("stage", "candidate")
                            ),
                            "trained_at": meta.get("trained_at"),
                            "training_observations": meta.get("training_observations"),
                            "dataset_version": meta.get("dataset_version"),
                            "dataset_hash": meta.get("dataset_hash"),
                            "model_sha256": meta.get("model_sha256"),
                            "primary_metrics": (meta.get("evaluation_metadata") or {}).get("primary_metrics"),
                            "unseen_repository_metrics": (meta.get("evaluation_metadata") or {}).get(
                                "unseen_repository_metrics"
                            ),
                        }
                    )
                except Exception:
                    continue

    orig_model = base / MODEL_FILENAME
    orig_meta_file = base / METADATA_FILENAME
    orig_meta = {}
    if orig_meta_file.is_file():
        try:
            orig_meta = json.loads(orig_meta_file.read_text(encoding="utf-8"))
        except Exception:
            orig_meta = {}

    archived = [
        {
            "candidate_id": "model_v1.0_original",
            "version": orig_meta.get("version", "1.0"),
            "algorithm": "logistic_regression",
            "stage": "production" if manifest.get("active_candidate_id") == "model_v1.0_original" else "archived",
            "trained_at": orig_meta.get("trained_at"),
            "training_observations": orig_meta.get("training_observations"),
            "dataset_version": orig_meta.get("dataset_version"),
            "dataset_hash": orig_meta.get("dataset_hash"),
            "model_sha256": _sha256_file(orig_model) if orig_model.is_file() else None,
            "primary_metrics": (orig_meta.get("evaluation_metadata") or {}).get("primary_metrics"),
        }
    ]

    return {
        "production": {
            "active_version": manifest.get("active_version"),
            "active_candidate_id": manifest.get("active_candidate_id"),
            "active_model_relpath": manifest.get("active_model_relpath"),
            "active_model_sha256": manifest.get("active_model_sha256"),
            "updated_at": manifest.get("updated_at"),
        },
        "candidates": candidates,
        "archived": archived,
        "promotion_history": manifest.get("promotion_history", []),
    }
