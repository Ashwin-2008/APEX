from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
import subprocess
from pathlib import Path
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


@router.get("/{project_id}/code-intelligence", summary="Line-by-line AST indexing and evidence-based risk localization")
def code_intelligence_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        _check_project_access(session, project_id, request)
        try:
            return project_code_intelligence(session, project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


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


