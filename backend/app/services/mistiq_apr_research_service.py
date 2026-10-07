"""MISTIQ-APR research service.

Thin orchestration layer between the HTTP routes and the research engine in
``backend/ml/mistiq_apr``. No training logic lives in FastAPI routes; the
online prediction endpoint loads saved artifacts only.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ReviewedProject
from backend.ml.mistiq_apr.ablation import run_ablation
from backend.ml.mistiq_apr.artifacts import artifact_status, artifacts_root, load_valid_artifact
from backend.ml.mistiq_apr.calibration import run_calibration
from backend.ml.mistiq_apr.dataset import (
    build_observations,
    build_prediction_features,
    dataset_status,
)
from backend.ml.mistiq_apr.evaluation import evaluate_temporal
from backend.ml.mistiq_apr.leakage import validate_leakage
from backend.ml.mistiq_apr.prediction import predict_next_failure
from backend.ml.mistiq_apr.report import REPORT_FILENAME, write_report
from backend.ml.mistiq_apr.temporal import generate_walk_forward_splits
from backend.ml.mistiq_apr.training import train_and_save_model


def research_status(session: Session) -> dict:
    """Dataset + leakage + model status for the Research Lab header panels."""
    status = dataset_status(session)
    observations = build_observations(session)
    splits, _, _ = generate_walk_forward_splits(observations)
    status["leakage"] = validate_leakage(observations, splits)
    artifact = artifact_status()
    if artifact["valid"]:
        model_status = "TRAINED"
    elif str(status["status"]).startswith("INSUFFICIENT"):
        model_status = "INSUFFICIENT DATA"
    else:
        model_status = "NOT TRAINED"
    status["model_status"] = model_status
    status["model_available"] = artifact["valid"]
    status["model_detail"] = artifact["reason"]
    status["artifact"] = artifact["metadata"]
    return status


def research_dataset(session: Session) -> dict:
    """Dataset summary, project list, and full chronological observation dump."""
    observations = build_observations(session)
    projects = session.scalars(select(ReviewedProject).order_by(ReviewedProject.id)).all()
    return {
        "status": research_status(session),
        "project_list": [
            {"id": project.id, "name": project.name, "repository_path": project.repository_path}
            for project in projects
        ],
        "observations": [
            {
                "project_id": row.project_id,
                "review_id": row.review_id,
                "review_number": row.review_number,
                "timestamp": row.timestamp,
                "target": row.target,
                "features": row.features,
            }
            for row in observations
        ],
    }


def research_evaluation(session: Session) -> dict:
    """Run the full research pipeline: leakage -> walk-forward -> ablation ->
    calibration -> gated training -> report. Refuses on critical leakage."""
    dataset = dataset_status(session)
    observations = build_observations(session)
    evaluation = evaluate_temporal(observations)

    if evaluation.get("refused"):
        evaluation["ablation"] = {
            "status": "Ablation evaluation refused: critical data leakage detected.",
            "results": [],
            "n_cutoffs": 0,
        }
        evaluation["calibration"] = {
            "available": False,
            "reason": "Calibration withheld because evaluation was refused due to detected data leakage.",
        }
        evaluation["training"] = {
            "trained": False,
            "reason": "critical data leakage was detected",
            "path": None,
            "metadata": None,
        }
    else:
        splits, _, _ = generate_walk_forward_splits(observations)
        evaluation["ablation"] = run_ablation(observations, splits)
        evaluation["calibration"] = run_calibration(evaluation)
        evaluation["training"] = train_and_save_model(
            observations, evaluation.get("leakage", {"passed": False}), evaluation
        )

    report_path = write_report(artifacts_root() / REPORT_FILENAME, dataset, evaluation)
    return {"dataset": dataset, "evaluation": evaluation, "report_path": str(report_path)}


def research_prediction(session: Session, project_id: int) -> dict:
    """Online prediction from the saved artifact only; never trains."""
    project = session.get(ReviewedProject, project_id)
    if project is None:
        raise ValueError("Project not found")

    artifact, reason = load_valid_artifact()
    payload: dict = {
        "available": False,
        "project_id": project_id,
        "project_name": project.name,
    }
    if artifact is None:
        payload.update({
            "reason": reason,
            "message": f"Prediction unavailable. Reason: {reason}.",
        })
        return payload

    built = build_prediction_features(session, project_id)
    if built is None:
        payload.update({
            "reason": "project has no persisted review history",
            "message": "Prediction unavailable. Reason: project has no persisted review history.",
        })
        return payload
    features, evidence = built
    result = predict_next_failure(artifact, features)
    payload.update({
        "available": True,
        **result,
        "historical_evidence": evidence,
    })
    return payload
