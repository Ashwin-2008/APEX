"""MISTIQ-APR (MISTIQ AI Project Reviewer) research engine.

Research question:
    "Can the trajectory of software engineering failures predict the next project
     failure category better than static project-quality metrics?"

MISTIQ-APR is a project-specific sequential failure-prediction framework adapted
from the MISTIQ mistake-intelligence architecture. It is not claimed to be a newly
invented universal machine-learning paradigm; its contribution is the engineering of
an engineering-specific failure representation, sequential feature construction,
evidence grounding, next-failure prediction, and rigorous temporal evaluation.

See docs/mistiq-apr.md for the full methodology and docs/ for academic honesty notes.
"""
from __future__ import annotations

from pathlib import Path

try:
    from backend.ml.mistiq_apr.dataset import (
        PROJECT_REVIEW_DATASET_VERSION, load_real_reviews,
        load_or_build_simulated_reviews, run_simulation, SimulationConfig,
        build_observations, dataset_status, build_prediction_features, compute_dataset_hash,
    )
    from backend.ml.mistiq_apr.evaluation import (
        run_mistiq_apr_pipeline, PipelineStatus, PipelineReport,
        build_evaluation_report, save_evaluation_to_disk, evaluate_temporal,
    )
    from backend.ml.mistiq_apr.artifacts import (
        MISTIQAPRModelArtifact, save_mistiq_apr_artifact, load_mistiq_apr_artifact,
        load_valid_artifact, validate_artifact, artifact_status, artifacts_root,
        ARTIFACTS_ROOT,
    )
    from backend.ml.mistiq_apr.report import write_mistiq_apr_report
    from backend.ml.mistiq_apr.temporal import generate_walk_forward_splits
    from backend.ml.mistiq_apr.leakage import validate_leakage
    from backend.ml.mistiq_apr.ablation import run_ablation
    from backend.ml.mistiq_apr.calibration import run_calibration
    from backend.ml.mistiq_apr.training import train_and_save_model
    from backend.ml.mistiq_apr.prediction import predict_next_failure
except ModuleNotFoundError:
    from ml.mistiq_apr.dataset import (
        PROJECT_REVIEW_DATASET_VERSION, load_real_reviews,
        load_or_build_simulated_reviews, run_simulation, SimulationConfig,
        build_observations, dataset_status, build_prediction_features, compute_dataset_hash,
    )
    from ml.mistiq_apr.evaluation import (
        run_mistiq_apr_pipeline, PipelineStatus, PipelineReport,
        build_evaluation_report, save_evaluation_to_disk, evaluate_temporal,
    )
    from ml.mistiq_apr.artifacts import (
        MISTIQAPRModelArtifact, save_mistiq_apr_artifact, load_mistiq_apr_artifact,
        load_valid_artifact, validate_artifact, artifact_status, artifacts_root,
        ARTIFACTS_ROOT,
    )
    from ml.mistiq_apr.report import write_mistiq_apr_report
    from ml.mistiq_apr.temporal import generate_walk_forward_splits
    from ml.mistiq_apr.leakage import validate_leakage
    from ml.mistiq_apr.ablation import run_ablation
    from ml.mistiq_apr.calibration import run_calibration
    from ml.mistiq_apr.training import train_and_save_model
    from ml.mistiq_apr.prediction import predict_next_failure


__all__ = [
    "PROJECT_REVIEW_DATASET_VERSION",
    "load_real_reviews", "load_or_build_simulated_reviews", "run_simulation", "SimulationConfig",
    "build_observations", "dataset_status", "build_prediction_features", "compute_dataset_hash",
    "run_mistiq_apr_pipeline", "PipelineStatus", "PipelineReport",
    "build_evaluation_report", "save_evaluation_to_disk", "evaluate_temporal",
    "MISTIQAPRModelArtifact", "save_mistiq_apr_artifact", "load_mistiq_apr_artifact",
    "load_valid_artifact", "validate_artifact", "artifact_status", "artifacts_root",
    "ARTIFACTS_ROOT",
    "write_mistiq_apr_report",
    "generate_walk_forward_splits", "validate_leakage", "run_ablation", "run_calibration",
    "train_and_save_model", "predict_next_failure",
]

ROOT = Path(__file__).resolve().parents[2]