"""MISTIQ-APR research, model registry, code intelligence, and remediation service.

Thin orchestration layer between the HTTP routes and the research engine in
``backend/ml/mistiq_apr`` plus ``code_intelligence_service`` and ``llm/remediation``.
No training logic lives in FastAPI routes; the online prediction endpoint loads
saved artifacts only.
"""
from __future__ import annotations

from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ReviewedProject
from app.services.code_intelligence_service import build_repository_code_intelligence
from app.services.llm.remediation import generate_remediation_suggestion
from backend.ml.mistiq_apr.ablation import run_ablation
from backend.ml.mistiq_apr.artifacts import artifact_status, artifacts_root, load_valid_artifact
from backend.ml.mistiq_apr.calibration import run_calibration
from backend.ml.mistiq_apr.dataset import (
    build_curated_observations,
    build_observations,
    build_prediction_features,
    dataset_status,
    load_review_records,
)
from backend.ml.mistiq_apr.evaluation import evaluate_temporal
from backend.ml.mistiq_apr.ingestion import (
    IngestionConfig,
    get_ingestion_status,
    load_ingested_dataset,
    run_ingestion_pipeline,
)
from backend.ml.mistiq_apr.leakage import validate_leakage
from backend.ml.mistiq_apr.prediction import predict_next_failure
from backend.ml.mistiq_apr.registry import (
    compare_with_production,
    list_registry_models,
    promote_candidate,
    rollback_production,
    train_candidate,
)
from backend.ml.mistiq_apr.report import REPORT_FILENAME, write_report
from backend.ml.mistiq_apr.temporal import generate_walk_forward_splits
from backend.ml.mistiq_apr.training import train_and_save_model


def research_status(session: Session) -> dict[str, Any]:
    """Dataset + leakage + model status + registry + ingestion summary for the Research Lab."""
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
    status["registry"] = list_registry_models()
    status["ingestion"] = get_ingestion_status()
    return status


def research_dataset(session: Session) -> dict[str, Any]:
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
                "repository_group": row.repository_group,
                "is_synthetic": row.is_synthetic,
                "data_category": row.data_category,
                "label_confidence": row.label_confidence,
            }
            for row in observations
        ],
    }


def research_evaluation(session: Session) -> dict[str, Any]:
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
    return {
        "dataset": dataset,
        "evaluation": evaluation,
        "report_path": str(report_path),
        "registry": list_registry_models(),
        "ingestion": get_ingestion_status(),
    }


def research_prediction(session: Session, project_id: int) -> dict[str, Any]:
    """Online prediction from the saved artifact only; never trains."""
    project = session.get(ReviewedProject, project_id)
    if project is None:
        raise ValueError("Project not found")

    artifact, reason = load_valid_artifact()
    payload: dict[str, Any] = {
        "available": False,
        "project_id": project_id,
        "project_name": project.name,
    }
    if artifact is None:
        payload.update(
            {
                "reason": reason,
                "message": f"Prediction unavailable. Reason: {reason}.",
            }
        )
        return payload

    built = build_prediction_features(session, project_id)
    if built is None:
        payload.update(
            {
                "reason": "project has no persisted review history",
                "message": "Prediction unavailable. Reason: project has no persisted review history.",
            }
        )
        return payload
    features, evidence = built
    result = predict_next_failure(artifact, features, evidence=evidence)

    # Attach lightweight code-intelligence risk localization preview if repo path exists
    code_intel_preview: dict[str, Any] = {"available": False}
    if project.repository_path:
        intel = build_repository_code_intelligence(
            project.repository_path,
            predicted_category=result.get("predicted_category"),
        )
        if intel.get("available"):
            code_intel_preview = {
                "available": True,
                "summary": intel.get("summary"),
                "top_risk_regions": (intel.get("risk_regions") or [])[:8],
            }

    payload.update(
        {
            "available": True,
            **result,
            "historical_evidence": evidence,
            "code_intelligence": code_intel_preview,
        }
    )
    return payload


def research_registry() -> dict[str, Any]:
    """Return production, candidate, and archived models in the registry."""
    return list_registry_models()


def research_candidate_comparison(candidate_id: str) -> dict[str, Any]:
    """Compare a candidate model against active production using the 10-point promotion gate."""
    return compare_with_production(candidate_id)


def research_train_candidate(
    session: Session,
    algorithm: str = "random_forest",
    dataset_version: str = "v001",
    candidate_id: str | None = None,
) -> dict[str, Any]:
    """Train a new candidate model on the curated dataset without modifying production."""
    observations = load_ingested_dataset(dataset_version)
    if not observations:
        observations = build_curated_observations(
            session, exclude_synthetic=True, primary_target_only=True, deduplicate=True
        )
    return train_candidate(
        observations=observations,
        algorithm=algorithm,
        dataset_version=dataset_version,
        candidate_id=candidate_id,
    )


def research_promote_candidate(candidate_id: str) -> dict[str, Any]:
    """Promote an eligible candidate model to production."""
    return promote_candidate(candidate_id)


def research_rollback_production(target_candidate_id: str | None = None) -> dict[str, Any]:
    """Roll back active production model to v1.0 or a specified candidate."""
    return rollback_production(target_candidate_id)


def research_ingestion_status() -> dict[str, Any]:
    """Return latest dataset ingestion metadata."""
    return get_ingestion_status()


def research_run_ingestion(
    session: Session,
    target_repository_count: int = 100,
    dataset_version: str = "v001",
) -> dict[str, Any]:
    """Execute the 16-stage repository collection & dataset generation pipeline."""
    cfg = IngestionConfig(
        dataset_version=dataset_version,
        target_repository_count=target_repository_count,
    )
    return run_ingestion_pipeline(cfg, session=session)


def project_code_intelligence(session: Session, project_id: int) -> dict[str, Any]:
    """Perform line-level AST/static indexing and risk localization for a project."""
    project = session.get(ReviewedProject, project_id)
    if project is None:
        raise ValueError("Project not found")

    reviews = load_review_records(session, project_id)
    historical_findings = [
        {
            "category": f.category,
            "severity": f.severity,
            "title": getattr(f, "title", None) or f"{f.category} finding in {f.file or f.component}",
            "file": f.file,
            "line": f.line,
            "component": f.component,
        }
        for rev in reviews
        for f in rev.findings
    ]

    predicted_cat = None
    artifact, _ = load_valid_artifact()
    if artifact is not None and reviews:
        built = build_prediction_features(session, project_id)
        if built is not None:
            pred = predict_next_failure(artifact, built[0], evidence=built[1])
            predicted_cat = pred.get("predicted_category")

    intel = build_repository_code_intelligence(
        repository_path=project.repository_path or "",
        predicted_category=predicted_cat,
        historical_findings=historical_findings,
    )
    return {
        "project_id": project.id,
        "project_name": project.name,
        **intel,
    }


def project_remediation(
    session: Session,
    project_id: int,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    """Generate an evidence-grounded Groq (or deterministic fallback) remediation suggestion."""
    project = session.get(ReviewedProject, project_id)
    if project is None:
        raise ValueError("Project not found")

    reviews = load_review_records(session, project_id)
    historical_findings = [
        {
            "category": f.category,
            "severity": f.severity,
            "title": getattr(f, "title", None) or f"{f.category} finding in {f.file or f.component}",
            "file": f.file,
            "line": f.line,
        }
        for rev in reviews
        for f in rev.findings
    ]

    predicted_cat = None
    supporting_features: list[dict[str, Any]] = []
    artifact, _ = load_valid_artifact()
    if artifact is not None and reviews:
        built = build_prediction_features(session, project_id)
        if built is not None:
            pred = predict_next_failure(artifact, built[0], evidence=built[1])
            predicted_cat = pred.get("predicted_category")
            supporting_features = pred.get("supporting_features") or []

    return generate_remediation_suggestion(
        repository_path=project.repository_path,
        file_path=request_payload.get("file"),
        start_line=request_payload.get("start_line"),
        end_line=request_payload.get("end_line"),
        category=str(request_payload.get("category") or predicted_cat or "error_handling"),
        title=str(request_payload.get("title") or "Localized engineering review item"),
        explanation=str(request_payload.get("explanation") or ""),
        evidence_state=str(request_payload.get("state") or "verified_finding"),
        predicted_category=predicted_cat,
        supporting_features=supporting_features,
        historical_findings=historical_findings[:5],
    )
