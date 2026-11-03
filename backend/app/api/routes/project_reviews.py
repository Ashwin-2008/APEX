from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
import subprocess
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field
from urllib.parse import urlparse

from app.services.project_review_service import analyze_project
from app.services.project_review_persistence import compare_reviews, failure_history, persist_analysis, project_history, serialize_review
from app.services.project_evolution_service import evolution, trajectory, requirements, research_observations
from app.services.mistiq_apr_research_service import (
    project_code_intelligence,
    project_remediation,
    research_candidate_comparison,
    research_dataset,
    research_evaluation,
    research_ingestion_status,
    research_prediction,
    research_promote_candidate,
    research_registry,
    research_rollback_production,
    research_run_ingestion,
    research_status,
    research_train_candidate,
)
from app.services.project_monitor import event_bus, start_watcher, stop_watcher
from app.services.git_service import get_current_sha, get_branch, is_git_repository
from app.models.entities import ProjectReview, ReviewedProject
from sqlalchemy import select

router = APIRouter(prefix="/project-reviews")


def _check_project_access(session, project_id: int, request: Request) -> ReviewedProject:
    """Validate project existence and tenant ownership if an auth token is provided."""
    project = session.get(ReviewedProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif "token" in request.query_params:
        token = request.query_params.get("token")

    if token:
        from app.services.auth_service import decode_access_token
        payload = decode_access_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired session token")
        if project.owner_id is not None and project.owner_id != payload["sub"]:
            raise HTTPException(status_code=404, detail="Project not found")
    return project


def _check_project_sse_access(session, project_id: int, request: Request) -> ReviewedProject:
    """Validate SSE connection via single-use ticket, standard header, or legacy dev token."""
    project = session.get(ReviewedProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    ticket = request.query_params.get("ticket")
    if ticket:
        from app.services.ticket_service import sse_ticket_store
        ticket_data = sse_ticket_store.validate_and_consume(ticket, expected_project_id=project_id)
        if not ticket_data:
            raise HTTPException(status_code=401, detail="Invalid, expired, or replayed SSE ticket.")
        if project.owner_id is not None and project.owner_id != ticket_data["user_id"]:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif "token" in request.query_params:
        from app.core.config import settings
        if settings.environment == "production":
            raise HTTPException(
                status_code=400,
                detail="Bearer tokens in URL parameters are forbidden in production. Use POST /api/auth/sse-ticket instead.",
            )
        token = request.query_params.get("token")

    if token:
        from app.services.auth_service import decode_access_token
        payload = decode_access_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired session token")
        if project.owner_id is not None and project.owner_id != payload["sub"]:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    if project.owner_id is not None:
        raise HTTPException(status_code=401, detail="Authentication required to access project stream.")
    return project


class ReviewRequest(BaseModel):
    project_path: str = Field(..., min_length=1, description="Path to a repository visible to the API worker")

class ConnectRequest(BaseModel):
    source_type: str = Field(..., pattern="^(local|github)$")
    path: str | None = None
    repository_url: str | None = None
    branch: str | None = None


@router.post("/analyze", summary="Run an evidence-first project review")
def analyze(request: ReviewRequest, app_request: Request):
    try:
        analysis = analyze_project(request.project_path)
        with app_request.app.state.SessionLocal() as session:
            persisted = persist_analysis(session, analysis)
        analysis["persistence"] = {"project_id": persisted["project_id"], "review_id": persisted["id"], "review_number": persisted["review_number"]}
        return analysis
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/taxonomy", summary="List supported engineering failure categories")
def taxonomy():
    from app.services.project_review_service import FAILURE_CATEGORIES
    return {"categories": FAILURE_CATEGORIES}

@router.post("/connect")
def connect(request: ConnectRequest, app_request: Request):
    path = request.path.strip().strip('"').strip("'") if request.path else None
    if request.source_type == "github":
        parsed = urlparse(request.repository_url or "")
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if parsed.scheme != "https" or parsed.hostname != "github.com" or len(parts) != 2 or any(part in {".", ".."} for part in parts):
            raise HTTPException(422, "Only public HTTPS GitHub repository URLs are supported.")
        slug = [parts[0], parts[1].removesuffix(".git")]
        target = (Path("data/repositories") / "-".join(slug)).resolve(); base = Path("data/repositories").resolve()
        if base not in target.parents: raise HTTPException(422, "Unsafe repository path.")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            command = ["git", "clone"]
            if request.branch:
                command.extend(["--branch", request.branch])
            command.extend([request.repository_url, str(target)])
            try:
                subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                detail = getattr(error, "stderr", "") or "clone failed"
                raise HTTPException(502, f"Public GitHub repository could not be cloned: {detail.strip()[:240]}") from error
        else:
            try:
                subprocess.run(["git", "-C", str(target), "remote", "set-url", "origin", request.repository_url], check=True, capture_output=True, text=True, timeout=30)
                subprocess.run(["git", "-C", str(target), "fetch", "--prune", "origin"], check=True, capture_output=True, text=True, timeout=180)
                remote_ref = f"origin/{request.branch}" if request.branch else "origin/HEAD"
                subprocess.run(["git", "-C", str(target), "reset", "--hard", remote_ref], check=True, capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                detail = getattr(error, "stderr", "") or "refresh failed"
                raise HTTPException(502, f"Public GitHub repository could not be refreshed: {detail.strip()[:240]}") from error
        path = str(target)
    if not path or not Path(path).is_dir(): raise HTTPException(422, "A valid local project directory is required.")
    try:
        analysis = analyze_project(path)
        # Detect Git SHA and branch information
        git_sha = get_current_sha(path) if is_git_repository(path) else None
        git_branch = get_branch(path) if is_git_repository(path) else request.branch
        
        with app_request.app.state.SessionLocal() as session:
            persisted = persist_analysis(session, analysis, related_commit=git_sha)
            project = session.get(ReviewedProject, persisted["project_id"])
            project.source_type = request.source_type
            project.repository_url = request.repository_url
            project.branch = git_branch
            project.current_commit_sha = git_sha
            project.monitoring_status = "active"
            session.commit()
        project_id = persisted["project_id"]
        
        # Emit initial project.changed and analysis events for the first connection
        initial_files = []
        initial_analyzers = ["source", "api", "authentication", "testing", "requirements", "coverage", "dependency", "security", "deployment", "configuration"]
        event_bus.emit(project_id, {"type": "project.changed", "project_id": project_id, "files": initial_files, "analyzers": initial_analyzers, "current_commit_sha": git_sha, "branch": git_branch})
        event_bus.emit(project_id, {"type": "analysis.started", "project_id": project_id, "files": initial_files, "analyzers": initial_analyzers, "current_commit_sha": git_sha, "branch": git_branch})
        event_bus.emit(project_id, {"type": "analysis.completed", "project_id": project_id, "review_id": persisted["id"], "review_number": persisted["review_number"], "files": initial_files, "analyzers": initial_analyzers, "current_commit_sha": git_sha, "branch": git_branch})
        
        # Emit finding events for initial findings
        for finding in persisted.get("findings", []):
            event_bus.emit(project_id, {"type": "finding.created", "project_id": project_id, "finding": finding, "related_commit": git_sha})
        
        # Emit requirement, DNA, and prediction events for initial analysis
        if analysis.get("requirements"):
            event_bus.emit(project_id, {"type": "requirement.updated", "project_id": project_id, "requirements": analysis.get("requirements", []), "review_id": persisted["id"], "related_commit": git_sha})
        if analysis.get("failure_dna"):
            event_bus.emit(project_id, {"type": "dna.updated", "project_id": project_id, "failure_dna": analysis["failure_dna"], "review_id": persisted["id"], "related_commit": git_sha})
        if analysis.get("next_failure_predictions"):
            event_bus.emit(project_id, {"type": "prediction.updated", "project_id": project_id, "predictions": analysis["next_failure_predictions"], "review_id": persisted["id"], "related_commit": git_sha})
        
        last_git_sha = git_sha

        def on_change(event):
            nonlocal last_git_sha
            event_type = event.get("type")
            print(f"[E2E] CALLBACK_RECEIVED project={project_id} type={event_type}", flush=True)
            if event_type == "monitoring.status":
                event_bus.emit(project_id, event)
                return
            # Emit project.changed event first for filesystem/Git changes
            if event_type == "project.changed":
                # Extract Git SHA information if available
                current_commit_sha = event.get("current_commit_sha")
                previous_commit_sha = event.get("previous_commit_sha")
                branch = event.get("branch")
                commit_info = event.get("commit_info")
                
                # Emit the project.changed event
                event_bus.emit(project_id, event)
                
                # Update the project's Git SHA in the database if this is a Git transition
                if current_commit_sha and current_commit_sha != last_git_sha:
                    with app_request.app.state.SessionLocal() as session:
                        project = session.get(ReviewedProject, project_id)
                        if project:
                            project.current_commit_sha = current_commit_sha
                            project.branch = branch
                            session.commit()
                    last_git_sha = current_commit_sha
                
                # Emit analysis.started
                print(f"[E2E] ANALYSIS_STARTED project={project_id}", flush=True)
                event_bus.emit(project_id, {"type": "analysis.started", "project_id": project_id, "files": event.get("files", []), "analyzers": event.get("analyzers", []), "current_commit_sha": current_commit_sha, "previous_commit_sha": previous_commit_sha, "branch": branch})
                
                try:
                    updated = analyze_project(path)
                    print(f"[E2E] ANALYSIS_COMPLETED project={project_id}", flush=True)
                    # Pass the current commit SHA to the persistence layer
                    current_sha_for_analysis = current_commit_sha or last_git_sha
                    with app_request.app.state.SessionLocal() as session:
                        print(f"[E2E] PERSISTENCE_STARTED project={project_id}", flush=True)
                        saved = persist_analysis(session, updated, affected_files=event.get("files", []), affected_analyzers=event.get("analyzers", []), related_commit=current_sha_for_analysis)
                    print(f"[E2E] REVIEW_PERSISTED project={project_id} review={saved['id']}", flush=True)
                    
                    # Emit analysis.completed
                    event_bus.emit(project_id, {"type": "analysis.completed", "project_id": project_id, "review_id": saved["id"], "review_number": saved["review_number"], "files": event.get("files", []), "analyzers": event.get("analyzers", []), "current_commit_sha": current_commit_sha, "previous_commit_sha": previous_commit_sha})
                    
                    # Emit finding events
                    for finding in saved.get("findings", []): 
                        finding_status = finding.get("status", "NEW")
                        if finding_status == "ACTIVE":
                            print(f"[E2E] FINDING_UPDATED project={project_id} fingerprint={finding.get('fingerprint')}", flush=True)
                            event_bus.emit(project_id, {"type": "finding.updated", "project_id": project_id, "finding": finding, "related_commit": current_sha_for_analysis})
                        else:
                            print(f"[E2E] FINDING_CREATED project={project_id} fingerprint={finding.get('fingerprint')}", flush=True)
                            event_bus.emit(project_id, {"type": "finding.created", "project_id": project_id, "finding": finding, "related_commit": current_sha_for_analysis})
                    
                    # Emit finding.resolved events
                    for resolved in saved.get("resolved_events", []):
                        print(f"[E2E] FINDING_UPDATED project={project_id} resolved={resolved.get('finding_id')}", flush=True)
                        event_bus.emit(project_id, {"type": "finding.resolved", "project_id": project_id, **resolved, "related_commit": current_sha_for_analysis})
                    
                    # Emit requirement.updated if requirements changed
                    if saved.get("requirements"):
                        event_bus.emit(project_id, {"type": "requirement.updated", "project_id": project_id, "requirements": saved.get("requirements", []), "review_id": saved["id"], "related_commit": current_sha_for_analysis})
                    
                    # Emit dna.updated if failure DNA changed
                    if updated.get("failure_dna"):
                        event_bus.emit(project_id, {"type": "dna.updated", "project_id": project_id, "failure_dna": updated["failure_dna"], "review_id": saved["id"], "related_commit": current_sha_for_analysis})
                    
                    # Emit prediction.updated if predictions changed
                    if updated.get("next_failure_predictions"):
                        event_bus.emit(project_id, {"type": "prediction.updated", "project_id": project_id, "predictions": updated["next_failure_predictions"], "review_id": saved["id"], "related_commit": current_sha_for_analysis})
                    
                except Exception as error:
                    print(f"[E2E] ANALYSIS_FAILED project={project_id} error={error}", flush=True)
                    event_bus.emit(project_id, {"type": "analysis.failed", "project_id": project_id, "message": str(error)})
        start_watcher(project_id, path, on_change, git_sha)
        return {"project_id": persisted["project_id"], "review_id": persisted["id"], "review_number": persisted["review_number"], "source_type": request.source_type, "path": path, "branch": git_branch, "current_commit_sha": git_sha, "monitoring_status": "active", "analysis": analysis, "persisted_review": persisted}
    except ValueError as error: raise HTTPException(422, str(error)) from error

@router.post("/{project_id}/monitoring/stop")
def stop_monitoring(project_id: int, request: Request):
    stop_watcher(project_id)
    with request.app.state.SessionLocal() as session:
        project = session.get(ReviewedProject, project_id)
        if not project: raise HTTPException(404, "Project not found")
        project.monitoring_status = "paused"; session.commit()
    return {"project_id": project_id, "monitoring_status": "paused"}

@router.get("/{project_id}/events")
async def project_events(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        _check_project_sse_access(session, project_id, request)
    async def stream():
        yield ": sse connected\n\n"
        async for event in event_bus.subscribe(project_id):
            import json
            yield f"event: {event.get('type', 'project.event')}\ndata: {json.dumps(event)}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.get("/{project_id}/history", summary="Return chronological persisted reviews")
def history(project_id: int, request: Request):
    try:
        with request.app.state.SessionLocal() as session:
            _check_project_access(session, project_id, request)
            return project_history(session, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{project_id}/failure-history", summary="Aggregate persisted failure findings across reviews")
def failure_history_report(project_id: int, request: Request):
    try:
        with request.app.state.SessionLocal() as session:
            _check_project_access(session, project_id, request)
            return failure_history(session, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{project_id}/compare", summary="Compare the latest two persisted reviews")
def compare(project_id: int, request: Request):
    try:
        with request.app.state.SessionLocal() as session:
            _check_project_access(session, project_id, request)
            return compare_reviews(session, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{project_id}/evolution")
def evolution_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        _check_project_access(session, project_id, request)
        return evolution(session, project_id)


@router.get("/{project_id}/trajectory")
def trajectory_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        _check_project_access(session, project_id, request)
        return trajectory(session, project_id)


@router.get("/{project_id}/requirements")
def requirement_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        _check_project_access(session, project_id, request)
        return requirements(session, project_id)


@router.get("/{project_id}/requirements/coverage")
def requirement_coverage(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        _check_project_access(session, project_id, request)
        return requirements(session, project_id)


@router.get("/{project_id}/research-observations")
def research_data(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        return research_observations(session, project_id)


@router.get("/{project_id}/research-prediction", summary="Next-failure prediction from the saved MISTIQ-APR artifact")
def research_prediction_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        try:
            return research_prediction(session, project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/research/status")
def research_status_report(request: Request):
    with request.app.state.SessionLocal() as session:
        return research_status(session)


@router.get("/research/dataset")
def research_dataset_report(request: Request):
    with request.app.state.SessionLocal() as session:
        return research_dataset(session)


@router.get("/research/evaluation")
def research_evaluation_report(request: Request):
    with request.app.state.SessionLocal() as session:
        return research_evaluation(session)


@router.get("/projects", summary="List all reviewed projects")
def list_projects(request: Request):
    with request.app.state.SessionLocal() as session:
        token = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif "token" in request.query_params:
            token = request.query_params.get("token")

        query = select(ReviewedProject)
        if token:
            from app.services.auth_service import decode_access_token
            payload = decode_access_token(token)
            if payload and "sub" in payload:
                query = query.where(ReviewedProject.owner_id == payload["sub"])
        query = query.order_by(ReviewedProject.updated_at.desc())
        projects = session.scalars(query).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "repository_path": p.repository_path,
                "source_type": p.source_type,
                "repository_url": p.repository_url,
                "branch": p.branch,
                "current_commit_sha": p.current_commit_sha,
                "monitoring_status": p.monitoring_status,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            }
            for p in projects
        ]


@router.get("/{project_id}/latest", summary="Get latest completed review for a project")
def get_latest_review(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        _check_project_access(session, project_id, request)
        latest = session.scalar(
            select(ProjectReview)
            .where(ProjectReview.project_id == project_id)
            .order_by(ProjectReview.review_number.desc())
        )
        if not latest:
            raise HTTPException(404, "No reviews found for this project")
        return serialize_review(session, latest.id)


class RemediationRequest(BaseModel):
    file: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    category: str = "error_handling"
    title: str = "Localized engineering review item"
    explanation: str = ""
    state: str = "verified_finding"


class CandidateTrainRequest(BaseModel):
    algorithm: str = "random_forest"
    dataset_version: str = "v001"
    candidate_id: str | None = None


class RollbackRequest(BaseModel):
    target_candidate_id: str | None = None


class IngestionRunRequest(BaseModel):
    target_repository_count: int = 100
    dataset_version: str = "v001"


@router.get("/{project_id}/code-intelligence", summary="Line-by-line AST indexing, type-safety, and runtime intelligence")
def code_intelligence_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)
        try:
            base_data = project_code_intelligence(session, project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        repo_path = Path(project.repository_path)
        if repo_path.is_dir():
            from app.services.analyzers.type_engine import run_type_intelligence_analysis
            from app.services.analyzers.resource_concurrency_analyzer import run_resource_concurrency_analysis
            from app.services.analyzers.trace_engine import DynamicTraceReconciler

            type_findings, type_metrics, _ = run_type_intelligence_analysis(repo_path)
            rc_findings, rc_metrics = run_resource_concurrency_analysis(repo_path)
            reconciler = DynamicTraceReconciler(repo_path)

            base_data["type_intelligence"] = {
                "metrics": type_metrics,
                "findings": [f.to_dict() for f in type_findings],
            }
            base_data["resource_concurrency"] = {
                "metrics": rc_metrics,
                "findings": [f.to_dict() for f in rc_findings],
            }
            base_data["dynamic_traces"] = {
                "executed_files_count": len(reconciler.executed_lines),
                "test_failures_count": len(reconciler.test_failures),
                "failures": [
                    {
                        "test_name": tf.test_name,
                        "message": tf.message,
                        "failure_type": tf.failure_type,
                        "stack_frames": [{"file": f.file_path, "line": f.line_number, "function": f.function_name} for f in tf.stack_frames],
                    }
                    for tf in reconciler.test_failures
                ],
            }
        return base_data


@router.get("/{project_id}/architecture-graph", summary="Repository-wide architecture dependency graph, cycles, and metrics")
def architecture_graph_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)
        repo_path = project.repository_path
        if not repo_path or not Path(repo_path).is_dir():
            raise HTTPException(status_code=404, detail="Project repository directory does not exist on worker host.")
        from app.services.analyzers.architecture_analyzer import run_architecture_analysis
        arch_out = run_architecture_analysis(repo_path)
        return {
            "project_id": project_id,
            "architecture_graph": arch_out.metrics.get("architecture_graph", {}),
            "metrics": arch_out.metrics,
            "cycle_findings": [f.to_dict() for f in arch_out.findings if f.rule_id == "ARCH-CIRCULAR-DEPENDENCY"],
        }


@router.post("/{project_id}/remediation", summary="Evidence-grounded AI remediation suggestion with secret redaction and patch validation")
def remediation_report(project_id: int, body: RemediationRequest, request: Request):
    with request.app.state.SessionLocal() as session:
        _check_project_access(session, project_id, request)
        try:
            return project_remediation(session, project_id, body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/research/registry", summary="List production, candidate, and archived models in the registry")
def registry_list_report():
    return research_registry()


@router.get("/research/candidates/{candidate_id}/comparison", summary="Compare candidate model against production using 10-point promotion gate")
def candidate_comparison_report(candidate_id: str):
    try:
        return research_candidate_comparison(candidate_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/research/candidates/train", summary="Train a new candidate model without modifying production")
def train_candidate_report(body: CandidateTrainRequest, request: Request):
    with request.app.state.SessionLocal() as session:
        try:
            return research_train_candidate(
                session,
                algorithm=body.algorithm,
                dataset_version=body.dataset_version,
                candidate_id=body.candidate_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/research/candidates/{candidate_id}/promote", summary="Promote an eligible candidate model to production")
def promote_candidate_report(candidate_id: str):
    try:
        return research_promote_candidate(candidate_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/research/production/rollback", summary="Roll back production model to v1.0 or specified candidate")
def rollback_production_report(body: RollbackRequest):
    try:
        return research_rollback_production(body.target_candidate_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/research/ingestion/status", summary="Get repository ingestion pipeline status and dataset manifest summary")
def ingestion_status_report():
    return research_ingestion_status()


@router.post("/research/ingestion/run", summary="Execute the 16-stage repository collection and ingestion pipeline")
def ingestion_run_report(body: IngestionRunRequest, request: Request):
    with request.app.state.SessionLocal() as session:
        return research_run_ingestion(
            session,
            target_repository_count=body.target_repository_count,
            dataset_version=body.dataset_version,
        )




# --- PHASE 2C: DETECTION INTELLIGENCE & EVIDENCE VALIDATION ENDPOINTS ---

class FeedbackSubmissionRequest(BaseModel):
    classification: str
    justification: str


@router.get("/{project_id}/intelligence", summary="Unified finding intelligence, correlation, root cause, and priority summary")
def intelligence_summary_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)
        repo_path = Path(project.repository_path)
        if not repo_path.is_dir():
            raise HTTPException(status_code=400, detail="Repository path does not exist on disk.")

        from app.services.analyzers.engine import run_comprehensive_analysis
        from app.services.intelligence.evidence_validator import EvidenceValidator
        from app.services.intelligence.finding_correlator import FindingCorrelator
        from app.services.intelligence.confidence_engine import ConfidenceCalibrator
        from app.services.intelligence.root_cause_engine import RootCauseAnalyzer
        from app.services.intelligence.prioritization_engine import RiskPrioritizer

        comp = run_comprehensive_analysis(repo_path)
        raw_findings = comp.get("findings", [])

        validator = EvidenceValidator(repo_path, current_commit=project.current_commit_sha)
        correlator = FindingCorrelator()
        correlator.correlate(raw_findings)
        deduped, clusters = correlator.deduplicate_multi_stage(raw_findings)

        root_causes = RootCauseAnalyzer.analyze(deduped)

        priorities = []
        validated_findings = []
        for f in deduped:
            v_state, ev_items = validator.validate_finding(f)
            conf = ConfidenceCalibrator.calibrate(f, ev_items, v_state)
            prio = RiskPrioritizer.prioritize(f, conf.level)
            f_copy = dict(f)
            f_copy["validation_state"] = v_state.value
            f_copy["calibrated_confidence"] = conf.to_dict()
            f_copy["remediation_priority"] = prio.to_dict()
            priorities.append(prio.to_dict())
            validated_findings.append(f_copy)

        return {
            "project_id": project_id,
            "total_findings": len(validated_findings),
            "findings": validated_findings,
            "relationships": [r.to_dict() for r in correlator.relationships],
            "correlation_clusters": [c.to_dict() for c in clusters],
            "root_causes": [rc.to_dict() for rc in root_causes],
            "risk_priorities": priorities,
        }


@router.get("/{project_id}/findings/{finding_id}/evidence", summary="Inspect verified ground-truth evidence items for a specific finding")
def finding_evidence_report(project_id: int, finding_id: str, request: Request):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)
        repo_path = Path(project.repository_path)
        if not repo_path.is_dir():
            raise HTTPException(status_code=400, detail="Repository path does not exist.")

        from app.services.intelligence.evidence_validator import EvidenceValidator

        # Query finding from DB if present
        finding_dict = None
        if finding_id.isdigit():
            db_f = session.get(ProjectFinding, int(finding_id))
            if db_f and db_f.review and db_f.review.project_id == project_id:
                from app.services.finding_service import serialize_finding
                finding_dict = serialize_finding(db_f)
        if not finding_dict:
            # Check by fingerprint
            db_f = session.scalar(
                select(ProjectFinding).join(ProjectReview).where(
                    ProjectReview.project_id == project_id,
                    ProjectFinding.fingerprint == finding_id,
                )
            )
            if db_f:
                from app.services.finding_service import serialize_finding
                finding_dict = serialize_finding(db_f)

        if not finding_dict:
            # Fallback to current workspace scan
            from app.services.analyzers.engine import run_comprehensive_analysis
            comp = run_comprehensive_analysis(repo_path)
            finding_dict = next((f for f in comp.get("findings", []) if (f.get("fingerprint") == finding_id or f.get("rule_id") == finding_id)), None)

        if not finding_dict:
            raise HTTPException(status_code=404, detail="Finding not found for this project.")

        validator = EvidenceValidator(repo_path, current_commit=project.current_commit_sha)
        v_state, ev_items = validator.validate_finding(finding_dict, finding_id=finding_id)

        from app.services.intelligence.confidence_engine import ConfidenceCalibrator
        conf = ConfidenceCalibrator.calibrate(finding_dict, ev_items, v_state)

        return {
            "finding_id": finding_id,
            "validation_state": v_state.value,
            "calibrated_confidence": conf.to_dict(),
            "evidence_items": [e.to_dict() for e in ev_items],
        }


@router.get("/{project_id}/findings/{finding_id}/relationships", summary="Inspect cross-analyzer relationships for a finding")
def finding_relationships_report(project_id: int, finding_id: str, request: Request):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)
        repo_path = Path(project.repository_path)
        if not repo_path.is_dir():
            raise HTTPException(status_code=400, detail="Repository path does not exist.")

        from app.services.analyzers.engine import run_comprehensive_analysis
        from app.services.intelligence.finding_correlator import FindingCorrelator

        comp = run_comprehensive_analysis(repo_path)
        correlator = FindingCorrelator()
        correlator.correlate(comp.get("findings", []))

        related = [
            r.to_dict() for r in correlator.relationships
            if r.source_finding_id == finding_id or r.target_finding_id == finding_id
        ]
        return {
            "finding_id": finding_id,
            "relationships_count": len(related),
            "relationships": related,
        }


@router.get("/{project_id}/root-causes", summary="Synthesized root causes underlying multiple project findings")
def root_causes_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)
        repo_path = Path(project.repository_path)
        if not repo_path.is_dir():
            raise HTTPException(status_code=400, detail="Repository path does not exist.")

        from app.services.analyzers.engine import run_comprehensive_analysis
        from app.services.intelligence.root_cause_engine import RootCauseAnalyzer

        comp = run_comprehensive_analysis(repo_path)
        root_causes = RootCauseAnalyzer.analyze(comp.get("findings", []))
        return {
            "project_id": project_id,
            "root_causes_count": len(root_causes),
            "root_causes": [rc.to_dict() for rc in root_causes],
        }


@router.get("/{project_id}/regressions", summary="Track finding regressions and resolutions across commits")
def regressions_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)
        repo_path = Path(project.repository_path)
        if not repo_path.is_dir():
            raise HTTPException(status_code=400, detail="Repository path does not exist.")

        from app.services.analyzers.engine import run_comprehensive_analysis
        from app.services.intelligence.regression_engine import RegressionTracker
        from app.services.finding_service import serialize_finding

        comp = run_comprehensive_analysis(repo_path)
        current_findings = comp.get("findings", [])

        # Fetch historical findings from database
        hist_rows = session.scalars(
            select(ProjectFinding).join(ProjectReview).where(ProjectReview.project_id == project_id)
        ).all()
        hist_serialized = [serialize_finding(r) for r in hist_rows]

        regressions = RegressionTracker.evaluate_regressions(
            current_findings=current_findings,
            historical_findings=hist_serialized,
            current_commit=project.current_commit_sha,
        )
        return {
            "project_id": project_id,
            "current_commit": project.current_commit_sha,
            "regressions_count": len(regressions),
            "regressions": [r.to_dict() for r in regressions],
        }


@router.get("/{project_id}/risk-priorities", summary="Multi-dimensional remediation priorities (P0-P3)")
def risk_priorities_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)
        repo_path = Path(project.repository_path)
        if not repo_path.is_dir():
            raise HTTPException(status_code=400, detail="Repository path does not exist.")

        from app.services.analyzers.engine import run_comprehensive_analysis
        from app.services.intelligence.prioritization_engine import RiskPrioritizer

        comp = run_comprehensive_analysis(repo_path)
        priorities = [
            RiskPrioritizer.prioritize(f).to_dict()
            for f in comp.get("findings", [])
        ]
        return {
            "project_id": project_id,
            "priorities_count": len(priorities),
            "priorities": priorities,
        }


@router.post("/{project_id}/findings/{finding_id}/feedback", summary="Submit auditable review decision and false-positive feedback")
def submit_feedback_report(project_id: int, finding_id: str, body: FeedbackSubmissionRequest, request: Request):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)

        # Resolve user_id from token
        user_id = project.owner_id or 1
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            from app.services.auth_service import decode_access_token
            payload = decode_access_token(auth_header[7:].strip())
            if payload:
                user_id = payload.get("sub", user_id)

        # Validate finding belongs to project
        db_f = None
        if finding_id.isdigit():
            db_f = session.get(ProjectFinding, int(finding_id))
            if db_f and db_f.review and db_f.review.project_id != project_id:
                raise HTTPException(status_code=404, detail="Finding does not belong to this project.")

        from app.services.intelligence.false_positive_engine import feedback_manager
        try:
            item = feedback_manager.record_feedback(
                project_id=project_id,
                user_id=user_id,
                finding_id=finding_id,
                rule_id=db_f.rule_id if db_f and hasattr(db_f, "rule_id") else (db_f.category if db_f else "RULE"),
                analyzer_source=db_f.analyzer_source if db_f else "manual_review",
                file=db_f.file if db_f else None,
                evidence=db_f.evidence if db_f else body.justification,
                classification=body.classification,
                justification=body.justification,
                commit_sha=project.current_commit_sha,
            )
            # Sync to suppression if false positive or accepted risk
            if db_f and body.classification in {"CONFIRMED_FALSE_POSITIVE", "ACCEPTED_RISK", "WONT_FIX"}:
                from app.services.finding_service import suppress_finding
                suppress_finding(session, db_f.id, user_id, body.justification, body.classification.lower())

            return {
                "status": "recorded",
                "feedback": item.to_dict(),
            }
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


class GenerateFixRequest(BaseModel):
    custom_finding: dict[str, Any] | None = None


@router.post("/{project_id}/findings/{finding_id}/generate-fix", summary="Synthesize deterministic or AI-grounded verified code patch for a finding")
def generate_fix_report(project_id: int, finding_id: str, request: Request, body: GenerateFixRequest | None = None):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)
        repo_path = Path(project.repository_path)
        if not repo_path.is_dir():
            raise HTTPException(status_code=400, detail="Repository path does not exist.")

        from app.models.entities import ProjectFinding
        from app.services.remediation import (
            PatchGenerator,
            PatchIntegrityService,
            PatchVerifier,
            SemanticVerifier,
            global_patch_manager,
        )

        finding_dict = None
        if body and body.custom_finding:
            finding_dict = body.custom_finding

        if not finding_dict:
            if finding_id.isdigit():
                db_f = session.get(ProjectFinding, int(finding_id))
                if db_f and db_f.review and db_f.review.project_id == project_id:
                    from app.services.finding_service import serialize_finding
                    finding_dict = serialize_finding(db_f)
            if not finding_dict:
                db_f = session.scalar(
                    select(ProjectFinding).join(ProjectReview).where(
                        ProjectReview.project_id == project_id,
                        ProjectFinding.fingerprint == finding_id,
                    )
                )
                if db_f:
                    from app.services.finding_service import serialize_finding
                    finding_dict = serialize_finding(db_f)

        if not finding_dict:
            from app.services.intelligence.evidence_validator import run_comprehensive_analysis
            comp = run_comprehensive_analysis(repo_path)
            for f in comp.get("findings", []):
                if str(f.get("fingerprint")) == finding_id or str(f.get("rule_id")) == finding_id:
                    finding_dict = f
                    break

        if not finding_dict:
            raise HTTPException(status_code=404, detail="Finding not found for fix generation.")

        patch = PatchGenerator.generate_patch(finding_dict, repo_path)
        if not patch:
            raise HTTPException(status_code=422, detail="Unable to synthesize patch for finding.")

        # Read original code for cryptographic provenance & semantic verification
        target_file = repo_path / patch.file
        orig_code = target_file.read_text(encoding="utf-8", errors="ignore") if target_file.is_file() else ""
        patched_code = patch.patched_full_content or orig_code

        # AST syntax & flaw elimination check
        verification = PatchVerifier.verify_patch(patch, repo_root=repo_path, original_code=orig_code)

        # Cryptographic provenance binding
        provenance = PatchIntegrityService.generate_provenance(
            patch=patch,
            original_code=orig_code,
            patched_code=patched_code,
            project_id=project_id,
            repo_revision=project.current_commit_sha,
        )

        # Semantic contract & control-flow verification
        semantic_res = SemanticVerifier.verify_semantics(
            original_code=orig_code,
            patched_code=patched_code,
            rule_id=patch.rule_id,
            expected_strategy=patch.strategy.value,
        )

        record = global_patch_manager.register_patch(
            patch=patch,
            verification=verification,
            provenance=provenance,
            semantic_verification=semantic_res,
        )

        return {
            "patch": patch.to_dict(),
            "verification": verification.to_dict(),
            "provenance": provenance.to_dict(),
            "semantic_verification": semantic_res.to_dict(),
            "record": record.to_dict(),
        }


@router.post("/{project_id}/patches/{patch_id}/apply", summary="Apply verified code patch with automated backup snapshot")
def apply_patch_report(project_id: int, patch_id: str, request: Request):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)
        repo_path = Path(project.repository_path)
        if not repo_path.is_dir():
            raise HTTPException(status_code=400, detail="Repository path does not exist.")

        from app.services.remediation import PostApplyVerifier, global_patch_manager

        success, msg = global_patch_manager.apply_patch(patch_id, repo_path)
        if not success:
            raise HTTPException(status_code=400, detail=msg)

        record = global_patch_manager.get_patch_record(patch_id)
        if record:
            # Run automatic post-apply flaw reanalysis
            post_res = PostApplyVerifier.verify_application(repo_path, record.patch)
            record.post_apply_verification = post_res.to_dict()

        return {
            "success": True,
            "message": msg,
            "patch_record": record.to_dict() if record else None,
        }


@router.post("/{project_id}/patches/{patch_id}/rollback", summary="Roll back applied code patch from pre-modification backup snapshot")
def rollback_patch_report(project_id: int, patch_id: str, request: Request):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)
        repo_path = Path(project.repository_path)
        if not repo_path.is_dir():
            raise HTTPException(status_code=400, detail="Repository path does not exist.")

        from app.services.remediation import global_patch_manager

        success, msg = global_patch_manager.rollback_patch(patch_id, repo_path)
        if not success:
            if "ROLLBACK_CONFLICT" in msg:
                raise HTTPException(status_code=409, detail=msg)
            raise HTTPException(status_code=400, detail=msg)

        record = global_patch_manager.get_patch_record(patch_id)
        return {
            "success": True,
            "message": msg,
            "patch_record": record.to_dict() if record else None,
        }


@router.get("/{project_id}/patches/{patch_id}/provenance", summary="Retrieve cryptographic provenance and SHA-256 digests for a patch")
def patch_provenance_report(project_id: int, patch_id: str, request: Request):
    with request.app.state.SessionLocal() as session:
        _check_project_access(session, project_id, request)
        from app.services.remediation import global_patch_manager

        record = global_patch_manager.get_patch_record(patch_id)
        if not record or (record.provenance and record.provenance.project_id != project_id):
            raise HTTPException(status_code=404, detail="Patch provenance not found for this project.")

        return {
            "patch_id": patch_id,
            "provenance": record.provenance.to_dict() if record.provenance else None,
            "state": record.state.value,
        }


@router.get("/{project_id}/patches/{patch_id}/verification", summary="Retrieve transparent multi-dimensional patch confidence assessment")
def patch_verification_report(project_id: int, patch_id: str, request: Request):
    with request.app.state.SessionLocal() as session:
        _check_project_access(session, project_id, request)
        from app.services.remediation import PatchConfidenceEngine, global_patch_manager

        record = global_patch_manager.get_patch_record(patch_id)
        if not record or (record.provenance and record.provenance.project_id != project_id):
            raise HTTPException(status_code=404, detail="Patch not found for this project.")

        report = PatchConfidenceEngine.evaluate_patch(record)
        return report.to_dict()


@router.get("/{project_id}/patches/{patch_id}/history", summary="Retrieve complete auditable lifecycle timeline for a patch")
def patch_history_report(project_id: int, patch_id: str, request: Request):
    with request.app.state.SessionLocal() as session:
        _check_project_access(session, project_id, request)
        from app.services.remediation import global_patch_manager

        record = global_patch_manager.get_patch_record(patch_id)
        if not record or (record.provenance and record.provenance.project_id != project_id):
            raise HTTPException(status_code=404, detail="Patch not found for this project.")

        return {
            "patch_id": patch_id,
            "state": record.state.value,
            "audit_trail": [a.to_dict() for a in record.audit_trail],
        }


@router.post("/{project_id}/patches/{patch_id}/verify-semantic", summary="Execute deep AST semantic and function contract verification")
def verify_patch_semantic_report(project_id: int, patch_id: str, request: Request):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)
        repo_path = Path(project.repository_path)
        if not repo_path.is_dir():
            raise HTTPException(status_code=400, detail="Repository path does not exist.")

        from app.services.remediation import SemanticVerifier, global_patch_manager

        record = global_patch_manager.get_patch_record(patch_id)
        if not record or (record.provenance and record.provenance.project_id != project_id):
            raise HTTPException(status_code=404, detail="Patch not found for this project.")

        target_file = repo_path / record.patch.file
        orig_code = target_file.read_text(encoding="utf-8", errors="ignore") if target_file.is_file() else ""
        patched_code = record.patch.patched_full_content or orig_code

        res = SemanticVerifier.verify_semantics(
            original_code=orig_code,
            patched_code=patched_code,
            rule_id=record.patch.rule_id,
            expected_strategy=record.patch.strategy.value,
        )
        record.semantic_verification = res
        return res.to_dict()


@router.post("/{project_id}/patches/{patch_id}/verify-behavioral", summary="Execute isolated behavioral regression tests against candidate patch")
def verify_patch_behavioral_report(project_id: int, patch_id: str, request: Request):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)
        repo_path = Path(project.repository_path)
        if not repo_path.is_dir():
            raise HTTPException(status_code=400, detail="Repository path does not exist.")

        from app.services.remediation import BehavioralVerifier, global_patch_manager

        record = global_patch_manager.get_patch_record(patch_id)
        if not record or (record.provenance and record.provenance.project_id != project_id):
            raise HTTPException(status_code=404, detail="Patch not found for this project.")

        target_file = repo_path / record.patch.file
        orig_code = target_file.read_text(encoding="utf-8", errors="ignore") if target_file.is_file() else ""
        patched_code = record.patch.patched_full_content or orig_code

        beh_res = BehavioralVerifier.verify_patch_behavior(repo_path, record.patch, patched_code)
        record.behavioral_verification = beh_res.to_dict()
        return beh_res.to_dict()


@router.post("/{project_id}/patches/{patch_id}/post-apply-verify", summary="Re-run specialized analyzer on disk to confirm flaw elimination")
def post_apply_verify_report(project_id: int, patch_id: str, request: Request):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)
        repo_path = Path(project.repository_path)
        if not repo_path.is_dir():
            raise HTTPException(status_code=400, detail="Repository path does not exist.")

        from app.services.remediation import PostApplyVerifier, global_patch_manager

        record = global_patch_manager.get_patch_record(patch_id)
        if not record or (record.provenance and record.provenance.project_id != project_id):
            raise HTTPException(status_code=404, detail="Patch not found for this project.")

        res = PostApplyVerifier.verify_application(repo_path, record.patch)
        record.post_apply_verification = res.to_dict()
        return res.to_dict()


@router.get("/{project_id}/patches/stale-check", summary="Check all registered patches in project for stale source files")
def check_patches_stale_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        project = _check_project_access(session, project_id, request)
        repo_path = Path(project.repository_path)
        if not repo_path.is_dir():
            raise HTTPException(status_code=400, detail="Repository path does not exist.")

        from app.services.remediation import PatchIntegrityService, global_patch_manager

        records = global_patch_manager.list_patches_for_project(project_id)
        results = []
        for r in records:
            if r.provenance:
                is_valid, msg, code = PatchIntegrityService.check_integrity(r.provenance, r.patch, repo_path)
                results.append({
                    "patch_id": r.patch.patch_id,
                    "file": r.patch.file,
                    "is_stale": code == "STALE_PATCH",
                    "status_code": code,
                    "message": msg,
                })
        return {"project_id": project_id, "checks": results}

